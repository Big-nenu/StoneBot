"""Herramientas de procesos del chat y enlace con su diario de ejecución."""
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
from time import monotonic
from uuid import uuid4

import managed_process
from mcp_client import data_path
from read_tools import read_tool
from stonebot_engine.safety import IsolationError, check_path
from tool_loop import ToolResult


EXECUTE = "ejecutar_proceso"
MANAGE = "gestionar_proceso"
START = "iniciar_proceso"
QUERY = "consultar_proceso"
CANCEL = "cancelar_proceso"
PROCESS_NAMES = {START, QUERY, CANCEL}
WAIT_MS = 1500
MAX_WAIT_MS = 2000
TERMINAL = {"terminado", "cancelado", "fallido"}
WAIT_FIELD = {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS,
              "description": "Espera máxima en milisegundos. Por defecto, 1500. Usa 0 para devolver el estado actual."}

PROCESS_TOOLS = [
    read_tool(EXECUTE, "Ejecuta un .exe de Windows con autorización. Devuelve estado, salida y código si termina pronto. "
              "Si sigue activo o hay más salida, conserva el ID y usa gestionar_proceso. "
              "Si el usuario proporciona argv, pasa su primer elemento como programa y el resto como argumentos.",
              {"programa": {"type": "string", "description": "Ruta absoluta del .exe"},
               "argumentos": {"type": "array", "items": {"type": "string"}},
               "cwd": {"type": "string", "description": "Carpeta absoluta. Puede omitirse si el proyecto tiene carpeta vinculada."},
               "espera_ms": WAIT_FIELD}, ["programa"]),
    read_tool(MANAGE, "Lista ejecuciones del chat, consulta por ID o solicita cancelar por ID con autorización. "
              "Al consultar, omite el cursor para continuar donde quedó la lectura o usa 0 para releer.",
              {"accion": {"type": "string", "enum": ["listar", "consultar", "cancelar"]}, "id": {"type": "string"},
               "cursor": {"type": "integer", "minimum": 0, "maximum": 2**63 - 1}, "espera_ms": WAIT_FIELD}, ["accion"]),
]
INTERFACE = {EXECUTE, MANAGE}


def resolved_command(arguments):
    argv, cwd = managed_process.command_spec(arguments)
    for argument in argv[1:]:
        if Path(argument).is_absolute():
            check_path(argument, reject_hard_links=False)
    executable = check_path(argv[0], reject_hard_links=False)
    return {"argv": [executable, *argv[1:]], "cwd": check_path(cwd)}


def translate(name, arguments, project):
    """Entrega al ejecutor y al diario las identidades históricas."""
    if name == EXECUTE:
        if set(arguments) - {"programa", "argumentos", "cwd", "espera_ms"}:
            raise ValueError("Usa programa, argumentos, cwd y espera_ms.")
        cwd = arguments.get("cwd", (project or {}).get("folder"))
        command = resolved_command({"argv": [arguments["programa"], *arguments.get("argumentos", [])], "cwd": cwd})
        return START, command, arguments.get("espera_ms", WAIT_MS)

    action = arguments["accion"]
    if action == "listar":
        if set(arguments) != {"accion"}:
            raise ValueError("Para listar indica únicamente la acción.")
        return QUERY, {}, 0
    if not arguments.get("id"):
        raise ValueError("Indica el ID de una ejecución de este chat.")
    if action == "cancelar":
        if set(arguments) != {"accion", "id"}:
            raise ValueError("Para cancelar indica únicamente la acción y el ID.")
        return CANCEL, {"id": arguments["id"]}, 0
    if set(arguments) - {"accion", "id", "cursor", "espera_ms"}:
        raise ValueError("Para consultar usa acción, ID, cursor y espera_ms.")
    return QUERY, {key: arguments[key] for key in ("id", "cursor") if key in arguments}, arguments.get("espera_ms", WAIT_MS)


async def observe_until(folder, run_id, cursor, first, wait_ms, remaining, check_pause):
    deadline = monotonic() + min(wait_ms / 1000, remaining())
    while first["estado"] in managed_process.ACTIVE:
        delay = min(deadline - monotonic(), remaining())
        if delay <= 0:
            break
        await asyncio.sleep(min(delay, 0.075))
        check_pause()
        delay = min(deadline - monotonic(), remaining())
        if delay <= 0:
            break
        try:
            async with asyncio.timeout(delay):
                first = await asyncio.to_thread(managed_process.inspect_run, folder, run_id, cursor,
                                                lock_timeout=min(0.05, delay))
        except TimeoutError:
            break
        except sqlite3.OperationalError as exc:
            if (getattr(exc, "sqlite_errorcode", 0) & 0xff) not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise
    return first


def latest_runs(steps):
    runs = {}
    for step in steps:
        if step["tool"] not in PROCESS_NAMES or step["status"] == "sin ejecutar":
            continue
        try:
            result = json.loads(step.get("result", ""))
        except ValueError:
            result = {}
        if isinstance(result, dict) and result.get("id") and result.get("estado"):
            runs[result["id"]] = (step.get("process_state", result["estado"]), result.get("cancelacion_solicitada", False))
        elif step.get("run_id"):
            runs[step["run_id"]] = (step.get("process_state", "sin confirmar"), False)
    return runs


async def execute(name, arguments, journal, confirm, check_pause, *, wait_ms, remaining):
    scope_key = hashlib.sha256(json.dumps(journal.state["scope"]).encode()).hexdigest()
    folder = data_path("procesos", str(journal.chat_id), scope_key)
    step = journal.state["steps"][-1]
    try:
        if name == START:
            managed_process.command_spec(arguments)
            duplicate = await asyncio.to_thread(managed_process.active_command, folder,
                                                journal.process_positions().keys(), arguments)
            if duplicate:
                return ToolResult(f"La misma invocación ya está activa o preparando su inicio. Consulta el ID {duplicate}.",
                                  reuse=False, status="sin ejecutar", code="EFECTO_YA_REGISTRADO")
            run_id = uuid4().hex
        else:
            run_id = arguments.get("id")
            positions = journal.process_positions()
            if run_id is not None and run_id not in positions:
                raise ValueError("Ejecución desconocida en este chat.")
        if name == QUERY and run_id is None:
            recent = sorted(folder.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
            result = {"ejecuciones_recientes": [p.stem for p in recent if p.stem in positions][:20]}
        else:
            if name != QUERY:
                details = (managed_process.description(folder, run_id)
                           if name == CANCEL else arguments)
                if not await confirm("Terminal de Windows", name, details, local=True):
                    return ToolResult("Operación denegada.", reuse=False, status="sin ejecutar")
                check_pause()
                if name == START and resolved_command(arguments) != arguments:
                    raise ValueError("Cambió el programa o directorio autorizado.")
                step["run_id"] = run_id
                journal.dispatched()
            if name == START:
                cursor = 0
                result = await asyncio.to_thread(managed_process.start, folder, run_id, arguments)
            else:
                cursor = arguments.get("cursor", positions[run_id])
                if name == QUERY and not managed_process.location(folder, run_id).is_file():
                    result = dict(id=run_id, estado="sin confirmar", codigo=None, inicio_confirmado=None,
                                  cancelacion_solicitada=False, salida="", cursor=cursor,
                                  hay_mas=False, truncada=False, parcial=True, error="Registro aún no disponible.")
                else:
                    result = await asyncio.to_thread(managed_process.inspect_run, folder, run_id, cursor,
                                                     cancel=name == CANCEL,
                                                     lock_timeout=5 if name == CANCEL else min(0.05, remaining()))
            if name != CANCEL:
                result = await observe_until(folder, run_id, cursor, result, wait_ms, remaining, check_pause)
            if result["salida"]:
                step["page"] = {"id": run_id, "cursor": result["cursor"]}
            if name == QUERY and result["estado"] not in {"sin confirmar", "preparando"}:
                journal.verify_process(run_id, result["estado"], cancellation_checked=(
                    result["cancelacion_solicitada"] or result["estado"] in TERMINAL))
            if name != QUERY and result["estado"] in {"sin confirmar", "preparando"}:
                return ToolResult(json.dumps(result, ensure_ascii=False), reuse=False, status="sin confirmar")
        return ToolResult(json.dumps(result, ensure_ascii=False), reuse=False, status="registro comprobado")
    except IsolationError:
        return ToolResult("La operación apunta a una ruta bloqueada.", reuse=False, status=step["status"],
                          code="DESTINO_BLOQUEADO")
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        return ToolResult(f"No se pudo completar la operación: {exc}", reuse=False, status=step["status"])

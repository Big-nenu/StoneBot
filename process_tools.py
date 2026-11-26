"""Herramientas de procesos del chat y enlace con su diario de ejecución."""
import asyncio
import hashlib
import json
import sqlite3
from uuid import uuid4

import managed_process
from mcp_client import data_path
from read_tools import read_tool
from tool_loop import ToolResult


PROCESS_TOOLS = [
    read_tool("iniciar_proceso", "Inicia un programa de Windows con autorización. Devuelve un ID. "
              "Consulta después su salida y código final para continuar el encargo.",
              {"argv": {"type": "array", "items": {"type": "string"}, "description": "Ruta absoluta del .exe seguida de sus argumentos"},
               "cwd": {"type": "string", "description": "Directorio absoluto de trabajo"}}, ["argv", "cwd"]),
    read_tool("consultar_proceso", "Sin ID lista ejecuciones recientes del chat. Con ID devuelve estado, código "
              "final y la siguiente página pendiente. Omite cursor para continuar, usa 0 para releer.",
              {"id": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}}, []),
    read_tool("cancelar_proceso", "Solicita cancelar una ejecución de este chat. Consulta después su estado final.",
              {"id": {"type": "string"}}, ["id"]),
]
PROCESS_NAMES = {tool.function.name for tool in PROCESS_TOOLS}


async def execute(name, arguments, journal, confirm, check_pause):
    scope_key = hashlib.sha256(json.dumps(journal.state["scope"]).encode()).hexdigest()
    folder = data_path("procesos", str(journal.chat_id), scope_key)
    step = journal.state["steps"][-1]
    try:
        if name == "iniciar_proceso":
            managed_process.command_spec(arguments)
            run_id = uuid4().hex
        else:
            run_id = arguments.get("id")
            positions = journal.process_positions()
            if run_id is not None and run_id not in positions:
                raise ValueError("Ejecución desconocida en este chat.")
        if name == "consultar_proceso" and run_id is None:
            recent = sorted(folder.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
            result = {"ejecuciones_recientes": [p.stem for p in recent if p.stem in positions][:20]}
        else:
            if name != "consultar_proceso":
                details = (managed_process.description(folder, run_id)
                           if name == "cancelar_proceso" else arguments)
                if not await confirm("Terminal de Windows", name, details, local=True):
                    return ToolResult("Operación denegada.", reuse=False, status="sin ejecutar")
                check_pause()
                step["run_id"] = run_id
                journal.dispatched()
            if name == "iniciar_proceso":
                result = await asyncio.to_thread(managed_process.start, folder, run_id, arguments)
            else:
                result = await asyncio.to_thread(managed_process.inspect_run, folder, run_id,
                                                 arguments.get("cursor", positions[run_id]),
                                                 cancel=name == "cancelar_proceso")
            if result["salida"]:
                step["page"] = {"id": run_id, "cursor": result["cursor"]}
            if name == "consultar_proceso":
                for pending_step in journal.unconfirmed():
                    if pending_step.get("run_id") == run_id and result["estado"] != "sin confirmar":
                        if pending_step["tool"] == "iniciar_proceso" or result["cancelacion_solicitada"]:
                            pending_step["status"] = "registro comprobado"
        return ToolResult(json.dumps(result, ensure_ascii=False), reuse=False, status="registro comprobado")
    except (ValueError, OSError, sqlite3.Error, TypeError) as exc:
        return ToolResult(f"No se pudo completar la operación: {exc}", reuse=False, status=step["status"])

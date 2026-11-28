"""Puente entre el trabajador compartido y el hilo lector de la terminal."""
import asyncio
import json
import os
import re
import unicodedata
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread

from turn_events import NullEvents, TurnOutcome


OPERATIVE_KEYS = frozenset("""
operation path target cwd argv offset cursor limit recursive name_contains id estado estado_final codigo
cancelacion_solicitada parcial desplazamiento_siguiente count total source fuente arguments content text
query output salida entradas archivo mensaje run_id shell truncado estado_archivo
programa argumentos accion espera_ms inicio_confirmado hay_mas truncada
""".split())
NUMERIC_KEYS = {"offset", "cursor", "limit", "count", "total", "codigo", "desplazamiento_siguiente", "espera_ms"}
FLAG_KEYS = {"recursive", "cancelacion_solicitada", "parcial", "truncado", "inicio_confirmado", "hay_mas", "truncada"}
STATUS_VALUES = {"ok", "error", "terminado", "cancelado", "fallido", "en ejecución", "preparando", "ejecutando",
                 "sin confirmar", "sin ejecutar"}
SECRET_KEY = re.compile(r"token|secret|pass(?:word|wd)?|clave|contras|authorization|cookie|api.?key|credential", re.I)
SECRET_TEXT = re.compile(r"(?i)bearer\s+[^\s]+|(?:token|secret|password|api[_-]?key)\s*[=:]\s*[^\s]+|sk-[A-Za-z0-9_-]+")
SECRET_ARG = re.compile(r"(?i)^-{1,2}(?:token|secret|password|api[_-]?key|authorization|cookie|credential|clave)$")


def terminal_text(value):
    return "".join(char if char in "\n\t" or unicodedata.category(char) not in ("Cc", "Cf")
                   else repr(char)[1:-1] for char in str(value))


def trace_value(value, key=None, depth=0):
    if key in FLAG_KEYS and type(value) is bool:
        return value
    if key in NUMERIC_KEYS and type(value) is int:
        return value
    if key == "estado" and isinstance(value, str) and value in STATUS_VALUES:
        return value
    if key == "accion" and isinstance(value, str) and value in {"listar", "consultar", "cancelar"}:
        return value
    if value is None:
        return None
    if depth < 3 and isinstance(value, dict):
        known = {k: trace_value(v, k, depth + 1) for k, v in value.items() if k in OPERATIVE_KEYS}
        return {"campos": known, "otros": len(value) - len(known)}
    if depth < 3 and isinstance(value, (tuple, list)):
        return {"total": len(value), "muestra": [trace_value(v, depth=depth + 1) for v in value[:6]]}
    if isinstance(value, str):
        return {"texto_oculto": True, "caracteres": len(value)}
    return {"tipo": type(value).__name__}


def safe_trace_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", value):
        return "(nombre oculto)"
    if SECRET_TEXT.search(value) or any(
        (SECRET_KEY.search(key) or key.startswith("STONEBOT_MCP_")) and secret and secret in value for key, secret in os.environ.items()
    ):
        return "(nombre oculto)"
    return value


def trace_payload(event, fields):
    fields = dict(fields)
    if "argumentos" in fields:
        fields["argumentos"] = trace_value(fields["argumentos"])
    if "estado_ejecutor" in fields:
        status = fields["estado_ejecutor"]
        fields["estado_ejecutor"] = status if status in STATUS_VALUES | {
            "respuesta recibida", "registro comprobado", "error de lectura", "error de herramienta",
            "verificada en disco", "cierre", "ejecución reconocida por MCP, efecto sin comprobación independiente",
        } else "otro"
    if "resultado" in fields:
        raw = fields["resultado"]
        if isinstance(raw, str) and len(raw) <= 20000:
            try:
                raw = json.loads(raw)
            except (ValueError, RecursionError):
                pass
        fields["resultado"] = trace_value(raw)
    if "herramientas" in fields:
        fields["herramientas"] = [safe_trace_name(name) for name in fields["herramientas"]]
    for name in ("servidor", "herramienta"):
        if name in fields and fields[name] not in ("(desconocida)", "(no disponible)"):
            fields[name] = safe_trace_name(fields[name])
    return {"evento": event, **fields}


def permission_details(value, secrets, key="", depth=0):
    if SECRET_KEY.search(key) or key.casefold() in {"texto", "text", "content", "contenido", "query", "payload"}:
        return "[oculto]"
    if depth > 8:
        return "[detalle omitido]"
    if isinstance(value, dict):
        return {permission_details(str(k), secrets): permission_details(v, secrets, str(k), depth + 1)
                for k, v in value.items()}
    if isinstance(value, list):
        if key.casefold() == "argv":
            scrubbed = []
            hide_next = False
            for arg in value:
                scrubbed.append("[oculto]" if hide_next else permission_details(arg, secrets, depth=depth + 1))
                hide_next = isinstance(arg, str) and SECRET_ARG.fullmatch(arg) is not None
            return scrubbed
        return [permission_details(v, secrets, depth=depth + 1) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[oculto]")
        return SECRET_TEXT.sub("[oculto]", value)
    return value


class CliTurnEvents(NullEvents):
    def __init__(self, queue):
        self.queue = queue
        self.last_request = None

    async def confirm(self, request):
        reply = Future()
        self.queue.put(("confirmar", (request, reply, self.last_request)))
        await asyncio.wrap_future(reply)

    def trace(self, event, **fields):
        if event == "peticion_modelo":
            self.last_request = fields["peticion"]
        self.queue.put(("traza", trace_payload(event, fields)))


def confirm(request, stdin, stderr):
    request.update(approved=False, remember=False)
    if not stdin.isatty():
        return
    arguments = request.get("arguments", {})
    secrets = tuple(sorted({v for k, v in os.environ.items() if v and (SECRET_KEY.search(k) or k.startswith("STONEBOT_MCP_"))}, key=len, reverse=True))
    label = request.get("tool") or request.get("operation") or "Operación"
    info = permission_details({"operación": label, "servidor": request.get("server"), "argumentos": arguments}, secrets)
    print(json.dumps(info, ensure_ascii=True, indent=2), file=stderr)
    print("¿Permitir una vez? [s/N]", file=stderr, flush=True)
    request["approved"] = stdin.readline().strip().casefold() == "s"


def run_turn(session, plan, stdin, stderr, *, verbose=False):
    queue = Queue()
    events = CliTurnEvents(queue)
    worker = plan.create_worker(events=events, trace=events.trace if verbose else None)

    def execute():
        try:
            queue.put(("fin", worker.run()))
        except Exception:
            queue.put(("fin", TurnOutcome("error", "No se pudo completar el turno.")))

    def interrupt():
        session.stopping_turn = True
        worker.request_pause()
        worker.stop()

    thread = Thread(target=execute)
    thread.start()
    try:
        while True:
            try:
                # Un timeout permite que Windows entregue Ctrl+C al hilo principal.
                event, payload = queue.get(timeout=0.1)
            except KeyboardInterrupt:
                interrupt()
                continue
            except Empty:
                continue
            if event == "confirmar":
                request, reply, request_id = payload
                if not reply.set_running_or_notify_cancel():
                    continue
                try:
                    if not session.stopping_turn:
                        confirm(request, stdin, stderr)
                except KeyboardInterrupt:
                    interrupt()
                except (EOFError, OSError):
                    pass
                finally:
                    reply.set_result(None)
                if verbose:
                    print(json.dumps(trace_payload("permiso", {"aprobado": request["approved"],
                                                  "servidor": request.get("server"), "herramienta": request.get("tool"),
                                                  "peticion": request_id}),
                                     ensure_ascii=True), file=stderr, flush=True)
            elif event == "traza":
                print(json.dumps(payload, ensure_ascii=True), file=stderr, flush=True)
            elif event == "fin":
                thread.join()
                return session.complete_turn(payload, worker)
    finally:
        if thread.is_alive():
            interrupt()
            thread.join()

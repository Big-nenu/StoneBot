"""Estado de la tarea del chat y contexto acotado para reanudarla."""
import hashlib
import json
from pathlib import Path

from ollama import Tool

from mcp_permissions import permission_signature


LABELS = {
    "running": "En curso", "waiting": "Espera tu respuesta", "paused": "Pausada · /reanudar",
    "interrupted": "Interrumpida · /reanudar", "completed": "Completada", "cancelled": "Cancelada",
}
STEP_LABELS = {
    "running": "Resultado pendiente", "response": "Resultado guardado", "no_text": "Sin datos",
    "tool_error": "Error", "exception": "Resultado incierto", "timeout": "Resultado incierto",
    "not_run": "Sin ejecutar",
}
REPORT_STATES = {"espera": "waiting", "completada": "completed", "pausa": "paused"}
REPORT_STATUS = {"type": "object", "required": ["estado"], "properties": {
    "estado": {"type": "string", "enum": list(REPORT_STATES)},
}}
REPORT = Tool.model_validate({
    "type": "function", "function": {
        "name": "informar_estado_tarea",
        "description": "Termina este turno de la tarea. Haz esta llamada sola. Usa espera para pedir un dato "
                       "indispensable, completada para entregar el resultado comprobado o pausa al quedar bloqueado.",
        "parameters": {"type": "object", "required": ["estado", "mensaje"], "properties": {
            "estado": REPORT_STATUS["properties"]["estado"],
            "mensaje": {"type": "string", "description": "Pregunta concreta, resultado con evidencia o bloqueo."},
        }},
    },
})


def new_task(objective):
    return {"objective": objective, "status": "running", "message": "", "steps": []}


def checkpoint_key(name, server, tool, arguments):
    payload = json.dumps([name, permission_signature(server, tool), arguments], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def step_caption(step):
    resource = f" · {Path(step['resource']).name}" if step.get("resource") else ""
    return f"{step['tool']}{resource} · {STEP_LABELS[step['status']]}"


def task_context(task):
    # shortcut: conserva todas las lecturas en SQLite, usa hasta 18 mil caracteres recientes al reanudar.
    recent = []
    remaining = 18_000
    for step in reversed(task["steps"]):
        if remaining <= 0:
            break
        result = step.get("result", "")[:min(4000, remaining)]
        entry = {"herramienta": step["tool"], "estado": STEP_LABELS[step["status"]], "resultado": result}
        if step.get("resource"):
            entry["recurso"] = step["resource"]
        recent.append(entry)
        remaining -= len(json.dumps(entry, ensure_ascii=False))
    return json.dumps({"objetivo": task["objective"], "mensaje_anterior": task["message"],
                       "pasos_recientes": list(reversed(recent))}, ensure_ascii=False)

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
COVERAGE_STATUS = {"type": "object", "required": ["verificada", "faltante"], "properties": {
    "verificada": {"type": "boolean"},
    "faltante": {"type": "string"},
}}
LIMIT_REASON = ("Se agotó el presupuesto de herramientas antes de verificar la cobertura. "
                "Falta demostrar qué universo debía revisarse y que no quedaron elementos pendientes.")
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
    return {"objective": objective, "status": "running", "message": "", "steps": [], "coverage_notes": []}


def upgrade_task(task):
    if "coverage_notes" in task:
        return False
    task["coverage_notes"] = []
    if task["steps"] and task["status"] != "cancelled":
        task["coverage_notes"].append("La ejecución anterior guardó lecturas sin verificar la cobertura del objetivo.")
        if task["status"] == "completed":
            task["status"] = "paused"
    return True


def checkpoint_key(name, server, tool, arguments):
    payload = json.dumps([name, permission_signature(server, tool), arguments], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def step_caption(step):
    resource = f" · {Path(step['resource']).name}" if step.get("resource") else ""
    status = "Resultado parcial" if step.get("partial") else STEP_LABELS[step["status"]]
    return f"{step['tool']}{resource} · {status}"


def task_context(task):
    # shortcut: conserva todas las lecturas en SQLite, usa hasta 18 mil caracteres recientes al reanudar.
    recent = []
    remaining = 18_000
    for step in reversed(task["steps"]):
        if remaining <= 0:
            break
        full_result = step.get("result", "")
        result = full_result[:min(4000, remaining)]
        entry = {"herramienta": step["tool"], "estado": STEP_LABELS[step["status"]], "resultado": result}
        if step.get("partial") or len(result) < len(full_result):
            entry["cobertura"] = step.get("partial") or "El resultado se abrevió para este turno."
        if step.get("resource"):
            entry["recurso"] = step["resource"]
        recent.append(entry)
        remaining -= len(json.dumps(entry, ensure_ascii=False))
    return json.dumps({"objetivo": task["objective"], "mensaje_anterior": task["message"],
                       "observaciones_de_cobertura": task.get("coverage_notes", []),
                       "pasos_fuera_del_contexto": len(task["steps"]) - len(recent),
                       "pasos_recientes": list(reversed(recent))}, ensure_ascii=False)


def completion_evidence(task):
    reasons = list(task.get("coverage_notes", []))
    latest = {step["key"]: step for step in task["steps"]}
    evidence = []
    for step in latest.values():
        if step.get("partial"):
            reasons.append(f"{step_caption(step)}. {step['partial']}")
        elif step["status"] != "response":
            reasons.append(f"{step_caption(step)}. Falta una lectura verificable.")
        evidence.append({key: value for key, value in step.items() if key != "key"})
    serialized = json.dumps({"objetivo": task["objective"], "lecturas": evidence}, ensure_ascii=False)
    if len(serialized) > 24_000:
        reasons.append("El conjunto de evidencias supera lo que puedo comprobar en una sola revisión.")
    return list(dict.fromkeys(reasons)), serialized

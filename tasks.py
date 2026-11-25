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
PLAN_STATUS = {"type": "object", "required": ["pasos"], "properties": {
    "pasos": {"type": "array", "minItems": 1, "maxItems": 6,
              "items": {"type": "string", "maxLength": 300}},
}}
LIMIT_REASON = ("Se agotó el presupuesto de herramientas antes de verificar la cobertura. "
                "Falta demostrar qué universo debía revisarse y que no quedaron elementos pendientes.")
START_TASK = Tool.model_validate({
    "type": "function", "function": {
        "name": "iniciar_tarea",
        "description": "Abre una tarea reanudable de solo lectura para el encargo de varios pasos que acaba de pedir "
                       "el usuario. Llámala antes de las herramientas externas. Incluye el objetivo y las referencias "
                       "que el usuario ya dio. No la uses para preguntas simples, memoria ni acciones de escritura.",
        "parameters": {"type": "object", "required": ["objetivo"], "properties": {
            "objetivo": {"type": "string", "maxLength": 4000},
        }},
    },
})
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


def project_checkpoint_key(name, arguments):
    payload = json.dumps(["project_read", name, arguments], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def invalidate_project_reads(task, resources):
    stale = {}
    steps = []
    for step in task["steps"]:
        kind = step.get("project_read")
        if kind == "memory":
            continue
        resource = step.get("resource")
        if kind != "file" or resource not in resources:
            steps.append(step)
            continue
        if resource not in stale or step["arguments"]["offset"] < stale[resource]["arguments"]["offset"]:
            stale[resource] = step
    for step in stale.values():
        replacement = {key: step[key] for key in ("key", "tool", "resource", "project_read", "arguments")}
        replacement.update(status="not_run", result="La lectura guardada dejó de ser válida. Vuelve a leer el archivo.")
        steps.append(replacement)
    task["steps"] = steps
    task["message"] = ""
    task["pending"] = ""


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
        if step.get("project_read") or step.get("inventory_read"):
            entry["argumentos"] = step["arguments"]
        recent.append(entry)
        remaining -= len(json.dumps(entry, ensure_ascii=False))
    return json.dumps({"objetivo": task["objective"], "mensaje_anterior": task["message"],
                       "plan": task.get("plan", []),
                       "aclaraciones": task.get("clarifications", []),
                       "pendiente": task.get("pending", ""),
                       "observaciones_de_cobertura": task.get("coverage_notes", []),
                       "pasos_fuera_del_contexto": len(task["steps"]) - len(recent),
                       "pasos_recientes": list(reversed(recent))}, ensure_ascii=False)


def completion_evidence(task):
    reasons = [note for note in task.get("coverage_notes", []) if note != LIMIT_REASON]
    latest = {step["key"]: step for step in task["steps"]}
    pages = {(step["resource"], step["arguments"]["offset"], tuple(step["revision"])): step
             for step in latest.values() if step.get("project_read") == "file" and step.get("revision")
             and step["status"] == "response"}
    complete_files = set()
    for (resource, offset, revision), first in pages.items():
        if offset != 0:
            continue
        page = first
        while page and (next_offset := page.get("next_offset")) is not None:
            page = pages.get((resource, next_offset, revision)) if next_offset > page["arguments"]["offset"] else None
        if page and not page.get("partial"):
            complete_files.add((resource, revision))
    evidence = []
    for step in latest.values():
        next_page = step.get("next_offset")
        continuation = (next_page is not None and
                        (step["resource"], next_page, tuple(step["revision"])) in pages)
        if step.get("partial") and not continuation:
            reasons.append(f"{step_caption(step)}. {step['partial']}")
        elif step["status"] != "response":
            reasons.append(f"{step_caption(step)}. Falta una lectura verificable.")
        item = {key: value for key, value in step.items() if key != "key"}
        if step.get("project_read") == "file" and step["status"] == "response":
            version = (step["resource"], tuple(step["revision"]))
            item["cobertura_archivo"] = "completo" if version in complete_files else "parcial"
        if continuation:
            item.pop("partial", None)
            item["continuation_read"] = True
        evidence.append(item)
    serialized = json.dumps({"objetivo": task["objective"], "aclaraciones": task.get("clarifications", []),
                             "lecturas": evidence}, ensure_ascii=False)
    if len(serialized) > 24_000:
        reasons.append("El conjunto de evidencias supera lo que puedo comprobar en una sola revisión.")
    return list(dict.fromkeys(reasons)), serialized

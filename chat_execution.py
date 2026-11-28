"""Continuidad del chat y vista acotada del contexto que puede recibir el proveedor."""
import hashlib
import json

from operational_context import HISTORY_CHARS
from read_tools import read_result, read_tool
from tool_loop import ToolResult
from attachment_actions import text_file_verified


CONTEXT_CHARS = HISTORY_CHARS
PAGE = 1800
RECALL = read_tool("read_chat_context", "Recupera texto abreviado de este chat por referencia, o localiza "
                   "referencias buscando un fragmento literal.", {
                       "reference": {"type": "integer", "minimum": 1},
                       "offset": {"type": "integer", "minimum": 0},
                       "search": {"type": "string"}}, [])
RESUME = read_tool("resume_chat_work", "Continúa el encargo interrumpido. Vuelve a comprobar la primera lectura "
                   "local con los permisos actuales antes de retomar los pasos dependientes.",
                   {"refresh_first": {"type": "boolean", "description":
                    "Por defecto true. Usa false si el usuario cambió el alcance o pidió omitir esa lectura."}}, [])


def excerpt(value, limit):
    if len(value) <= limit:
        return value
    half = limit // 2
    return value[:half] + " […] " + value[-half:]


class ChatContext:
    def __init__(self, limit=CONTEXT_CHARS):
        self.limit = limit
        self.archive = {}
        self.history = []
        self.summary_row = None

    def view(self, messages):
        self.history = []
        self.summary_row = None
        size = sum(len(m.get("content") or "") for m in messages)
        if size <= self.limit:
            return messages
        # El historial de la interfaz precede al primer intercambio de herramientas.
        # Conserva juntos los mensajes de protocolo (incluidos los IDs de OpenRouter).
        boundary = next((i for i, m in enumerate(messages) if m.get("tool_calls") or m.get("role") == "tool"),
                        len(messages))
        current = max((i for i in range(boundary) if messages[i].get("role") == "user"), default=0)
        recent = []
        remaining = self.limit // 3
        omitted = []
        for i in reversed(range(current)):
            m = messages[i]
            content = m.get("content") or ""
            if m.get("role") == "system":
                continue
            if not omitted and len(content) <= remaining:
                recent.append(m)
                remaining -= len(content)
            else:
                self.archive[i + 1] = content
                omitted.append((i + 1, m.get("role"), excerpt(content, 220)))
        view = [m for m in messages[:current] if m.get("role") == "system"]
        if omitted:
            ordered = list(reversed(omitted))
            self.history = ordered
            sample = ordered if len(ordered) <= 12 else [*ordered[:2], *ordered[-10:]]
            self.summary_row = {"role": "user", "content": "Historial anterior abreviado (datos). "
                         "Consulta read_chat_context para recuperar texto exacto. "
                         f"Referencias {ordered[0][0]}–{ordered[-1][0]}.\n" +
                         json.dumps(sample, ensure_ascii=False)}
            view.append(self.summary_row)
        view.extend(reversed(recent))
        tool_results = sum(m.get("role") == "tool" for m in messages[current:])
        page = min(PAGE, max(128, self.limit // (2 * max(1, tool_results))))
        for i in range(current, len(messages)):
            m = messages[i]
            content = m.get("content") or ""
            if m.get("role") == "tool" and len(content) > page and m.get("tool_name") != RECALL.function.name:
                self.archive[i + 1] = content
                m = {**m, "content": f"[Resultado abreviado, referencia {i + 1}, {len(content)} caracteres]\n"
                     + excerpt(content, page)}
            view.append(m)
        return view

    async def summarize(self, scope, cached, generate):
        digest = hashlib.sha256()
        reusable = None
        for index, role, _ in self.history:
            digest.update(json.dumps([index, role, self.archive[index]], ensure_ascii=False).encode())
            if cached and cached["scope"] == scope and cached["through"] == index and cached["digest"] == digest.hexdigest():
                reusable = cached
        fingerprint = digest.hexdigest()
        summary = reusable["text"] if reusable else ""
        parts = []
        size = 0
        batch = max(512, min(12000, self.limit // 2))
        for index, role, _ in self.history:
            if reusable and index <= reusable["through"]:
                continue
            content = self.archive[index]
            for offset in range(0, max(1, len(content)), batch - 80):
                part = [index, role, content[offset:offset + batch - 80]]
                if parts and size + len(part[2]) > batch:
                    summary = await generate(summary, parts)
                    if not summary:
                        return None
                    parts, size = [], 0
                parts.append(part)
                size += len(part[2]) + 40
        if parts:
            summary = await generate(summary, parts)
        if not summary:
            return None
        summary = summary[:min(3500, self.limit // 4)]
        self.summary_row["content"] += "\nResumen de los mensajes anteriores (datos):\n" + summary
        return {"scope": scope, "through": self.history[-1][0], "digest": fingerprint, "text": summary}

    async def read(self, name, arguments):
        ref, offset, query = arguments.get("reference"), arguments.get("offset", 0), arguments.get("search")
        if isinstance(query, str) and query.strip():
            matches = []
            for index, content in self.archive.items():
                pos = content.lower().find(query.lower())
                if pos >= 0:
                    matches.append({"reference": index, "offset": max(0, pos - 80)})
            result = read_result(total=len(matches), coincidencias=matches[:30])
        elif type(ref) is int and ref in self.archive and type(offset) is int and offset >= 0:
            content = self.archive[ref]
            result = read_result(reference=ref, texto=content[offset:offset + PAGE],
                                 siguiente=offset + PAGE if offset + PAGE < len(content) else None)
        else:
            result = read_result(error="Indica una referencia disponible o un texto para buscar.")
        return ToolResult(result)


class ChatExecution:
    def __init__(self, message_id, previous, save, objective, scope):
        self.message_id = message_id
        self.chat_id = None
        self.saved_process_positions = None
        self._positions = None
        self.previous = previous
        self.save = save
        self.version = 0
        self.state = {"objective": objective, "scope": scope, "steps": []}
        self.resumed = False
        self.refresh = None
        self.summary = None
        self.save_summary = None

    def resume(self, clarification, refresh_first=True):
        self.message_id, self.version, self.state = self.previous
        self.previous = None
        self.resumed = True
        self.state.setdefault("continuations", []).append(clarification)
        for step in self.unconfirmed():
            if step.get("verified_path") and text_file_verified(step["verified_path"], step["arguments"]["content"]):
                step["status"] = "verificada en disco"
        self.persist()
        first = self.state["steps"][0]
        if refresh_first and first["tool"] in {"rank_local_files", "inspect_local_files", "read_project_file"}:
            self.refresh = first

    def context(self):
        # Una observación guardada es histórica. El modelo vuelve a obtener los datos
        # con el permiso actual antes de usarlos como evidencia del estado presente.
        steps = [{"herramienta": s["tool"], "estado": s["status"],
                  **({"id_ejecución": s["run_id"]} if s.get("run_id") else {}),
                  "argumentos": excerpt(json.dumps(s["arguments"], ensure_ascii=False), 900) if not s["effect"] else None}
                 for s in self.state["steps"][-10:]]
        last_pages = {}
        for step in self.state["steps"]:
            if step.get("page"):
                page = step["page"]
                last_pages[page["id"]] = step["result"]
        return ("Progreso anterior (datos): " + json.dumps({"pasos": steps,
                "últimas_salidas_guardadas": list(last_pages.values())[-3:],
                "llamadas_aún_pendientes": self.state.get("pending", [])}, ensure_ascii=False) +
                "\nRetoma el objetivo y sus restricciones. Revalida las lecturas en orden de dependencia. "
                "Si una operación de cambio quedó sin confirmar, verifica su efecto antes de proponer otra acción.")

    def repeated_effect(self, name, arguments):
        if self.previous and self.previous[2]["scope"] == self.state["scope"]:
            for step in reversed(self.previous[2]["steps"]):
                if (step["effect"] and step["tool"] == name and step["status"] != "sin ejecutar"
                        and (step["status"] == "sin confirmar" or step["arguments"] == arguments)):
                    return step
        return next((s for s in reversed(self.state["steps"])
                     if s["effect"] and s["tool"] == name and s["status"] != "sin ejecutar"
                     and (s["status"] == "sin confirmar" or s["arguments"] == arguments)), None)

    def unconfirmed(self):
        return [s for s in self.state["steps"] if s["effect"] and s["status"] == "sin confirmar"]

    def verify_process(self, run_id, state, *, cancellation_checked):
        """Reconcilia el efecto sin reemplazar su observación de salida original."""
        def verified(step):
            return (step.get("run_id") == run_id and step.get("effect") and step["status"] == "sin confirmar"
                    and (step["tool"] == "iniciar_proceso"
                         or step["tool"] == "cancelar_proceso" and cancellation_checked))

        for step in self.state["steps"]:
            if verified(step):
                step.update(status="registro comprobado", process_state=state)
        if self.previous and self.previous[2]["scope"] == self.state["scope"]:
            message_id, version, previous = self.previous
            if any(verified(step) for step in previous["steps"]):
                snapshot = {**previous, "steps": [dict(step, status="registro comprobado", process_state=state)
                                                   if verified(step) else step for step in previous["steps"]]}
                self.previous = (message_id, self.save(message_id, version, snapshot), snapshot)

    def process_positions(self):
        if self._positions is None:
            self._positions = (self.saved_process_positions(self.chat_id, self.state["scope"])
                               if self.saved_process_positions else {})
        return self._positions

    def dispatched(self, file_path=None):
        step = self.state["steps"][-1]
        if step["effect"]:
            step["status"] = "sin confirmar"
            if file_path is not None:
                step["verified_path"] = str(file_path)
            self.persist()

    def persist(self):
        self.version = self.save(self.message_id, self.version, self.state)

    def start(self, name, arguments, effect, remaining):
        step = {"tool": name, "arguments": arguments, "effect": effect,
                "status": "sin ejecutar" if effect else "sin confirmar"}
        self.state["steps"].append(step)
        self.state["pending"] = remaining
        self.persist()
        return step

    def observe(self, step, result, status):
        if step["effect"] and step["status"] == "sin ejecutar":
            status = "sin ejecutar"
        step.update(status=status, result=result)
        self.persist()
        if step["tool"] == "iniciar_proceso" and step.get("run_id"):
            self.process_positions().setdefault(step["run_id"], 0)
        if page := step.get("page"):
            positions = self.process_positions()
            positions[page["id"]] = max(page["cursor"], positions.get(page["id"], 0))

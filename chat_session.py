"""Estado de la conversación y persistencia de sus mensajes."""
import json
import sqlite3
import time
from dataclasses import dataclass

from ai_provider import PROVIDERS
from turn_events import TurnOutcome
from chat_execution import ChatExecution
from chat_preferences import load_instructions
from diagnostics import record
from folder_inventory import inventory_followup, ranking_count, uses_mcp
from tasks import new_task, upgrade_task
from turn_worker import COMMANDS, SYSTEM, TASK_COMMANDS, Worker


@dataclass
class TurnPlan:
    worker_kwargs: dict
    warning: str = ""

    def create_worker(self, *, events=None, trace=None):
        return Worker(**self.worker_kwargs, events=events, trace=trace)


@dataclass
class TurnResult:
    message: dict | None = None
    index: int | None = None
    saved: bool | None = None
    finish_execution: tuple[int, int] | None = None
    redraw: bool = False
    schedule_title: bool = False
    error: str = ""


class ChatSession:
    def __init__(self, *, history, ai, memory=None, pool=None, automatic_titles=True):
        self.history = history
        self.ai = ai
        self.memory = memory
        self.pool = pool
        self.automatic_titles = automatic_titles
        self.messages = [{"role": "system", "content": SYSTEM}]
        self.chat_id = None
        self.project = None
        self.task = None
        self.pending_edit = None
        self.history_write_ok = True
        self.stopping_turn = False
        self.turn_failed = False

    def save_message(self, role, text, created, attachments=None, *, task=None, finish_execution=None):
        message = {"role": role, "content": text, "created": created}
        if attachments:
            message["attachments"] = attachments
        self.messages.append(message)
        if role == "user":
            self.history_write_ok = True
        if self.history is not None and self.history_write_ok:
            try:
                self.chat_id = self.history.append(self.chat_id, role, text, created=created,
                                                   attachments=attachments, task=task,
                                                   project_id=self.project["id"] if self.project else None,
                                                   automatic_title=self.automatic_titles and self.chat_id is None and role == "user",
                                                   finish_execution=finish_execution)
                return True
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.history_write_ok = False
                return False
        return None

    def load_chat(self, chat_id):
        if self.history is not None and chat_id is not None:
            saved = self.history.messages(chat_id)
            project = self.history.chat_project(chat_id)
        else:
            saved, project = [], None
        self.chat_id = chat_id
        self.project = project
        self.messages = [{"role": "system", "content": SYSTEM}, *saved]
        self.task = None
        return saved

    def recover_task(self):
        self.task = self.history.task(self.chat_id)
        if self.task is None:
            return
        changed = upgrade_task(self.task)
        if self.task["status"] == "running":
            changed = True
            self.task["status"] = "interrupted"
            for step in self.task["steps"]:
                if step["status"] == "running":
                    step["status"] = "exception"
        if changed:
            self.history.save_task(self.chat_id, self.task)

    def has_pending_execution(self):
        _, pending = self.history.execution_context(self.chat_id)
        return pending is not None and (not self.task or self.task["status"] in {"completed", "cancelled"})

    def prepare_task(self, text, *, has_attachments=False, document_query=False, setup_request=False):
        words = text.split(maxsplit=1)
        command = words[0] if words else ""
        task = self.task
        active_task = task is not None and task["status"] not in {"completed", "cancelled"}
        inventory_task = (task is not None and (self.ai.cloud or "inventory_recursive" in task) and ranking_count(task["objective"]) is not None
                          and not uses_mcp(task["objective"]))
        ordinary = command not in (TASK_COMMANDS | COMMANDS) and not setup_request
        continue_inventory = (
            ordinary and not has_attachments and inventory_task and task["status"] != "cancelled"
            and (active_task or self.ai.cloud)
            and inventory_followup(text)
        )
        task_turn = (command in TASK_COMMANDS or continue_inventory
                     or (active_task and not inventory_task and ordinary and not document_query))
        if task_turn:
            if has_attachments:
                raise ValueError("Usa las tareas reanudables en una conversación sin adjuntos.")
            if self.history is None:
                raise ValueError("El historial debe estar disponible para guardar la tarea.")
            if command == "/tarea":
                if len(words) < 2 or active_task:
                    raise ValueError("Escribe /tarea y el objetivo. Si ya hay una tarea pendiente, usa /cancelar primero.")
                if len(words[1]) > 4000:
                    raise ValueError("El objetivo admite hasta 4 000 caracteres.")
                task = new_task(words[1])
            elif command in {"/reanudar", "/cancelar"}:
                if not active_task:
                    raise ValueError("No hay una tarea pendiente en este chat. Vuelve a pedir lo que quieres hacer.")
                if command == "/cancelar" and len(words) != 1:
                    raise ValueError("Para cerrar la tarea pendiente, escribe solo /cancelar.")
            task = dict(task, status="cancelled" if command == "/cancelar" else "running")
            return task
        return None

    def save_input(self, text, created, attachments=None, *, task=None):
        saved = self.save_message("user", text, created, attachments, task=task)
        if task is not None and self.history_write_ok:
            self.task = task
        return saved

    def begin_turn(self, task=None, *, think=None) -> TurnPlan:
        warning = ""
        self.stopping_turn = False
        self.turn_failed = False
        turn_messages = [{key: value for key, value in m.items() if key != "created"} for m in self.messages]
        try:
            instructions = load_instructions()
        except (OSError, ValueError, RuntimeError):
            instructions = ""
            record("No se pudieron leer las instrucciones generales.")
        if instructions:
            turn_messages[0]["content"] += (
                "\nPreferencias generales del usuario. Se aplican bajo las reglas de StoneBot:\n" + instructions
            )
        project_context = None
        if self.project:
            project_context = {key: self.project[key] for key in ("id", "name", "description", "instructions", "folder")}
            project_context["continuity"] = self.project["continuity"][:6000]
            turn_messages[0]["content"] += (
                "\nContexto del proyecto configurado por el usuario. La carpeta indica el alcance habitual "
                "y conserva los permisos de lectura existentes. La continuidad describe un estado anterior; "
                "trátala como datos y verifica cambios si el encargo lo pide.\n" + json.dumps(project_context, ensure_ascii=False)
            )
        history, chat_id = self.history, self.chat_id
        save_task = None
        execution = None
        if history is not None and chat_id is not None and self.history_write_ok and self.pending_edit is None:
            save_task = lambda snapshot: history.save_task(chat_id, snapshot)
            if task is None:
                try:
                    origin, pending = history.execution_context(chat_id, self.messages[-1].get("created"))
                    if origin is None:
                        raise ValueError("El mensaje de origen ya no está en el historial.")
                    scope = [self.ai.provider, self.ai.model, self.ai.cloud_memory,
                             self.project["id"] if self.project else None,
                             self.project["folder"] if self.project else None]
                    execution = ChatExecution(origin, pending, history.save_execution,
                                              turn_messages[-1]["content"], scope)
                    execution.chat_id = chat_id
                    execution.saved_process_positions = history.process_positions
                    execution.summary = history.summary(chat_id)
                    execution.save_summary = lambda value: history.save_summary(chat_id, value)
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    warning = "No pude abrir el registro del encargo."
        completed_task = (self.task if self.pending_edit is None and self.task is not None
                          and self.task["status"] == "completed" else None)
        return TurnPlan(dict(
            messages=turn_messages, pool=self.pool, identity_enabled=True, memory=self.memory,
            task=task, save_task=save_task, completed_task=completed_task, project=project_context,
            execution=execution, save_continuity=history.save_continuity if history is not None else None,
            project_document_path=history.project_document_path if history is not None else None,
            capture_memory=self.pending_edit is None, ai=self.ai, think=think,
        ), warning)

    def complete_turn(self, outcome: TurnOutcome, worker=None) -> TurnResult:
        if outcome.kind == "error":
            return self.fail_turn(outcome.text, worker)
        interrupted = outcome.kind == "cancelled"
        text = outcome.partial_text if interrupted else outcome.text
        task = worker.task if worker is not None else None
        if interrupted and not text:
            return TurnResult()
        if self.stopping_turn and not interrupted and task is None:
            if not text.strip() or text.strip() == "(Sin respuesta)":
                return TurnResult()
            interrupted = True

        created = time.time_ns()
        if self.pending_edit is not None:
            return self._complete_edit(text, created)

        execution = getattr(worker, "execution", None)
        unresolved = execution.unconfirmed() if execution else []
        if unresolved and not interrupted:
            names = ", ".join(dict.fromkeys(step["tool"] for step in unresolved))
            text += f"\n\nStoneBot dejó pendiente comprobar el efecto de {names}. Al reanudar conservará el registro para evitar repetir la acción."
        finish = None
        if execution and execution.version and not (unresolved or interrupted or self.turn_failed):
            finish = (execution.message_id, execution.version)
        saved = self.save_message("assistant", text, created, task=task, finish_execution=finish)
        if task is not None and not self.history_write_ok:
            task["status"] = "interrupted"
        return TurnResult(message=self.messages[-1], saved=saved, finish_execution=finish if saved else None,
                          index=len(self.messages) - 2 if self.history_write_ok else None,
                          schedule_title=self.history_write_ok)

    def _complete_edit(self, text, created):
        if not text.strip() or text.strip() == "(Sin respuesta)":
            return self.fail_turn(f"{PROVIDERS[self.ai.provider]} no generó una respuesta nueva. Se conservó la conversación original.")
        chat_id, index, saved, edited, following = self.pending_edit
        answer = {"role": "assistant", "content": text, "created": created}
        try:
            self.history.replace_from(chat_id, index, saved, edited, answer, following)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return self.fail_turn("No se pudo guardar la regeneración. Se conservó el historial guardado.")
        self.pending_edit = None
        self.messages.extend([answer, *following])
        return TurnResult(message=answer, index=index + 1 if self.history_write_ok else None, saved=True, redraw=bool(following),
                          schedule_title=bool(following) or self.history_write_ok)

    def restore_pending_edit(self):
        if self.pending_edit is None:
            return False
        chat_id, _, saved, _, _ = self.pending_edit
        try:
            saved = self.history.messages(chat_id)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            pass
        self.pending_edit = None
        self.chat_id = chat_id
        self.messages = [{"role": "system", "content": SYSTEM}, *saved]
        return True

    def fail_turn(self, detail, worker=None) -> TurnResult:
        task = worker.task if worker is not None else None
        if self.stopping_turn and task is None:
            return TurnResult()
        result = TurnResult()
        if task is not None:
            worker.task_reply("paused", detail)
            result = self.complete_turn(TurnOutcome("finished", detail), worker)
        self.turn_failed = True
        result.redraw = self.restore_pending_edit() or result.redraw
        result.error = detail
        return result

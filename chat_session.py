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
from turn_worker import SYSTEM, Worker


@dataclass
class TurnPlan:
    worker_kwargs: dict
    warning: str = ""

    def create_worker(self):
        return Worker(**self.worker_kwargs)


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
    def __init__(self, *, history, ai, memory=None, pool=None):
        self.history = history
        self.ai = ai
        self.memory = memory
        self.pool = pool
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
                                                   automatic_title=self.chat_id is None and role == "user",
                                                   finish_execution=finish_execution)
                return True
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.history_write_ok = False
                return False
        return None

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

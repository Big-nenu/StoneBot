"""Estado de la conversación y persistencia de sus mensajes."""
import json
import sqlite3
from dataclasses import dataclass

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

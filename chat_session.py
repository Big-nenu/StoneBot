"""Estado de la conversación y persistencia de sus mensajes."""
import sqlite3

from turn_worker import SYSTEM


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

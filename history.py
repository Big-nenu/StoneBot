"""Almacenamiento local de conversaciones, separado de la memoria."""
import json
import sqlite3
import time
from contextlib import closing, contextmanager

from mcp_client import data_path
from stonebot_engine import check_db_path


class History:
    def __init__(self):
        self.path = data_path("conversations.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS message (
                    id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chat(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')), content TEXT NOT NULL,
                    created INTEGER, attachments TEXT
                );
                CREATE INDEX IF NOT EXISTS messages_by_chat ON message(chat_id, id);
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(message)")}
            if "created" not in columns:
                conn.execute("ALTER TABLE message ADD COLUMN created INTEGER")
            if "attachments" not in columns:
                conn.execute("ALTER TABLE message ADD COLUMN attachments TEXT")

    @contextmanager
    def connect(self):
        path = check_db_path(self.path, self.path.parent)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    def append(self, chat_id, role, content, *, created=None, attachments=None):
        now = time.time_ns() if created is None else created
        with self.connect() as conn:
            if chat_id is None:
                title = " ".join(content.split())
                title = title if len(title) <= 60 else title[:59].rstrip() + "…"
                chat_id = conn.execute("INSERT INTO chat(title, updated) VALUES (?, ?)",
                                       (title, now)).lastrowid
            self.insert_message(conn, chat_id, role, content, now, attachments)
            conn.execute("UPDATE chat SET updated=? WHERE id=?", (now, chat_id))
        return chat_id

    def find(self, query=""):
        needle = query.strip().casefold()
        with self.connect() as conn:
            conn.create_function("casefold", 1, str.casefold, deterministic=True)
            return conn.execute("""
                SELECT c.id, c.title FROM chat AS c
                WHERE ? = '' OR instr(casefold(c.title), ?) OR EXISTS (
                    SELECT 1 FROM message AS m WHERE m.chat_id = c.id AND instr(casefold(m.content), ?)
                )
                ORDER BY c.updated DESC, c.id DESC
            """, (needle, needle, needle)).fetchall()

    def messages(self, chat_id):
        with self.connect() as conn:
            return [message for _, message in self.message_rows(conn, chat_id)]

    @staticmethod
    def message_rows(conn, chat_id):
        rows = []
        for mid, role, content, created, attachments in conn.execute(
                "SELECT id, role, content, created, attachments FROM message WHERE chat_id=? ORDER BY id", (chat_id,)):
            message = dict(role=role, content=content, created=created)
            if attachments:
                message["attachments"] = json.loads(attachments)
            rows.append((mid, message))
        return rows

    @staticmethod
    def insert_message(conn, chat_id, role, content, created, attachments):
        packed = json.dumps(attachments, ensure_ascii=False) if attachments else None
        conn.execute("INSERT INTO message(chat_id, role, content, created, attachments) VALUES (?, ?, ?, ?, ?)",
                     (chat_id, role, content, created, packed))

    def replace_from(self, chat_id, index, expected, edited, answer):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = self.message_rows(conn, chat_id)
            current = [message for _, message in rows]
            if current != expected or not 0 <= index < len(rows) or current[index]["role"] != "user":
                raise ValueError("La conversación cambió durante la regeneración.")
            conn.execute("DELETE FROM message WHERE chat_id=? AND id>=?", (chat_id, rows[index][0]))
            for item in (edited, answer):
                self.insert_message(conn, chat_id, item["role"], item["content"], item["created"], item.get("attachments"))
            conn.execute("UPDATE chat SET updated=? WHERE id=?", (answer["created"], chat_id))

    def rename(self, chat_id, title):
        title = title.strip()
        if not title:
            raise ValueError("El título no puede estar vacío.")
        with self.connect() as conn:
            conn.execute("UPDATE chat SET title=? WHERE id=?", (title, chat_id))

    def delete(self, chat_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM chat WHERE id=?", (chat_id,))

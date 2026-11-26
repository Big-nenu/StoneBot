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
                CREATE TABLE IF NOT EXISTS chat_execution (
                    message_id INTEGER PRIMARY KEY REFERENCES message(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_summary (
                    chat_id INTEGER PRIMARY KEY REFERENCES chat(id) ON DELETE CASCADE, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_task (
                    chat_id INTEGER PRIMARY KEY REFERENCES chat(id) ON DELETE CASCADE, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    instructions TEXT NOT NULL, folder TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                    continuity TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS project_document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    UNIQUE(project_id, path)
                );
                CREATE TABLE IF NOT EXISTS project_sequence (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1), last_id INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO project_sequence SELECT 1, COALESCE(MAX(id), 0) FROM project;
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(message)")}
            if "created" not in columns:
                conn.execute("ALTER TABLE message ADD COLUMN created INTEGER")
            if "attachments" not in columns:
                conn.execute("ALTER TABLE message ADD COLUMN attachments TEXT")
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            chat_columns = {row[1] for row in conn.execute("PRAGMA table_info(chat)")}
            if "project_id" not in chat_columns:
                conn.execute("ALTER TABLE chat ADD COLUMN project_id INTEGER REFERENCES project(id) ON DELETE SET NULL")
            if "pinned" not in chat_columns:
                conn.execute("ALTER TABLE chat ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            if "title_pending" not in chat_columns:
                conn.execute("ALTER TABLE chat ADD COLUMN title_pending INTEGER NOT NULL DEFAULT 0")
            if "continuity" not in {row[1] for row in conn.execute("PRAGMA table_info(project)")}:
                conn.execute("ALTER TABLE project ADD COLUMN continuity TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE INDEX IF NOT EXISTS chat_project ON chat(project_id, updated)")

    @contextmanager
    def connect(self):
        path = check_db_path(self.path, self.path.parent)
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn

    def append(self, chat_id, role, content, *, created=None, attachments=None, task=None, project_id=None,
               automatic_title=False, finish_execution=None):
        now = time.time_ns() if created is None else created
        with self.connect() as conn:
            if chat_id is None:
                title = "Nuevo chat" if automatic_title else " ".join(content.split())
                title = title if len(title) <= 60 else title[:59].rstrip() + "…"
                chat_id = conn.execute("INSERT INTO chat(title, updated, project_id, title_pending) VALUES (?, ?, ?, ?)",
                                       (title, now, project_id, automatic_title)).lastrowid
            self.insert_message(conn, chat_id, role, content, now, attachments)
            if finish_execution is not None:
                origin, version = finish_execution
                updated = conn.execute("""UPDATE chat_execution SET finished=1 WHERE message_id=? AND version=?
                    AND finished=0 AND message_id IN (SELECT id FROM message WHERE chat_id=?)""",
                                       (origin, version, chat_id))
                if updated.rowcount != 1:
                    raise ValueError("El estado del encargo cambió antes de guardar la respuesta.")
            if task is not None:
                self.write_task(conn, chat_id, task)
            conn.execute("UPDATE chat SET updated=? WHERE id=?", (now, chat_id))
        return chat_id

    def execution_context(self, chat_id, created=None):
        with self.connect() as conn:
            current = conn.execute("""SELECT MAX(id) FROM message WHERE chat_id=? AND role='user'
                AND (? IS NULL OR created=?)""", (chat_id, created, created)).fetchone()[0]
            row = conn.execute("""SELECT e.message_id,e.version,e.snapshot FROM chat_execution e
                JOIN message m ON m.id=e.message_id WHERE m.chat_id=? AND e.finished=0
                ORDER BY e.message_id DESC LIMIT 1""", (chat_id,)).fetchone()
        return current, (row[0], row[1], json.loads(row[2])) if row else None

    def save_execution(self, message_id, version, snapshot):
        data = json.dumps(snapshot, ensure_ascii=False)
        with self.connect() as conn:
            if not version:
                conn.execute("INSERT INTO chat_execution(message_id,version,snapshot) VALUES (?,1,?)", (message_id, data))
            else:
                change = conn.execute("""UPDATE chat_execution SET version=version+1,snapshot=?
                    WHERE message_id=? AND version=? AND finished=0""", (data, message_id, version))
                if change.rowcount != 1:
                    raise ValueError("Este encargo fue actualizado en otra sesión.")
        return version + 1

    def process_positions(self, chat_id, scope):
        # Las páginas y sus cursores se confirman juntos en save_execution.
        # Incluye turnos ya cerrados y diarios anteriores a esta versión.
        with self.connect() as conn:
            rows = conn.execute("""
                WITH observations AS (
                    SELECT step.value ->> '$.tool' AS tool, step.value ->> '$.run_id' AS dispatched,
                           CASE WHEN json_valid(step.value ->> '$.result')
                                THEN step.value ->> '$.result' END AS page
                    FROM message m JOIN chat_execution e ON e.message_id=m.id,
                         json_each(e.snapshot,'$.steps') step
                    WHERE m.chat_id=? AND json_extract(e.snapshot,'$.scope')=json(?)
                      AND step.value ->> '$.tool' IN ('iniciar_proceso','consultar_proceso','cancelar_proceso')
                )
                SELECT COALESCE(dispatched, page ->> '$.id') AS run_id,
                       MAX(CASE WHEN page ->> '$.salida' != '' THEN page ->> '$.cursor' ELSE 0 END)
                FROM observations GROUP BY run_id
                HAVING MAX(tool='iniciar_proceso' AND dispatched IS NOT NULL)
            """, (chat_id, json.dumps(scope, ensure_ascii=False))).fetchall()
        return dict(rows)

    def summary(self, chat_id):
        with self.connect() as conn:
            row = conn.execute("SELECT snapshot FROM chat_summary WHERE chat_id=?", (chat_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_summary(self, chat_id, snapshot):
        with self.connect() as conn:
            conn.execute("""INSERT INTO chat_summary VALUES (?,?) ON CONFLICT(chat_id)
                DO UPDATE SET snapshot=excluded.snapshot""", (chat_id, json.dumps(snapshot, ensure_ascii=False)))

    def task(self, chat_id):
        with self.connect() as conn:
            row = conn.execute("SELECT snapshot FROM chat_task WHERE chat_id=?", (chat_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_task(self, chat_id, task):
        with self.connect() as conn:
            self.write_task(conn, chat_id, task)

    @staticmethod
    def write_task(conn, chat_id, task):
        conn.execute("INSERT INTO chat_task VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET snapshot=excluded.snapshot",
                     (chat_id, json.dumps(task, ensure_ascii=False)))

    def find(self, query="", *, project_id=None, include_metadata=False):
        needle = query.strip().casefold()
        columns = "c.id, c.title, c.updated, c.pinned" if include_metadata else "c.id, c.title"
        with self.connect() as conn:
            conn.create_function("casefold", 1, str.casefold, deterministic=True)
            return conn.execute(f"""
                SELECT {columns} FROM chat AS c
                WHERE (? IS NULL OR c.project_id = ?) AND (? = '' OR instr(casefold(c.title), ?) OR EXISTS (
                    SELECT 1 FROM message AS m WHERE m.chat_id = c.id AND instr(casefold(m.content), ?)
                ))
                ORDER BY c.updated DESC, c.id DESC
            """, (project_id, project_id, needle, needle, needle)).fetchall()

    def projects(self):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("""
                SELECT p.*, count(c.id) AS chats, max(c.updated) AS updated
                FROM project p LEFT JOIN chat c ON c.project_id = p.id
                GROUP BY p.id ORDER BY p.pinned DESC, max(c.updated) DESC, p.name COLLATE NOCASE
            """)]

    def save_project(self, name, description, instructions, folder, project_id=None):
        name = name.strip()
        if not name:
            raise ValueError("Escribe un nombre para el proyecto.")
        with self.connect() as conn:
            if project_id is None:
                # Las correcciones guardadas usan el ID del proyecto y no deben heredarse al volver a crearlo.
                project_id, = conn.execute("""UPDATE project_sequence SET last_id =
                    MAX(last_id, (SELECT COALESCE(MAX(id), 0) FROM project)) + 1
                    WHERE singleton = 1 RETURNING last_id""").fetchone()
                conn.execute("INSERT INTO project(id, name, description, instructions, folder) VALUES (?, ?, ?, ?, ?)",
                             (project_id, name, description, instructions, folder))
            else:
                conn.execute("UPDATE project SET name=?, description=?, instructions=?, folder=? WHERE id=?",
                             (name, description, instructions, folder, project_id))
            return project_id

    def delete_project(self, project_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM project WHERE id=?", (project_id,))

    def pin_project(self, project_id, pinned):
        with self.connect() as conn:
            conn.execute("UPDATE project SET pinned=? WHERE id=?", (pinned, project_id))

    def save_continuity(self, project_id, text):
        with self.connect() as conn:
            updated = conn.execute("UPDATE project SET continuity=? WHERE id=?", (text.strip(), project_id))
            if not updated.rowcount:
                raise ValueError("El proyecto ya no está disponible.")

    def project_documents(self, project_id):
        with self.connect() as conn:
            return conn.execute("SELECT id, path FROM project_document WHERE project_id=? ORDER BY id",
                                (project_id,)).fetchall()

    def link_project_document(self, project_id, path):
        with self.connect() as conn:
            conn.execute("INSERT INTO project_document(project_id, path) VALUES (?, ?) "
                         "ON CONFLICT(project_id, path) DO NOTHING", (project_id, path))

    def unlink_project_document(self, project_id, document_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM project_document WHERE project_id=? AND id=?", (project_id, document_id))

    def project_document_path(self, project_id, document_id):
        with self.connect() as conn:
            row = conn.execute("SELECT path FROM project_document WHERE project_id=? AND id=?",
                               (project_id, document_id)).fetchone()
            return row[0] if row else None

    def project_chats(self):
        with self.connect() as conn:
            chats = {}
            for project_id, chat_id, title in conn.execute("""
                SELECT project_id, id, title FROM chat WHERE project_id IS NOT NULL
                ORDER BY project_id, updated DESC, id DESC
            """):
                chats.setdefault(project_id, []).append((chat_id, title))
            return chats

    def chat_project(self, chat_id):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT p.* FROM project p JOIN chat c ON c.project_id=p.id WHERE c.id=?",
                               (chat_id,)).fetchone()
            return dict(row) if row else None

    def move_chat(self, chat_id, project_id):
        with self.connect() as conn:
            conn.execute("UPDATE chat SET project_id=? WHERE id=?", (project_id, chat_id))

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

    def replace_from(self, chat_id, index, expected, edited, answer, following=()):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = self.message_rows(conn, chat_id)
            current = [message for _, message in rows]
            if current != expected or not 0 <= index < len(rows) or current[index]["role"] != "user":
                raise ValueError("La conversación cambió durante la regeneración.")
            conn.execute("DELETE FROM chat_summary WHERE chat_id=?", (chat_id,))
            conn.execute("DELETE FROM message WHERE chat_id=? AND id>=?", (chat_id, rows[index][0]))
            for item in (edited, answer, *following):
                self.insert_message(conn, chat_id, item["role"], item["content"], item["created"], item.get("attachments"))
            conn.execute("UPDATE chat SET updated=? WHERE id=?", (answer["created"], chat_id))

    def rename(self, chat_id, title):
        title = title.strip()
        if not title:
            raise ValueError("El título no puede estar vacío.")
        with self.connect() as conn:
            conn.execute("UPDATE chat SET title=?, title_pending=0 WHERE id=?", (title, chat_id))

    def title_pending(self, chat_id):
        with self.connect() as conn:
            row = conn.execute("SELECT title_pending FROM chat WHERE id=?", (chat_id,)).fetchone()
        return bool(row and row[0])

    def finish_title(self, chat_id, created, title):
        with self.connect() as conn:
            changed = conn.execute("""
                UPDATE chat SET title=?, title_pending=0
                WHERE id=? AND title_pending=1 AND ? = (
                    SELECT created FROM message WHERE chat_id=chat.id ORDER BY id LIMIT 1
                )
            """, (title, chat_id, created))
            return bool(changed.rowcount)

    def pin_chat(self, chat_id, pinned):
        with self.connect() as conn:
            conn.execute("UPDATE chat SET pinned=? WHERE id=?", (pinned, chat_id))

    def delete(self, chat_id):
        with self.connect() as conn:
            conn.execute("DELETE FROM chat WHERE id=?", (chat_id,))

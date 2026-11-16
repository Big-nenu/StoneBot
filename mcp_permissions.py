"""Autorizaciones persistentes, limitadas a herramientas de lectura."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing, contextmanager


RISKY = re.compile(
    r"delete|remove|unlink|purge|destroy|drop|truncate|write|edit|update|modify|overwrite|"
    r"rename|move|copy|append|mkdir|rmdir|chmod|chown|upload|insert|create|publish|send|"
    r"execute|shell|command|terminal|script|install|deploy|patch|kill|wipe|purchase|"
    r"(?:^|[_-])(?:set|run|exec|rm|cmd|bash|powershell)(?:$|[_-])|"
    r"eliminar|borrar|modificar|escribir|ejecutar|enviar|crear",
    re.I,
)


def safe_read(tool, arguments=None):
    annotations = tool.annotations
    if (annotations is None or annotations.readOnlyHint is not True
            or annotations.destructiveHint is True or RISKY.search(tool.name)):
        return False

    def safe_schema(schema):
        if isinstance(schema, list):
            return all(safe_schema(value) for value in schema)
        if not isinstance(schema, dict):
            return True
        properties = schema.get("properties")
        if isinstance(properties, dict) and any(RISKY.search(key) for key in properties):
            return False
        choices = schema.get("enum")
        if isinstance(choices, list) and any(isinstance(value, str) and RISKY.search(value) for value in choices):
            return False
        return all(safe_schema(value) for value in schema.values())

    def safe_values(value):
        if isinstance(value, list):
            return all(safe_values(item) for item in value)
        if not isinstance(value, dict):
            return True
        for key, item in value.items():
            if (key.casefold() in {"action", "operation", "method", "mode", "command", "script"}
                    and isinstance(item, str) and RISKY.search(item)):
                return False
            if not safe_values(item):
                return False
        return True

    return safe_schema(tool.inputSchema) and safe_values(arguments)


def permission_signature(server, tool):
    fields = ("transport", "url", "token_env", "command", "args")
    payload = [dict((key, server.get(key)) for key in fields), tool.model_dump(mode="json")]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@contextmanager
def database():
    from mcp_client import data_path
    from stonebot_engine import check_db_path

    path = data_path("mcp_permissions.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(check_db_path(path, path.parent))) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS permission (
                server TEXT NOT NULL, tool TEXT NOT NULL, signature TEXT NOT NULL,
                PRIMARY KEY(server, tool)
            )
        """)
        yield conn


def allowed(server, tool, signature):
    with database() as conn:
        return conn.execute("SELECT 1 FROM permission WHERE server=? AND tool=? AND signature=?",
                            (server, tool, signature)).fetchone() is not None


def remember(server, tool, signature):
    with database() as conn:
        conn.execute("INSERT OR REPLACE INTO permission VALUES (?, ?, ?)", (server, tool, signature))


def list_permissions(server):
    with database() as conn:
        return [row[0] for row in conn.execute("SELECT tool FROM permission WHERE server=? ORDER BY tool", (server,))]


def revoke(server, tool=None):
    with database() as conn:
        if tool is None:
            conn.execute("DELETE FROM permission WHERE server=?", (server,))
        else:
            conn.execute("DELETE FROM permission WHERE server=? AND tool=?", (server, tool))

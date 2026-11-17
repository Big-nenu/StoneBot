"""Observaciones sobre operaciones MCP y resultados de tareas de StoneBot."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing, contextmanager

from mcp_client import data_path
from stonebot_engine import check_db_path


OBSERVATIONS = {
    "response": "MCP devolvió texto o datos estructurados y no marcó error.",
    "no_text": "MCP respondió sin marcar error, sin texto ni datos estructurados.",
    "tool_error": "MCP devolvió una respuesta marcada como error.",
    "timeout": "La llamada terminó por tiempo de espera.",
    "exception": "La llamada terminó con una excepción antes de obtener un resultado utilizable.",
}
SUCCEEDED = {"response", "no_text"}


@contextmanager
def connect():
    path = data_path("experiences.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(check_db_path(path, path.parent))) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("""CREATE TABLE IF NOT EXISTS observation (
            id INTEGER PRIMARY KEY, server TEXT NOT NULL, tool TEXT NOT NULL,
            outcome TEXT NOT NULL, observed TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS observation_tool ON observation(server, tool, id)")
        db.execute("""CREATE TABLE IF NOT EXISTS folder_ranking (
            id INTEGER PRIMARY KEY, scope TEXT NOT NULL, method TEXT NOT NULL,
            outcome TEXT NOT NULL, omitted INTEGER, observed TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS folder_ranking_scope ON folder_ranking(scope, id)")
        db.execute("""CREATE TABLE IF NOT EXISTS task_result (
            id INTEGER PRIMARY KEY, scope TEXT NOT NULL, methods TEXT NOT NULL,
            outcome TEXT NOT NULL, observed TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            family TEXT NOT NULL DEFAULT ''
        )""")
        if "family" not in {row[1] for row in db.execute("PRAGMA table_info(task_result)")}:
            db.execute("ALTER TABLE task_result ADD COLUMN family TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS task_result_scope ON task_result(scope, id)")
        db.execute("CREATE INDEX IF NOT EXISTS task_result_family ON task_result(family, id)")
        yield db


def task_scope(task):
    scope = [task["objective"], task.get("clarifications", [])]
    if task.get("project_id") is not None:
        scope.append(task["project_id"])
    return hashlib.sha256(json.dumps(scope).encode()).hexdigest()


def task_family(task):
    # shortcut: la recuperación por similitud cubre revisiones de proyectos; ampliar al validar más tipos.
    text = task["objective"]
    review = re.search(r"\b(?:revis\w*|retom\w*|resum\w*|estado|avances?|pendientes?|"
                       r"d[oó]nde (?:me )?qued\w*|qu[eé] sigue|review|status)\b", text, re.I)
    project = task.get("project_id") is not None or re.search(r"\b(?:proyecto|repositorio|repo|readme)\b", text, re.I)
    return "revision_proyecto" if review and project else ""


def record_task_result(task, outcome):
    methods = sorted({step["tool"] for step in task["steps"] if step["status"] not in {"not_run", "running"}})
    if methods:
        with connect() as db:
            db.execute("INSERT INTO task_result(scope, methods, outcome, family) VALUES (?, ?, ?, ?)",
                       (task_scope(task), json.dumps(methods), outcome, task_family(task)))


def task_results(task):
    scope, family = task_scope(task), task_family(task)
    with connect() as db:
        return [dict(row) for row in db.execute(
            """SELECT id, methods, outcome, scope=? AS mismo_encargo
               FROM task_result WHERE scope=? OR (family=? AND family<>'')
               ORDER BY mismo_encargo DESC, id DESC LIMIT 3""",
            (scope, scope, family),
        )]


def ranking_scope(folder, count, recursive):
    scope = [os.path.normcase(os.path.abspath(folder)), count, recursive]
    return hashlib.sha256(json.dumps(scope).encode()).hexdigest()


def record_ranking(scope, method, outcome, omitted=None):
    with connect() as db:
        db.execute("INSERT INTO folder_ranking(scope, method, outcome, omitted) VALUES (?, ?, ?, ?)",
                   (scope, method, outcome, omitted))


def ranking_evidence(scope):
    with connect() as db:
        rows = db.execute("""SELECT id, method, outcome, omitted FROM folder_ranking
            WHERE scope=? AND id IN (SELECT max(id) FROM folder_ranking WHERE scope=? GROUP BY method)
            ORDER BY id DESC""", (scope, scope))
        return [dict(row) for row in rows]


def record_experience(server, tool, outcome):
    if outcome not in OBSERVATIONS:
        raise ValueError("Resultado de experiencia desconocido.")
    with connect() as db:
        return db.execute("INSERT INTO observation(server, tool, outcome) VALUES (?, ?, ?)",
                          (server, tool, outcome)).lastrowid


def evidence(row):
    outcome = row["outcome"]
    return dict(id=row["id"], observado_utc=row["observed"],
                tipo="hecho observado" if outcome in SUCCEEDED else "error observado",
                resultado=OBSERVATIONS[outcome])


def query_experiences(busqueda: str) -> str:
    """Recupera experiencias propias por nombre de servidor o herramienta MCP. Usa una cadena vacía para las recientes."""
    if not isinstance(busqueda, str) or len(busqueda) > 256:
        raise ValueError("La búsqueda de experiencias debe tener hasta 256 caracteres.")
    terms = busqueda.casefold().split()
    with connect() as db:
        db.execute("BEGIN")
        db.create_function("casefold", 1, str.casefold, deterministic=True)
        rows = db.execute("""
            SELECT o.* FROM observation o JOIN (
                SELECT max(id) AS latest FROM observation GROUP BY server, tool
            ) latest ON o.id = latest.latest
            WHERE NOT EXISTS (
                SELECT 1 FROM json_each(?) term
                WHERE instr(casefold(o.server || ' ' || o.tool), term.value) = 0
            )
            ORDER BY o.id DESC LIMIT 5
        """, (json.dumps(terms),)).fetchall()
        experiences = []
        for row in rows:
            succeeded = row["outcome"] in SUCCEEDED
            previous = db.execute("""
                SELECT * FROM observation WHERE server=? AND tool=? AND id<?
                AND (outcome IN ('response', 'no_text')) != ?
                ORDER BY id DESC LIMIT 1
            """, (row["server"], row["tool"], row["id"], succeeded)).fetchone()
            item = dict(servidor=row["server"], herramienta=row["tool"], intento="ejecutar la herramienta",
                        evidencia_actual=evidence(row),
                        conclusion=("La última ejecución obtuvo una respuesta sin error de MCP." if succeeded
                                    else "La última ejecución no obtuvo una respuesta satisfactoria."),
                        incertidumbre="Se desconoce si se repetirá con otros argumentos o configuraciones.")
            if previous:
                item["evidencia_contraria_anterior"] = evidence(previous)
                item["hipotesis"] = "El resultado podría depender de las condiciones de ejecución; no se verificó la causa."
            experiences.append(item)
    return json.dumps(experiences, ensure_ascii=False)

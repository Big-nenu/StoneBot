"""Identidad declarada por el responsable del proyecto, fuera del historial."""
import sqlite3
from contextlib import closing, contextmanager

from mcp_client import data_path
from stonebot_engine import check_db_path


INITIAL_IDENTITY = {
    "nombre": "StoneBot",
    "creador": "Luis Eduardo Hernández Vargas",
    "github": "Big-nenu",
    "origen": "Proyecto experimental de agente local basado en un motor derivado de StoneWave.",
    "separacion": "StoneWave y StoneBot son proyectos diferentes con memorias separadas.",
    "desarrollo": "StoneBot es desarrollado por Luis con asistencia de herramientas de IA.",
}


@contextmanager
def identity_store():
    path = data_path("identity.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(check_db_path(path, path.parent))) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS identity (field TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.executemany("INSERT OR IGNORE INTO identity VALUES (?, ?)", INITIAL_IDENTITY.items())
        yield db


def load_identity():
    with identity_store() as db:
        return dict(db.execute("SELECT field, value FROM identity"))


def update_identity(field, value):
    value = value.strip()
    if field not in INITIAL_IDENTITY or not 1 <= len(value) <= 400 or not value.isprintable():
        raise ValueError("Campo de identidad inválido o valor fuera de 1 a 400 caracteres de una línea.")
    with identity_store() as db:
        db.execute("UPDATE identity SET value=? WHERE field=?", (value, field))

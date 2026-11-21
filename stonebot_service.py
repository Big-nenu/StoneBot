"""Servicio de memoria de StoneBot: el único dueño del motor y de memoria.db.

La aplicación, la línea de comandos (stonebot_memory.py) y el sueño automático
usan este módulo. Nadie más abre StoneBotEngine para trabajar con la memoria viva.

Dos protecciones evitan que la base se corrompa o se bloquee:
  - un candado interno (RLock): dentro del proceso, una operación de memoria a la vez;
  - un candado de proceso (stonebot.lock junto a la base): solo un proceso puede ser dueño.
    Lo suelta el sistema si el proceso muere, así que no queda "pegado".
"""
import functools
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from diagnostics import record
from experiences import connect, evidence
from stonebot_engine import StoneBotEngine, check_db_path, default_root
from stonebot_engine.safety import IsolationError, check_path

EXPERIENCES = "experiencias_mcp"
SCOPES = {"memoria": "default", "experiencias": EXPERIENCES}
LOCK_NAME = "stonebot.lock"

DB_PATH = default_root() / "memoria.db"
_memory = None


class AlreadyRunning(RuntimeError):
    """Otro proceso ya es el dueño de la memoria de StoneBot."""


_lock = threading.RLock()
_owners = {}  # ruta del candado -> archivo abierto que lo mantiene


def _try_lock(handle):
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle):
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


def _lock_path(db_path):
    database = Path(db_path).absolute()
    folder = database.parent
    if Path(check_db_path(database, folder)) != folder.resolve() / database.name:
        raise IsolationError(f"Base de memoria redirigida: {database}")
    expected = folder.resolve() / LOCK_NAME
    if Path(check_path(folder / LOCK_NAME, folder)) != expected:
        raise IsolationError(f"Candado de memoria redirigido: {expected}")
    return expected


def acquire_owner(db_path=None):
    """Se hace dueño de la memoria que vive junto a db_path (por defecto, la de StoneBot).

    Es idempotente dentro del proceso. Si otro proceso ya es el dueño, lanza AlreadyRunning."""
    path = _lock_path(DB_PATH if db_path is None else db_path)
    key = os.path.normcase(str(path))
    with _lock:
        if key in _owners:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        try:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")  # la región bloqueada es el primer byte
                handle.flush()
            _try_lock(handle)
        except OSError as exc:
            handle.close()
            raise AlreadyRunning(
                "StoneBot ya tiene abierta su memoria (la aplicación u otro proceso la está usando). "
                "Ciérralo e inténtalo de nuevo; desde el chat puedes usar /sueno o /integrar.") from exc
        _owners[key] = handle
        return path


@contextmanager
def memory_session(*, create=False):
    """Ejecuta una operación de CLI con acceso exclusivo al motor."""
    with _lock:
        owns_session = _memory is None and not _owners
        try:
            yield get_memory(create=create)
        finally:
            if owns_session:
                close()


def get_memory(*, create=False):
    """Motor de memoria de StoneBot: se crea una sola vez y se reutiliza. Toma el candado de proceso."""
    global _memory
    with _lock:
        if _memory is None:
            db_path = check_db_path(DB_PATH)
            if not create and not Path(db_path).is_file():
                raise FileNotFoundError(f"No existe la memoria de StoneBot: {DB_PATH}")
            key = os.path.normcase(str(_lock_path(DB_PATH)))
            already_owned = key in _owners
            acquire_owner()
            try:
                _memory = StoneBotEngine(db_path=db_path)
            except BaseException:
                if not already_owned:
                    _unlock(_owners.pop(key))
                raise
        return _memory


def close():
    """Cierra el motor y suelta el candado de proceso."""
    global _memory
    with _lock:
        try:
            if _memory is not None:
                _memory.close()
        finally:
            _memory = None
            for handle in list(_owners.values()):
                _unlock(handle)
            _owners.clear()


def _locked(function):
    """Una operación de memoria a la vez dentro del proceso (el motor no está hecho para llamadas simultáneas)."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _lock:
            return function(*args, **kwargs)
    return wrapper


# ----------------------------------------------------------------------
# Herramientas que recibe el modelo (los nombres y las descripciones no cambian)
# ----------------------------------------------------------------------

def _memory_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Se requiere texto no vacío.")
    return text.strip()


@_locked
def query_memory(text: str) -> str:
    """Busca recuerdos persistentes sobre el tema o pregunta indicada."""
    results = get_memory().query(_memory_text(text))
    if isinstance(results, str):
        return results
    return json.dumps([{"id": fact_id, "content": content} for _, fact_id, _, content in results],
                      ensure_ascii=False)


@_locked
def inject_memory(content: str) -> str:
    """Guarda un hecho o una preferencia duradera cuando el usuario pide recordarlo."""
    return get_memory().inject(_memory_text(content), source="chat", reinforce=False)


@_locked
def bridge_memory(topic_a: str, topic_b: str) -> str:
    """Busca recuerdos que conecten semánticamente los dos temas indicados."""
    result = get_memory().bridge(_memory_text(topic_a), _memory_text(topic_b))
    return json.dumps(result, ensure_ascii=False)


@_locked
def query_conclusions(text: str, ambito: str = "experiencias") -> str:
    """Busca hipótesis y conclusiones con sus evidencias. Ámbito: experiencias o memoria."""
    if ambito not in SCOPES:
        raise ValueError("Ámbito de conclusiones inválido.")
    engine = get_memory()
    namespace = SCOPES[ambito]
    matches = engine.query_conclusions(_memory_text(text), namespace)
    sources = {row["id"]: row["sources"] for row in engine.list_conclusions(namespace)}
    return json.dumps([{**row, "recuerdos_origen": sources.get(row["id"], [])} for row in matches],
                      ensure_ascii=False)


def integrate_experience(engine, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**63:
        raise ValueError("El ID de observación debe ser un entero positivo válido.")
    with connect() as db:
        row = db.execute("SELECT * FROM observation WHERE id=?", (observation_id,)).fetchone()
    if row is None:
        raise ValueError(f"No existe la observación MCP {observation_id}.")
    fact = evidence(row)
    content = (f"Evidencia MCP #{row['id']}, {fact['observado_utc']} UTC. "
               f"Servidor {json.dumps(row['server'], ensure_ascii=False)}, "
               f"herramienta {json.dumps(row['tool'], ensure_ascii=False)}. "
               f"{fact['tipo'].capitalize()}: {fact['resultado']}")
    # El sueño evalúa evidencias nuevas por incorporación; el recibo conserva la fecha observada.
    result = engine.inject(content, namespace=EXPERIENCES, pinned=True,
                           source=f"mcp-observation:{observation_id}", reinforce=False, distinct_source=True)
    if "ERROR" in result:
        raise RuntimeError(result)
    return result


MEMORY_TOOLS = {tool.__name__: tool for tool in (query_memory, inject_memory, bridge_memory, query_conclusions)}


@_locked
def list_memories():
    try:
        engine = get_memory()
    except FileNotFoundError:
        return []
    return [(archived, fact_id, content) for archived in (False, True)
            for fact_id, content, _, _ in engine.list_facts(archived=archived)]


@_locked
def change_memory(memory, new_content=None):
    archived, fact_id, expected = memory
    engine = get_memory()
    if not any(fid == fact_id and content == expected for fid, content, _, _ in engine.list_facts(archived=archived)):
        raise ValueError("El recuerdo cambió. Vuelve a elegirlo en la lista.")
    if new_content is None:
        result = engine.forget(fact_id, archived=archived)
        if result["status"] == "deleted":
            return None
    else:
        result = engine.update_memory(fact_id, _memory_text(new_content), archived=archived)
        if result["status"] == "updated":
            return False, result["id"], result["new"]
        if result["status"] == "error":
            raise ValueError("No pude guardar la corrección. Comprueba que Ollama esté disponible e inténtalo otra vez.")
    raise ValueError(result["message"])


# ----------------------------------------------------------------------
# Operaciones explícitas (comandos /sueno y /integrar, y la línea de comandos)
# ----------------------------------------------------------------------
@_locked
def dream(scope):
    """Sueña un ámbito ('memoria' o 'experiencias') y devuelve el resumen del motor."""
    if scope not in SCOPES:
        raise ValueError("Ámbito de sueño inválido.")
    return get_memory().dream(SCOPES[scope])


@_locked
def dream_if_due(scope):
    """Comprueba y ejecuta el sueño del ámbito sin soltar el candado del motor."""
    try:
        try:
            engine = get_memory()
        except FileNotFoundError:
            return
        if engine.dream_due(SCOPES[scope]):
            record(f"Sueño automático ({scope}) iniciado.")
            record(f"Sueño automático ({scope}): {dream(scope)}")
            from chat_preferences import load_obsidian_vault
            from stonebot_memory import publish_notes

            if vault := load_obsidian_vault():
                try:
                    data = engine.notes_data(SCOPES[scope], include_all_facts=True)
                    result = publish_notes(data, vault, scope)
                    record(f"Obsidian ({scope}): {result['written']} notas actualizadas, "
                           f"{result['conclusions']} conclusiones, {len(result['skipped'])} notas editadas conservadas.")
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                    record(f"Obsidian ({scope}), error de publicación: {exc!r}")
    except Exception as exc:
        record(f"Sueño automático ({scope}), error: {exc!r}")


@_locked
def integrate(observation_id):
    """Incorpora una observación MCP a la memoria (ver integrate_experience)."""
    return integrate_experience(get_memory(), observation_id)

"""Trabajos de terminal del chat. Un supervisor independiente conserva la salida y el estado."""
import codecs
import json
import locale
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import UUID

LIMIT = 4 * 1024 * 1024
PAGE = 8192
WINDOWS_BACKEND = os.name == "nt"
ACTIVE = ("preparando", "ejecutando")
SCHEMA = """
CREATE TABLE job(command TEXT, cwd TEXT, state TEXT, code INTEGER, cancel INTEGER DEFAULT 0,
                 heartbeat REAL, error TEXT DEFAULT '', truncated INTEGER DEFAULT 0);
CREATE TABLE output(seq INTEGER PRIMARY KEY, text TEXT);
"""


def location(folder, run_id):
    if not isinstance(run_id, str) or UUID(run_id).hex != run_id:
        raise ValueError("Identificador de ejecución inválido.")
    return folder / (run_id + ".sqlite3")


def command_spec(arguments):
    argv, cwd = arguments.get("argv"), arguments.get("cwd")
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and '\0' not in arg for arg in argv):
        raise ValueError("Indica el ejecutable y sus argumentos por separado.")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise ValueError("Indica un directorio de trabajo absoluto existente.")
    exe = Path(argv[0])
    if not exe.is_absolute() or not exe.is_file() or (os.name == "nt" and exe.suffix.lower() != ".exe"):
        raise ValueError("Indica la ruta absoluta del ejecutable (.exe en Windows).")
    return argv, cwd


def start(folder, run_id, arguments):
    argv, cwd = command_spec(arguments)
    folder.mkdir(parents=True, exist_ok=True)
    path = location(folder, run_id)
    path.touch(exist_ok=False)
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO job(command,cwd,state,heartbeat) VALUES(?,?,?,?)",
                   (json.dumps(argv), cwd, ACTIVE[0], time.time()))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.Popen([sys.executable, "-E", "-P", "-B", str(Path(__file__).resolve()), str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    except OSError as exc:
        with sqlite3.connect(path) as db:
            db.execute("UPDATE job SET state='fallido', error=?", (str(exc),))
        raise
    return inspect_run(folder, run_id)


def description(folder, run_id):
    path = location(folder, run_id)
    if not path.is_file():
        raise ValueError("Ejecución desconocida en este chat.")
    with sqlite3.connect(path) as db:
        command, cwd = db.execute("SELECT command,cwd FROM job").fetchone()
    return {"id": run_id, "argv": json.loads(command), "cwd": cwd}


def inspect_run(folder, run_id, cursor=0, *, cancel=False):
    path = location(folder, run_id)
    if not path.is_file() or type(cursor) is not int or cursor < 0:
        raise ValueError("Ejecución o cursor desconocido en este chat.")
    with sqlite3.connect(path) as db:
        if cancel:
            db.execute("UPDATE job SET cancel=1 WHERE state IN (?,?)", ACTIVE)
        if not cancel:
            db.execute("BEGIN")
        state, code, requested, heartbeat, error, truncated = db.execute(
            "SELECT state,code,cancel,heartbeat,error,truncated FROM job").fetchone()
        rows = db.execute("SELECT seq,text FROM output WHERE seq>? ORDER BY seq LIMIT 2", (cursor,)).fetchall()
    if state in ACTIVE and time.time() - heartbeat > 15:
        state = "sin confirmar"
    return dict(id=run_id, estado=state, codigo=code, cancelacion_solicitada=bool(requested),
                salida=rows[0][1] if rows else "", cursor=rows[0][0] if rows else cursor,
                hay_mas=len(rows) > 1, truncada=bool(truncated), error=error)


def capture(stream, path, errors):
    try:
        _capture(stream, path)
    except (OSError, sqlite3.Error) as exc:
        errors.append(str(exc))


def _capture(stream, path):
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace")
    retained = 0
    with stream, sqlite3.connect(path) as db:
        while True:
            raw = os.read(stream.fileno(), PAGE)
            chunk = decoder.decode(raw, final=not raw)
            with db:
                if retained < LIMIT and chunk:
                    db.execute("INSERT INTO output(text) VALUES(?)", (chunk[:LIMIT-retained],))
                if retained <= LIMIT < retained + len(chunk):
                    db.execute("UPDATE job SET truncated=1")
            retained += len(chunk)
            if not raw:
                break


def windows_job():
    # Los descendientes heredan el Job. Al salir el supervisor se cierra el último handle.
    import win32api
    import win32job
    handle = win32job.CreateJobObject(None, None)
    cls = win32job.JobObjectExtendedLimitInformation
    info = win32job.QueryInformationJobObject(handle, cls)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(handle, cls, info)
    win32job.AssignProcessToJobObject(handle, win32api.GetCurrentProcess())
    return handle


def supervise(path):
    with sqlite3.connect(path) as db:
        process = None
        try:
            job = windows_job() if os.name == "nt" else None
            command, cwd, cancelled = db.execute("SELECT command,cwd,cancel FROM job").fetchone()
            if cancelled:
                db.execute("UPDATE job SET state='cancelado'")
                return
            process = subprocess.Popen(json.loads(command), cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
            with db:
                db.execute("UPDATE job SET state='ejecutando',heartbeat=?", (time.time(),))
            errors = []
            reader = threading.Thread(target=capture, args=(process.stdout, path, errors), daemon=True)
            reader.start()
            last_update = time.monotonic()
            while process.poll() is None:
                cancelled, = db.execute("SELECT cancel FROM job").fetchone()
                if cancelled:
                    process.kill()
                    break
                if time.monotonic() - last_update >= 1:
                    with db:
                        db.execute("UPDATE job SET heartbeat=?", (time.time(),))
                    last_update = time.monotonic()
                time.sleep(0.2)
            code = process.wait()
            reader.join(timeout=2)
            state = "cancelado" if cancelled else "terminado"
            with db:
                db.execute("UPDATE job SET state=?,code=?,error=?,truncated=MAX(truncated,?)",
                           (state, code, "; ".join(errors), int(reader.is_alive() or bool(errors))))
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            with db:
                db.execute("UPDATE job SET state='fallido',error=?", (str(exc),))
        # Mantener el handle del Job hasta que se haya confirmado la transacción final.


if __name__ == "__main__":
    supervise(Path(sys.argv[1]))

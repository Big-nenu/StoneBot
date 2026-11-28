"""Trabajos de terminal del chat. Un supervisor independiente conserva la salida y el estado."""
import codecs
from contextlib import closing, contextmanager
import json
import locale
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

LIMIT = 4 * 1024 * 1024
PAGE = 8192
WINDOWS_BACKEND = os.name == "nt"
ACTIVE = ("preparando", "ejecutando")
SCHEMA = """
CREATE TABLE job(command TEXT, cwd TEXT, state TEXT, code INTEGER, cancel INTEGER DEFAULT 0,
                 heartbeat REAL, error TEXT DEFAULT '', truncated INTEGER DEFAULT 0);
CREATE TABLE output(seq INTEGER PRIMARY KEY, text TEXT);
"""


@contextmanager
def connection(path):
    with closing(sqlite3.connect(path)) as db, db:
        yield db


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
    with connection(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO job(command,cwd,state,heartbeat) VALUES(?,?,?,?)",
                   (json.dumps(argv), cwd, ACTIVE[0], time.time()))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.Popen([sys.executable, "-E", "-P", "-B", str(Path(__file__).resolve()), str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    except OSError as exc:
        with connection(path) as db:
            db.execute("UPDATE job SET state='fallido', error=?", (str(exc),))
        return {**inspect_run(folder, run_id), "inicio_confirmado": False}
    return inspect_run(folder, run_id)


def description(folder, run_id):
    path = location(folder, run_id)
    if not path.is_file():
        raise ValueError("Ejecución desconocida en este chat.")
    with connection(path) as db:
        command, cwd = db.execute("SELECT command,cwd FROM job").fetchone()
    return {"id": run_id, "argv": json.loads(command), "cwd": cwd}


def active_command(folder, run_ids, arguments):
    """Busca la misma invocación entre los ID ya registrados en este ámbito."""
    for run_id in run_ids:
        path = location(folder, run_id)
        if not path.is_file():
            continue
        with closing(sqlite3.connect(path, timeout=0.05)) as db:
            entry = db.execute("SELECT command,cwd FROM job WHERE state IN (?,?)", ACTIVE).fetchone()
        if entry:
            argv = json.loads(entry[0])
            if (os.path.normcase(os.path.realpath(entry[1])) == os.path.normcase(arguments["cwd"])
                    and os.path.normcase(os.path.realpath(argv[0])) == os.path.normcase(arguments["argv"][0])
                    and argv[1:] == arguments["argv"][1:]):
                return run_id
    return None


def inspect_run(folder, run_id, cursor=0, *, cancel=False, lock_timeout=5):
    path = location(folder, run_id)
    if not path.is_file() or type(cursor) is not int or not 0 <= cursor <= 2**63 - 1:
        raise ValueError("Ejecución o cursor desconocido en este chat.")
    start_cursor = cursor
    with closing(sqlite3.connect(path, timeout=lock_timeout)) as db, db:
        if cancel:
            db.execute("UPDATE job SET cancel=1 WHERE state IN (?,?)", ACTIVE)
        if not cancel:
            db.execute("BEGIN")
        state, code, requested, heartbeat, error, truncated = db.execute(
            "SELECT state,code,cancel,heartbeat,error,truncated FROM job").fetchone()
        chunks = []
        size = 0
        more = False
        for seq, text in db.execute("SELECT seq,text FROM output WHERE seq>? ORDER BY seq", (cursor,)):
            if chunks and size + len(text) > PAGE:
                more = True
                break
            chunks.append(text)
            size += len(text)
            cursor = seq
    confirmed = state in {"ejecutando", "terminado"} or code is not None or bool(chunks)
    if not confirmed and state == "fallido":
        confirmed = None
    if state in ACTIVE and time.time() - heartbeat > 15:
        state = "sin confirmar"
    return dict(id=run_id, estado=state, codigo=code, inicio_confirmado=confirmed,
                cancelacion_solicitada=bool(requested), salida="".join(chunks), cursor=cursor, cursor_inicio=start_cursor,
                hay_mas=more, truncada=bool(truncated),
                parcial=bool(more or truncated or state in (*ACTIVE, "sin confirmar")), error=error)


def capture(stream, path, errors):
    try:
        _capture(stream, path)
    except (OSError, sqlite3.Error) as exc:
        errors.append(str(exc))


def _capture(stream, path):
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace")
    retained = 0
    with stream, connection(path) as db:
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


class WindowsProcess:
    """El proceso arranca suspendido hasta que todo su árbol pertenece al Job."""

    def __init__(self, argv, cwd):
        import msvcrt
        import win32api
        import win32event
        import win32job
        import win32process

        self.jobs = win32job
        self.events = win32event
        self.processes = win32process
        self.job = win32job.CreateJobObject(None, "StoneBot-" + uuid4().hex)
        self.handle = None
        self.stdout = None
        try:
            cls = win32job.JobObjectExtendedLimitInformation
            info = win32job.QueryInformationJobObject(self.job, cls)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, cls, info)
            read_fd, write_fd = os.pipe()
            self.stdout = os.fdopen(read_fd, "rb")
            with os.fdopen(write_fd, "wb") as output, open(os.devnull, "rb") as stdin:
                os.set_inheritable(output.fileno(), True)
                os.set_inheritable(stdin.fileno(), True)
                startup = win32process.STARTUPINFO()
                startup.dwFlags = subprocess.STARTF_USESTDHANDLES
                startup.hStdInput = msvcrt.get_osfhandle(stdin.fileno())
                startup.hStdError = startup.hStdOutput = msvcrt.get_osfhandle(output.fileno())
                self.handle, thread, _, _ = win32process.CreateProcess(
                    argv[0], subprocess.list2cmdline(argv), None, None, True,
                    win32process.CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW, None, cwd, startup)
                try:
                    win32job.AssignProcessToJobObject(self.job, self.handle)
                    win32process.ResumeThread(thread)
                except BaseException:
                    win32api.TerminateProcess(self.handle, 1)
                    raise
                finally:
                    thread.Close()
        except BaseException:
            if self.stdout:
                self.stdout.close()
            self.close()
            raise

    def poll(self):
        if self.events.WaitForSingleObject(self.handle, 0) == self.events.WAIT_TIMEOUT:
            return None
        return self.processes.GetExitCodeProcess(self.handle)

    def wait(self):
        self.events.WaitForSingleObject(self.handle, self.events.INFINITE)
        return self.processes.GetExitCodeProcess(self.handle)

    def kill(self):
        self.jobs.TerminateJobObject(self.job, 1)

    def active(self):
        info = self.jobs.JobObjectBasicAccountingInformation
        return self.jobs.QueryInformationJobObject(self.job, info)["ActiveProcesses"] > 0

    def close(self):
        if self.handle:
            self.handle.Close()
        self.job.Close()


def supervise(path):
    with connection(path) as db:
        process = None
        try:
            command, cwd, cancelled = db.execute("SELECT command,cwd,cancel FROM job").fetchone()
            if cancelled:
                db.execute("UPDATE job SET state='cancelado'")
                return
            argv = json.loads(command)
            if os.name == "nt":
                process = WindowsProcess(argv, cwd)
            else:
                process = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
            with db:
                db.execute("UPDATE job SET state='ejecutando',heartbeat=?", (time.time(),))
            errors = []
            reader = threading.Thread(target=capture, args=(process.stdout, path, errors), daemon=True)
            reader.start()
            last_update = time.monotonic()
            cancelling = False
            while (process.active() if isinstance(process, WindowsProcess) else process.poll() is None):
                cancelled, = db.execute("SELECT cancel FROM job").fetchone()
                if cancelled and not cancelling:
                    process.kill()
                    cancelling = True
                if time.monotonic() - last_update >= 1:
                    with db:
                        db.execute("UPDATE job SET heartbeat=?", (time.time(),))
                    last_update = time.monotonic()
                time.sleep(0.2)
            code = process.wait()
            reader.join(timeout=2)
            state = "cancelado" if cancelling else "terminado"
            with db:
                db.execute("UPDATE job SET state=?,code=?,error=?,truncated=MAX(truncated,?)",
                           (state, code, "; ".join(errors), int(reader.is_alive() or bool(errors))))
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            with db:
                db.execute("UPDATE job SET state='fallido',error=?", (str(exc),))
        finally:
            if isinstance(process, WindowsProcess):
                process.close()


if __name__ == "__main__":
    supervise(Path(sys.argv[1]))

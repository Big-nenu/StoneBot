"""Permisos y operaciones para los archivos del chat."""
import ctypes
import os
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QSettings

from mcp_client import data_path
from stonebot_engine import safety
from stonebot_engine.safety import IsolationError

OPERATIONS = {"list": "Listar carpetas", "search": "Buscar archivos", "info": "Consultar propiedades",
              "rank": "Clasificar por tamaño", "read": "Leer contenido de archivos del proyecto"}
MODES = {"allow": "Permitir", "ask": "Preguntar", "deny": "Denegar"}
RESULT_HEADER = "**Archivos locales**\n\n"
RESULT_LIMIT = 80
SCAN_LIMIT = 50_000
SCAN_SECONDS = 15
SENSITIVE_DIRS = {".ssh", ".aws", ".kube", ".gnupg"}
SENSITIVE_FILES = {".netrc", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}


@dataclass(frozen=True)
class FileSettings:
    modes: dict
    exclusions: tuple = ()


def settings_file():
    return QSettings(str(data_path("local_files.ini")), QSettings.Format.IniFormat)


def load_settings():
    settings = settings_file()
    modes = {key: settings.value(f"permissions/{key}", "ask" if key == "read" else "allow", type=str)
             for key in OPERATIONS}
    exclusions = settings.value("exclusions", [], type=list)
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudieron cargar los permisos de archivos locales.")
    return FileSettings(modes, tuple(Path(path) for path in exclusions))


def save_settings(modes, exclusions):
    exclusions = [str(local_path(path)) for path in exclusions]
    if any(modes.get(key) not in MODES for key in OPERATIONS):
        raise ValueError("Selecciona un permiso válido para cada operación.")
    settings = settings_file()
    for key in OPERATIONS:
        settings.setValue(f"permissions/{key}", modes[key])
    settings.setValue("exclusions", exclusions)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudieron guardar los permisos de archivos locales.")


def local_path(value):
    path = Path(value)
    if (not path.is_absolute() or str(path).startswith(("\\\\", "//")) or ".." in path.parts
            or any(":" in part for part in path.parts[1:]) or any(part.endswith((".", " ")) for part in path.parts[1:])):
        raise ValueError("Indica una ruta absoluta de una unidad local, sin redirecciones.")
    if os.name == "nt":
        if any(os.path.isreserved(part) for part in path.parts[1:]) or ctypes.windll.kernel32.GetDriveTypeW(path.anchor) not in (2, 3):
            raise ValueError("Indica una ruta de una unidad local disponible.")
    return path


def path_identity(path):
    # Windows puede exponer nombres cortos para la misma carpeta.
    return Path(os.path.realpath(path, strict=os.path.ALLOW_MISSING))


def blocked(path, roots):
    return (any(path.is_relative_to(root) for root in roots)
            or any(part.casefold() in SENSITIVE_DIRS for part in path.parts)
            or path.name.casefold() in SENSITIVE_FILES
            or path.name.casefold() == ".env" or path.name.casefold().startswith(".env."))


def redirected(info):
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))


@lru_cache(maxsize=1)
def windows_handles():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                       wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    return create, close


@contextmanager
def pin_directory(path):
    """En Windows conserva el directorio mientras se consulta su árbol inmediato."""
    if os.name != "nt":
        yield
        return
    create, close = windows_handles()
    # Comparte lectura y escritura. OPEN_REPARSE_POINT evita seguir un enlace.
    handle = create(str(path), 0, 3, None, 3, 0x02200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        close(handle)


def open_readonly(path, flags):
    if os.name != "nt":
        return os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK)
    import msvcrt

    create, close = windows_handles()
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT.
    handle = create(path, 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, flags)
    except OSError:
        close(handle)
        raise


class LocalFiles:
    def __init__(self, settings):
        self.settings = settings
        credential_stores = [Path(os.environ[key]) / "Microsoft" / folder
                             for key in ("LOCALAPPDATA", "APPDATA") if os.getenv(key)
                             for folder in ("Credentials", "Protect", "Vault")]
        paths = (*safety.protected_paths(), data_path(), *credential_stores, *settings.exclusions)
        self.blocked_roots = tuple({*paths, *(path_identity(path) for path in paths)})

    def mode(self, operation):
        return self.settings.modes.get(operation, "deny")

    def check(self, path):
        if blocked(path, self.blocked_roots):
            raise IsolationError("La ruta está protegida o excluida en Archivos locales.")

    @contextmanager
    def target(self, path, *, directory=False):
        path = local_path(path)
        self.check(path)
        with ExitStack() as pins:
            for parent in reversed(path.parents):
                pins.enter_context(pin_directory(parent))
                if redirected(parent.lstat()):
                    raise IsolationError("La ruta contiene una redirección.")
                self.check(path_identity(parent))
            if directory:
                pins.enter_context(pin_directory(path))
            info = path.lstat()
            if redirected(info):
                raise IsolationError("La ruta contiene una redirección.")
            self.check(path_identity(path))
            if directory and not stat.S_ISDIR(info.st_mode):
                raise ValueError("La ruta indicada debe ser una carpeta.")
            if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise IsolationError("La ruta no corresponde a un archivo regular sin enlaces duros.")
            yield info

    def read_text(self, path, offset, length):
        with self.target(path) as expected:
            if not stat.S_ISREG(expected.st_mode):
                raise ValueError("Indica un archivo de texto del proyecto.")
            with open(path, encoding="utf-8-sig", opener=open_readonly) as stream:
                current = os.fstat(stream.fileno())
                if (redirected(current) or not stat.S_ISREG(current.st_mode)
                        or current.st_nlink != 1 or not os.path.samestat(expected, current)):
                    raise IsolationError("El archivo cambió durante la apertura.")
                stream.read(offset)
                return stream.read(length)

    def scan(self, folder, recursive, check_pause, visit, *, exclude_hidden=False):
        pending = [folder]
        directories = skipped = visited = 0
        deadline = monotonic() + SCAN_SECONDS
        limit_reached = False
        while pending:
            check_pause()
            directory = pending.pop()
            try:
                with self.target(directory, directory=True), os.scandir(directory) as entries:
                    directories += 1
                    for entry in entries:
                        check_pause()
                        visited += 1
                        if visited > SCAN_LIMIT or monotonic() >= deadline:
                            return directories, skipped, True
                        path = Path(entry.path)
                        try:
                            self.check(path)
                            # DirEntry.stat no informa el número de enlaces en Windows.
                            info = path.lstat() if os.name == "nt" else entry.stat(follow_symlinks=False)
                            hidden = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_HIDDEN
                            if exclude_hidden and (entry.name.startswith(".") or hidden):
                                continue
                            is_directory = stat.S_ISDIR(info.st_mode)
                            if redirected(info) or (not is_directory
                                                   and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                                skipped += 1
                                continue
                            if visit(path, info, is_directory):
                                return directories, skipped, True
                            if recursive and is_directory:
                                pending.append(path)
                        except IsolationError:
                            skipped += 1
                            continue
                        except OSError:
                            skipped += 1
            except (OSError, IsolationError, ValueError):
                if directory == folder:
                    raise
                skipped += 1
            if pending and monotonic() >= deadline:
                limit_reached = True
                break
        return directories, skipped, limit_reached

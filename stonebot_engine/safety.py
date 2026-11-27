"""Validación de rutas de la base de datos y archivos auxiliares de StoneBot."""
import ctypes
import os
import stat
from pathlib import Path


class IsolationError(RuntimeError):
    """Se intento usar una ruta que podria tocar la memoria personal o salir de la carpeta de StoneBot."""


def _real(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(p))))


def _inside(path, folder):
    path, folder = _real(path), _real(folder)
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def default_root():
    """Carpeta donde StoneBot guarda su memoria."""
    return Path.home() / ".stonebot"


_cli_root = None


def cli_root():
    return _cli_root


def configure_cli_profile(value=None):
    global _cli_root
    path = Path.home() / ".stonebot-cli" if value is None else Path(value)
    if not path.is_absolute() or str(path).startswith(("//", "\\\\")):
        raise IsolationError("STONEBOT_HOME debe ser una ruta absoluta local.")
    if os.name == "nt" and (ctypes.windll.kernel32.GetDriveTypeW(path.anchor) not in (2, 3)
                            or any(os.path.isreserved(part) for part in path.parts[1:])):
        raise IsolationError("STONEBOT_HOME debe estar en una unidad local.")
    expected = Path(os.path.abspath(path))
    if ".." in path.parts or any(parent.is_symlink() or parent.is_junction() for parent in (path, *path.parents)):
        raise IsolationError("La carpeta de datos de la CLI está redirigida.")
    if Path(check_path(expected)) != expected or (expected.exists() and not expected.is_dir()):
        raise IsolationError("La carpeta de datos de la CLI no es válida.")
    for protected in (default_root(), *protected_paths()):
        if _inside(expected, protected) or _inside(protected, expected):
            raise IsolationError("La carpeta de la CLI se solapa con un perfil protegido.")
    if _cli_root is not None and _cli_root != expected:
        raise IsolationError("El proceso ya tiene un perfil de CLI.")
    _cli_root = expected
    return expected


def protected_paths():
    """Rutas que StoneBot nunca puede abrir: la memoria personal y el codigo original de StoneWave."""
    h = Path.home()
    paths = [h / ".stonewave", h / ".memholografic", h / "Projects" / "StoneWave"]
    for name in ("STONEWAVE_DB", "MEMHOLOGRAFIC_DB"):
        if db := os.getenv(name):
            paths.extend(Path(db + suffix) for suffix in ("", "-journal", "-wal", "-shm"))
    if cli_root() is not None:
        paths.append(default_root())
    return paths


def check_path(path, root=None, *, reject_hard_links=True):
    """Valida la ruta declarada y su destino, incluyendo enlaces a archivos externos."""
    path = os.path.abspath(os.fspath(path))
    if os.name == "nt" and ":" in os.path.splitdrive(path)[1]:
        raise IsolationError(f"Flujo NTFS bloqueado: {path}")
    target = os.path.realpath(path, strict=os.path.ALLOW_MISSING)
    for protected in protected_paths():
        if _inside(path, protected) or Path(os.path.normcase(path)).is_relative_to(
            Path(os.path.normcase(os.path.abspath(protected)))
        ):
            raise IsolationError(f"Ruta protegida: {path}")
    if root is not None and not _inside(target, root):
        raise IsolationError(f"La ruta debe estar dentro de {root}: {path}")
    try:
        info = os.stat(target)
    except FileNotFoundError:
        return target
    if reject_hard_links and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise IsolationError(f"Archivo con enlaces duros: {path}")
    return target


def check_db_path(db_path, allowed_root=None):
    """Valida la ruta de la base de datos y la devuelve como ruta absoluta. Lanza IsolationError si no es segura."""
    if db_path is None or not str(db_path).strip():
        raise IsolationError(
            "StoneBot necesita una ruta explicita para su base de datos (no hay ruta por defecto, "
            "para no tocar la memoria personal por accidente).")
    root = Path(default_root() if allowed_root is None else allowed_root)
    if root.is_symlink() or root.is_junction():
        raise IsolationError(f"Carpeta de memoria redirigida: {root}")
    target = check_path(db_path, root)
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = target + suffix
        if os.path.normcase(check_path(sidecar, root)) != os.path.normcase(sidecar):
            raise IsolationError(f"Archivo auxiliar de SQLite redirigido: {sidecar}")
    return target

"""Validación de rutas de la base de datos y archivos auxiliares de StoneBot."""
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


def protected_paths():
    """Rutas que StoneBot nunca puede abrir: la memoria personal y el codigo original de StoneWave."""
    h = Path.home()
    paths = [h / ".stonewave", h / ".memholografic", h / "Projects" / "StoneWave"]
    for name in ("STONEWAVE_DB", "MEMHOLOGRAFIC_DB"):
        if db := os.getenv(name):
            paths.extend(Path(db + suffix) for suffix in ("", "-journal", "-wal", "-shm"))
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

"""Clasificación local de archivos por tamaño, sin leer su contenido."""
import ctypes
import heapq
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from stonebot_engine.safety import check_path

NUMBER_WORDS = dict(zip("uno dos tres cuatro cinco seis siete ocho nueve diez".split(), range(1, 11)))
RANKING = re.compile(
    r"\b(?:([1-9]\d{0,2}|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+)?"
    r"archivos\s+m[aá]s\s+(?:grandes|pesados)\b", re.I
)
PATH = re.compile(r'(?:^|\s)(?:"([A-Za-z]:[\\/][^"\r\n]+)"|([A-Za-z]:[\\/][^\r\n]+)$)')
DIRECT = re.compile(r"\b(?:solo archivos directos|sin subcarpetas|excluye las subcarpetas)\b", re.I)
RECURSIVE = re.compile(r"\b(?:incluy\w*|revisa|con|tambi[eé]n)\s+(?:(?:las|sus)\s+)?subcarpetas\b", re.I)
DOWNLOADS_REPLY = re.compile(r"^\s*(?:(?:en|es)\s+)?(?:(?:mi|la)\s+)?(?:carpeta\s+)?(?:Descargas|Downloads)[.!]?\s*$", re.I)


def downloads_folder():
    if os.name == "nt":
        identifier = (ctypes.c_byte * 16).from_buffer_copy(
            UUID("374DE290-123F-4565-9164-39C4925E467B").bytes_le
        )
        result = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(identifier), 0, None, ctypes.byref(result)) == 0:
            try:
                return Path(result.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(result)
    return Path.home() / "Downloads"


def ranking_count(objective):
    match = RANKING.search(objective)
    if not match:
        return None
    count = (match[1] or "5").casefold()
    return int(count) if count.isdecimal() else NUMBER_WORDS[count]


def is_ranking_request(text):
    # shortcut: reconoce encargos de clasificación en español, ampliar con un enrutador de intención.
    return (ranking_count(text) is not None
            and not uses_mcp(text)
            and not re.match(r"\s*[¿¡]?\s*(?:c[oó]mo|qu[eé] significa|por qu[eé])\b", text, re.I)
            and bool(re.search(r"\b(?:revisa|revisar|busca|buscar|encuentra|encontrar|dime|mu[eé]strame|"
                               r"lista|ordena|identifica|cu[aá]les son|quiero ver|saca|dame)\b", text, re.I)))


def uses_mcp(text):
    return bool(re.search(r"Desktop Commander|\bMCP\b", text, re.I))


def inventory_followup(text):
    return bool(PATH.search(text) or DIRECT.search(text) or RECURSIVE.search(text) or DOWNLOADS_REPLY.fullmatch(text))


def ranking_request(objective, user_input, previous_folder="", previous_recursive=None):
    count = ranking_count(objective)
    if count is None:
        return None
    supplied = PATH.search(user_input.removeprefix("/reanudar").strip())
    if not supplied and not previous_folder:
        supplied = PATH.search(objective)
    folder = next(group for group in supplied.groups() if group) if supplied else previous_folder
    if DOWNLOADS_REPLY.fullmatch(user_input) or (
        not folder and re.search(r"\b(?:Descargas|Downloads)\b", objective, re.I)
    ):
        folder = str(downloads_folder())
    recursive = previous_recursive if previous_recursive is not None else not DIRECT.search(objective)
    if user_input.removeprefix("/tarea").strip() != objective:
        if DIRECT.search(user_input):
            recursive = False
        elif RECURSIVE.search(user_input):
            recursive = True
    return folder, count, recursive


def largest_files(folder, count, recursive, check_pause):
    root = Path(folder)
    if not root.is_absolute() or str(root).startswith(("\\\\", "//")):
        raise ValueError("Indica una ruta absoluta de una carpeta local.")
    root = Path(check_path(root))
    if str(root).startswith(("\\\\", "//")) or not root.is_dir():
        raise ValueError(f"No pude abrir la carpeta {root}. Indícame la ruta correcta.")
    pending, top, skipped = [root], [], []
    files = folders = missing = 0

    def omit(path):
        nonlocal missing
        missing += 1
        if len(skipped) < 10:
            skipped.append(str(path))

    while pending:
        check_pause()
        folder = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    check_pause()
                    try:
                        info = entry.stat(follow_symlinks=False)
                        redirected = getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        if redirected or stat.S_ISLNK(info.st_mode):
                            omit(entry.path)
                        elif stat.S_ISDIR(info.st_mode) and recursive:
                            pending.append(check_path(entry.path, root))
                        elif stat.S_ISREG(info.st_mode):
                            check_path(entry.path, root, reject_hard_links=False)
                            files += 1
                            item = (info.st_size, entry.path)
                            if len(top) < count:
                                heapq.heappush(top, item)
                            else:
                                heapq.heappushpop(top, item)
                    except (OSError, RuntimeError, ValueError):
                        omit(entry.path)
            folders += 1
        except OSError:
            omit(folder)
    return root, sorted(top, reverse=True), files, folders, missing, skipped

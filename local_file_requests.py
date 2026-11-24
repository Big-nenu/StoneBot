"""Interpreta encargos de exploración sin delegar rutas al modelo."""
import re
import stat
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from folder_inventory import DIRECT, RECURSIVE, downloads_folder, known_folder
from local_files import OPERATIONS, RESULT_HEADER, RESULT_LIMIT, local_path
from request_routing import INTERNAL_LOOKUP, LOCAL_READ_ACTION

PATH_START = r"(?:[A-Za-z]:[\\/]|/(?!/)|\\\\)"
QUOTED_PATH = re.compile(r'[`"“«](' + PATH_START + r'[^`"”»\r\n]*)[`"”»]')
BARE_PATH = re.compile(r'(?<![\w/:])(' + PATH_START + r'[^\s<>"`]*)(?![\w])')
FOLDER_NAMES = {
    "descargas": downloads_folder, "downloads": downloads_folder,
    "documentos": lambda: known_folder("FDD39AD0-238F-46AF-ADB4-6C85480369C7", "Documents"),
    "escritorio": lambda: known_folder("B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "Desktop"),
}
LOCAL_SCOPE = re.compile(r"\b(?:carpeta|directorio|unidad|disco|equipo|mi (?:pc|computadora))\b", re.I)
PROJECT_SCOPE = re.compile(r"\b(?:en|de)\s+(?:mi|este|el) proyecto\b", re.I)
SEARCH = re.compile(r"\b(?:busca(?:r)?|encuentra|encuentres|encontrar|localiza|localizar)\b", re.I)
PROPERTIES = re.compile(r"\b(?:metadatos|propiedades|tama[ñn]o|cu[aá]nto pesa|fecha de modificaci[oó]n)\b", re.I)
CONTENT = re.compile(r"^\s*¿?\s*(?:(?:me )?(?:puedes|podr[ií]as)\s+)?(?:lee|leer|resume|resumir|analiza|analizar)\b", re.I)
EXTENSION = re.compile(r"(?:\bextensi[oó]n\s+\.?|\*\.)([a-z0-9]+)\b|\barchivos?\s+(?:\.([a-z0-9]+)|(pdf|csv|json|docx|xlsx|pptx|txt|md|png|jpg|zip))\b", re.I)


@dataclass(frozen=True)
class FileRequest:
    operation: str
    path: Path | None
    query: str = ""
    extension: str = ""
    recursive: bool = False


def request_path(text):
    quoted = list(QUOTED_PATH.finditer(text))
    candidates = quoted or list(BARE_PATH.finditer(text))
    if len(candidates) > 1:
        raise ValueError("Indica una sola ruta por operación.")
    if candidates:
        match = candidates[0]
        value = match[1]
        if not quoted:
            tail = text[match.end():].splitlines()[0] if text[match.end():] else ""
            if tail and re.fullmatch(r"[ \t]+[^?\r\n:]+", tail) and not re.search(
                r"\b(?:y|con|sin|incluye|excluye|para|dime)\b", tail, re.I
            ):
                value += tail.rstrip()
            if value.endswith((".", "?", "!", ",", ";")):
                value = value.rstrip(".?!,;")
        return Path(value)
    return None


def parse_request(text, *, project=None, selected=False):
    if (INTERNAL_LOOKUP.search(text) or re.search(r"\b(?:Desktop Commander|MCP)\b", text, re.I)
            or re.search(r"https?://", text, re.I) or re.match(r"\s*(?:no\b|/|(?:c[oó]mo|por qu[eé])\s+)", text, re.I)):
        return None
    search = SEARCH.search(text)
    properties = PROPERTIES.search(text)
    action = LOCAL_READ_ACTION.search(text) or re.search(r"\b(?:abres|revises|listes|lista|mu[eé]strame)\b", text, re.I)
    content = CONTENT.search(text)
    names = [name for name in FOLDER_NAMES if re.search(rf"\b{name}\b", text, re.I)]
    project_scope = project and project.get("folder") and PROJECT_SCOPE.search(text)
    local = (names or QUOTED_PATH.search(text) or BARE_PATH.search(text) or LOCAL_SCOPE.search(text) or project_scope
             or EXTENSION.search(text) or re.search(r"\barchivos?\b", text, re.I))
    if not selected and not (local and (search or properties or action or content)):
        return None
    path = request_path(text)
    if path is None and len(names) == 1:
        path = FOLDER_NAMES[names[0]]()
    if path is None and project_scope:
        path = Path(project["folder"])
    if content:
        return FileRequest("content", path)
    if search:
        extension = EXTENSION.search(text)
        suffix = next(filter(None, extension.groups()), "") if extension else ""
        term = text[search.end():].strip()
        if names:
            term = re.sub(r"^en\s+(?:(?:mi|la)\s+|carpeta\s+)*" + re.escape(names[0]) + r"\b[\s,]*", "", term, flags=re.I)
        term = re.split(r"\s+en\b|\s+(?:con|sin|incluye)\s+(?:las\s+)?subcarpetas\b",
                        term, maxsplit=1, flags=re.I)[0]
        if extension:
            term = EXTENSION.sub("", term)
            term = re.sub(r"\bde\s*$", "", term, flags=re.I)
        term = re.sub(r"^(?:(?:los|las|un|una|el|la|todos|todas|archivos?|documentos?|carpetas?|llamad[oa]s?)\b\s*)+",
                      "", term, flags=re.I)
        term = re.sub(r"^(?:con (?:el )?nombre|que (?:se llam(?:e|a)|contenga))\s+", "", term, flags=re.I)
        return FileRequest("search", path, term.strip(' "`«»“”¿?'), suffix.casefold(), not DIRECT.search(text))
    if properties:
        return FileRequest("info", path)
    return FileRequest("list", path, recursive=bool(RECURSIVE.search(text) and not DIRECT.search(text)))


def continued_request(messages, *, project=None):
    latest = messages[-1]["content"].strip()
    if (len(messages) < 3 or messages[-2]["role"] != "assistant" or messages[-3]["role"] != "user"
            or not latest or "\n" in latest):
        return None
    answer = messages[-2]["content"]
    if not answer.startswith(RESULT_HEADER) or "¿En qué carpeta" not in answer:
        return None
    previous = parse_request(messages[-3]["content"], project=project, selected=True)
    supplied = request_path(latest) if re.match(r'^(?:en\s+|es\s+)?[`"“«]?' + PATH_START, latest, re.I) else None
    if supplied is None:
        known = FOLDER_NAMES.get(latest.strip().casefold())
        supplied = known() if known else None
    if previous and supplied:
        return replace(previous, path=supplied)
    return None


def file_answer(service, request, check_pause):
    path = local_path(request.path)
    if request.operation == "info":
        with service.target(path) as info:
            kind = "Carpeta" if stat.S_ISDIR(info.st_mode) else "Archivo"
            size = f" · {info.st_size:,} bytes" if kind == "Archivo" else ""
        modified = datetime.fromtimestamp(info.st_mtime).strftime("%d/%m/%Y %H:%M")
        return f"`{path}`\n\n{kind}{size} · Modificado el {modified}."

    results = []

    def collect(entry, _info, directory):
        if request.operation == "search" and (
            directory or request.query.casefold() not in entry.name.casefold()
            or (request.extension and entry.suffix.casefold() != "." + request.extension)
        ):
            return False
        relative = str(entry.relative_to(path)).replace("`", "ʼ")
        results.append(f"- `{relative}`" + (" · carpeta" if directory else ""))
        return len(results) > RESULT_LIMIT

    _, skipped, partial = service.scan(path, request.recursive, check_pause, collect)
    if results:
        listing = "\n".join(sorted(results[:RESULT_LIMIT], key=str.casefold))
    else:
        listing = "No encontré coincidencias." if request.operation == "search" else "No hay elementos para mostrar."
    summary = f"{OPERATIONS[request.operation]} en `{path}`\n\n{listing}"
    if partial or skipped:
        summary += "\n\n**Revisión parcial.**"
        if partial:
            summary += " Se alcanzó un límite de recorrido o resultados."
        if skipped:
            summary += f" Se omitieron {skipped} entradas excluidas, inaccesibles o redirigidas."
    return summary

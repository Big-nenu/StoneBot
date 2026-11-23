"""Reglas del chat para elegir entre memoria, web y lectura local."""
import re
from urllib.parse import urlsplit

from ollama import Tool


TURN_SOURCES = {
    "enlace": "abrir una URL que el usuario señaló en el chat",
    "web": "buscar o verificar información en internet",
    "archivos": "inspeccionar archivos o carpetas del equipo",
    "mcp": "usar una aplicación, servicio o servidor MCP solicitado",
    "memoria": "consultar o corregir recuerdos, o leer notas y actividad de StoneWave",
}
SELECT_SOURCE = Tool.model_validate({
    "type": "function",
    "function": {
        "name": "elegir_fuente",
        "description": (
            "Habilita la fuente que requiere la solicitud actual, incluso si la señala por contexto. "
            "No ejecuta acciones. Para preguntas que puedas responder con el chat o conocimiento general, responde directamente. "
            "Elige memoria solo para recuerdos personales o funciones de StoneWave. "
            "Fuentes: " + ", ".join(f"{key}: {description}" for key, description in TURN_SOURCES.items())
        ),
        "parameters": {"type": "object", "properties": {"fuente": {"type": "string", "enum": list(TURN_SOURCES)}},
                       "required": ["fuente"], "additionalProperties": False},
    },
})

EXTERNAL_ACTION = re.compile(
    r"^\s*[¿¡]?\s*(?:(?:por favor[\s,]+|(?:me (?:puedes ayudar|podrías ayudar|ayudas) a|"
    r"puedes|podrías|quiero que|necesito que)\s+))*"
    r"(?:/mcp(?=\s|$)|(?:busca|buscar|busques|investiga|investigar|investigues|consulta|consultar|consultes|"
    r"verifica|verificar|verifiques|comprueba|comprobar|revisa|revisar|abre|abrir|lee|leer|lista|listar|"
    r"enumera|ejecuta|ejecutar|usa|usar|utiliza|prueba|explora|descarga|crea|escribe|edita|guarda|"
    r"search|look up|find|check|verify|open|read|list|run|use|browse|download|create|write)\b)", re.I,
)
EXTERNAL_SOURCE = re.compile(
    r"\b(?:MCP|Desktop Commander|Context7|Exa|Tavily|web|internet|en l[ií]nea|online|"
    r"documentaci[oó]n|docs|archivos?|carpetas?|directorios?|rutas?|repositorios?|servidor(?:es)?|GitHub|"
    r"files?|folders?|directories|repositories|noticias|p[aá]ginas?|sitios?|fuentes?|sources?|url)\b|https?://", re.I,
)
EXTERNAL_LOOKUP = re.compile(r"\b(?:busca|buscar|busques|investiga|investigar|investigues|consulta|consultar|consultes|search|look up)\b", re.I)
INTERNAL_LOOKUP = re.compile(r"\b(?:(?:en|de) (?:tu|la|mi) memoria|(?:en|con) StoneWave|(?:tus|mis) recuerdos|"
                             r"historial (?:del chat|de conversaciones))\b", re.I)
MEMORY_REQUEST = re.compile(
    r"^\s*¿?\s*(?:qu[eé]\s+recuerdas|recuerdas\s+(?:si|qu[eé]|cu[aá]l)|"
    r"(?:actualiza|corrige|olvida|restaura)\s+(?:(?:mi|el|ese|este)\s+)?recuerdo)\b", re.I,
)
EXTERNAL_CLARIFICATION = re.compile(
    r"\b(?:clave|ruta|carpeta|archivo|repositorio|servidor|fuente|t[eé]rmino|versi[oó]n|path|folder|file|repository|server|source|version|key)\b", re.I,
)
WEB_OPEN = re.compile(
    r"^\s*¿?\s*(?:por favor[\s,]+)?"
    r"(?:(?:(?:me\s+)?(?:puedes|podr[ií]as|(?P<negative>no\s+puedes))\s+)?"
    r"(?:entra(?:r)?|abre|abrir|visita(?:r)?|lee|leer|revisa(?:r)?|ve|ver|consulta(?:r)?|explora(?:r)?)"
    r"|(?:(?:quiero|necesito)\s+)?que\s+(?:entres|abras|visites|leas|revises|consultes|explores))\b", re.I,
)
WEB_REFERENCE = re.compile(r"\b(?:enlace|link|url|p[aá]gina|sitio|readme|repositorio)\b", re.I)
WEB_URL = re.compile(r"https?://[^\s<>`\"'\])]+", re.I)
WEB_SHOW_RESULT = re.compile(r"(?:^|[,\n.!?])\s*(?:y\s+)?mira\s+(?:ya\s+)?c[oó]mo\s+qued[oó]\b", re.I)
GITHUB_CLONE_PATH = re.compile(r"/[^/]+/[^/]+\.git/?\Z", re.I)
WEB_LINK_TOOLS = {"web_fetch_exa", "web_search_exa", "crawling_exa", "tavily_extract", "tavily_search"}
LOCAL_PATH = re.compile(r"(?<![\w/])(?:[a-z]:[\\/][^\s\r\n\x22<>]|/(?:home|Users|mnt|tmp|var|opt|srv)/[^\s<>])", re.I)
LOCAL_READ_ACTION = re.compile(
    r"(?:^|(?<=[.!?;]))[^\S\n]*¿?\s*(?:por favor[ ,]+)?"
    r"(?:(?:me\s+)?(?:puedes|podr[ií]as)\s+)?"
    r"(?:entra(?:r)?|revisa(?:r)?|abre|abrir|lee|leer|lista(?:r)?|inspecciona(?:r)?|"
    r"explora(?:r)?|consulta(?:r)?|verifica(?:r)?|qu[eé]\s+contiene)\b[^\n]*", re.I | re.M,
)
LOCAL_READ_TOOLS = {"list_directory", "get_file_info", "read_file", "read_multiple_files"}


def requests_local_read(messages):
    if not messages or messages[-1]["role"] != "user":
        return False
    text = messages[-1]["content"]
    return bool(LOCAL_PATH.search(text) and any(
        not INTERNAL_LOOKUP.search(match.group()) for match in LOCAL_READ_ACTION.finditer(text)
    ))


def requested_web_link(messages):
    if not messages or messages[-1]["role"] != "user":
        return None
    text = messages[-1]["content"].strip()
    action = WEB_OPEN.match(text)
    has_url = WEB_URL.search(text)
    if (not (action or (has_url and WEB_SHOW_RESULT.search(text))) or INTERNAL_LOOKUP.search(text)
            or not (has_url or WEB_REFERENCE.search(text))):
        return None
    if action and action["negative"] and not (text.startswith("¿") or text.endswith("?") or re.search(
            r"\bporque\s+(?:ah[ií]|all[ií])\b.*\breadme\b", text, re.I)):
        return None

    link = referenced_web_link(messages)
    if link is not None:
        return link
    return "" if re.search(r"\b(?:enlace|link|url|repositorio)\b", text, re.I) else None


def referenced_web_link(messages):
    for message in reversed(messages[-5:]):
        if message["role"] not in {"user", "assistant"}:
            continue
        links = set()
        for match in WEB_URL.finditer(message["content"]):
            link = match.group().rstrip(".,;!?*")
            try:
                parts = urlsplit(link)
                if parts.hostname and parts.username is None and parts.password is None:
                    if parts.hostname == "github.com" and GITHUB_CLONE_PATH.fullmatch(parts.path):
                        link = parts._replace(path=parts.path.rstrip("/")[:-4]).geturl()
                    links.add(link)
            except ValueError:
                continue
        if links:
            return next(iter(links)) if len(links) == 1 else ""
    return None


def requests_memory(text):
    return bool(MEMORY_REQUEST.search(text) or INTERNAL_LOOKUP.search(text))


def requests_external_tools(messages):
    def explicit(text):
        line = text.strip().partition("\n")[0]
        match = EXTERNAL_ACTION.match(line)
        if not match or INTERNAL_LOOKUP.search(line):
            return False
        return bool(EXTERNAL_SOURCE.search(line) or match.group().strip().startswith("/mcp")
                    or EXTERNAL_LOOKUP.search(match.group()))

    if not messages or messages[-1]["role"] != "user":
        return False
    text = messages[-1]["content"].strip()
    if requests_local_read(messages) or explicit(text):
        return True
    if (len(messages) < 3 or messages[-2]["role"] != "assistant" or messages[-3]["role"] != "user"
            or not explicit(messages[-3]["content"]) or not 0 < len(text) <= 240 or "\n" in text
            or re.match(r"^(?:no\b|nunca\b|gracias\b|cambia\b)", text, re.I)):
        return False
    question = messages[-2]["content"].rstrip()
    return question.endswith("?") and bool(EXTERNAL_CLARIFICATION.search(question.rsplit("¿", 1)[-1]))

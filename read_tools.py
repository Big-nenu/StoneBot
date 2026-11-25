"""Herramientas de consulta del agente local."""
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from ollama import Tool

from local_file_requests import FOLDER_NAMES, FileRequest
from local_files import local_path

PAGE_CHARS = 12_000
MAX_OFFSET = 120_000


def read_tool(name, description, properties, required):
    return Tool.model_validate({
        "type": "function",
        "function": {
            "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False},
        },
    })


PROJECT_FILE = read_tool(
    "read_project_file",
    "Lee contenido UTF-8 de un archivo Markdown o de texto del proyecto activo. "
    "Sigue desplazamiento_siguiente si necesitas más contenido.",
    {"path": {"type": "string", "description": "Ruta relativa al proyecto, por ejemplo README.md."},
     "offset": {"type": "integer", "description": "Desplazamiento en caracteres, cero para empezar.",
                "minimum": 0, "maximum": MAX_OFFSET}},
    ["path"],
)
MEMORY_QUERY = read_tool(
    "search_stonewave_memory",
    "Busca recuerdos personales pertinentes en StoneWave. Úsala cuando el usuario pida recordar "
    "o contrastar una decisión previa. Construye la consulta con la evidencia que ya leíste.",
    {"text": {"type": "string", "description": "Tema o decisión específica que quieres contrastar."}},
    ["text"],
)
PROJECT_LINK = read_tool(
    "read_project_link",
    "Abre el enlace indicado por el usuario para este encargo. La URL ya está determinada.",
    {},
    [],
)
LOCAL_TARGET = {"type": "string", "description": "Ruta local absoluta o un nombre de carpeta conocido: "
                "perfil (raíz de la carpeta del usuario de Windows), Descargas, Documentos, Escritorio "
                "o proyecto si hay un proyecto abierto."}
LOCAL_FILES = read_tool(
    "inspect_local_files",
    "Explora archivos y carpetas del equipo. Elige count para obtener un total, list para mostrar entradas, "
    "search para filtrar por nombre o extensión e info para consultar propiedades de una ruta. "
    "Para ubicar una carpeta en el perfil de Windows, usa search con target perfil y entry_type folders. "
    "El resultado incluye la ruta base y las entradas relativas para continuar la exploración. "
    "Para totales elige qué tipo de entradas contar y si hay que recorrer las subcarpetas. "
    "El resultado indica si el recorrido fue parcial.",
    {"operation": {"type": "string", "enum": ["count", "list", "search", "info"]},
     "target": LOCAL_TARGET,
     "entry_type": {"type": "string", "enum": ["folders", "files", "all"],
                    "description": "Tipo de entradas. Por defecto incluye archivos y carpetas."},
     "recursive": {"type": "boolean", "description": "Incluye entradas anidadas. Por defecto, false."},
     "name_contains": {"type": "string", "description": "Texto opcional para filtrar por nombre."},
     "extension": {"type": "string", "description": "Extensión opcional, por ejemplo pdf."}},
    ["operation", "target"],
)

RANK_FILES = read_tool(
    "rank_local_files",
    "Encuentra los archivos de mayor tamaño en una carpeta. Devuelve nombres, rutas y tamaños en bytes "
    "que puedes usar para continuar el encargo con otras herramientas.",
    {"target": LOCAL_TARGET,
     "limit": {"type": "integer", "minimum": 1, "maximum": 999, "description": "Por defecto 5."},
     "recursive": {"type": "boolean", "description": "Incluye subcarpetas por defecto."},
     "exclude_hidden": {"type": "boolean", "description": "Indicar solo si se especifica el trato de los ocultos."}},
    ["target"],
)


@dataclass(frozen=True)
class ReadTool:
    spec: Tool
    execute: Callable[[dict], Awaitable[str]]
    private: bool = True


def project_read_tools(read_file, query_memory, read_link):
    tools = [ReadTool(PROJECT_FILE, read_file)]
    if query_memory is not None:
        tools.append(ReadTool(MEMORY_QUERY, query_memory))
    if read_link is not None:
        tools.append(ReadTool(PROJECT_LINK, read_link, private=False))
    return {tool.spec.function.name: tool for tool in tools}


def local_file_request(arguments, project):
    operation = arguments.get("operation")
    target = arguments.get("target")
    entry_type = arguments.get("entry_type", "all")
    recursive = arguments.get("recursive", False)
    query = arguments.get("name_contains", "")
    extension = arguments.get("extension", "")
    if operation not in ("count", "list", "search", "info") or entry_type not in ("folders", "files", "all"):
        raise ValueError("Indica una operación y un tipo de entrada válidos.")
    if type(recursive) is not bool or not all(isinstance(value, str) for value in (target, query, extension)):
        raise ValueError("Indica una carpeta o ruta local y argumentos válidos.")
    path = resolve_target(target, project)
    if operation == "info" and (recursive or query or extension):
        raise ValueError("Para consultar propiedades, indica únicamente la ruta.")
    if extension and entry_type == "folders":
        raise ValueError("El filtro por extensión se aplica a archivos.")
    return FileRequest(operation, path, query.strip(), extension.strip().lstrip(".").casefold(), recursive, entry_type)


def resolve_target(target, project):
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Indica una carpeta o ruta local.")
    target = target.strip()
    alias = target.casefold()
    if alias in FOLDER_NAMES:
        target = FOLDER_NAMES[alias]()
    elif alias == "perfil":
        target = Path.home()
    elif alias == "proyecto":
        if not project or not project.get("folder"):
            raise ValueError("El chat necesita un proyecto con carpeta vinculada.")
        target = project["folder"]
    return local_path(target)


def project_file_path(folder, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Indica la ruta relativa de un archivo del proyecto.")
    path = Path(value)
    if path.anchor or ".." in path.parts:
        raise ValueError("La ruta debe ser relativa y estar dentro del proyecto.")
    if path.suffix.casefold() not in {".md", ".txt"}:
        raise ValueError("El lector de proyectos admite archivos Markdown y de texto.")
    return path, local_path(local_path(folder) / path)


def read_result(**fields):
    return json.dumps(fields, ensure_ascii=False)

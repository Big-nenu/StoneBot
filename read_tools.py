"""Registro de las herramientas de consulta del turno local de proyecto."""
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from ollama import Tool

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

"""Etiquetas visuales para catálogos MCP de distintos proveedores."""
import re

from mcp_permissions import safe_read


CATEGORIES = (
    ("Configuración", r"config|settings|preferences|permission|usage_stat|feedback"),
    ("Terminal y procesos", r"terminal|command|shell|process|terminate|session|bash|powershell|comando|proceso"),
    ("Búsqueda", r"search|lookup|query|find|grep|investigar|buscar|búsqueda"),
    ("Edición", r"edit|patch|replace|write|append|modify|update|rename|edit[ae]|escribir|modificar"),
    ("Archivos", r"file|directory|folder|filesystem|readdir|archivo|directorio|carpeta"),
    ("Web y documentos", r"fetch|browse|web|page|document|pdf|docs|documento|navegación"),
)


def category(tool):
    # shortcut: nombres y descripciones orientan la presentación, usar categorías del servidor si MCP las estandariza.
    for text in (tool.name, f"{tool.title or ''} {(tool.description or '')[:180]}"):
        for label, pattern in CATEGORIES:
            if re.search(pattern, text, re.I):
                return label
    return "Otras"


def operation(tool):
    if safe_read(tool):
        return "Lectura"
    if re.search(r"execute|command|terminal|shell|start_process|interact_with_process|kill_process|force_terminate|(?:^|[_-])(?:exec|run)(?:$|[_-])", tool.name, re.I):
        return "Ejecución"
    if (tool.annotations and (tool.annotations.destructiveHint is True or tool.annotations.readOnlyHint is False)
            or re.search(r"write|edit|patch|replace|create|remove|delete|rename|move|set_config|update|copy|append", tool.name, re.I)):
        return "Cambios"
    return "Sin confirmar"

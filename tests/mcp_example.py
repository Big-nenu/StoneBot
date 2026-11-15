"""Servidor MCP de prueba con una lectura y una escritura local."""
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


server = FastMCP("stonebot-example", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def echo(text: str) -> str:
    """Devuelve un texto de prueba sin modificar datos."""
    assert "STONEBOT_TEST_PARENT_ONLY" not in os.environ
    return f"Eco MCP: {text}"


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def mark(text: str) -> str:
    """Escribe una marca de prueba en el directorio del servidor."""
    Path("mcp-test-marker.txt").write_text(text, encoding="utf-8")
    return "Marca escrita"


if __name__ == "__main__":
    server.run(transport="streamable-http" if len(sys.argv) > 1 else "stdio")

"""Servidores STDIO sintéticos para la matriz del paso 5.1."""
import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


MODE = sys.argv[1]
SERVER = FastMCP("stonebot-evaluacion")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)


def observe(tool, arguments):
    with Path("observaciones.jsonl").open("a", encoding="utf-8") as log:
        print(json.dumps({"tool": tool, "arguments": arguments}), file=log)


if MODE in {"fuente_a", "fuente_b"}:
    @SERVER.tool(annotations=READ)
    def echo(text: str) -> str:
        """Devuelve el eco del valor desde esta fuente."""
        observe("echo", {"text": text})
        return f"{MODE[-1].upper()}: {text}"

elif MODE in {"recorte", "registro_final"}:
    @SERVER.tool(annotations=READ)
    def consultar_registro() -> dict:
        """Devuelve la referencia y la fecha del registro si están disponibles."""
        observe("consultar_registro", {})
        if MODE == "recorte":
            return {"referencia": "X-518", "truncated": True, "fecha": None}
        return {"referencia": "X-518", "fecha": "2031-04-19", "truncated": False}

else:
    @SERVER.tool(annotations=READ)
    def consultar_inventario(cursor: int = 1) -> dict:
        """Lee el inventario. El cursor entero 2 identifica la segunda página."""
        first = not Path("observaciones.jsonl").exists()
        observe("consultar_inventario", {"cursor": cursor})
        if MODE == "atascado":
            return {"cursor": 1, "next_cursor": 1, "parcial": True, "elementos": ["PÁGINA-INICIAL"]}
        if first:
            raise RuntimeError("Fallo transitorio de prueba. El inventario puede volver a consultarse.")
        if cursor != 2:
            return {"cursor": 1, "next_cursor": 2, "elementos": ["PÁGINA-INICIAL"]}
        return {"cursor": 2, "next_cursor": None, "elementos": ["PÁGINA-SEGUNDA-472"]}


if __name__ == "__main__":
    SERVER.run(transport="stdio")

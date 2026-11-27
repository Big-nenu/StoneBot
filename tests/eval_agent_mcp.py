"""Servidores STDIO sintéticos para la matriz de evaluación del agente."""
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


if MODE in {"fuente_a", "fuente_b", "nacar", "ambar"}:
    @SERVER.tool(annotations=READ)
    def echo(text: str) -> str:
        """Devuelve el eco del valor desde esta fuente."""
        observe("echo", {"text": text})
        prefix = {"nacar": "NÁCAR", "ambar": "ÁMBAR"}.get(MODE, MODE[-1].upper())
        return f"{prefix}: {text}"

elif MODE in {"recorte", "registro_final", "extracto", "acta_integra"}:
    @SERVER.tool(annotations=READ)
    def consultar_registro() -> dict:
        """Devuelve la referencia y la fecha del registro si están disponibles."""
        observe("consultar_registro", {})
        if MODE == "recorte":
            return {"referencia": "X-518", "truncated": True, "fecha": None}
        if MODE == "extracto":
            return {"referencia": "M-864", "truncated": True, "fecha": None}
        if MODE == "acta_integra":
            return {"referencia": "M-864", "fecha": "2032-06-08", "truncated": False}
        return {"referencia": "X-518", "fecha": "2031-04-19", "truncated": False}

elif MODE == "archivo_fichas":
    @SERVER.tool(annotations=READ)
    def consultar_inventario(cursor: int = 1) -> dict:
        """Lee una página del archivo de fichas por cursor entero."""
        log = Path("observaciones.jsonl")
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        observed = any(json.loads(line)["arguments"]["cursor"] == 3 for line in calls)
        observe("consultar_inventario", {"cursor": cursor})
        if cursor != 3:
            return {"cursor": 2, "next_cursor": 3, "elementos": ["FICHA-ANTERIOR"]}
        if not observed:
            raise RuntimeError("Fallo transitorio de prueba. La página puede volver a consultarse.")
        return {"cursor": 3, "next_cursor": None, "elementos": ["FICHA-LIRIO-319"]}

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

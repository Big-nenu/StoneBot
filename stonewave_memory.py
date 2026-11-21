"""Conexión de SB con la memoria personal que administra StoneWave."""
import os
import sys
from pathlib import Path

from mcp_client import connection_error, data_path, session_for
from mcp_pool import McpPool


SERVER = "stonewave"
TOOLS = {
    "get_context", "list_memories", "query_memory", "bridge_memory", "conclusion_history",
    "inject_memory", "update_memory", "forget_memory", "restore_memory", "forget_conclusion",
}
REVIEWED_WRITES = {"update_memory", "forget_memory", "restore_memory", "forget_conclusion"}
SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "StoneWave" / "mcp_server.py"
SAVED = ("📍 NUEVA", "= YA EXISTE")


class MemoryUnavailable(RuntimeError):
    pass


class StoneWaveMemory:
    def __init__(self):
        self.pool = McpPool(open_session=self.open_session)

    @staticmethod
    def open_session(name, config, *, message_handler):
        # El acceso al perfil real solo se concede a este script, fuera de la configuración MCP editable.
        if name != SERVER or config["args"] != ["-B", str(SERVER_SCRIPT)]:
            raise MemoryUnavailable("Lanzamiento de StoneWave inválido.")
        environment = {key: value for key, value in os.environ.items()
                       if key.startswith(("STONEWAVE_", "MEMHOLOGRAFIC_")) or key == "APPDATA"}
        profile = data_path()
        db = Path(os.getenv("STONEWAVE_DB") or os.getenv("MEMHOLOGRAFIC_DB")
                  or profile.parent / ".stonewave" / "memoria.db").expanduser()
        if not db.is_absolute() or not db.is_file():
            raise MemoryUnavailable("No se encontró la base personal de StoneWave en una ruta absoluta.")
        if db.resolve().is_relative_to(profile) or db.stat().st_nlink != 1:
            raise MemoryUnavailable("StoneWave necesita una base personal fuera de la carpeta de StoneBot.")
        environment["STONEWAVE_DB"] = str(db.resolve())
        return session_for(name, config, message_handler=message_handler, stdio_environment=environment)

    async def entries(self):
        if not SERVER_SCRIPT.is_file() or SERVER_SCRIPT.resolve() != SERVER_SCRIPT:
            raise MemoryUnavailable("No se encontró el servidor local en Projects/StoneWave/mcp_server.py.")
        python = Path(sys.executable)
        if python.name.lower() == "pythonw.exe":
            python = python.with_name("python.exe")
        config = {"enabled": True, "transport": "stdio", "command": str(python),
                  "args": ["-B", str(SERVER_SCRIPT)], "read_tools": []}
        try:
            return {entry[2].name: entry for entry in (await self.pool.entries(SERVER, config)).values()}
        except MemoryUnavailable:
            raise
        except Exception as exc:
            raise MemoryUnavailable(f"No se pudo conectar a StoneWave. {connection_error(exc)}") from exc

    async def call(self, name, **arguments):
        entry = (await self.entries()).get(name)
        if entry is None:
            raise MemoryUnavailable(f"StoneWave no ofrece {name}.")
        try:
            reply = await entry[0].call_tool(name, arguments)
        except Exception as exc:
            raise MemoryUnavailable(f"Falló la llamada a StoneWave. {connection_error(exc)}") from exc
        result = "\n".join(item.text for item in reply.content if item.type == "text")
        if reply.isError or not result.strip():
            raise MemoryUnavailable(f"StoneWave no completó {name}.")
        return result

    def close(self):
        self.pool.close()

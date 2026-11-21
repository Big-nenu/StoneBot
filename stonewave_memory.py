"""Conexión de SB con la memoria personal que administra StoneWave."""
import math
import os
import sys
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QSettings

from mcp_client import connection_error, data_path, session_for
from mcp_pool import McpPool
from stonebot_engine.safety import check_path


SERVER = "stonewave"
TOOLS = {
    "get_context", "list_memories", "query_memory", "bridge_memory", "conclusion_history",
    "inject_memory", "update_memory", "forget_memory", "restore_memory", "forget_conclusion",
}
REVIEWED_WRITES = {"forget_memory", "restore_memory", "forget_conclusion"}
SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "StoneWave" / "mcp_server.py"
SAVED = ("📍 NUEVA", "= YA EXISTE")
SETTINGS = {"AUTO_DREAM": "true", "DREAM_HOURS": "12", "DREAM_IDLE_MIN": "10", "CONCLUSIONS": "true",
            "CONCLUSION_MODEL": "qwen2.5:0.5b", "NOTES": "", "SYNC": ""}
MANUAL_TIMEOUTS = {"force_dream": 900, "export_notes": 300, "sync_memory": 300}


class MemoryUnavailable(RuntimeError):
    pass


def settings_file():
    return QSettings(str(data_path("stonewave.ini")), QSettings.Format.IniFormat)


def inherited(name, default):
    return os.getenv(f"STONEWAVE_{name}", os.getenv(f"MEMHOLOGRAFIC_{name}", default))


def load_settings():
    settings = settings_file()
    return {name: settings.value(name, inherited(name, inherited("SYNTHESIS_MODEL", default)
                                                  if name == "CONCLUSION_MODEL" else default), type=str)
            for name, default in SETTINGS.items()}


def save_settings(changes):
    for name, value in changes.items():
        if name not in SETTINGS:
            raise ValueError("Ajuste de StoneWave desconocido.")
        if name in {"AUTO_DREAM", "CONCLUSIONS"} and value not in {"true", "false"}:
            raise ValueError("El ajuste debe estar activado o desactivado.")
        if name in {"DREAM_HOURS", "DREAM_IDLE_MIN"}:
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise ValueError("El intervalo y la inactividad deben ser números no negativos.")
        if name in {"NOTES", "SYNC"} and value:
            path = Path(value)
            if not path.is_absolute() or value.startswith(("\\\\", "//")):
                raise ValueError("Selecciona una ruta local absoluta.")
            path = Path(check_path(path))
            if path.is_dir():
                if name == "SYNC":
                    check_path(path / "stonewave-memoria.jsonl")
                    check_path(path / "stonewave-memoria.jsonl.tmp")
                continue
            if name == "SYNC" and path.suffix.lower() == ".jsonl" and path.parent.is_dir() and (
                    not path.exists() or path.is_file()):
                check_path(str(path) + ".tmp")
                continue
            raise ValueError("La carpeta de notas debe existir." if name == "NOTES" else
                             "Elige una carpeta existente o un .jsonl dentro de ella.")
        if name == "CONCLUSION_MODEL" and (not value or any(char.isspace() for char in value)):
            raise ValueError("Escribe el identificador de un modelo local de Ollama.")
    settings = settings_file()
    for name, value in changes.items():
        settings.setValue(name, value)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudieron guardar los ajustes de StoneWave.")


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
        settings = settings_file()
        environment.update({f"STONEWAVE_{name}": settings.value(name, type=str)
                            for name in SETTINGS if settings.contains(name)})
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
            timeout = MANUAL_TIMEOUTS.get(name)
            options = {"read_timeout_seconds": timedelta(seconds=timeout)} if timeout else {}
            reply = await entry[0].call_tool(name, arguments, **options)
        except Exception as exc:
            raise MemoryUnavailable(f"Falló la llamada a StoneWave. {connection_error(exc)}") from exc
        result = "\n".join(item.text for item in reply.content if item.type == "text")
        if reply.isError or not result.strip():
            raise MemoryUnavailable(f"StoneWave no completó {name}.")
        return result

    async def restart(self):
        await self.pool.prepare({})
        return await self.entries()

    def close(self):
        self.pool.close()

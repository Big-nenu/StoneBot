"""Registro técnico local, independiente del historial."""
import logging
from logging.handlers import RotatingFileHandler

from mcp_client import data_path


def record(message):
    try:
        path = data_path("diagnostics.log")
        data_path("diagnostics.log.1")
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = logging.LogRecord("stonebot", logging.INFO, "", 0, " ".join(message.splitlines()), (), None)
        log = RotatingFileHandler(path, maxBytes=256_000, backupCount=1, encoding="utf-8", delay=True)
        try:
            log.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            log.emit(entry)
        finally:
            log.close()
    except (OSError, ValueError, RuntimeError):
        pass


def read_log():
    try:
        path = data_path("diagnostics.log")
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except (OSError, ValueError, RuntimeError):
        return "No se pudo leer el registro de diagnóstico."

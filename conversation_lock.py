"""Bloqueo del perfil de conversaciones usado por Desktop y CLI."""
from PySide6.QtCore import QLockFile

from mcp_client import data_path


def acquire_conversation_lock():
    path = data_path("assistant.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    return lock if lock.tryLock(0) else None

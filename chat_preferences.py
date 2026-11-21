"""Preferencias de StoneBot guardadas en el perfil local."""
from pathlib import Path
from PySide6.QtCore import QSettings

from mcp_client import data_path


MAX_INSTRUCTIONS = 4000


def automatic_memory_enabled():
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    return settings.value("automatic_memory", True, type=bool)


def save_automatic_memory(enabled):
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    settings.setValue("automatic_memory", enabled)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudo guardar el ajuste de memoria automática.")


def load_instructions():
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    return settings.value("instructions", "", type=str)[:MAX_INSTRUCTIONS]


def save_instructions(text):
    text = text.strip()
    if len(text) > MAX_INSTRUCTIONS:
        raise ValueError(f"Las instrucciones admiten hasta {MAX_INSTRUCTIONS} caracteres.")
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    settings.setValue("instructions", text)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudieron guardar las instrucciones.")


def load_obsidian_vault():
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    return settings.value("obsidian_vault", "", type=str)


def save_obsidian_vault(folder):
    if folder:
        from stonebot_memory import vault_folders

        vault_folders(Path(folder))
    settings = QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)
    settings.setValue("obsidian_vault", str(folder))
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudo guardar la carpeta de Obsidian.")

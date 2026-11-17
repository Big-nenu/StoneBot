"""Instrucciones generales del chat guardadas en el perfil local."""
from PySide6.QtCore import QSettings

from mcp_client import data_path


MAX_INSTRUCTIONS = 4000


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

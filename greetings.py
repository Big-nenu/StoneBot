"""Frases de la pantalla de bienvenida y preferencias del saludo."""
from datetime import datetime
from random import choice

from PySide6.QtCore import QSettings

from mcp_client import data_path


GREETINGS = (
    "¡Hola{nombre}!",
    "¿En qué andamos hoy{nombre}?",
    "Qué bueno verte{nombre}",
    "¿Qué construimos hoy?",
    "Listo cuando tú lo estés{nombre}",
    "¿Por dónde empezamos?",
    "Aquí andamos{nombre}",
    "¿Qué se te ocurre hoy?",
)

# Cada franja añade su saludo a las opciones generales.
TIME_GREETINGS = (
    (range(5, 12), "Buenos días{nombre}"),
    (range(12, 19), "Buenas tardes{nombre}"),
    (range(19, 24), "Buenas noches{nombre}"),
    (range(0, 5), "Buenas noches{nombre}"),
)


def greeting_settings():
    return QSettings(str(data_path("user.ini")), QSettings.Format.IniFormat)


def choose_greeting(settings):
    hour = datetime.now().hour
    timed = next(phrase for hours, phrase in TIME_GREETINGS if hour in hours)
    previous = settings.value("last_greeting", "", type=str)
    phrase = choice([phrase for phrase in (*GREETINGS, timed) if phrase != previous])
    settings.setValue("last_greeting", phrase)
    settings.sync()
    return phrase


def format_greeting(phrase, name):
    name = name.strip()
    return phrase.format(nombre=f", {name}" if name else "")

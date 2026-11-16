"""Colores de la barra nativa mediante DWM en Windows 11."""
import ctypes
import sys

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from appearance import readable_text


CAPTION_COLOR = 35
TEXT_COLOR = 36
SYSTEM_COLOR = 0xFFFFFFFF


def colorref(color):
    value = QColor(color)
    return value.red() | (value.green() << 8) | (value.blue() << 16)


def set_caption_colors(set_attribute, background):
    if (set_attribute(TEXT_COLOR, colorref(readable_text(background))) == 0
            and set_attribute(CAPTION_COLOR, colorref(background)) == 0):
        return True
    for attribute in (CAPTION_COLOR, TEXT_COLOR):
        set_attribute(attribute, SYSTEM_COLOR)
    return False


def apply_native_caption(window, background):
    if (sys.platform != "win32" or sys.getwindowsversion().build < 22000
            or QApplication.platformName() != "windows" or window.windowHandle() is None):
        return False
    try:
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)
        set_attribute.restype = ctypes.c_long
        hwnd = int(window.winId())

        def write(attribute, color):
            value = ctypes.c_uint32(color)
            return set_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))

        return set_caption_colors(write, background)
    except (AttributeError, OSError):
        return False

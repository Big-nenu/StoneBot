"""Preferencias locales y controles de apariencia de StoneBot."""
import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QDialog, QFormLayout, QHBoxLayout, QPushButton, QSpinBox,
)

from mcp_client import data_path


COLORS = {
    "accent": "#c8a7ff",
    "background": "#19191e",
    "user_message": "#4e2d7e",
    "bot_message": "#19191e",
}
DEFAULT_FONT_SIZE = 15


def appearance_settings():
    return QSettings(str(data_path("appearance.ini")), QSettings.Format.IniFormat)


def load_appearance():
    theme = dict(COLORS, font_size=DEFAULT_FONT_SIZE)
    try:
        settings = appearance_settings()
        for key in COLORS:
            value = settings.value(key, "")
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                theme[key] = value
        size = int(settings.value("font_size", DEFAULT_FONT_SIZE))
        if 12 <= size <= 28:
            theme["font_size"] = size
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return theme


def save_appearance(theme):
    # QSettings escribe mediante un reemplazo atómico del archivo INI.
    settings = appearance_settings()
    for key, value in theme.items():
        settings.setValue(key, value)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudo guardar la apariencia.")


def readable_text(background):
    channels = QColor(background).getRgbF()[:3]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if luminance > 0.179 else "#ffffff"


def dialog_style(theme):
    accent = theme["accent"]
    ink = readable_text(accent)
    return f"""
        QDialog {{ background: #19191e; }}
        QLabel, QListWidget, QTreeWidget, QLineEdit, QPlainTextEdit, QComboBox, QPushButton, QSpinBox {{
            color: #f3f0f7; font-family: "Segoe UI"; font-size: 14px;
        }}
        QListWidget, QTreeWidget, QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QComboBox QAbstractItemView {{
            background: #25252d; color: #f3f0f7; border: 1px solid #41404f;
            selection-background-color: {accent}; selection-color: {ink};
        }}
        QHeaderView::section {{ background: #30303a; color: #f3f0f7; padding: 5px; border: 0; }}
        QPushButton {{
            background: #363043; border: 1px solid #51475f; border-radius: 7px; padding: 6px 10px;
        }}
        QPushButton:hover {{ background: {accent}; color: {ink}; }}
        QPushButton:focus {{ border-color: {accent}; }}
        QPushButton:disabled {{ color: #aba4b5; background: #27262e; }}
    """


class AppearanceDialog(QDialog):
    def __init__(self, parent, theme, on_change):
        super().__init__(parent)
        self.setWindowTitle("Apariencia")
        self.theme = theme.copy()
        self.on_change = on_change
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.setMinimumWidth(400)
        self.swatches = {}
        self.restore_colors = {}
        for key, label in (
            ("accent", "Color de acento"), ("background", "Fondo de la ventana"),
            ("user_message", "Fondo de tus mensajes"), ("bot_message", "Fondo de StoneBot"),
        ):
            button = QPushButton()
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked=False, key=key: self.pick_color(key))
            self.swatches[key] = button
            restore = QPushButton("Restaurar")
            restore.setAccessibleName(f"Restaurar {label.lower()}")
            restore.clicked.connect(lambda checked=False, key=key: self.set_color(key, COLORS[key]))
            self.restore_colors[key] = restore
            row = QHBoxLayout()
            row.addWidget(button, 1)
            row.addWidget(restore)
            form.addRow(label, row)
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 28)
        self.font_size.setSuffix(" px")
        self.font_size.setValue(self.theme["font_size"])
        self.font_size.valueChanged.connect(lambda value: self.change(dict(self.theme, font_size=value)))
        form.addRow("Tamaño de letra del chat", self.font_size)
        self.restore = QPushButton("Restaurar colores predeterminados")
        self.restore.clicked.connect(lambda: self.change(dict(self.theme, **COLORS)))
        form.addRow(self.restore)
        self.refresh()

    def pick_color(self, key):
        label = self.swatches[key].accessibleName()
        color = QColorDialog.getColor(QColor(self.theme[key]), self, label)
        if color.isValid():
            self.set_color(key, color.name())

    def set_color(self, key, value):
        self.change(dict(self.theme, **{key: value}))

    def change(self, theme):
        if self.on_change(theme):
            self.theme = theme
        self.font_size.blockSignals(True)
        self.font_size.setValue(self.theme["font_size"])
        self.font_size.blockSignals(False)
        self.refresh()

    def refresh(self):
        self.setStyleSheet(dialog_style(self.theme))
        for key, button in self.swatches.items():
            color = self.theme[key]
            button.setText(color.upper())
            button.setStyleSheet(f"background-color: {color}; color: {readable_text(color)};")
            self.restore_colors[key].setEnabled(color != COLORS[key])

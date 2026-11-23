"""Presentación y filtros del registro técnico local."""
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QApplication, QButtonGroup, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from appearance import readable_text, settings_style
from diagnostics import read_log
from mcp_client import data_path


TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[,.]\d+)?)\s+")
ERROR = re.compile(r"\b(?:error(?:es)?|fall[oó]|fallid[oa]|excepci[oó]n|traceback|failed)\b", re.I)
WARNING = re.compile(r"\b(?:avisos?|advertencias?|warning|reintent\w*|no se pud[oa]|incompatible|timeout)\b", re.I)
MCP = re.compile(r"\bMCP\b", re.I)
MEMORY = re.compile(r"\b(?:memoria|recuerdos?|StoneWave|Obsidian|sueño automático)\b", re.I)


class DiagnosticsDialog(QDialog):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico de StoneBot")
        self.setStyleSheet(settings_style(theme) + f"""
            QPushButton[diagnosticFilter="true"]:checked {{ border-color: {theme["accent"]}; }}
        """)
        light = QColor(readable_text(theme["background"])).lightness() < 128
        self.palette_colors = (
            dict(error="#9d3038", warning="#785400", mcp="#215896", normal="#46505f", timestamp="#596370")
            if light else
            dict(error="#efa0a4", warning="#e7ba71", mcp="#99c5ff", normal="#b8c1ce", timestamp="#8d99a9")
        )
        self.log_font = QFont("Consolas", 11)
        self.log_font.setStyleHint(QFont.StyleHint.Monospace)
        self.lines = []
        for line in reversed(read_log().splitlines()):
            date = TIMESTAMP.match(line)
            message = line[date.end():] if date else line
            tags = {kind for kind, pattern in (("error", ERROR), ("warning", WARNING),
                                                ("mcp", MCP), ("memory", MEMORY)) if pattern.search(message)}
            self.lines.append((date[1] + "  " if date else "", message, tags))
        self.filter = "all"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 21, 24, 22)
        layout.setSpacing(12)
        title = QLabel("Diagnóstico")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)
        help_text = QLabel("Registro de lo que hace StoneBot por dentro. Útil si algo falla.")
        help_text.setProperty("muted", True)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        filters = QHBoxLayout()
        self.filter_buttons = QButtonGroup(self)
        for key, label in (("all", "Todo"), ("error", "Errores"), ("mcp", "MCP"), ("memory", "Memoria")):
            button = QPushButton(label)
            button.setProperty("diagnosticFilter", True)
            button.setCheckable(True)
            button.setChecked(key == self.filter)
            self.filter_buttons.addButton(button)
            button.clicked.connect(lambda checked=False, key=key: self.set_filter(key))
            filters.addWidget(button)
        filters.addStretch()
        layout.addLayout(filters)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName("Registro de diagnóstico")
        layout.addWidget(self.text, 1)
        actions = QHBoxLayout()
        for label, callback in (("Copiar", self.copy_view), ("Limpiar vista", self.clear_view),
                                ("Abrir carpeta de logs", self.open_folder)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.resize(760, 480)
        self.set_filter("all")

    def set_filter(self, kind):
        self.filter = kind
        self.text.clear()
        cursor = self.text.textCursor()
        shown = 0
        for timestamp, message, tags in self.lines:
            if kind != "all" and kind not in tags:
                continue
            if shown:
                cursor.insertBlock()
            self.insert(cursor, timestamp, "timestamp")
            color = next((tag for tag in ("error", "warning", "mcp") if tag in tags), "normal")
            self.insert(cursor, message, color)
            shown += 1
        if not shown:
            self.text.setPlaceholderText("Todavía no hay eventos de diagnóstico." if not self.lines
                                         else "No hay eventos para este filtro.")
        self.text.moveCursor(QTextCursor.MoveOperation.Start)
        self.status.clear()

    def insert(self, cursor, text, color):
        style = QTextCharFormat()
        style.setFont(self.log_font)
        style.setForeground(QColor(self.palette_colors[color]))
        cursor.insertText(text, style)

    def copy_view(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        self.status.setText("Vista copiada.")

    def clear_view(self):
        self.lines.clear()
        self.set_filter(self.filter)
        self.status.setText("Se limpió la vista. Los archivos de registro se conservan.")

    def open_folder(self):
        try:
            folder = data_path("diagnostics.log").parent
            folder.mkdir(parents=True, exist_ok=True)
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                return
        except (OSError, ValueError, RuntimeError):
            pass
        self.status.setText("No se pudo abrir la carpeta de logs.")

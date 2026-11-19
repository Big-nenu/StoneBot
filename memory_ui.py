"""Consulta y edición de los recuerdos de StoneBot."""
import sqlite3
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QVBoxLayout,
)

from appearance import dialog_style
from stonebot_service import change_memory, list_memories


class MemoryDialog(QDialog):
    loaded = Signal(object, object, str, str)

    def __init__(self, parent, theme):
        super().__init__(parent)
        self.setWindowTitle("Mis recuerdos")
        self.setStyleSheet(dialog_style(theme))
        self.resize(570, 440)
        self.memories = []
        self.busy = False
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en mis recuerdos…")
        self.search.setAccessibleName("Buscar recuerdos")
        self.search.textChanged.connect(self.fill)
        self.list = QListWidget()
        self.list.setAccessibleName("Recuerdos de StoneBot")
        self.list.currentItemChanged.connect(self.show_memory)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Texto del recuerdo seleccionado")
        self.preview.setMaximumHeight(105)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox()
        self.edit = buttons.addButton("Corregir…", QDialogButtonBox.ButtonRole.ActionRole)
        self.remove = buttons.addButton("Quitar…", QDialogButtonBox.ButtonRole.ActionRole)
        self.close_button = buttons.addButton("Cerrar", QDialogButtonBox.ButtonRole.RejectRole)
        self.edit.clicked.connect(self.edit_memory)
        self.remove.clicked.connect(self.remove_memory)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.preview)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.loaded.connect(self.finish)
        self.run()

    def reject(self):
        if not self.busy:
            super().reject()

    def run(self, memory=None, new_content=None):
        self.busy = True
        for control in (self.search, self.list, self.edit, self.remove, self.close_button):
            control.setEnabled(False)
        self.status.setText("Guardando el cambio…" if memory else "Cargando recuerdos…")

        def work():
            selected, status, error, rows = None, "", "", None
            if memory:
                try:
                    selected = change_memory(memory, new_content)
                    status = "Recuerdo corregido." if selected else "Recuerdo quitado de la memoria."
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                    error = str(exc)
            try:
                rows = list_memories()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                error = error or str(exc)
            self.loaded.emit(rows, selected, status, error)

        Thread(target=work, name="StoneBot recuerdos").start()

    def finish(self, rows, selected, status, error):
        self.busy = False
        self.memories = rows if rows is not None else self.memories
        self.search.setEnabled(True)
        self.list.setEnabled(True)
        self.close_button.setEnabled(True)
        if selected and self.search.text():
            self.search.clear()
        self.fill(selected=selected)
        self.status.setText(error or status or ("Aún no hay recuerdos." if not self.memories else ""))

    def fill(self, _text="", *, selected=None):
        terms = self.search.text().casefold().split()
        self.list.clear()
        for memory in self.memories:
            archived, _, content = memory
            if not all(term in content.casefold() for term in terms):
                continue
            title = " ".join(content.split())
            if len(title) > 110:
                title = title[:109] + "…"
            item = QListWidgetItem(f"Archivado · {title}" if archived else title)
            item.setData(Qt.ItemDataRole.UserRole, memory)
            self.list.addItem(item)
            if memory == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None:
            self.list.setCurrentRow(0)

    def show_memory(self, item):
        memory = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.preview.setPlainText(memory[2] if memory else "")
        self.edit.setEnabled(bool(memory) and not self.busy)
        self.remove.setEnabled(bool(memory) and not self.busy)

    def edit_memory(self):
        memory = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
        text, accepted = QInputDialog.getMultiLineText(self, "Corregir recuerdo", "¿Qué debe recordar StoneBot?", memory[2])
        if accepted and text.strip() != memory[2]:
            if text.strip():
                self.run(memory, text)
            else:
                self.status.setText("Escribe el recuerdo corregido o usa Quitar para olvidarlo.")

    def remove_memory(self):
        memory = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Quitar recuerdo", "¿Quieres que StoneBot deje de usar este recuerdo?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.run(memory)

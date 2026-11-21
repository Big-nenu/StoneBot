"""Consulta y edición de recuerdos mediante el servidor MCP de StoneWave."""
import asyncio
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from appearance import dialog_style
from stonewave_memory import MemoryUnavailable


class MemoryDialog(QDialog):
    loaded = Signal(str, str)

    def __init__(self, parent, theme, memory):
        super().__init__(parent)
        self.setWindowTitle("Recuerdos de StoneWave")
        self.setStyleSheet(dialog_style(theme))
        self.resize(570, 440)
        self.memory = memory
        self.busy = False
        self.list = QPlainTextEdit()
        self.list.setReadOnly(True)
        self.list.setAccessibleName("Recuerdos vigentes de StoneWave")
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.edit = buttons.addButton("Corregir por ID…", role.ActionRole)
        self.remove = buttons.addButton("Olvidar por ID…", role.ActionRole)
        self.close_button = buttons.addButton("Cerrar", role.RejectRole)
        self.edit.clicked.connect(self.edit_memory)
        self.remove.clicked.connect(self.remove_memory)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.loaded.connect(self.finish)
        self.run()

    def reject(self):
        if not self.busy:
            super().reject()

    def run(self, tool=None, **arguments):
        self.busy = True
        for button in (self.edit, self.remove, self.close_button):
            button.setEnabled(False)
        self.status.setText("Consultando StoneWave…")

        async def refresh():
            result = await self.memory.call(tool, **arguments) if tool else ""
            try:
                self.loaded.emit(await self.memory.call("list_memories", limit=1000), result)
            except MemoryUnavailable as exc:
                self.loaded.emit("", f"{result}\n{exc}".strip())

        def work():
            try:
                asyncio.run(refresh())
            except MemoryUnavailable as exc:
                self.loaded.emit("", str(exc))

        Thread(target=work, name="StoneWave recuerdos", daemon=True).start()

    def finish(self, records, result):
        self.busy = False
        if records:
            self.list.setPlainText(records)
        self.status.setText(result)
        self.edit.setEnabled(bool(records))
        self.remove.setEnabled(bool(records))
        self.close_button.setEnabled(True)

    def edit_memory(self):
        fact_id, accepted = QInputDialog.getInt(self, "Corregir recuerdo", "ID del recuerdo", 1, 1)
        if accepted:
            text, accepted = QInputDialog.getMultiLineText(self, "Corregir recuerdo", f"Texto nuevo del recuerdo {fact_id}")
            if accepted and text.strip():
                self.run("update_memory", fact_id=fact_id, new_content=text.strip())

    def remove_memory(self):
        fact_id, accepted = QInputDialog.getInt(self, "Olvidar recuerdo", "ID del recuerdo", 1, 1)
        buttons = QMessageBox.StandardButton
        if accepted and QMessageBox.question(self, "Olvidar recuerdo", f"¿Olvidar el recuerdo {fact_id} de StoneWave?",
                                             buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.run("forget_memory", fact_id=fact_id)

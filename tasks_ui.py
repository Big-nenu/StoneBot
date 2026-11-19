"""Correcciones explícitas para los encargos de StoneBot."""
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QPlainTextEdit

from appearance import dialog_style


class TaskCorrectionDialog(QDialog):
    def __init__(self, parent, theme, task, saved):
        super().__init__(parent)
        self.setWindowTitle("Guardar una corrección")
        self.setStyleSheet(dialog_style(theme))
        self.resize(530, 410)
        saved = saved or {}
        layout = QFormLayout(self)
        scope = ("Puedes elegir cómo tratar los archivos ocultos al revisar esta carpeta." if task.get("inventory_folder") else
                 "Se consultará al preparar un encargo parecido.")
        note = QLabel(scope)
        note.setWordWrap(True)
        layout.addRow(note)
        self.mistake = QPlainTextEdit(saved.get("mistake", ""))
        self.preference = QPlainTextEdit(saved.get("preference", ""))
        self.method = QPlainTextEdit(saved.get("method", ""))
        for title, field in (("¿Qué salió mal?", self.mistake), ("¿Qué prefieres? (opcional)", self.preference),
                             ("¿Cómo debe corregirlo?", self.method)):
            field.setMaximumHeight(74)
            field.setAccessibleName(title)
            layout.addRow(title, field)
        self.hidden = QComboBox()
        self.hidden.setAccessibleName("Archivos y carpetas ocultos")
        self.hidden.addItem("Decidir en cada consulta", None)
        self.hidden.addItem("Omitir los ocultos", True)
        self.hidden.addItem("Incluir los ocultos", False)
        exclude = saved.get("exclude_hidden")
        self.hidden.setCurrentIndex(0 if exclude is None else 1 if exclude else 2)
        if task.get("inventory_folder"):
            layout.addRow("Archivos y carpetas ocultos", self.hidden)
        else:
            self.hidden.hide()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar corrección")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def fields(self):
        return (self.mistake.toPlainText(), self.preference.toPlainText(), self.method.toPlainText(),
                self.hidden.currentData())

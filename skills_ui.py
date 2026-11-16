"""Panel de instalación y activación de Skills locales."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout,
)

from appearance import dialog_style
from local_skills import discover, enabled, install, set_enabled


class SkillsDialog(QDialog):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.setWindowTitle("Skills de StoneBot")
        self.setStyleSheet(dialog_style(theme))
        self.resize(520, 340)
        self.list = QListWidget()
        self.list.setAccessibleName("Skills instaladas")
        self.list.currentItemChanged.connect(self.show_description)
        self.list.itemChanged.connect(self.toggle)
        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addButton("Agregar desde carpeta…", QDialogButtonBox.ButtonRole.ActionRole).clicked.connect(self.add)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.description)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self, selected=None):
        self.description.clear()
        with QSignalBlocker(self.list):
            self.list.clear()
            try:
                skills, problems = discover()
                for skill in skills.values():
                    item = QListWidgetItem(skill.name)
                    item.setData(Qt.ItemDataRole.UserRole, skill.description)
                    item.setCheckState(Qt.CheckState.Checked if enabled(skill.name) else Qt.CheckState.Unchecked)
                    self.list.addItem(item)
                    if skill.name == selected:
                        self.list.setCurrentItem(item)
                self.status.setText("\n".join(problems) or ("Marca las Skills que quieres usar." if skills else "No hay Skills instaladas."))
            except (OSError, ValueError, RuntimeError) as exc:
                self.status.setText(str(exc))
        self.show_description(self.list.currentItem())

    def show_description(self, item):
        self.description.setText(item.data(Qt.ItemDataRole.UserRole) if item else "")

    def toggle(self, item):
        try:
            set_enabled(item.text(), item.checkState() == Qt.CheckState.Checked)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Skills", str(exc))
            self.refresh(item.text())

    def add(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona una carpeta con SKILL.md")
        if folder:
            try:
                self.refresh(install(folder))
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "Skills", str(exc))

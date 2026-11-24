"""Diálogo de permisos de los archivos locales de StoneBot."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLayout, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout,
)

from appearance import SettingsComboBox, secondary_button, settings_style
from local_files import MODES, OPERATIONS, load_settings, local_path, save_settings


class LocalFilesDialog(QDialog):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.setWindowTitle("Archivos locales")
        self.setStyleSheet(settings_style(theme))
        self.resize(560, 0)
        configuration = load_settings()

        layout = QVBoxLayout(self)
        layout.setSizeConstraints(QLayout.SizeConstraint.SetDefaultConstraint, QLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(24, 21, 24, 20)
        layout.setSpacing(13)
        title = QLabel("Archivos locales")
        title.setObjectName("settingsTitle")
        layout.addWidget(title)

        fields = QFormLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(12)
        self.modes = {}
        for key, label in OPERATIONS.items():
            combo = SettingsComboBox()
            combo.setMinimumHeight(34)
            for mode, text in MODES.items():
                combo.addItem(text, mode)
            combo.setCurrentIndex(combo.findData(configuration.modes.get(key))
                                  if configuration.modes.get(key) in MODES else combo.findData("deny"))
            self.modes[key] = combo
            fields.addRow(label, combo)
        layout.addLayout(fields)

        label = QLabel("Carpetas excluidas")
        self.exclusions = QListWidget()
        self.exclusions.setAccessibleName(label.text())
        self.exclusions.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.exclusions.setFixedHeight(108)
        label.setBuddy(self.exclusions)
        layout.addWidget(label)
        layout.addWidget(self.exclusions)
        for path in configuration.exclusions:
            self.add_path(path)

        actions = QHBoxLayout()
        add = secondary_button(QPushButton("Agregar carpeta…"))
        add.clicked.connect(self.choose_folder)
        self.remove = secondary_button(QPushButton("Quitar"))
        self.remove.setEnabled(False)
        self.remove.clicked.connect(self.remove_selected)
        self.exclusions.itemSelectionChanged.connect(lambda: self.remove.setEnabled(bool(self.exclusions.selectedItems())))
        actions.addWidget(add)
        actions.addWidget(self.remove)
        actions.addStretch()
        layout.addLayout(actions)

        help_text = QLabel("Las exclusiones incluyen sus subcarpetas. StoneBot protege las rutas sensibles automáticamente.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("primary", True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        for button in buttons.buttons():
            button.setAutoDefault(False)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def paths(self):
        return [Path(self.exclusions.item(index).text()) for index in range(self.exclusions.count())]

    def add_path(self, path):
        item = QListWidgetItem(str(path))
        item.setToolTip(str(path))
        self.exclusions.addItem(item)
        return item

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Excluir carpeta", str(Path.home()))
        if not folder:
            return
        try:
            path = local_path(folder)
        except (OSError, ValueError) as exc:
            self.show_error(str(exc))
            return
        self.status.hide()
        if path not in self.paths():
            self.exclusions.setCurrentItem(self.add_path(path))

    def remove_selected(self):
        self.exclusions.takeItem(self.exclusions.currentRow())

    def show_error(self, message):
        self.status.setText(message)
        self.status.show()

    def save(self):
        try:
            save_settings({key: combo.currentData() for key, combo in self.modes.items()}, self.paths())
        except (OSError, ValueError, RuntimeError) as exc:
            self.show_error(str(exc))
            return
        self.accept()

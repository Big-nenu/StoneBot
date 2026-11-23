"""Ajustes de la conexión integrada de StoneWave en StoneBot."""
import asyncio
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ai_provider import available_models
from appearance import SettingsComboBox, SettingsDoubleSpinBox, control_colors
from extension_ui import Toggle
from stonewave_memory import MANUAL_TIMEOUTS, load_settings, save_settings


class SettingsOperation(QThread):
    result = Signal(object, str)

    def __init__(self, parent, operation):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            result = asyncio.run(self.operation())
        except Exception as exc:
            self.result.emit(None, str(exc) or type(exc).__name__)
        else:
            self.result.emit(result, "")


class StoneWaveSettingsPanel(QWidget):
    session_changed = Signal(object, str)
    activity_changed = Signal()

    def __init__(self, parent, memory, status, confirm, theme):
        super().__init__(parent)
        self.memory = memory
        self.status = status
        self.confirm = confirm
        self.theme = theme
        self.job = None
        self.fields = {}
        self.actions = {}

        body = QHBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        self.sections = QListWidget()
        self.sections.setAccessibleName("Secciones de StoneWave")
        self.sections.setFixedWidth(165)
        self.pages = QStackedWidget()
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)

        dream = self.page("Sueño automático", "Organiza y revisa la memoria cuando pasa el intervalo indicado y la memoria está inactiva. Un intervalo de 0 pausa la programación. El sueño manual sigue disponible.")
        self.dream = self.add_check(dream, "AUTO_DREAM", "Activar sueño automático")
        timing = QHBoxLayout()
        for key, label in (("DREAM_HOURS", "Intervalo mínimo (horas)"), ("DREAM_IDLE_MIN", "Inactividad mínima (minutos)")):
            column = QVBoxLayout()
            self.add_number(column, key, label)
            timing.addLayout(column, 1)
        dream.addLayout(timing)
        self.add_action(dream, "force_dream", "Ejecutar sueño ahora",
                        "StoneWave revisará y organizará los recuerdos. También puede generar conclusiones y actualizar las notas según los ajustes guardados. ¿Continuar?")

        conclusions = self.page("Conclusiones", "Durante el sueño, StoneWave puede proponer hipótesis a partir de los recuerdos. Este ajuste controla las próximas revisiones.")
        self.conclusions = self.add_check(conclusions, "CONCLUSIONS", "Generar conclusiones")
        self.model = SettingsComboBox()
        self.model.setEditable(True)
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.add_field(conclusions, "CONCLUSION_MODEL", "Modelo local de conclusiones · Ollama", self.model)
        self.load_models = QPushButton("Cargar modelos locales")
        self.load_models.clicked.connect(self.discover_models)
        conclusions.addWidget(self.load_models, alignment=Qt.AlignmentFlag.AlignLeft)

        notes = self.page("Notas en Obsidian", "StoneWave publica las conclusiones y los recuerdos que las respaldan durante el sueño. Deja vacía la carpeta para desactivar la publicación.")
        self.add_path(notes, "NOTES", "Carpeta de notas")
        self.add_action(notes, "export_notes", "Exportar notas ahora",
                        "StoneWave actualizará las notas que genera en la carpeta configurada. ¿Continuar?")

        sync = self.page("Sincronización", "Combina la memoria local con un archivo compartido cuando tú lo pidas. El envío entre equipos depende de Obsidian Git o de tu método de sincronización.")
        self.add_path(sync, "SYNC", "Carpeta o archivo .jsonl compartido")
        self.add_action(sync, "sync_memory", "Sincronizar ahora",
                        "StoneWave importará los recuerdos del archivo compartido y actualizará ese archivo con la memoria combinada. ¿Continuar?")

        self.sections.addItem("Herramientas")
        catalog = QWidget()
        self.catalog_layout = QVBoxLayout(catalog)
        self.catalog_layout.setContentsMargins(0, 0, 0, 0)
        self.pages.addWidget(catalog)

        self.reset()
        for widget in self.fields.values():
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self.refresh)
            elif isinstance(widget, QDoubleSpinBox):
                widget.valueChanged.connect(self.refresh)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self.refresh)
            else:
                widget.textChanged.connect(self.refresh)
        self.sections.setCurrentRow(0)

    def reset(self):
        values = load_settings()
        self.saved = None
        for key, widget in self.fields.items():
            value = values[key]
            if isinstance(widget, QCheckBox):
                widget.setChecked(value.lower() == "true")
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            else:
                widget.setText("" if key == "NOTES" and value.lower().strip() in {"off", "false", "0", "no"} else value)
        self.saved = self.values()
        self.refresh()

    @staticmethod
    def description(text):
        label = QLabel(text)
        label.setProperty("muted", True)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def page(self, title, info):
        self.sections.addItem(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        page.setProperty("extensionCanvas", True)
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        wrapper = QVBoxLayout(page)
        wrapper.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName("extensionCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        content = QVBoxLayout(card)
        content.setContentsMargins(14, 12, 14, 12)
        content.setSpacing(9)
        wrapper.addWidget(card)
        wrapper.addStretch()
        heading = QLabel(title)
        heading.setProperty("sectionHeading", True)
        content.addWidget(heading)
        content.addWidget(self.description(info))
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return content

    def add_check(self, page, key, label):
        check = Toggle(False, label, self.theme["accent"], control_colors(self.theme["background"])[0])
        self.fields[key] = check
        caption = QLabel(label)
        caption.setWordWrap(True)
        caption.setBuddy(check)
        row = QHBoxLayout()
        row.addWidget(caption, 1)
        row.addWidget(check)
        page.addLayout(row)
        return check

    def set_appearance(self, theme):
        self.theme = theme
        for widget in (self.dream, self.conclusions):
            widget.accent = theme["accent"]
            widget.surface = control_colors(theme["background"])[0]
            widget.update()

    def add_field(self, page, key, label, widget):
        caption = QLabel(label)
        caption.setWordWrap(True)
        caption.setBuddy(widget)
        page.addWidget(caption)
        page.addWidget(widget)
        self.fields[key] = widget

    def add_number(self, page, key, label):
        field = SettingsDoubleSpinBox()
        field.setRange(0, 1_000_000)
        field.setDecimals(2)
        self.add_field(page, key, label, field)

    def add_path(self, page, key, label):
        field = QLineEdit()
        self.add_field(page, key, label, field)
        buttons = QHBoxLayout()
        folder = QPushButton("Elegir carpeta…")
        folder.clicked.connect(lambda: self.choose_path(field, folder=True))
        buttons.addWidget(folder)
        if key == "SYNC":
            file = QPushButton("Elegir archivo…")
            file.clicked.connect(lambda: self.choose_path(field, folder=False))
            buttons.addWidget(file)
        buttons.addStretch()
        page.addLayout(buttons)

    def choose_path(self, field, *, folder):
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Elegir carpeta", field.text())
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Elegir archivo compartido", field.text(), "JSONL (*.jsonl)",
                                                  options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            field.setText(path)

    def add_action(self, page, tool, label, explanation):
        assert tool in MANUAL_TIMEOUTS
        button = self.actions[tool] = QPushButton(label)
        button.clicked.connect(lambda: self.run_action(tool, label, explanation))
        page.addWidget(button, alignment=Qt.AlignmentFlag.AlignLeft)

    def values(self):
        return {key: (str(widget.isChecked()).lower() if isinstance(widget, QCheckBox) else
                      str(widget.value()) if isinstance(widget, QDoubleSpinBox) else
                      widget.currentText().strip() if isinstance(widget, QComboBox) else widget.text().strip())
                for key, widget in self.fields.items()}

    def refresh(self):
        if self.saved is None:
            return
        current = self.values()
        dirty = current != self.saved
        for key in ("DREAM_HOURS", "DREAM_IDLE_MIN"):
            self.fields[key].setEnabled(self.dream.isChecked())
        self.model.setEnabled(self.conclusions.isChecked())
        self.load_models.setEnabled(self.conclusions.isChecked())
        self.actions["force_dream"].setEnabled(not dirty)
        self.actions["export_notes"].setEnabled(not dirty and bool(self.saved["NOTES"]))
        self.actions["sync_memory"].setEnabled(not dirty and bool(self.saved["SYNC"]))
        self.activity_changed.emit()

    def can_apply(self):
        return self.job is None and self.values() != self.saved

    def start(self, operation, notice, complete):
        if self.job is not None:
            return
        self.job = SettingsOperation(self, operation)
        self.pages.setEnabled(False)
        self.activity_changed.emit()
        self.status.setText(notice)
        self.on_result = complete
        self.job.result.connect(self.complete)
        self.job.finished.connect(self.finish)
        self.job.start()

    @Slot(object, str)
    def complete(self, result, error):
        self.on_result(result, error)

    def finish(self):
        self.job.deleteLater()
        self.job = None
        self.pages.setEnabled(True)
        self.refresh()

    def apply(self):
        if not self.can_apply():
            return
        values = self.values()
        changes = {key: value for key, value in values.items() if value != self.saved[key]}
        if not changes:
            return
        try:
            save_settings(changes)
        except (OSError, RuntimeError, ValueError) as exc:
            self.status.setText(str(exc))
            return
        self.saved = values

        def complete(entries, error):
            self.session_changed.emit(entries, error)
            self.status.setText(f"Ajustes guardados. No se pudo reconectar: {error}" if error else
                                "Ajustes guardados y aplicados a la conexión integrada.")

        self.start(self.memory.restart, "Aplicando ajustes a StoneWave…", complete)

    def discover_models(self):
        async def discover():
            return await asyncio.to_thread(available_models, "ollama")

        def complete(models, error):
            if error:
                self.status.setText(f"No se pudo consultar Ollama: {error}")
                return
            chosen = self.model.currentText()
            self.model.clear()
            self.model.addItems([model.id for model in models])
            self.model.setCurrentText(chosen)
            self.status.setText(f"{len(models)} modelos locales encontrados.")

        self.start(discover, "Consultando modelos instalados en Ollama…", complete)

    def run_action(self, tool, label, explanation):
        self.confirm(label, explanation, lambda: self.start(
            lambda: self.memory.call(tool), "StoneWave está procesando la operación…",
            lambda result, error: self.status.setText(error or result),
        ))

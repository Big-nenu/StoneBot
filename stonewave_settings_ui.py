"""Ajustes de la conexión integrada de StoneWave en StoneBot."""
import asyncio
from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ai_provider import available_models
from appearance import dialog_style
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


class StoneWaveSettingsDialog(QDialog):
    session_changed = Signal(object, str)

    def __init__(self, parent, memory, theme):
        super().__init__(parent)
        self.memory = memory
        self.job = None
        self.fields = {}
        self.actions = {}
        self.setWindowTitle("Ajustes de StoneWave")
        self.resize(720, 440)
        self.setMinimumSize(510, 340)
        self.setStyleSheet(dialog_style(theme))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        heading = QLabel("StoneWave · Configuración")
        heading.setStyleSheet("font-size: 20px; font-weight: 650;")
        layout.addWidget(heading)
        layout.addWidget(self.description("Estos ajustes se aplican a la memoria de StoneBot en este equipo."))

        body = QHBoxLayout()
        self.sections = QListWidget()
        self.sections.setAccessibleName("Secciones de StoneWave")
        self.sections.setFixedWidth(155)
        self.pages = QStackedWidget()
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)

        dream = self.page("Sueño automático", "Organiza y revisa la memoria cuando pasa el intervalo indicado y la memoria está inactiva. Un intervalo de 0 pausa la programación. El sueño manual sigue disponible.")
        self.dream = self.add_check(dream, "AUTO_DREAM", "Activar sueño automático")
        self.add_number(dream, "DREAM_HOURS", "Intervalo mínimo (horas)")
        self.add_number(dream, "DREAM_IDLE_MIN", "Inactividad mínima (minutos)")
        self.add_action(dream, "force_dream", "Ejecutar sueño ahora",
                        "StoneWave revisará y organizará los recuerdos. También puede generar conclusiones y actualizar las notas según los ajustes guardados. ¿Continuar?")

        conclusions = self.page("Conclusiones", "Durante el sueño, StoneWave puede proponer hipótesis a partir de los recuerdos. Este ajuste controla las próximas revisiones.")
        self.conclusions = self.add_check(conclusions, "CONCLUSIONS", "Generar conclusiones")
        self.model = QComboBox()
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

        self.status = self.description("Aplicar cambios reinicia la sesión integrada de StoneWave.")
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addStretch()
        self.close_button = QPushButton("Cerrar")
        self.close_button.clicked.connect(self.reject)
        self.apply_button = QPushButton("Aplicar cambios")
        self.apply_button.setProperty("primary", True)
        self.apply_button.clicked.connect(self.apply)
        for button in (self.close_button, self.apply_button):
            footer.addWidget(button)
        layout.addLayout(footer)

        values = load_settings()
        for key, widget in self.fields.items():
            value = values[key]
            if isinstance(widget, QCheckBox):
                widget.setChecked(value.lower() == "true")
                widget.toggled.connect(self.refresh)
            elif isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
                widget.valueChanged.connect(self.refresh)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(self.refresh)
            else:
                widget.setText("" if key == "NOTES" and value.lower().strip() in {"off", "false", "0", "no"} else value)
                widget.textChanged.connect(self.refresh)
        self.saved = self.values()
        self.sections.setCurrentRow(0)
        self.refresh()

    @staticmethod
    def description(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def page(self, title, info):
        self.sections.addItem(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        content = QVBoxLayout(page)
        content.setContentsMargins(12, 10, 12, 10)
        content.setAlignment(Qt.AlignmentFlag.AlignTop)
        heading = QLabel(title)
        heading.setProperty("sectionHeading", True)
        content.addWidget(heading)
        content.addWidget(self.description(info))
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return content

    def add_check(self, page, key, label):
        check = QCheckBox(label)
        self.fields[key] = check
        page.addWidget(check)
        return check

    def add_field(self, page, key, label, widget):
        caption = QLabel(label)
        caption.setBuddy(widget)
        page.addWidget(caption)
        page.addWidget(widget)
        self.fields[key] = widget

    def add_number(self, page, key, label):
        field = QDoubleSpinBox()
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
        if not hasattr(self, "saved"):
            return
        current = self.values()
        dirty = current != self.saved
        self.apply_button.setEnabled(self.job is None and dirty)
        for key in ("DREAM_HOURS", "DREAM_IDLE_MIN"):
            self.fields[key].setEnabled(self.dream.isChecked())
        self.model.setEnabled(self.conclusions.isChecked())
        self.load_models.setEnabled(self.conclusions.isChecked())
        self.actions["force_dream"].setEnabled(not dirty)
        self.actions["export_notes"].setEnabled(not dirty and bool(self.saved["NOTES"]))
        self.actions["sync_memory"].setEnabled(not dirty and bool(self.saved["SYNC"]))

    def start(self, operation, notice, complete):
        self.job = SettingsOperation(self, operation)
        self.pages.setEnabled(False)
        self.close_button.setEnabled(False)
        self.apply_button.setEnabled(False)
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
        self.close_button.setEnabled(True)
        self.refresh()

    def apply(self):
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
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, label, explanation, buttons.Yes | buttons.No, buttons.No) != buttons.Yes:
            return
        self.start(lambda: self.memory.call(tool), "StoneWave está procesando la operación…",
                   lambda result, error: self.status.setText(error or result))

    def reject(self):
        if self.job is None:
            super().reject()

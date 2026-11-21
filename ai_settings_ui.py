"""Diálogo de proveedor y modelo para StoneBot."""
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from ai_provider import AISettings, PROVIDERS, available_models, save_ai, saved_model
from appearance import dialog_style, readable_text, secondary_button


class AISettingsDialog(QDialog):
    models_loaded = Signal(str, object, str)

    def __init__(self, parent, theme, current):
        super().__init__(parent)
        self.setWindowTitle("Modelo y proveedor de IA")
        self.setStyleSheet(dialog_style(theme) + f"""
            QCheckBox {{ color: {readable_text(theme['background'])}; }}
            QLineEdit {{ padding: 0 8px; border-radius: 6px; }}
            QListWidget {{ border-radius: 7px; }}
        """)
        self.resize(520, 0)
        self.config = current
        self.provider = QComboBox()
        for key, label in PROVIDERS.items():
            self.provider.addItem(f"{label} · {'Local' if key == 'ollama' else 'Nube'}", key)
        self.provider.setCurrentIndex(self.provider.findData(current.provider))
        self.model = QLineEdit(current.model)
        self.model.setPlaceholderText("Elige un modelo o escribe su identificador")
        self.model.setAccessibleName("Identificador del modelo elegido")
        self.load = secondary_button(QPushButton("Cargar modelos"))
        self.load.clicked.connect(self.load_models)
        models = QHBoxLayout()
        models.addWidget(self.model, 1)
        models.addWidget(self.load)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre o proveedor…")
        self.search.setAccessibleName("Buscar modelos por nombre o proveedor")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.free_only = QCheckBox("Solo gratuitos")
        self.free_only.setToolTip("Incluye variantes :free y el selector gratuito de OpenRouter cuando están disponibles.")
        filters = QHBoxLayout()
        filters.addWidget(self.search, 1)
        filters.addWidget(self.free_only)
        self.results = QListWidget()
        self.results.setAccessibleName("Modelos disponibles")
        self.results.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.results.setFixedHeight(148)
        self.results.setStyleSheet("QListWidget::item { padding: 4px 7px; }")
        self.catalog_status = QLabel()
        self.catalog_status.setWordWrap(True)
        self.catalog_status.setTextFormat(Qt.TextFormat.PlainText)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Deja vacío si ya guardaste la clave")
        for control in (self.provider, self.model, self.load, self.key):
            control.setMinimumHeight(34)
        self.key_label = QLabel("Clave API")
        self.key_label.setBuddy(self.key)
        self.cloud_memory = QCheckBox("Incluir recuerdos de StoneWave en las respuestas de la nube")
        self.cloud_memory.setChecked(current.cloud_memory)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        fields = QFormLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(8)
        fields.addRow("Proveedor", self.provider)
        fields.addRow("Modelo", models)
        fields.addRow(self.key_label, self.key)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        for button in buttons.buttons():
            button.setAutoDefault(False)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSizeConstraints(QLayout.SizeConstraint.SetDefaultConstraint, QLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        title = QLabel("Modelo y proveedor de IA")
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        layout.addWidget(title)
        layout.addLayout(fields)
        layout.addLayout(filters)
        layout.addWidget(self.results)
        layout.addWidget(self.catalog_status)
        layout.addWidget(self.info)
        layout.addWidget(self.cloud_memory)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        self.provider.currentIndexChanged.connect(self.switch_provider)
        self.models_loaded.connect(self.finish_models)
        self.model_choices = {current.provider: current.model}
        self.catalogs = {}
        self.active_provider = current.provider
        self.search.textChanged.connect(self.filter_models)
        self.free_only.toggled.connect(self.filter_models)
        self.results.itemClicked.connect(self.choose_model)
        self.results.itemActivated.connect(self.choose_model)
        self.switch_provider()

    def switch_provider(self):
        self.model_choices[self.active_provider] = self.model.text()
        self.active_provider = self.provider.currentData()
        self.model.setText(self.model_choices.get(self.active_provider) or saved_model(self.active_provider))
        cloud = self.active_provider == "openrouter"
        for control in (self.key_label, self.key, self.cloud_memory, self.free_only):
            control.setVisible(cloud)
        self.info.setText(
            "OpenRouter recibe el contexto del chat y los adjuntos que envíes. La clave se guarda en el Administrador de credenciales de Windows. La lista ofrece modelos compatibles con herramientas."
            if cloud else "StoneBot usa el modelo instalado en Ollama en este equipo."
        )
        self.search.clear()
        self.filter_models()
        self.status.clear()

    def load_models(self):
        provider = self.active_provider
        self.load.setEnabled(False)
        self.status.setText("Cargando modelos…")

        def load():
            try:
                models = available_models(provider)
            except Exception:
                self.models_loaded.emit(provider, [], "No se pudieron cargar los modelos de " + PROVIDERS[provider] + ".")
            else:
                self.models_loaded.emit(provider, models, "" if models else "No hay modelos disponibles.")

        Thread(target=load, daemon=True).start()

    def finish_models(self, provider, models, error):
        self.load.setEnabled(True)
        if not error:
            self.catalogs[provider] = models
        if provider != self.active_provider:
            return
        self.filter_models()
        self.status.setText(error)

    def filter_models(self):
        self.results.clear()
        models = self.catalogs.get(self.active_provider, [])
        free_only = self.active_provider == "openrouter" and self.free_only.isChecked()
        terms = self.search.text().casefold().split()
        chosen = self.model.text().strip()
        price_details = {"Gratis": "Variante gratuita de OpenRouter. Sujeta a límites de uso.",
                         "Tarifa de texto $0": "OpenRouter puede requerir saldo para habilitar esta ruta."}
        for model in models:
            searchable = f"{model.name} {model.id} {model.price}".casefold()
            if (free_only and model.price != "Gratis") or not all(term in searchable for term in terms):
                continue
            title = f"{model.name} · {model.price}" if model.price else model.name
            label = title if model.name == model.id else f"{title}\n{model.id}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, model.id)
            item.setToolTip(f"{label}\n{price_details[model.price]}" if model.price in price_details else label)
            self.results.addItem(item)
            if model.id == chosen:
                self.results.setCurrentItem(item)
        count = self.results.count()
        self.results.setVisible(bool(count))
        if not models:
            message = "Carga el catálogo para buscar modelos."
        elif not count:
            message = "No hay modelos que coincidan con estos filtros."
        else:
            message = f"{count} de {len(models)} modelos"
        self.catalog_status.setText(message)

    def choose_model(self, item):
        self.model.setText(item.data(Qt.ItemDataRole.UserRole))

    def save(self):
        config = AISettings(self.active_provider, self.model.text().strip(), self.cloud_memory.isChecked())
        try:
            save_ai(config, self.key.text().strip())
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            self.status.setText(str(exc))
            return
        self.config = config
        self.accept()

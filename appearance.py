"""Preferencias locales y controles de apariencia de StoneBot."""
import re

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from mcp_client import data_path


COLORS = {
    "accent": "#c8a7ff",
    "background": "#19191e",
    "user_message": "#4e2d7e",
    "bot_message": "#19191e",
}
DEFAULT_FONT_SIZE = 15
PRESETS = {
    "StoneBot": COLORS,
    "GitHub Dark Dimmed": dict(zip(COLORS, ("#78b4fa", "#222831", "#294461", "#282f38"))),
    "One Dark Pro": dict(zip(COLORS, ("#69afea", "#292e37", "#3a4a61", "#303641"))),
    "SynthWave '84": dict(zip(COLORS, ("#f68ac5", "#251d35", "#55375e", "#332644"))),
}


def appearance_settings():
    return QSettings(str(data_path("appearance.ini")), QSettings.Format.IniFormat)


def preset_name(theme):
    colors = {key: theme[key] for key in COLORS}
    return next((name for name, palette in PRESETS.items() if palette == colors), "Personalizado")


def load_appearance():
    theme = dict(COLORS, font_size=DEFAULT_FONT_SIZE)
    try:
        settings = appearance_settings()
        selected = settings.value("theme", "")
        if isinstance(selected, str) and selected in PRESETS:
            theme.update(PRESETS[selected])
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
    settings.setValue("theme", preset_name(theme))
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


def shade(color, amount):
    base = QColor(color)
    ink = QColor(readable_text(color))
    return QColor.fromRgbF(*(a * (1 - amount) + b * amount
                             for a, b in zip(base.getRgbF()[:3], ink.getRgbF()[:3]))).name()


def link_color(background):
    return "#24448c" if readable_text(background) == "#000000" else "#a9ccff"


def apply_palette(theme):
    background, accent = theme["background"], theme["accent"]
    roles = QPalette.ColorRole
    palette = QPalette()
    for role, color in (
        (roles.Window, background), (roles.Base, shade(background, .05)),
        (roles.AlternateBase, shade(background, .08)), (roles.Text, readable_text(background)),
        (roles.WindowText, readable_text(background)), (roles.ButtonText, readable_text(background)),
        (roles.Button, shade(background, .12)), (roles.Highlight, accent),
        (roles.HighlightedText, readable_text(accent)), (roles.Link, link_color(background)),
        (roles.ToolTipBase, shade(background, .08)), (roles.ToolTipText, readable_text(background)),
    ):
        palette.setColor(role, QColor(color))
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(
            shade(background, .52) if role in (roles.Text, roles.WindowText, roles.ButtonText) else color
        ))
    QApplication.instance().setPalette(palette)


def dialog_style(theme):
    accent = theme["accent"]
    background = theme.get("background", COLORS["background"])
    surface = shade(background, .06)
    edge = shade(background, .24)
    text = readable_text(background)
    ink = readable_text(accent)
    return f"""
        QDialog {{ background: {background}; }}
        QLabel, QListWidget, QTreeWidget, QLineEdit, QPlainTextEdit, QComboBox, QPushButton, QSpinBox {{
            color: {text}; font-family: "Segoe UI"; font-size: 14px;
        }}
        QListWidget, QTreeWidget, QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QComboBox QAbstractItemView {{
            background: {surface}; color: {text}; border: 1px solid {edge};
            selection-background-color: {accent}; selection-color: {ink};
        }}
        QHeaderView::section {{ background: {shade(background, .1)}; color: {text}; padding: 5px; border: 0; }}
        QPushButton {{
            background: {shade(background, .12)}; border: 1px solid {edge}; border-radius: 7px; padding: 6px 10px;
        }}
        QPushButton:hover {{ background: {accent}; color: {ink}; }}
        QPushButton:focus {{ border-color: {accent}; }}
        QPushButton:disabled {{ color: {shade(background, .48)}; background: {surface}; }}
    """


def palette_icon(colors, *, artist=False):
    image = QPixmap(30, 20)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if artist:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors[0]))
        painter.drawEllipse(4, 1, 22, 17)
        for index, color in enumerate(colors[1:]):
            painter.setBrush(QColor(color))
            x, y = ((8, 7), (15, 4), (19, 10), (12, 12))[index]
            painter.drawEllipse(x, y, 4, 4)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        painter.drawEllipse(21, 12, 6, 6)
    else:
        for index, color in enumerate(colors):
            painter.fillRect(index * 7, 3, 7, 14, QColor(color))
    painter.end()
    return QIcon(image)


class ColorEditor(QDialog):
    def __init__(self, parent, label, color, theme):
        super().__init__(parent)
        self.setWindowTitle(label)
        self.setStyleSheet(dialog_style(theme))
        self.color = QColor(color)
        self.settings = appearance_settings()
        layout = QVBoxLayout(self)
        self.pick = QPushButton()
        self.pick.clicked.connect(self.choose_color)
        layout.addWidget(self.pick)
        layout.addWidget(QLabel("Favoritos"))
        grid = QGridLayout()
        self.slots = QButtonGroup(self)
        for index in range(8):
            button = QPushButton()
            button.setCheckable(True)
            self.slots.addButton(button, index)
            grid.addWidget(button, index // 4, index % 4)
        self.slots.button(0).setChecked(True)
        self.slots.idClicked.connect(self.refresh)
        layout.addLayout(grid)
        self.save_slot = QPushButton("Guardar en casilla")
        self.save_slot.clicked.connect(self.save_favorite)
        self.use_slot = QPushButton("Usar favorito")
        self.use_slot.clicked.connect(self.use_favorite)
        actions = QHBoxLayout()
        actions.addWidget(self.save_slot)
        actions.addWidget(self.use_slot)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def favorite(self, index):
        value = self.settings.value(f"favorites/{index}", "")
        return value if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else ""

    def choose_color(self):
        color = QColorDialog.getColor(self.color, self, "Elegir color", QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.color = color
            self.refresh()

    def save_favorite(self):
        self.settings.setValue(f"favorites/{self.slots.checkedId()}", self.color.name())
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            QMessageBox.warning(self, "Favoritos", "No se pudo guardar el color favorito.")
        self.refresh()

    def use_favorite(self):
        color = self.favorite(self.slots.checkedId())
        if color:
            self.color = QColor(color)
            self.refresh()

    def refresh(self):
        color = self.color.name()
        self.pick.setText(f"Elegir color… {color.upper()}")
        self.pick.setStyleSheet(f"background: {color}; color: {readable_text(color)};")
        for index in range(8):
            button = self.slots.button(index)
            saved = self.favorite(index)
            button.setText(f"{index + 1} · {saved.upper() if saved else 'Vacío'}")
            button.setStyleSheet(
                (f"background: {saved}; color: {readable_text(saved)};" if saved else "")
                + ("border: 2px solid #7588ac;" if button.isChecked() else "")
            )
        self.use_slot.setEnabled(bool(self.favorite(self.slots.checkedId())))


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
        self.preset = QComboBox()
        for name, palette in PRESETS.items():
            self.preset.addItem(palette_icon(list(palette.values())), name)
        self.preset.addItem("Personalizado")
        self.preset.activated.connect(self.select_preset)
        form.addRow("Tema", self.preset)
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
        editor = ColorEditor(self, label, self.theme[key], self.theme)
        try:
            if editor.exec():
                self.set_color(key, editor.color.name())
        finally:
            editor.deleteLater()

    def select_preset(self, _index):
        if palette := PRESETS.get(self.preset.currentText()):
            self.change(dict(self.theme, **palette))

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
        self.preset.setCurrentText(preset_name(self.theme))
        for key, button in self.swatches.items():
            color = self.theme[key]
            button.setText(color.upper())
            button.setStyleSheet(f"background-color: {color}; color: {readable_text(color)};")
            self.restore_colors[key].setEnabled(color != COLORS[key])

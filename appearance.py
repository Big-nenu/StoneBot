"""Preferencias locales y controles de apariencia de StoneBot."""
import json
import re

from PySide6.QtCore import QPointF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)

from mcp_client import data_path


COLORS = {
    "accent": "#5d8cc2",
    "background": "#222831",
    "user_message": "#294461",
    "bot_message": "#282f38",
}
ORIGINAL = "StoneBot Original"
DEFAULT_FONT_SIZE = 15
PRESETS = {
    ORIGINAL: COLORS,
    "GitHub Dark Dimmed": dict(zip(COLORS, ("#78b4fa", "#222831", "#294461", "#282f38"))),
    "One Dark Pro": dict(zip(COLORS, ("#69afea", "#292e37", "#3a4a61", "#303641"))),
    "SynthWave '84": dict(zip(COLORS, ("#f68ac5", "#251d35", "#55375e", "#332644"))),
}


def appearance_settings():
    return QSettings(str(data_path("appearance.ini")), QSettings.Format.IniFormat)


def valid_color(color):
    return isinstance(color, str) and bool(re.fullmatch(r"#[0-9a-fA-F]{6}", color))


def custom_themes(settings=None):
    try:
        items = json.loads((settings or appearance_settings()).value("custom_themes", "{}"))
        if isinstance(items, dict):
            return {name: {key: palette[key].lower() for key in COLORS} for name, palette in items.items()
                    if isinstance(palette, dict) and all(valid_color(palette.get(key)) for key in COLORS)
                    and name.casefold() not in RESERVED_NAMES}
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return {}


RESERVED_NAMES = {name.casefold() for name in (*PRESETS, "Personalizado", "StoneBot")}


def save_custom_themes(items):
    settings = appearance_settings()
    settings.setValue("custom_themes", json.dumps(items, ensure_ascii=False))
    sync(settings)


def preset_name(theme, saved=None):
    colors = {key: theme[key] for key in COLORS}
    named = theme.get("named_theme")
    if named and (saved if saved is not None else custom_themes()).get(named) == colors:
        return named
    return next((name for name, palette in PRESETS.items() if palette == colors), "Personalizado")


def load_appearance():
    theme = dict(COLORS, font_size=DEFAULT_FONT_SIZE)
    try:
        settings = appearance_settings()
        selected = settings.value("theme", "")
        saved = custom_themes(settings)
        if isinstance(selected, str) and selected in PRESETS:
            theme.update(PRESETS[selected])
        elif isinstance(selected, str) and selected in saved:
            theme.update(saved[selected])
        elif selected == "StoneBot":
            theme.update(zip(COLORS, ("#c8a7ff", "#19191e", "#4e2d7e", "#19191e")))
        for key in COLORS:
            value = settings.value(key, "")
            if valid_color(value):
                theme[key] = value.lower()
        if isinstance(selected, str) and selected in saved and saved[selected] == {key: theme[key] for key in COLORS}:
            theme["named_theme"] = selected
        size = int(settings.value("font_size", DEFAULT_FONT_SIZE))
        if 12 <= size <= 28:
            theme["font_size"] = size
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return theme


def save_appearance(theme):
    # QSettings escribe mediante un reemplazo atómico del archivo INI.
    settings = appearance_settings()
    settings.setValue("theme", preset_name(theme, custom_themes(settings)))
    for key in (*COLORS, "font_size"):
        settings.setValue(key, theme[key])
    sync(settings)


def sync(settings):
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


class ColorPlane(QWidget):
    picked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self.hue, self.saturation, self.value = 0, 0, 1

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        horizontal = QLinearGradient(0, 0, self.width(), 0)
        horizontal.setColorAt(0, QColor("#ffffff"))
        horizontal.setColorAt(1, QColor.fromHsv(self.hue, 255, 255))
        vertical = QLinearGradient(0, 0, 0, self.height())
        vertical.setColorAt(0, QColor(0, 0, 0, 0))
        vertical.setColorAt(1, QColor("#000000"))
        painter.fillRect(self.rect(), horizontal)
        painter.fillRect(self.rect(), vertical)
        point = QPointF(5 + self.saturation * (self.width() - 10), 5 + (1 - self.value) * (self.height() - 10))
        for color, width in (("#000000", 4), ("#ffffff", 2)):
            painter.setPen(QPen(QColor(color), width))
            painter.drawEllipse(point, 4, 4)
        painter.end()

    def select_point(self, event):
        point = event.position()
        clamp = lambda value: min(max(value, 0.0), 1.0)
        self.picked.emit(clamp((point.x() - 5) / max(self.width() - 10, 1)),
                         clamp(1 - (point.y() - 5) / max(self.height() - 10, 1)))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.select_point(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.select_point(event)


class ColorEditor(QDialog):
    def __init__(self, parent, label, color, theme):
        super().__init__(parent)
        self.setWindowTitle(label)
        self.setStyleSheet(dialog_style(theme))
        self.color = QColor(color)
        self.settings = appearance_settings()
        layout = QVBoxLayout(self)
        self.hue = QSlider(Qt.Orientation.Horizontal)
        self.hue.setRange(0, 359)
        self.hue.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 8px; border-radius: 4px;
                background: qlineargradient(x1:0, x2:1, stop:0 #ff0000, stop:.167 #ffff00,
                    stop:.333 #00ff00, stop:.5 #00ffff, stop:.667 #0000ff, stop:.833 #ff00ff, stop:1 #ff0000);
            }
            QSlider::handle:horizontal {
                width: 12px; margin: -4px 0; background: white; border: 1px solid black; border-radius: 6px;
            }
        """)
        self.hue.setAccessibleName("Matiz")
        self.hue.setValue(max(0, self.color.hsvHue()))
        self.hue.valueChanged.connect(self.change_hue)
        self.plane = ColorPlane()
        self.plane.picked.connect(self.pick_point)
        self.hex = QLineEdit()
        self.hex.setMaxLength(7)
        self.hex.setAccessibleName("Color hexadecimal")
        self.hex.textEdited.connect(self.change_hex)
        self.hex.editingFinished.connect(self.refresh)
        self.sample = QLabel()
        self.sample.setMinimumSize(36, 24)
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color"))
        color_row.addWidget(self.hex, 1)
        color_row.addWidget(self.sample)
        layout.addLayout(color_row)
        layout.addWidget(self.plane)
        layout.addWidget(QLabel("Matiz"))
        layout.addWidget(self.hue)
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
        self.clear_slot = QPushButton("Borrar favorito")
        self.clear_slot.clicked.connect(self.delete_favorite)
        actions = QHBoxLayout()
        actions.addWidget(self.save_slot)
        actions.addWidget(self.use_slot)
        actions.addWidget(self.clear_slot)
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Aplicar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(440, self.sizeHint().height())
        self.refresh()

    def favorite(self, index):
        value = self.settings.value(f"favorites/{index}", "")
        return value if valid_color(value) else ""

    def set_color(self, color):
        self.color = QColor(color)
        if self.color.hsvHue() >= 0:
            self.hue.blockSignals(True)
            self.hue.setValue(self.color.hsvHue())
            self.hue.blockSignals(False)
        self.refresh()

    def change_hex(self, value):
        if valid_color(value):
            self.set_color(QColor(value))

    def pick_point(self, saturation, value):
        self.color = QColor.fromHsvF(self.hue.value() / 360, saturation, value)
        self.refresh()

    def change_hue(self, _value):
        self.pick_point(self.color.hsvSaturationF(), self.color.valueF())

    def save_favorite(self):
        self.settings.setValue(f"favorites/{self.slots.checkedId()}", self.color.name())
        self.sync_favorites()

    def delete_favorite(self):
        self.settings.remove(f"favorites/{self.slots.checkedId()}")
        self.sync_favorites()

    def sync_favorites(self):
        try:
            sync(self.settings)
        except OSError:
            QMessageBox.warning(self, "Favoritos", "No se pudo actualizar el favorito.")
        self.refresh()

    def use_favorite(self):
        color = self.favorite(self.slots.checkedId())
        if color:
            self.set_color(QColor(color))

    def refresh(self):
        color = self.color.name()
        if self.hex.text().lower() != color:
            self.hex.setText(color)
        self.sample.setStyleSheet(f"background: {color}; border: 1px solid {readable_text(color)};")
        self.plane.hue = self.hue.value()
        self.plane.saturation = self.color.hsvSaturationF()
        self.plane.value = self.color.valueF()
        self.plane.update()
        for index in range(8):
            button = self.slots.button(index)
            saved = self.favorite(index)
            button.setText(f"{index + 1} · {saved.upper() if saved else 'Vacío'}")
            button.setStyleSheet(
                (f"background: {saved}; color: {readable_text(saved)};" if saved else "")
                + (f"border: 2px solid {readable_text(saved) if saved else '#7588ac'};" if button.isChecked() else "")
            )
        occupied = bool(self.favorite(self.slots.checkedId()))
        self.use_slot.setEnabled(occupied)
        self.clear_slot.setEnabled(occupied)


class AppearanceDialog(QDialog):
    def __init__(self, parent, theme, on_change):
        super().__init__(parent)
        self.setWindowTitle("Apariencia")
        self.theme = theme.copy()
        self.saved = custom_themes()
        self.on_change = on_change
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.setMinimumWidth(400)
        self.preset = QComboBox()
        self.preset.activated.connect(self.select_preset)
        form.addRow("Tema", self.preset)
        self.save_theme = QPushButton("Guardar como…")
        self.save_theme.clicked.connect(self.add_theme)
        self.rename_theme = QPushButton("Renombrar…")
        self.rename_theme.clicked.connect(self.rename_selected)
        self.delete_theme = QPushButton("Eliminar…")
        self.delete_theme.clicked.connect(self.delete_selected)
        theme_actions = QHBoxLayout()
        for button in (self.save_theme, self.rename_theme, self.delete_theme):
            theme_actions.addWidget(button)
        form.addRow(theme_actions)
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
        self.restore.clicked.connect(lambda: self.apply_named(ORIGINAL))
        form.addRow(self.restore)
        self.refresh_themes()
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
        self.apply_named(self.preset.currentText())

    def apply_named(self, name):
        if palette := PRESETS.get(name) or self.saved.get(name):
            theme = dict(self.theme, **palette)
            theme.pop("named_theme", None)
            if name in self.saved:
                theme["named_theme"] = name
            self.change(theme)
        else:
            self.refresh()

    def prompt_name(self, title, previous=""):
        name, accepted = QInputDialog.getText(self, title, "Nombre del tema", text=previous)
        name = name.strip()
        if not accepted or name == previous:
            return None
        used = {item.casefold() for item in self.saved if item != previous}
        if not name or len(name) > 50 or name.casefold() in (RESERVED_NAMES | used):
            QMessageBox.warning(self, "Temas", "Usa un nombre distinto de hasta 50 caracteres.")
            return None
        return name

    def update_saved(self, items):
        try:
            save_custom_themes(items)
        except (OSError, ValueError, RuntimeError):
            QMessageBox.warning(self, "Temas", "No se pudieron guardar los temas.")
            return False
        self.saved = items
        self.refresh_themes()
        return True

    def add_theme(self):
        if name := self.prompt_name("Guardar tema personalizado"):
            palette = {key: self.theme[key] for key in COLORS}
            if self.update_saved({**self.saved, name: palette}):
                self.apply_named(name)

    def rename_selected(self):
        old = self.preset.currentText()
        if old in self.saved and (name := self.prompt_name("Renombrar tema", old)):
            items = self.saved.copy()
            items[name] = items.pop(old)
            if self.update_saved(items):
                self.apply_named(name)

    def delete_selected(self):
        name = self.preset.currentText()
        buttons = QMessageBox.StandardButton
        if name in self.saved and QMessageBox.question(
            self, "Eliminar tema", f"¿Eliminar el tema «{name}»?", buttons.Yes | buttons.No, buttons.No
        ) == buttons.Yes:
            if self.update_saved({key: value for key, value in self.saved.items() if key != name}):
                theme = self.theme.copy()
                theme.pop("named_theme", None)
                self.change(theme)

    def refresh_themes(self):
        self.preset.clear()
        for name, palette in {**PRESETS, **dict(sorted(self.saved.items(), key=lambda item: item[0].casefold()))}.items():
            self.preset.addItem(palette_icon(list(palette.values())), name)
        self.preset.addItem("Personalizado")

    def set_color(self, key, value):
        theme = dict(self.theme, **{key: value})
        theme.pop("named_theme", None)
        self.change(theme)

    def change(self, theme):
        if self.on_change(theme):
            self.theme = theme
        self.font_size.blockSignals(True)
        self.font_size.setValue(self.theme["font_size"])
        self.font_size.blockSignals(False)
        self.refresh()

    def refresh(self):
        self.setStyleSheet(dialog_style(self.theme))
        self.preset.setCurrentText(preset_name(self.theme, self.saved))
        is_saved = self.preset.currentText() in self.saved
        self.rename_theme.setEnabled(is_saved)
        self.delete_theme.setEnabled(is_saved)
        for key, button in self.swatches.items():
            color = self.theme[key]
            button.setText(color.upper())
            button.setStyleSheet(f"background-color: {color}; color: {readable_text(color)};")
            self.restore_colors[key].setEnabled(color != COLORS[key])

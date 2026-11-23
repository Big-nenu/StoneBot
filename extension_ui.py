"""Controles y estilos del centro de extensiones."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox

from appearance import COLORS, control_colors, dialog_style, link_color, readable_text, shade


class Toggle(QCheckBox):
    def __init__(self, checked, label, accent, surface=COLORS["background"]):
        super().__init__()
        self.accent = accent
        self.surface = surface
        self.setAccessibleName(label)
        self.setChecked(checked)
        self.setFixedSize(QSize(38, 24))

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        checked = self.isChecked()
        enabled = self.isEnabled()
        track = self.accent if checked and enabled else shade(self.surface, .16 if enabled else .07)
        if enabled and (self.underMouse() or self.isDown()):
            track = shade(track, .18 if self.isDown() else .09)
        edge = link_color(self.surface) if self.hasFocus() else shade(self.surface, .42 if enabled else .26)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(edge), 2 if self.hasFocus() else 1))
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(self.rect().adjusted(2, 3, -2, -3), 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(readable_text(track) if enabled else shade(self.surface, .42)))
        painter.drawEllipse(22 if checked else 5, 6, 12, 12)


def extension_style(theme):
    background, accent = theme["background"], theme["accent"]
    surface, edge, _, text = control_colors(background)
    muted = shade(background, .68)
    focus = link_color(background)
    return dialog_style(theme) + f"""
        QLabel#extensionsTitle {{
            color: {readable_text(background)}; font-size: 29px; font-weight: 700;
        }}
        QLabel[muted="true"] {{ color: {muted}; }}
        QLabel[sectionHeading="true"] {{ font-size: 16px; }}
        QTabBar#extensionTabs::tab {{
            background: transparent; color: {muted}; min-width: 72px;
            font-family: "Segoe UI"; font-size: 14px; font-weight: 600;
            padding: 8px 12px; border: 0; border-bottom: 2px solid transparent;
        }}
        QTabBar#extensionTabs::tab:hover {{ background: {shade(background, .08)}; color: {text}; }}
        QTabBar#extensionTabs::tab:selected {{ color: {text}; border-bottom-color: {accent}; }}
        QTabBar#extensionTabs::tab:focus {{ color: {text}; border-bottom-color: {focus}; }}
        QFrame#extensionDivider {{ background: {shade(background, .18)}; }}
        QTreeWidget[extensionList="true"], QListWidget#skillList {{
            background: {surface}; border: 1px solid {shade(background, .20)};
            border-radius: 10px; outline: none;
            selection-background-color: {shade(surface, .13)}; selection-color: {text};
        }}
        QTreeWidget[extensionList="true"] QHeaderView {{
            font-family: "Segoe UI"; font-size: 13px;
        }}
        QTreeWidget[extensionList="true"]::item:hover, QListWidget#skillList::item:hover {{
            background: {shade(surface, .07)};
        }}
        QListWidget#skillList::item:selected, QTreeWidget[extensionList="true"]::item:selected {{
            background: {shade(surface, .15)}; color: {text};
        }}
        QListWidget#skillList::item:focus, QTreeWidget[extensionList="true"]::item:focus {{
            border-bottom: 1px solid {focus};
        }}
        QLabel#skillName {{ color: {text}; font-weight: 600; }}
        QLabel#skillState {{ color: {shade(surface, .72)}; font-size: 13px; }}
        QScrollArea#skillDetail, QLabel#extensionEmpty {{
            background: {shade(background, .035)}; border: 1px solid {shade(background, .18)};
            border-radius: 10px;
        }}
        QWidget#skillDetailContent {{ background: transparent; }}
        QScrollBar:vertical {{
            background: transparent; width: 10px; margin: 3px 1px;
        }}
        QScrollBar::handle:vertical {{
            background: {shade(surface, .28)}; min-height: 24px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {shade(surface, .45)}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QLineEdit, QPlainTextEdit, QComboBox {{
            border: 1px solid {edge}; border-radius: 7px; padding: 5px 8px;
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {focus}; }}
    """

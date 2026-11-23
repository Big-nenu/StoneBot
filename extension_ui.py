"""Controles y estilos del centro de extensiones."""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QStyle, QStyledItemDelegate, QTreeWidget

from appearance import COLORS, DEFAULT_FONT_SIZE, control_colors, draw_chevron, link_color, readable_text, shade
from chat_ui import chat_style


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


class CardDelegate(QStyledItemDelegate):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme

    def paint(self, painter, option, index):
        background = self.theme["background"]
        surface = control_colors(background)[0]
        selected = option.state & QStyle.StateFlag.State_Selected
        hovered = option.state & QStyle.StateFlag.State_MouseOver
        focused = option.state & QStyle.StateFlag.State_HasFocus
        fill = shade(surface, .10) if selected else shade(surface, .06) if hovered else surface
        edge = link_color(background) if focused else shade(surface, .28) if selected else "transparent"
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(edge)))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(QRectF(option.rect).adjusted(1, 3, -1, -3), 8, 8)
        painter.restore()


class CardTree(QTreeWidget):
    def drawBranches(self, painter, rect, index):
        if self.model().hasChildren(index):
            arrow = rect.adjusted(rect.width() - self.indentation(), 0, 0, 0)
            draw_chevron(painter, arrow, self.palette().text().color(), 0 if self.isExpanded(index) else -90)


def extension_style(theme):
    return chat_style(dict({"font_size": DEFAULT_FONT_SIZE}, **theme))

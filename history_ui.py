"""Panel lateral del historial."""
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from appearance import appearance_settings, secondary_button, sync


DEFAULT_WIDTH = 236
MINIMUM_WIDTH = 184


def load_history_width():
    try:
        width = int(appearance_settings().value("history_width", DEFAULT_WIDTH))
        return max(MINIMUM_WIDTH, width)
    except (OSError, RuntimeError, TypeError, ValueError):
        return DEFAULT_WIDTH


def save_history_width(width):
    settings = appearance_settings()
    settings.setValue("history_width", width)
    sync(settings)


class ConversationDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(min(size.width(), self.parent().viewport().width()))
        return size


class ConversationList(QListWidget):
    options_requested = Signal(object, QPoint)

    def __init__(self):
        super().__init__()
        self.hovered = None
        self.options = secondary_button(QPushButton("...", self.viewport()))
        self.options.setObjectName("historyRowOptions")
        self.options.setAccessibleName("Opciones de la conversación")
        self.options.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.options.setFixedSize(28, 24)
        self.options.clicked.connect(self.show_hovered_options)
        self.options.hide()
        self.viewport().setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self.hide_options)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter):
            self.hovered = self.itemAt(event.position().toPoint())
            if self.hovered is None:
                self.hide_options()
            else:
                rect = self.visualItemRect(self.hovered)
                self.options.move(rect.right() - self.options.width() - 4, rect.center().y() - self.options.height() // 2)
                self.options.show()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Resize):
            self.hide_options()
        return super().viewportEvent(event)

    def hide_options(self):
        self.hovered = None
        self.options.hide()

    def show_hovered_options(self):
        if self.hovered is not None:
            self.options_requested.emit(self.hovered, self.options.mapToGlobal(self.options.rect().bottomLeft()))

    def contextMenuEvent(self, event):
        keyboard = event.reason() == QContextMenuEvent.Reason.Keyboard
        item = self.currentItem() if keyboard else self.itemAt(event.pos())
        if item is not None:
            point = self.viewport().mapToGlobal(self.visualItemRect(item).bottomLeft()) if keyboard else event.globalPos()
            self.options_requested.emit(item, point)
            event.accept()


class HistoryPanel(QWidget):
    opened = Signal(int)
    renamed = Signal(int, str)
    deleted = Signal(int)
    new_chat = Signal()
    searched = Signal(str)
    diagnostics = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("historyPanel")
        self.setMinimumWidth(MINIMUM_WIDTH)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar conversaciones…")
        self.search.setAccessibleName("Buscar conversaciones")
        self.search.textChanged.connect(self.searched)
        self.list = ConversationList()
        self.list.setAccessibleName("Conversaciones")
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.itemClicked.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.itemActivated.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.options_requested.connect(self.show_options)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 12, 11, 12)
        layout.setSpacing(8)
        new = secondary_button(QPushButton("+  Nuevo chat"))
        new.clicked.connect(self.new_chat)
        log = secondary_button(QPushButton("Diagnóstico"))
        log.setProperty("quiet", True)
        log.clicked.connect(self.diagnostics)
        heading = QLabel("Conversaciones")
        heading.setObjectName("historyHeading")
        layout.addWidget(new)
        layout.addWidget(self.search)
        layout.addSpacing(3)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)
        layout.addWidget(log)

    def fill(self, rows, current):
        self.list.hide_options()
        self.list.clear()
        for chat_id, title in rows:
            item = QListWidgetItem(title)
            item.setToolTip(title)
            item.setData(Qt.ItemDataRole.UserRole, chat_id)
            self.list.addItem(item)
            if chat_id == current:
                self.list.setCurrentItem(item)

    def show_options(self, item, point):
        chat_id, title = item.data(Qt.ItemDataRole.UserRole), item.text()
        menu = QMenu(self)
        menu.setObjectName("chatMenu")
        rename = menu.addAction("Renombrar")
        remove = menu.addAction("Eliminar")
        choice = menu.exec(point)
        menu.deleteLater()
        if choice is rename:
            self.prompt_name(chat_id, title)
        elif choice is remove:
            self.prompt_delete(chat_id)

    def prompt_name(self, chat_id, current_title):
        title, ok = QInputDialog.getText(self, "Renombrar conversación", "Título", text=current_title)
        if ok and title.strip():
            self.renamed.emit(chat_id, title.strip())

    def prompt_delete(self, chat_id):
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Eliminar conversación", "¿Eliminar esta conversación del historial?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.deleted.emit(chat_id)

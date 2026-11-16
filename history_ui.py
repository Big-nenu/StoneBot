"""Panel lateral del historial."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QStyledItemDelegate, QVBoxLayout, QWidget,
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
        self.list = QListWidget()
        self.list.setAccessibleName("Conversaciones")
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.itemClicked.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.itemActivated.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.currentItemChanged.connect(self.update_controls)
        self.rename = secondary_button(QPushButton("Renombrar"))
        self.rename.clicked.connect(self.prompt_name)
        self.remove = secondary_button(QPushButton("Eliminar"))
        self.remove.clicked.connect(self.prompt_delete)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(self.rename, 1)
        actions.addWidget(self.remove, 1)
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
        layout.addLayout(actions)
        layout.addWidget(log)
        self.update_controls()

    def fill(self, rows, current):
        self.list.clear()
        for chat_id, title in rows:
            item = QListWidgetItem(title)
            item.setToolTip(title)
            item.setData(Qt.ItemDataRole.UserRole, chat_id)
            self.list.addItem(item)
            if chat_id == current:
                self.list.setCurrentItem(item)
        self.update_controls()

    def update_controls(self):
        enabled = self.list.currentItem() is not None
        self.rename.setEnabled(enabled)
        self.remove.setEnabled(enabled)

    def prompt_name(self):
        item = self.list.currentItem()
        title, ok = QInputDialog.getText(self, "Renombrar conversación", "Título", text=item.text())
        if ok and title.strip():
            self.renamed.emit(item.data(Qt.ItemDataRole.UserRole), title.strip())

    def prompt_delete(self):
        item = self.list.currentItem()
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Eliminar conversación", "¿Eliminar esta conversación del historial?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.deleted.emit(item.data(Qt.ItemDataRole.UserRole))

"""Panel lateral del historial."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


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
        self.setFixedWidth(218)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar conversaciones…")
        self.search.setAccessibleName("Buscar conversaciones")
        self.search.textChanged.connect(self.searched)
        self.list = QListWidget()
        self.list.setAccessibleName("Conversaciones")
        self.list.itemClicked.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.itemActivated.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.currentItemChanged.connect(self.update_controls)
        self.rename = QPushButton("Renombrar")
        self.rename.clicked.connect(self.prompt_name)
        self.remove = QPushButton("Eliminar")
        self.remove.clicked.connect(self.prompt_delete)
        actions = QHBoxLayout()
        actions.addWidget(self.rename)
        actions.addWidget(self.remove)
        layout = QVBoxLayout(self)
        new = QPushButton("Nuevo chat")
        new.clicked.connect(self.new_chat)
        log = QPushButton("Diagnóstico")
        log.clicked.connect(self.diagnostics)
        layout.addWidget(new)
        layout.addWidget(self.search)
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

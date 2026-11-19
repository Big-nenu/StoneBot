"""Panel lateral del historial."""
from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QInputDialog, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QStyleOptionViewItem, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from appearance import appearance_settings, secondary_button, sync


DEFAULT_WIDTH = 236
MINIMUM_WIDTH = 184
RAIL_WIDTH = 48
PROJECT_ROLE = Qt.ItemDataRole.UserRole + 1
NESTED_ROLE = Qt.ItemDataRole.UserRole + 2
SIDEBAR_ACTIONS = (
    ("new", "Nuevo chat"), ("search", "Buscar conversaciones"),
    ("projects", "Proyectos"), ("diagnostics", "Diagnóstico"),
)


def sidebar_icon(name, color):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    with QPainter(pixmap) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if name == "search":
            painter.drawEllipse(QRect(3, 3, 10, 10))
            painter.drawLine(12, 12, 17, 17)
        elif name == "projects":
            painter.drawRoundedRect(QRect(2, 6, 16, 11), 2, 2)
            painter.drawLine(4, 4, 9, 4)
            painter.drawLine(9, 4, 11, 6)
        elif name == "diagnostics":
            painter.drawPolyline(QPolygon([QPoint(x, y) for x, y in [(2, 11), (6, 11), (8, 5), (11, 16), (13, 9), (18, 9)]]))
        elif name == "toggle":
            painter.drawRoundedRect(QRect(2, 4, 16, 12), 2, 2)
            painter.drawLine(7, 5, 7, 15)
        else:
            painter.drawLine(4, 10, 16, 10)
            painter.drawLine(10, 4, 10, 16)
    return QIcon(pixmap)


def sidebar_button(title):
    button = secondary_button(QPushButton())
    button.setProperty("quiet", True)
    button.setToolTip(title)
    button.setAccessibleName(title)
    button.setFixedHeight(34)
    return button


class SidebarRail(QWidget):
    def __init__(self, history):
        super().__init__()
        self.setObjectName("sidebarRail")
        self.expanded_max_width = self.maximumWidth()
        self.history = history
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        nav = QWidget()
        navigation = QVBoxLayout(nav)
        navigation.setContentsMargins(7, 9, 7, 8)
        navigation.setSpacing(5)
        layout.addWidget(nav, alignment=Qt.AlignmentFlag.AlignTop)
        self.toggle = sidebar_button("Mostrar u ocultar la barra lateral")
        self.toggle.setObjectName("sidebarToggle")
        self.toggle.setFixedWidth(34)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        navigation.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.actions = {}
        for name, title in SIDEBAR_ACTIONS:
            button = sidebar_button(title)
            button.setProperty("sidebarAction", True)
            self.actions[name] = button
            navigation.addWidget(button)
        layout.addWidget(history, 1)
        self.set_expanded(True)

    def set_expanded(self, expanded):
        self.setMinimumWidth(MINIMUM_WIDTH if expanded else RAIL_WIDTH)
        self.setMaximumWidth(self.expanded_max_width if expanded else RAIL_WIDTH)
        for name, title in SIDEBAR_ACTIONS:
            self.actions[name].setText(title if expanded else "")
        self.history.setVisible(expanded)

    def refresh_icons(self, color):
        self.toggle.setIcon(sidebar_icon("toggle", color))
        for name, button in self.actions.items():
            button.setIcon(sidebar_icon(name, color))


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
        heading = not index.flags() & Qt.ItemFlag.ItemIsEnabled
        size.setHeight(max(32 if heading else 30, option.fontMetrics.height() + (14 if heading else 10)))
        return size

    def paint(self, painter, option, index):
        if index.data(NESTED_ROLE):
            option = QStyleOptionViewItem(option)
            option.rect = option.rect.adjusted(18, 0, 0, 0)
        super().paint(painter, option, index)


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
            if self.hovered is None or not self.hovered.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.hide_options()
            else:
                rect = self.visualItemRect(self.hovered)
                project = self.hovered.data(PROJECT_ROLE) is not None
                self.options.setAccessibleName("Opciones del proyecto" if project else "Opciones de la conversación")
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
        if item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled:
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
    projects_requested = Signal()
    project_opened = Signal(int)
    project_deleted = Signal(int)
    move_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("historyPanel")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar conversaciones…")
        self.search.setAccessibleName("Buscar conversaciones")
        self.search.textChanged.connect(self.searched)
        self.search.hide()
        self.list = ConversationList()
        self.list.setAccessibleName("Conversaciones")
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.itemClicked.connect(self.activate_row)
        self.list.itemActivated.connect(self.activate_row)
        self.list.options_requested.connect(self.show_options)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 0, 7, 10)
        layout.setSpacing(7)
        self.expanded_projects = set()
        self.projects = []
        self.project_chats = {}
        self.rows = []
        self.current_chat = None
        self.icon_color = None
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)

    def show_search(self):
        self.search.show()
        self.search.setFocus()

    def toggle_search(self):
        if self.search.isHidden():
            self.show_search()
        else:
            self.search.clear()
            self.search.hide()

    def refresh_icons(self, color):
        self.icon_color = color
        self.rebuild()

    def activate_row(self, item):
        if (project_id := item.data(PROJECT_ROLE)) is not None:
            if project_id in self.expanded_projects:
                self.expanded_projects.remove(project_id)
            else:
                self.expanded_projects.add(project_id)
            self.rebuild()
        elif (chat_id := item.data(Qt.ItemDataRole.UserRole)) is not None:
            self.opened.emit(chat_id)

    def expand_project(self, project_id):
        if project_id is not None and project_id not in self.expanded_projects:
            self.expanded_projects.add(project_id)
            self.rebuild()

    def fill_projects(self, projects, chats):
        self.projects = projects
        self.expanded_projects.intersection_update(project["id"] for project in projects)
        self.project_chats = chats
        self.rebuild()

    def fill(self, rows, current, project_chats=None):
        self.rows = rows
        self.current_chat = current
        if project_chats is not None:
            self.project_chats = project_chats
        self.rebuild()

    def add_heading(self, text):
        item = QListWidgetItem(text)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)

    def add_chat(self, chat_id, title, *, nested=False):
        item = QListWidgetItem(title)
        item.setToolTip(title)
        item.setData(Qt.ItemDataRole.UserRole, chat_id)
        item.setData(NESTED_ROLE, nested)
        self.list.addItem(item)
        return item

    def rebuild(self):
        scroll = self.list.verticalScrollBar()
        position = scroll.value()
        self.list.hide_options()
        self.list.clear()
        selected_nested = None
        if not self.search.text().strip():
            if self.projects:
                self.add_heading("Proyectos")
            for project in self.projects:
                pid, name = project["id"], project["name"]
                expanded = pid in self.expanded_projects
                item = QListWidgetItem(("▾ " if expanded else "▸ ") + name)
                item.setToolTip(name + (" · Fijado" if project["pinned"] else "")
                                + "\nPulsa para desplegar. Abre la ficha desde el menú de la fila.")
                item.setData(PROJECT_ROLE, pid)
                if self.icon_color is not None:
                    item.setIcon(sidebar_icon("projects", self.icon_color))
                self.list.addItem(item)
                if expanded:
                    for chat_id, title in self.project_chats.get(pid, []):
                        child = self.add_chat(chat_id, title, nested=True)
                        if chat_id == self.current_chat:
                            selected_nested = child
            self.add_heading("Recientes")
        for chat_id, title in self.rows:
            item = self.add_chat(chat_id, title)
            if chat_id == self.current_chat and selected_nested is None:
                self.list.setCurrentItem(item)
        if selected_nested is not None:
            self.list.setCurrentItem(selected_nested)
        scroll.setValue(position)

    def show_options(self, item, point):
        if (project_id := item.data(PROJECT_ROLE)) is not None:
            menu = QMenu(self)
            menu.setObjectName("chatMenu")
            opened = menu.addAction("Abrir proyecto")
            remove = menu.addAction("Eliminar proyecto…")
            choice = menu.exec(point)
            if choice is opened:
                self.project_opened.emit(project_id)
            elif choice is remove:
                self.project_deleted.emit(project_id)
            menu.deleteLater()
            return
        chat_id, title = item.data(Qt.ItemDataRole.UserRole), item.text()
        menu = QMenu(self)
        menu.setObjectName("chatMenu")
        rename = menu.addAction("Renombrar")
        move = menu.addAction("Mover a proyecto…")
        remove = menu.addAction("Eliminar")
        choice = menu.exec(point)
        menu.deleteLater()
        if choice is rename:
            self.prompt_name(chat_id, title)
        elif choice is remove:
            self.prompt_delete(chat_id)
        elif choice is move:
            self.move_requested.emit(chat_id)

    def prompt_name(self, chat_id, current_title):
        title, ok = QInputDialog.getText(self, "Renombrar conversación", "Título", text=current_title)
        if ok and title.strip():
            self.renamed.emit(chat_id, title.strip())

    def prompt_delete(self, chat_id):
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Eliminar conversación", "¿Eliminar esta conversación del historial?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.deleted.emit(chat_id)

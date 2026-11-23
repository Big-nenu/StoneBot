"""Panel lateral del historial."""
from datetime import date, datetime, timedelta
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from math import cos, pi, sin

from PySide6.QtGui import (
    QColor, QContextMenuEvent, QCursor, QIcon, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap, QPolygon, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QStyleOptionViewItem, QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget,
)

from appearance import appearance_settings, secondary_button, settings_style, sync
from chat_ui import style_chat_menu


DEFAULT_WIDTH = 280
RAIL_WIDTH = 48
BUTTON_SIZE = 40
ICON_SIZE = 20
NEW_CHAT_SHORTCUT = "Ctrl+N"
SEARCH_SHORTCUT = "Ctrl+K"
PROJECT_ROLE = Qt.ItemDataRole.UserRole + 1
NESTED_ROLE = Qt.ItemDataRole.UserRole + 2
MORE_ROLE = Qt.ItemDataRole.UserRole + 3
DATE_ROLE = Qt.ItemDataRole.UserRole + 4
RECENT_BATCH = 10
SIDEBAR_ACTIONS = (
    ("new", "Nuevo chat"), ("projects", "Proyectos"),
    ("diagnostics", "Diagnóstico"), ("search", "Buscar conversaciones"),
)


def recent_heading(timestamp, today):
    try:
        day = datetime.fromtimestamp(timestamp / 1_000_000_000).date()
    except (OverflowError, OSError, TypeError, ValueError):
        return "Anteriores"
    if day >= today:
        return "Hoy"
    if day == today - timedelta(days=1):
        return "Ayer"
    if day >= today - timedelta(days=today.weekday()):
        return "Esta semana"
    return "Anteriores"


def sidebar_icon(name, color):
    pixmap = QPixmap(ICON_SIZE * 2, ICON_SIZE * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    with QPainter(pixmap) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if name == "search":
            painter.drawEllipse(QRectF(2.75, 2.75, 11, 11))
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
        elif name == "send":
            painter.drawLine(10, 16, 10, 4)
            painter.drawPolyline(QPolygon([QPoint(5, 9), QPoint(10, 4), QPoint(15, 9)]))
        elif name == "stop":
            painter.setBrush(color)
            painter.drawRoundedRect(QRect(5, 5, 10, 10), 1, 1)
        elif name == "chip":
            painter.drawRoundedRect(QRect(5, 5, 10, 10), 2, 2)
            painter.drawRect(QRect(8, 8, 4, 4))
            for pin in (8, 12):
                painter.drawLine(pin, 2, pin, 5)
                painter.drawLine(pin, 15, pin, 18)
                painter.drawLine(2, pin, 5, pin)
                painter.drawLine(15, pin, 18, pin)
        elif name == "delete":
            painter.drawRoundedRect(QRect(5, 6, 10, 11), 2, 2)
            painter.drawLine(3, 4, 17, 4)
            painter.drawLine(8, 2, 12, 2)
        elif name == "more":
            painter.setBrush(color)
            for y in (4, 10, 16):
                painter.drawEllipse(QRectF(9, y - 1, 2, 2))
        elif name == "settings":
            points = []
            for index in range(32):
                angle = index * pi / 16
                radius = 8.5 if index % 4 in (1, 2) else 6.5
                points.append(QPoint(round(10 + radius * cos(angle)), round(10 + radius * sin(angle))))
            painter.drawPolygon(QPolygon(points))
            painter.drawEllipse(QRect(7, 7, 6, 6))
        else:
            painter.drawLine(3, 10, 17, 10)
            painter.drawLine(10, 3, 10, 17)
    return QIcon(pixmap)


def sidebar_button(title):
    button = secondary_button(QPushButton())
    button.setProperty("quiet", True)
    button.setToolTip(title)
    button.setAccessibleName(title)
    button.setFixedHeight(BUTTON_SIZE)
    button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    return button


class SidebarRail(QWidget):
    def __init__(self, history):
        super().__init__()
        self.setObjectName("sidebarRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.history = history
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        edge = (RAIL_WIDTH - BUTTON_SIZE) // 2
        header.setContentsMargins(edge, 12, edge, 8)
        self.toggle = sidebar_button("Fijar barra lateral")
        self.toggle.setObjectName("sidebarToggle")
        self.toggle.setFixedWidth(BUTTON_SIZE)
        self.toggle.setCheckable(True)
        header.addWidget(self.toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(header)
        nav = QWidget()
        self.navigation = navigation = QVBoxLayout(nav)
        navigation.setSpacing(8)
        layout.addWidget(nav, alignment=Qt.AlignmentFlag.AlignTop)
        self.actions = {}
        for name, title in SIDEBAR_ACTIONS:
            button = sidebar_button(title)
            button.setProperty("sidebarAction", True)
            self.actions[name] = button
            if name == "search":
                button.setObjectName("sidebarSearch")
                button.setFixedWidth(BUTTON_SIZE)
            navigation.addWidget(button)
        new_chat = self.actions["new"]
        QShortcut(QKeySequence(NEW_CHAT_SHORTCUT), new_chat).activated.connect(new_chat.click)
        new_chat.setToolTip(f"Nuevo chat ({NEW_CHAT_SHORTCUT})")
        self.actions["search"].setToolTip(f"Buscar conversaciones ({SEARCH_SHORTCUT})")
        self.new_shortcut_hint = QLabel(NEW_CHAT_SHORTCUT)
        self.new_shortcut_hint.setObjectName("shortcutHint")
        self.new_shortcut_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        shortcut_row = QHBoxLayout(new_chat)
        shortcut_row.setContentsMargins(0, 0, 10, 0)
        shortcut_row.addStretch()
        shortcut_row.addWidget(self.new_shortcut_hint)
        layout.addWidget(history, 1)
        self.footer = footer = QVBoxLayout()
        self.provider_badge = sidebar_button("Modelo y proveedor de IA")
        self.provider_badge.setObjectName("providerBadge")
        self.provider_badge.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        footer.addWidget(self.provider_badge)
        layout.addLayout(footer)
        self.provider = self.model = ""
        self.provider_icon = QIcon()
        self.set_expanded(False)

    def set_expanded(self, expanded):
        self.expanded = expanded
        self.setFixedWidth(DEFAULT_WIDTH if expanded else RAIL_WIDTH)
        edge = 12 if expanded else (RAIL_WIDTH - BUTTON_SIZE) // 2
        self.navigation.setContentsMargins(edge, 0, edge, 12)
        self.footer.setContentsMargins(edge, 10, edge, 12)
        for name, title in SIDEBAR_ACTIONS:
            button = self.actions[name]
            show_label = expanded and name != "search"
            button.setText(title if show_label else "")
            button.setProperty("sidebarAction", show_label)
            button.style().unpolish(button)
            button.style().polish(button)
        self.provider_badge.setFixedHeight(44 if expanded else BUTTON_SIZE)
        self.new_shortcut_hint.setVisible(expanded)
        self.actions["search"].setVisible(not expanded)
        self.history.setVisible(expanded)
        self.update_provider_badge()

    def set_provider(self, provider, model):
        self.provider, self.model = provider, model
        self.provider_badge.setToolTip(f"{provider} · {model}")
        self.provider_badge.setAccessibleName(f"Modelo y proveedor de IA: {provider}, {model}")
        self.update_provider_badge()

    def update_provider_badge(self):
        if self.expanded:
            label = self.provider_badge.fontMetrics().elidedText(self.model, Qt.TextElideMode.ElideRight, max(60, self.width() - 42))
            self.provider_badge.setText(f"{self.provider}\n{label}")
            self.provider_badge.setIcon(QIcon())
        else:
            self.provider_badge.setText("")
            self.provider_badge.setIcon(self.provider_icon)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_provider_badge()

    def refresh_icons(self, color):
        self.toggle.setIcon(sidebar_icon("toggle", color))
        for name, button in self.actions.items():
            button.setIcon(sidebar_icon(name, color))
        self.provider_icon = sidebar_icon("chip", color)
        self.update_provider_badge()


class SidebarShadow(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        fade = QLinearGradient(0, 0, self.width(), 0)
        fade.setColorAt(0, QColor(0, 0, 0, 76))
        fade.setColorAt(1, QColor(0, 0, 0, 0))
        with QPainter(self) as painter:
            painter.fillRect(self.rect(), fade)


class SidebarPreview(QWidget):
    """Mantiene una sola barra y reserva espacio en el chat al fijarla."""

    def __init__(self, parent, slot, rail):
        super().__init__(parent)
        self.slot = slot
        self.rail = rail
        self.trigger = rail.toggle
        self.pinned = False
        self.floating = False
        self.wait_for_leave = False
        self.panel_width = RAIL_WIDTH
        self.shadow = SidebarShadow(parent)
        slot.setFixedWidth(RAIL_WIDTH)
        rail.setParent(self)
        rail.show()

        self.animation = QVariantAnimation(self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.valueChanged.connect(self.set_panel_width)
        self.animation.finished.connect(self.finish_preview)
        self.hide_timer = QTimer(self, singleShot=True, interval=300)
        self.hide_timer.timeout.connect(self.hide_if_outside)
        slot.installEventFilter(self)
        self.trigger.installEventFilter(self)
        self.sync_geometry()

    @staticmethod
    def cursor_inside(widget):
        return widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(QCursor.pos()))

    def eventFilter(self, watched, event):
        slot = getattr(self, "slot", None)
        if slot is None:
            return False
        kind = event.type()
        if watched is slot and kind in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show):
            self.sync_geometry()
        elif watched is getattr(self, "trigger", None):
            if kind == QEvent.Type.Enter and not self.pinned and not self.wait_for_leave:
                self.open_preview()
            elif kind == QEvent.Type.Leave:
                self.wait_for_leave = False
                if self.floating:
                    self.hide_timer.start()
        return super().eventFilter(watched, event)

    def set_pinned(self, pinned):
        self.animation.stop()
        self.hide_timer.stop()
        self.pinned = pinned
        self.floating = False
        self.wait_for_leave = not pinned and self.cursor_inside(self.rail.toggle)
        width = DEFAULT_WIDTH if pinned else RAIL_WIDTH
        self.panel_width = width
        self.slot.setFixedWidth(width)
        self.rail.set_expanded(pinned)
        self.update_tooltip()
        self.sync_geometry()

    def update_tooltip(self):
        label = "Cerrar barra lateral" if self.pinned else "Fijar barra lateral"
        self.rail.toggle.setAccessibleName(label)
        self.rail.toggle.setToolTip("" if self.floating else f"{label} (Ctrl+Shift+S)")
        if self.floating:
            QToolTip.hideText()

    def open_preview(self):
        self.hide_timer.stop()
        if not self.floating:
            self.floating = True
            self.rail.set_expanded(True)
            self.update_tooltip()
        self.animate_to(DEFAULT_WIDTH)

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.floating:
            self.open_preview()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.floating:
            self.hide_timer.start()

    def hide_if_outside(self):
        if not self.floating or self.cursor_inside(self):
            return
        popup = QApplication.activePopupWidget()
        parent = popup.parentWidget() if popup is not None else None
        if parent is not None and self.rail.isAncestorOf(parent):
            self.hide_timer.start()
        else:
            self.animate_to(RAIL_WIDTH)

    def animate_to(self, width):
        if self.animation.state() == QVariantAnimation.State.Running and self.animation.endValue() == width:
            return
        self.animation.stop()
        if self.panel_width == width:
            self.finish_preview()
            return
        self.animation.setStartValue(self.panel_width)
        self.animation.setEndValue(width)
        self.animation.start()

    def finish_preview(self):
        if self.panel_width == RAIL_WIDTH:
            self.floating = False
            self.rail.set_expanded(False)
            self.update_tooltip()
            self.sync_geometry()
        elif self.floating and not self.cursor_inside(self) and not self.hide_timer.isActive():
            self.hide_timer.start()

    def set_panel_width(self, width):
        self.panel_width = width
        self.sync_geometry()

    def sync_geometry(self):
        origin = self.slot.mapTo(self.parentWidget(), QPoint())
        height = self.slot.height()
        self.setGeometry(origin.x(), origin.y(), self.panel_width, height)
        self.rail.resize(self.rail.width(), height)
        self.shadow.setGeometry(origin.x() + self.panel_width, origin.y(), 14, height)
        self.shadow.setVisible(self.floating and self.panel_width > RAIL_WIDTH)
        self.shadow.raise_()
        self.raise_()


def load_sidebar_pinned():
    try:
        return appearance_settings().value("sidebar_pinned", False, type=bool)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def save_sidebar_pinned(pinned):
    settings = appearance_settings()
    settings.setValue("sidebar_pinned", pinned)
    sync(settings)


class ConversationDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(min(size.width(), self.parent().viewport().width()))
        heading = not index.flags() & Qt.ItemFlag.ItemIsEnabled
        if index.data(DATE_ROLE):
            size.setHeight(26)
        else:
            size.setHeight(max(34 if heading else 38, option.fontMetrics.height() + (15 if heading else 12)))
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
            if (self.hovered is None or self.hovered.data(MORE_ROLE) is not None
                    or not self.hovered.flags() & Qt.ItemFlag.ItemIsEnabled):
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
        if item is not None and item.data(MORE_ROLE) is None and item.flags() & Qt.ItemFlag.ItemIsEnabled:
            point = self.viewport().mapToGlobal(self.visualItemRect(item).bottomLeft()) if keyboard else event.globalPos()
            self.options_requested.emit(item, point)
            event.accept()


class HistoryPanel(QWidget):
    opened = Signal(int)
    renamed = Signal(int, str)
    deleted = Signal(int)
    pin_requested = Signal(int, bool)
    new_chat = Signal()
    searched = Signal(str)
    diagnostics = Signal()
    projects_requested = Signal()
    project_opened = Signal(int)
    project_deleted = Signal(int)
    transfer_requested = Signal(int, str, str)
    move_requested = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("historyPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar conversaciones…")
        self.search.setAccessibleName("Buscar conversaciones")
        self.search.setToolTip(f"Buscar conversaciones ({SEARCH_SHORTCUT})")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.searched)
        self.list = ConversationList()
        self.list.setAccessibleName("Conversaciones")
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSpacing(2)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.itemClicked.connect(self.activate_row)
        self.list.itemActivated.connect(self.activate_row)
        self.list.options_requested.connect(self.show_options)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(10)
        self.expanded_projects = set()
        self.projects = []
        self.project_chats = {}
        self.rows = []
        self.updated = {}
        self.pinned = set()
        self.recent_limit = RECENT_BATCH
        self.current_chat = None
        self.icon_color = None
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_hint = QLabel(SEARCH_SHORTCUT)
        search_hint.setObjectName("shortcutHint")
        search_row.addWidget(search_hint)
        layout.addLayout(search_row)
        layout.addWidget(self.list, 1)

    def show_search(self):
        self.search.show()
        self.search.setFocus()

    def refresh_icons(self, color):
        self.icon_color = color
        self.rebuild()

    def activate_row(self, item):
        if item.data(MORE_ROLE) is not None:
            first_older = item.data(MORE_ROLE)
            self.recent_limit += RECENT_BATCH
            self.rebuild()
            for index in range(self.list.count()):
                row = self.list.item(index)
                if row.data(Qt.ItemDataRole.UserRole) == first_older and not row.data(NESTED_ROLE):
                    self.list.setCurrentItem(row)
                    self.list.scrollToItem(row)
                    break
        elif (project_id := item.data(PROJECT_ROLE)) is not None:
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
        self.rows = [(row[0], row[1]) for row in rows]
        self.updated = {row[0]: row[2] for row in rows if len(row) > 2}
        self.pinned = {row[0] for row in rows if len(row) > 3 and row[3]}
        self.current_chat = current
        if project_chats is not None:
            self.project_chats = project_chats
        self.rebuild()

    def add_heading(self, text, *, small=False):
        item = QListWidgetItem(text)
        font = item.font()
        font.setBold(True)
        if small:
            font.setPointSize(9)
            item.setData(DATE_ROLE, True)
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
        searching = bool(self.search.text().strip())
        selected_pinned = None
        if not searching:
            if self.pinned:
                self.add_heading("Fijados")
                for chat_id, title in self.rows:
                    if chat_id in self.pinned:
                        item = self.add_chat(chat_id, title)
                        if chat_id == self.current_chat:
                            selected_pinned = item
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
        recent = self.rows if searching else [row for row in self.rows if row[0] not in self.pinned]
        if recent and not searching:
            self.add_heading("Recientes")
        today = date.today()
        previous_heading = None
        for chat_id, title in recent if searching else recent[:self.recent_limit]:
            if not searching:
                heading = recent_heading(self.updated.get(chat_id), today)
                if heading != previous_heading:
                    self.add_heading(heading, small=True)
                    previous_heading = heading
            item = self.add_chat(chat_id, title)
            if chat_id == self.current_chat and selected_nested is None:
                self.list.setCurrentItem(item)
        if not searching and len(recent) > self.recent_limit:
            more = QListWidgetItem("Ver más conversaciones…")
            more.setData(MORE_ROLE, recent[self.recent_limit][0])
            self.list.addItem(more)
        if selected_pinned is not None:
            self.list.setCurrentItem(selected_pinned)
        elif selected_nested is not None:
            self.list.setCurrentItem(selected_nested)
        scroll.setValue(position)

    def show_options(self, item, point):
        if (project_id := item.data(PROJECT_ROLE)) is not None:
            menu = style_chat_menu(QMenu(self))
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
        menu = style_chat_menu(QMenu(self))
        self.populate_chat_menu(menu, chat_id, title, chat_id in self.pinned)
        menu.exec(point)
        menu.deleteLater()

    def populate_chat_menu(self, menu, chat_id, title, pinned):
        menu.clear()
        menu.addAction("Quitar de fijados" if pinned else "Fijar",
                       lambda: self.pin_requested.emit(chat_id, not pinned))
        menu.addAction("Cambiar nombre", lambda: self.prompt_name(chat_id, title))
        menu.addAction("Mover a proyecto…", lambda: self.move_requested.emit(chat_id))
        for label, kind in (("Copiar conversación", "copy"), ("Exportar a Markdown…", "md"),
                            ("Exportar a PDF…", "pdf")):
            menu.addAction(label, lambda checked=False, kind=kind: self.transfer_requested.emit(chat_id, title, kind))
        menu.addSeparator()
        delete = menu.addAction("Eliminar", lambda: self.prompt_delete(chat_id))
        delete.setIcon(sidebar_icon("delete", QColor("#ef9999")))

    def prompt_name(self, chat_id, current_title):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Cambiar nombre")
        dialog.setLabelText("Título de la conversación")
        dialog.setTextValue(current_title)
        dialog.setOkButtonText("Guardar")
        dialog.setCancelButtonText("Cancelar")
        dialog.setMinimumWidth(380)
        dialog.setStyleSheet(settings_style(self.theme))
        if dialog.exec() and (title := dialog.textValue().strip()):
            self.renamed.emit(chat_id, title)
        dialog.deleteLater()

    def prompt_delete(self, chat_id):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Eliminar conversación")
        dialog.setText("¿Eliminar esta conversación del historial?")
        dialog.setStyleSheet(settings_style(self.theme))
        remove = dialog.addButton("Eliminar", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is remove:
            self.deleted.emit(chat_id)
        dialog.deleteLater()

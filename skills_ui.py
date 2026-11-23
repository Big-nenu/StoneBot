"""Panel de instalación y activación de skills locales."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QStackedWidget, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from appearance import control_colors
from extension_ui import Toggle
from local_skills import discover, enabled, install, set_enabled


class SkillRowDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator


class SkillsPanel(QWidget):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar skills…")
        self.search.setAccessibleName("Buscar skills por nombre o descripción")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_skills)

        self.list = QListWidget()
        self.list.setObjectName("skillList")
        self.list.setAccessibleName("Skills locales")
        self.list.setMouseTracking(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setItemDelegate(SkillRowDelegate(self.list))
        self.list.currentItemChanged.connect(self.show_description)
        self.list.itemChanged.connect(self.toggle)
        self.empty = QLabel()
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.results = QStackedWidget()
        self.results.addWidget(self.list)
        self.results.addWidget(self.empty)

        add_button = QPushButton("Importar carpeta…")
        add_button.setProperty("primary", False)
        add_button.setAutoDefault(False)
        add_button.clicked.connect(self.add)
        sidebar = QWidget()
        sidebar.setObjectName("extensionSidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sidebar.setFixedWidth(208)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.addWidget(self.search)
        sidebar_layout.addWidget(self.results, 1)
        sidebar_layout.addWidget(add_button)

        self.detail_title = QLabel()
        self.detail_title.setObjectName("extensionTitle")
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        self.state = QLabel()
        self.state.setObjectName("skillState")
        self.switch = Toggle(False, "Activar skill", theme["accent"], control_colors(theme["background"])[0])
        self.switch.toggled.connect(self.change_current)
        heading = QHBoxLayout()
        heading.addWidget(self.detail_title, 1)
        heading.addWidget(self.state)
        heading.addWidget(self.switch)

        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card = QWidget()
        card.setObjectName("extensionCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.addWidget(self.description)
        detail_content = QWidget()
        detail_content.setProperty("extensionCanvas", True)
        detail_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        detail_layout = QVBoxLayout(detail_content)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(card)
        detail_layout.addStretch()
        self.detail = QScrollArea()
        self.detail.setWidgetResizable(True)
        self.detail.setWidget(detail_content)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        content = QVBoxLayout()
        content.addLayout(heading)
        content.addWidget(self.detail, 1)
        content.addWidget(self.status)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(sidebar)
        layout.addLayout(content, 1)
        self.refresh()

    def set_appearance(self, theme):
        self.theme = theme
        self.switch.accent = theme["accent"]
        self.switch.surface = control_colors(theme["background"])[0]
        self.switch.update()

    def refresh(self, selected=None):
        if selected is None and self.list.currentItem() is not None:
            selected = self.list.currentItem().text()
        with QSignalBlocker(self.list):
            self.list.clear()
            try:
                skills, problems = discover()
                for skill in skills.values():
                    item = QListWidgetItem(skill.name)
                    item.setData(Qt.ItemDataRole.UserRole, skill.description)
                    item.setCheckState(Qt.CheckState.Checked if enabled(skill.name) else Qt.CheckState.Unchecked)
                    item.setToolTip(skill.name)
                    self.list.addItem(item)
                    if skill.name == selected:
                        self.list.setCurrentItem(item)
                self.status.setText("\n".join(problems))
            except (OSError, ValueError, RuntimeError) as exc:
                self.status.setText(str(exc))
        self.filter_skills()

    def filter_skills(self):
        query = self.search.text().strip().casefold()
        first = None
        for index in range(self.list.count()):
            item = self.list.item(index)
            description = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(query not in item.text().casefold() and query not in description.casefold())
            if first is None and not item.isHidden():
                first = item
        current = self.list.currentItem()
        if current is None or current.isHidden():
            self.list.setCurrentItem(first)
        self.empty.setText("Sin coincidencias" if query else "Todavía no hay skills")
        self.results.setCurrentWidget(self.list if first is not None else self.empty)
        self.show_description(self.list.currentItem())

    def show_description(self, item):
        self.detail_title.setText(item.text() if item else "Skills")
        self.description.setText(item.data(Qt.ItemDataRole.UserRole) if item else
                                 "Selecciona una skill o importa una carpeta que contenga SKILL.md.")
        self.state.setVisible(item is not None)
        self.switch.setVisible(item is not None)
        if item is not None:
            active = item.checkState() == Qt.CheckState.Checked
            self.state.setText("Activa" if active else "Inactiva")
            self.switch.setAccessibleName(f"Skill {item.text()}")
            with QSignalBlocker(self.switch):
                self.switch.setChecked(active)
        self.detail.verticalScrollBar().setValue(0)

    def change_current(self, active):
        if (item := self.list.currentItem()) is not None:
            item.setCheckState(Qt.CheckState.Checked if active else Qt.CheckState.Unchecked)

    def toggle(self, item):
        active = item.checkState() == Qt.CheckState.Checked
        try:
            set_enabled(item.text(), active)
        except (OSError, ValueError, RuntimeError) as exc:
            self.refresh(item.text())
            self.status.setText(str(exc))
            return
        if item is self.list.currentItem():
            self.show_description(item)

    def add(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona una carpeta con SKILL.md")
        if folder:
            try:
                name = install(folder)
            except (OSError, ValueError, RuntimeError) as exc:
                self.status.setText(str(exc))
                return
            self.search.clear()
            self.refresh(name)

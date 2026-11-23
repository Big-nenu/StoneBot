"""Panel de instalación y activación de skills locales."""

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from appearance import control_colors
from extension_ui import Toggle
from local_skills import discover, enabled, install, set_enabled


class SkillRowDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""
        option.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator


class SkillsPanel(QWidget):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar skills por nombre o descripción")
        self.search.setAccessibleName("Buscar skills")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_skills)
        add_button = QPushButton("Importar carpeta…")
        add_button.setProperty("primary", True)
        add_button.setAutoDefault(False)
        add_button.clicked.connect(self.add)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(add_button)

        self.list = QListWidget()
        self.list.setObjectName("skillList")
        self.list.setAccessibleName("Skills locales")
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setItemDelegate(SkillRowDelegate(self.list))
        self.list.currentItemChanged.connect(self.show_description)
        self.list.itemChanged.connect(self.toggle)
        self.empty = QLabel()
        self.empty.setObjectName("extensionEmpty")
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.results = QStackedWidget()
        self.results.addWidget(self.list)
        self.results.addWidget(self.empty)

        self.detail_title = QLabel()
        self.detail_title.setProperty("sectionHeading", True)
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_title.setWordWrap(True)
        self.description = QLabel()
        self.description.setTextFormat(Qt.TextFormat.PlainText)
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_content = QWidget()
        detail_content.setObjectName("skillDetailContent")
        detail_layout = QVBoxLayout(detail_content)
        detail_layout.setContentsMargins(14, 12, 14, 12)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.description)
        detail_layout.addStretch()
        self.detail = QScrollArea()
        self.detail.setObjectName("skillDetail")
        self.detail.setWidgetResizable(True)
        self.detail.setWidget(detail_content)
        self.detail.setFixedHeight(124)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(toolbar)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.detail)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self, selected=None):
        if selected is None and self.list.currentItem() is not None:
            selected = self.list.currentItem().text()
        with QSignalBlocker(self.list):
            self.list.clear()
            try:
                skills, problems = discover()
                for skill in skills.values():
                    item = self.add_row(skill, enabled(skill.name))
                    if skill.name == selected:
                        self.list.setCurrentItem(item)
                self.status.setText("\n".join(problems))
            except (OSError, ValueError, RuntimeError) as exc:
                self.status.setText(str(exc))
        self.status.setVisible(bool(self.status.text()))
        self.filter_skills()

    def add_row(self, skill, active):
        item = QListWidgetItem(skill.name)
        item.setData(Qt.ItemDataRole.UserRole, skill.description)
        item.setCheckState(Qt.CheckState.Checked if active else Qt.CheckState.Unchecked)
        item.setToolTip(skill.name)
        item.setSizeHint(QSize(0, 51))
        self.list.addItem(item)

        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 0, 12, 0)
        title = QLabel(skill.name)
        title.setObjectName("skillName")
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        state = QLabel("Activa" if active else "Inactiva")
        state.setObjectName("skillState")
        state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        surface = control_colors(self.theme["background"])[0]
        switch = Toggle(active, f"Skill {skill.name}", self.theme["accent"], surface)
        switch.toggled.connect(lambda checked: item.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked))
        layout.addWidget(title, 1)
        layout.addWidget(state)
        layout.addWidget(switch)
        self.list.setItemWidget(item, row)
        return item

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
        self.empty.setText("No hay skills que coincidan con la búsqueda." if query else
                           "Todavía no hay skills. Importa una carpeta que contenga SKILL.md.")
        self.results.setCurrentWidget(self.list if first is not None else self.empty)
        self.show_description(self.list.currentItem())

    def show_description(self, item):
        self.detail.setVisible(item is not None)
        self.detail_title.setText(item.text() if item else "")
        self.description.setText(item.data(Qt.ItemDataRole.UserRole) if item else "")
        self.detail.verticalScrollBar().setValue(0)

    def toggle(self, item):
        active = item.checkState() == Qt.CheckState.Checked
        try:
            set_enabled(item.text(), active)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Skills", str(exc))
            self.refresh(item.text())
            return
        row = self.list.itemWidget(item)
        switch = row.findChild(Toggle)
        with QSignalBlocker(switch):
            switch.setChecked(active)
        row.findChild(QLabel, "skillState").setText("Activa" if active else "Inactiva")

    def add(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona una carpeta con SKILL.md")
        if folder:
            try:
                name = install(folder)
            except (OSError, ValueError, RuntimeError) as exc:
                QMessageBox.warning(self, "Skills", str(exc))
                return
            self.search.clear()
            self.refresh(name)

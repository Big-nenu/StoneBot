"""Vistas de proyectos y diálogo de edición."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QPlainTextEdit, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from appearance import secondary_button


def label(text, style="projectMeta"):
    result = QLabel(text)
    result.setObjectName(style)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result


class ProjectDialog(QDialog):
    def __init__(self, parent, project=None):
        super().__init__(parent)
        self.setWindowTitle("Editar proyecto" if project else "Crear un proyecto")
        self.setMinimumWidth(460)
        project = project or {}
        self.name = QLineEdit(project.get("name", ""))
        self.name.setMaxLength(100)
        self.name.setPlaceholderText("Nombre del proyecto")
        self.description = QPlainTextEdit(project.get("description", ""))
        self.description.setPlaceholderText("Describe qué quieres lograr")
        self.description.setFixedHeight(80)
        self.instructions = QPlainTextEdit(project.get("instructions", ""))
        self.instructions.setPlaceholderText("Preferencias o instrucciones para los chats del proyecto")
        self.instructions.setFixedHeight(90)
        self.folder = QLineEdit(project.get("folder", ""))
        self.folder.setPlaceholderText("Carpeta local opcional")
        browse = secondary_button(QPushButton("Elegir…"))
        browse.clicked.connect(self.browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(9)
        for title, field in (("Nombre", self.name), ("Descripción", self.description),
                             ("Instrucciones", self.instructions)):
            heading = label(title, "projectSection")
            heading.setBuddy(field)
            field.setAccessibleName(title)
            layout.addWidget(heading)
            layout.addWidget(field)
        self.folder.setAccessibleName("Carpeta local")
        layout.addLayout(folder_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        accept = buttons.button(QDialogButtonBox.StandardButton.Ok)
        accept.setText("Guardar" if project else "Crear proyecto")
        accept.setEnabled(bool(self.name.text().strip()))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.name.textChanged.connect(lambda text: accept.setEnabled(bool(text.strip())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus()

    def browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Elegir carpeta del proyecto", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def fields(self):
        return self.name.text(), self.description.toPlainText().strip(), self.instructions.toPlainText().strip(), self.folder.text().strip()


class ProjectPage(QScrollArea):
    created = Signal()
    opened = Signal(int)
    back = Signal()
    edited = Signal(int)
    continuity_requested = Signal(int)
    document_requested = Signal(int)
    document_unlinked = Signal(int, int)
    pinned = Signal(int, bool)
    chat_started = Signal(int)
    chat_opened = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("projectPage")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("projectCanvas")
        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(24, 30, 24, 24)
        outer.addStretch(1)
        content = QWidget()
        content.setMaximumWidth(960)
        outer.addWidget(content, 100)
        outer.addStretch(1)
        self.content = QVBoxLayout(content)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(16)
        self.setWidget(canvas)

    @staticmethod
    def action(title, callback, *, primary=False):
        button = QPushButton(title.replace("&", "&&"))
        if primary:
            button.setObjectName("sendMessage")
        else:
            secondary_button(button)
        button.clicked.connect(callback)
        return button

    def clear_page(self):
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def heading(self, title, *buttons):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(title, "projectTitle"))
        row.addStretch()
        for button in buttons:
            row.addWidget(button)
        self.content.addWidget(bar)

    def show_projects(self, projects):
        self.clear_page()
        self.heading("Proyectos", self.action("Nuevo proyecto", self.created.emit, primary=True))
        if not projects:
            self.content.addWidget(label("Crea un proyecto para reunir sus conversaciones e instrucciones."))
        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, project in enumerate(projects):
            card = QWidget()
            card.setObjectName("projectCard")
            body = QVBoxLayout(card)
            body.setContentsMargins(12, 9, 12, 11)
            button = self.action(project["name"], lambda _checked=False, pid=project["id"]: self.opened.emit(pid))
            button.setObjectName("projectLink")
            button.setProperty("quiet", True)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.setToolTip(project["name"])
            body.addWidget(button)
            chats = project["chats"]
            body.addWidget(label(f"{chats} {'chat' if chats == 1 else 'chats'}" + (" · Fijado" if project["pinned"] else "")))
            grid.addWidget(card, index // 2, index % 2)
        self.content.addWidget(cards)
        self.content.addStretch()
        self.verticalScrollBar().setValue(0)

    def show_project(self, project, chats, documents):
        self.clear_page()
        pid = project["id"]
        self.content.addWidget(self.action("‹ Proyectos", self.back.emit), alignment=Qt.AlignmentFlag.AlignLeft)
        self.heading(project["name"],
                     self.action("Desfijar" if project["pinned"] else "Fijar",
                                 lambda: self.pinned.emit(pid, not project["pinned"])),
                     self.action("Editar", lambda: self.edited.emit(pid)))
        if project["description"]:
            self.content.addWidget(label(project["description"]))
        self.content.addWidget(self.action("Nuevo chat", lambda: self.chat_started.emit(pid), primary=True),
                               alignment=Qt.AlignmentFlag.AlignLeft)
        continuity = QWidget()
        continuity.setObjectName("projectCard")
        summary = QVBoxLayout(continuity)
        summary.setContentsMargins(14, 12, 14, 12)
        row = QHBoxLayout()
        row.addWidget(label("Punto de continuidad", "projectSection"), 1)
        row.addWidget(self.action("Editar" if project["continuity"] else "Añadir",
                                  lambda: self.continuity_requested.emit(pid)))
        summary.addLayout(row)
        document = QTextDocument()
        document.setMarkdown(project["continuity"])
        preview = document.toPlainText().strip()
        if len(preview) > 580:
            preview = preview[:579].rstrip() + "…"
        summary.addWidget(label(preview or "Guarda aquí en qué te quedaste y qué sigue."))
        self.content.addWidget(continuity)
        documents_card = QWidget()
        documents_card.setObjectName("projectCard")
        document_list = QVBoxLayout(documents_card)
        document_list.setContentsMargins(14, 12, 14, 12)
        row = QHBoxLayout()
        row.addWidget(label("Documentos", "projectSection"), 1)
        row.addWidget(self.action("Vincular archivo…", lambda: self.document_requested.emit(pid)))
        document_list.addLayout(row)
        if not documents:
            document_list.addWidget(label("Vincula un archivo para consultarlo desde los chats del proyecto."))
        for document_id, path in documents:
            row = QHBoxLayout()
            name = label(Path(path).name)
            name.setToolTip(path)
            row.addWidget(name, 1)
            unlink = self.action("Desvincular",
                                 lambda _checked=False, did=document_id: self.document_unlinked.emit(pid, did))
            unlink.setAccessibleName(f"Desvincular {name.text()}")
            row.addWidget(unlink)
            document_list.addLayout(row)
        self.content.addWidget(documents_card)
        context = QWidget()
        context.setObjectName("projectCard")
        details = QVBoxLayout(context)
        details.setContentsMargins(14, 12, 14, 12)
        details.addWidget(label("Instrucciones", "projectSection"))
        details.addWidget(label(project["instructions"] or "Sin instrucciones"))
        if project["folder"]:
            details.addWidget(label("Carpeta vinculada", "projectSection"))
            details.addWidget(label(project["folder"]))
        self.content.addWidget(context)
        self.content.addWidget(label("Conversaciones", "projectSection"))
        for chat_id, title in chats:
            button = self.action(title, lambda _checked=False, cid=chat_id: self.chat_opened.emit(cid))
            button.setObjectName("projectLink")
            button.setProperty("quiet", True)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.setToolTip(title)
            self.content.addWidget(button)
        if not chats:
            self.content.addWidget(label("Aún no hay conversaciones."))
        self.content.addStretch()
        self.verticalScrollBar().setValue(0)

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ai_provider import AISettings, DEFAULT_MODEL, PROVIDERS, load_ai
from ai_settings_ui import AISettingsDialog
from appearance import (
    AppearanceDialog, apply_palette, dialog_style, load_appearance, readable_text, save_appearance,
    secondary_button,
)
from attachments import FILE_FILTER, attachment_path, has_chat_attachments
from chat_markdown import MarkdownText
from chat_preferences import automatic_memory_enabled, load_instructions, save_automatic_memory, save_instructions
from chat_ui import ActivityPanel, AttachmentCard, AttachmentTray, ChatText, Composer, chat_style
from diagnostics import read_log, record
from experiences import save_task_correction, task_correction
from folder_inventory import HIDDEN_MISTAKE, inventory_followup, is_ranking_request, ranking_count, uses_mcp
from history import History
from history_ui import HistoryPanel, SidebarRail, load_history_width, save_history_width, sidebar_icon
import local_skills
from mcp_client import data_path
from mcp_pool import McpPool
from mcp_setup import is_setup_request
from mcp_ui import McpDialog
from memory_ui import MemoryDialog
from projects_ui import ProjectDialog, ProjectPage
from skills_ui import SkillsDialog
from stonebot_engine.safety import check_path
from stonewave_memory import StoneWaveMemory
from tasks import LABELS as TASK_LABELS, new_task, step_caption, upgrade_task
from tasks_ui import TaskCorrectionDialog
from win_caption import apply_native_caption
from PySide6.QtCore import QEvent, QLockFile, QSize, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QActionGroup, QColor, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)
from turn_worker import COMMANDS, SYSTEM, TASK_COMMANDS, Worker


MODEL = DEFAULT_MODEL
ICON_PATH = Path(__file__).resolve().parent / "assets" / "stonebot.ico"
COMPOSER_COMMANDS = (
    ("/buscar", "Buscar conversaciones", True),
    ("/resumir", "Resumir contenido", True),
    ("/tarea", "Empezar un encargo", True),
    ("/reanudar", "Retomar un encargo", False),
    ("/cancelar", "Cerrar el encargo", False),
    ("/identidad", "Consultar la identidad de StoneBot", False),
    ("/sueno", "Revisar la memoria de StoneWave", True),
    ("/aprender", "Registrar una experiencia MCP", True),
    ("/mcp instalar", "Configurar un servidor MCP", True),
)
CHAT_WIDTH = 820



class StoneBot(QMainWindow):
    def __init__(self, *, use_tray=False):
        super().__init__()
        self.setWindowTitle("StoneBot")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1000, 680)
        self.setMinimumSize(340, 360)

        self.messages = [{"role": "system", "content": SYSTEM}]
        self.thread = None
        self.worker = None
        self.memory = StoneWaveMemory()
        try:
            self.ai = load_ai()
        except (OSError, ValueError, RuntimeError):
            self.ai = AISettings()
        self.tray = None
        self.exit_requested = False
        self.mcp_dialog = None
        self.pool = McpPool()
        self.chat_id = None
        self.task = None
        self.history_write_ok = True
        self.pending_edit = None
        self.project = None
        self.projects = []
        try:
            self.history = History()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.history = None
        self.appearance = load_appearance()

        central = QWidget()
        central.setObjectName("chatWindow")
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.history_width = self.saved_history_width = load_history_width()
        self.history_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.history_splitter.setChildrenCollapsible(False)
        self.history_splitter.setHandleWidth(6)
        main_layout.addWidget(self.history_splitter)
        self.history_panel = HistoryPanel()
        self.history_panel.new_chat.connect(self.new_chat)
        self.history_panel.opened.connect(self.open_chat)
        self.history_panel.renamed.connect(self.rename_chat)
        self.history_panel.deleted.connect(self.delete_chat)
        self.history_panel.searched.connect(self.refresh_history)
        self.history_panel.diagnostics.connect(self.open_diagnostics)
        self.history_panel.projects_requested.connect(self.show_projects)
        self.history_panel.project_opened.connect(self.show_project)
        self.history_panel.project_deleted.connect(self.delete_project)
        self.history_panel.move_requested.connect(self.move_chat_to_project)
        self.sidebar_rail = SidebarRail(self.history_panel)
        self.sidebar_rail.actions["new"].clicked.connect(self.history_panel.new_chat)
        self.sidebar_rail.actions["search"].clicked.connect(self.search_sidebar)
        self.sidebar_rail.actions["projects"].clicked.connect(self.history_panel.projects_requested)
        self.sidebar_rail.actions["diagnostics"].clicked.connect(self.history_panel.diagnostics)
        self.history_splitter.addWidget(self.sidebar_rail)
        conversation = QWidget()
        self.history_splitter.addWidget(conversation)
        self.history_splitter.setStretchFactor(0, 0)
        self.history_splitter.setStretchFactor(1, 1)
        self.history_splitter.splitterMoved.connect(self.remember_history_width)
        layout = QVBoxLayout(conversation)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 9, 16, 9)
        header_layout.setSpacing(8)
        title = self.header_title = QLabel("StoneBot")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setObjectName("chatTitle")
        self.history_button = self.sidebar_rail.toggle
        self.history_button.setShortcut("Ctrl+Shift+S")
        self.history_button.toggled.connect(self.toggle_history)
        header_layout.addWidget(title, 1)
        self.settings_button = secondary_button(QPushButton())
        self.settings_button.setProperty("quiet", True)
        self.settings_button.setIconSize(QSize(20, 20))
        self.settings_button.setAccessibleName("Configuración")
        self.settings_button.setToolTip("Configuración")
        self.settings_menu = QMenu(self.settings_button)
        self.settings_menu.setObjectName("chatMenu")
        self.settings_button.setMenu(self.settings_menu)
        self.settings_menu.addAction("Modelo y proveedor de IA…", self.open_ai_settings)
        self.settings_menu.addAction("Apariencia…", self.open_appearance)
        self.settings_menu.addAction("Instrucciones generales…", self.open_instructions)
        self.settings_menu.addSeparator()
        header_layout.addWidget(self.settings_button)
        self.sidebar_rail.provider_badge.clicked.connect(self.open_ai_settings)
        self.refresh_provider()
        layout.addWidget(header)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.chat_page = QWidget()
        self.pages.addWidget(self.chat_page)
        self.project_page = ProjectPage()
        self.project_page.created.connect(self.edit_project)
        self.project_page.opened.connect(self.show_project)
        self.project_page.back.connect(self.show_projects)
        self.project_page.edited.connect(self.edit_project)
        self.project_page.deleted.connect(self.delete_project)
        self.project_page.continuity_requested.connect(self.edit_continuity)
        self.project_page.document_requested.connect(self.link_project_document)
        self.project_page.document_unlinked.connect(self.unlink_project_document)
        self.project_page.pinned.connect(self.pin_project)
        self.project_page.chat_started.connect(self.new_project_chat)
        self.project_page.chat_opened.connect(self.open_chat)
        self.pages.addWidget(self.project_page)
        layout = QVBoxLayout(self.chat_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chat = QScrollArea()
        self.chat.setAccessibleName("Conversación")
        self.chat.setWidgetResizable(True)
        self.chat.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar = self.chat.verticalScrollBar()
        self.follow_latest = True
        bar.rangeChanged.connect(self.scroll_to_latest)
        bar.actionTriggered.connect(self.update_scroll_preference)
        canvas = QWidget()
        canvas.setObjectName("chatCanvas")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(22, 24, 22, 16)
        transcript = QWidget()
        transcript.setMaximumWidth(CHAT_WIDTH)
        self.transcript = QVBoxLayout(transcript)
        self.transcript.setContentsMargins(0, 0, 0, 0)
        self.transcript.setSpacing(20)
        self.transcript.addStretch()
        canvas_layout.addStretch(1)
        canvas_layout.addWidget(transcript, 100)
        canvas_layout.addStretch(1)
        self.chat.setWidget(canvas)
        layout.addWidget(self.chat, 1)

        self.activity_panel = None
        self.task_panel = None

        composer = QWidget()
        composer.setObjectName("composerPanel")
        composer.setMaximumWidth(CHAT_WIDTH)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(11, 9, 11, 8)
        composer_layout.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.attachments = AttachmentTray()
        self.attachments.problem.connect(self.show_problem)
        self.message = Composer()
        self.message.shortcut_source = self.composer_shortcuts
        self.message.pasted_paths.connect(self.attachments.add_paths)
        self.message.pasted_image.connect(self.attachments.add_clipboard_image)
        menu = self.attachments.menu
        self.project_document_action = menu.addAction("Usar documento del proyecto…", self.choose_project_document)
        self.project_document_action.setVisible(False)
        self.mcp_menu = menu.addMenu("MCP")
        self.mcp_menu.setObjectName("chatMenu")
        self.mcp_menu.aboutToShow.connect(self.refresh_mcp_menu)
        self.memory_menu = menu.addMenu("Memoria")
        self.memory_menu.setObjectName("chatMenu")
        self.memory_menu.addAction("Consultar recuerdos…").setData("Busca en la memoria: ")
        self.memory_menu.addAction("Consultar conclusiones…").setData("Consulta las conclusiones de la memoria: ")
        self.memory_menu.addSeparator()
        self.memory_menu.addAction("Ver y corregir recuerdos…", self.open_memory)
        self.auto_memory_action = self.memory_menu.addAction("Guardar recuerdos automáticamente")
        self.auto_memory_action.setCheckable(True)
        self.auto_memory_action.setChecked(automatic_memory_enabled())
        self.auto_memory_action.triggered.connect(self.set_automatic_memory)
        self.memory_menu.triggered.connect(self.draft_memory_query)
        self.reasoning_button = secondary_button(QPushButton("Automático"))
        self.reasoning_button.setObjectName("composerReasoning")
        self.reasoning_button.setProperty("quiet", True)
        self.reasoning_button.setAccessibleName("Razonamiento · Automático")
        self.reasoning_button.setToolTip("Razonamiento")
        reasoning_menu = QMenu(self.reasoning_button)
        self.reasoning_button.setMenu(reasoning_menu)
        reasoning_menu.setObjectName("chatMenu")
        self.reasoning_modes = QActionGroup(reasoning_menu)
        for mode, value, tip in (
            ("Automático", None, "Usa el ajuste habitual del modelo."),
            ("Rápido", False, "Pide una respuesta directa."),
            ("Activado", True, "Pide que el modelo razone antes de responder."),
        ):
            action = reasoning_menu.addAction(mode)
            action.setCheckable(True)
            self.reasoning_modes.addAction(action)
            action.setChecked(value is None)
            action.setData(value)
            action.setToolTip(tip)
        reasoning_menu.setToolTipsVisible(True)
        self.reasoning_modes.triggered.connect(self.update_reasoning_mode)
        menu.aboutToShow.connect(self.update_composer_menu)
        menu.addSeparator()
        self.skills_menu = menu.addMenu("Skills")
        self.skills_menu.setObjectName("chatMenu")
        self.skills_menu.aboutToShow.connect(self.refresh_skills_menu)
        menu.addAction("Instrucciones generales…", self.open_instructions)
        self.settings_menu.addAction("Servidores MCP…", self.open_mcp)
        self.settings_menu.addMenu(self.memory_menu)
        self.settings_menu.addMenu(self.skills_menu)
        self.settings_menu.aboutToShow.connect(self.update_composer_menu)
        self.send = QPushButton("Enviar")
        self.send.setObjectName("sendMessage")
        self.send.clicked.connect(self.enviar)
        self.message.submitted.connect(self.enviar)
        row.addWidget(self.attachments.add_button)
        row.addStretch()
        row.addWidget(self.message.expand_button)
        row.addWidget(self.reasoning_button)
        row.addWidget(self.send)
        composer_layout.addWidget(self.attachments)
        composer_layout.addWidget(self.message)
        composer_layout.addLayout(row)

        footer = QHBoxLayout()
        footer.setContentsMargins(22, 0, 22, 0)
        footer.addStretch(1)
        footer.addWidget(composer, 100)
        footer.addStretch(1)
        self.problem = QLabel()
        self.problem.setObjectName("chatStatus")
        self.problem.setTextFormat(Qt.TextFormat.PlainText)
        self.problem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)
        layout.addLayout(footer)
        self.refresh_appearance()
        self.chat_min_width = max(340, header.minimumSizeHint().width())
        conversation.setMinimumWidth(self.chat_min_width)
        self.toggle_history(True)
        self.refresh_history()
        self.refresh_projects()
        if self.history is None:
            self.show_problem("No se pudo abrir el historial. Los mensajes de esta sesión no se guardarán.")
        self.message.setFocus()
        if use_tray:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip("StoneBot")
            menu = QMenu(self)
            menu.setObjectName("chatMenu")
            menu.addAction("Abrir StoneBot", self.restore_window)
            menu.addAction("Salir", self.request_exit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.restore_window()

    def restore_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def request_exit(self):
        self.exit_requested = True
        if self.thread is not None:
            self.tray.setToolTip("StoneBot · esperando a que termine el turno")
            self.restore_window()
        else:
            self.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "message"):
            self.message.fit_height(self.message.document().size())

    def toggle_history(self, visible):
        self.sidebar_rail.set_expanded(visible)
        self.history_button.setToolTip(("Ocultar" if visible else "Mostrar") + " barra lateral (Ctrl+Shift+S)")
        self.history_splitter.setHandleWidth(6 if visible else 0)
        self.history_splitter.handle(1).setEnabled(visible)
        self.setMinimumWidth(self.sidebar_rail.minimumWidth() + self.chat_min_width + self.history_splitter.handleWidth())
        if visible:
            self.restore_history_width()
        else:
            width = self.sidebar_rail.minimumWidth()
            self.history_splitter.setSizes([width, self.history_splitter.width() - width])

    def search_sidebar(self):
        if self.history_panel.isHidden():
            self.history_button.setChecked(True)
            self.history_panel.show_search()
        else:
            self.history_panel.toggle_search()

    def restore_history_width(self):
        available = self.history_splitter.width() - self.history_splitter.handleWidth()
        width = min(self.history_width, max(self.sidebar_rail.minimumWidth(), available - self.chat_min_width))
        self.history_splitter.setSizes([width, max(self.chat_min_width, available - width)])

    def remember_history_width(self, _position, _index):
        if not self.history_panel.isHidden():
            self.history_width = self.history_splitter.sizes()[0]

    def showEvent(self, event):
        super().showEvent(event)
        if not self.exit_requested:
            QApplication.instance().installEventFilter(self)
        if QApplication.platformName() == "windows":
            apply_native_caption(self, self.appearance["background"])
        if not self.history_panel.isHidden():
            self.restore_history_width()

    def refresh_history(self, _query=None):
        if self.history is not None:
            try:
                query = self.history_panel.search.text()
                chats = self.history.project_chats() if self.projects and not query.strip() else None
                self.history_panel.fill(self.history.find(query), self.chat_id, chats)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.show_problem("No se pudo leer el historial.")

    def new_chat(self):
        self.open_chat(None)
        self.history_panel.search.clear()

    def open_chat(self, chat_id):
        if self.thread is not None:
            return
        if chat_id is not None and chat_id == self.chat_id:
            self.show_chat_page()
            return
        try:
            saved = self.history.messages(chat_id) if self.history is not None and chat_id is not None else []
            self.project = self.history.chat_project(chat_id) if self.history is not None and chat_id is not None else None
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No se pudo abrir la conversación.")
            return
        self.render_chat(chat_id, saved)
        if self.project:
            self.history_panel.expand_project(self.project["id"])
        self.show_chat_page()

    def show_chat_page(self):
        self.pages.setCurrentWidget(self.chat_page)
        self.header_title.setText(f"StoneBot  /  {self.project['name']}" if self.project else "StoneBot")
        self.project_document_action.setVisible(self.project is not None)
        self.message.setFocus()

    def refresh_projects(self):
        chats = {}
        if self.history is not None:
            try:
                self.projects = self.history.projects()
                chats = self.history.project_chats() if self.projects else {}
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.show_problem("No se pudieron leer los proyectos.")
        self.history_panel.fill_projects(self.projects, chats)

    def show_projects(self):
        if self.thread is None:
            self.refresh_projects()
            self.project_page.show_projects(self.projects)
            self.pages.setCurrentWidget(self.project_page)
            self.header_title.setText("Proyectos")

    def show_project(self, project_id):
        if self.thread is not None or self.history is None:
            return
        project = next((item for item in self.projects if item["id"] == project_id), None)
        if project is None:
            return
        try:
            chats = self.history.find(project_id=project_id)
            documents = self.history.project_documents(project_id)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Proyectos", str(exc))
            return
        self.project_page.show_project(project, chats, documents)
        self.history_panel.expand_project(project_id)
        self.pages.setCurrentWidget(self.project_page)
        self.header_title.setText(f"Proyectos  /  {project['name']}")

    def edit_project(self, project_id=None):
        if self.history is None:
            QMessageBox.warning(self, "Proyectos", "El historial local no está disponible.")
            return
        project = next((item for item in self.projects if item["id"] == project_id), None)
        dialog = ProjectDialog(self, project)
        dialog.setStyleSheet(dialog_style(self.appearance))
        while dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                name, description, instructions, folder = dialog.fields()
                if folder:
                    if not Path(folder).is_absolute() or folder.startswith(("\\\\", "//")):
                        raise ValueError("Elige una carpeta local con ruta absoluta.")
                    folder = check_path(folder)
                    if folder.startswith(("\\\\", "//")) or not Path(folder).is_dir():
                        raise ValueError("La carpeta local no está disponible.")
                saved = self.history.save_project(name, description, instructions, folder, project_id)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                QMessageBox.warning(dialog, "Proyectos", str(exc))
            else:
                self.refresh_projects()
                if self.project and self.project["id"] == saved:
                    self.project = next(item for item in self.projects if item["id"] == saved)
                self.show_project(saved)
                return

    def edit_continuity(self, project_id):
        project = next((item for item in self.projects if item["id"] == project_id), None)
        if project is None or self.thread is not None:
            return
        text, accepted = QInputDialog.getMultiLineText(
            self, "Punto de continuidad", "¿En qué te quedaste y qué sigue?", project["continuity"],
        )
        if accepted:
            try:
                self.history.save_continuity(project_id, text)
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Proyectos", str(exc))
                return
            if self.project and self.project["id"] == project_id:
                self.project["continuity"] = text.strip()
            self.refresh_projects()
            self.show_project(project_id)

    def pin_project(self, project_id, pinned):
        try:
            self.history.pin_project(project_id, pinned)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Proyectos", str(exc))
            return
        self.refresh_projects()
        self.show_project(project_id)

    def delete_project(self, project_id):
        if self.history is None or self.thread is not None:
            return
        project = next((item for item in self.projects if item["id"] == project_id), None)
        if project is None:
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Eliminar proyecto")
        dialog.setStyleSheet(dialog_style(self.appearance))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"¿Eliminar «{project['name']}»?")
        dialog.setInformativeText("Sus chats quedarán en Recientes y tus archivos seguirán en su carpeta.")
        remove = dialog.addButton("Eliminar", QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        confirmed = dialog.clickedButton() is remove
        dialog.deleteLater()
        if not confirmed:
            return
        try:
            self.history.delete_project(project_id)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            QMessageBox.warning(self, "Eliminar proyecto", "No se pudo eliminar el proyecto.")
            return
        if self.project and self.project["id"] == project_id:
            self.project = None
            self.attachments.clear_project_documents()
            if self.pages.currentWidget() is self.chat_page:
                self.show_chat_page()
        if self.pages.currentWidget() is self.project_page:
            self.show_projects()
        else:
            self.refresh_projects()
        self.refresh_history()

    def link_project_document(self, project_id):
        project = next((item for item in self.projects if item["id"] == project_id), None)
        if project is None or self.history is None or self.thread is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Vincular archivo", project["folder"], FILE_FILTER)
        if not path:
            return
        try:
            self.history.link_project_document(project_id, str(attachment_path(path)))
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Documentos del proyecto", str(exc))
            return
        self.show_project(project_id)

    def unlink_project_document(self, project_id, document_id):
        if self.history is None or self.thread is not None:
            return
        try:
            self.history.unlink_project_document(project_id, document_id)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Documentos del proyecto", str(exc))
            return
        self.show_project(project_id)

    def choose_project_document(self):
        if self.project is None or self.history is None or self.thread is not None:
            return
        try:
            documents = self.history.project_documents(self.project["id"])
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No pude abrir la lista de documentos del proyecto.")
            return
        if not documents:
            self.show_problem("Abre la ficha del proyecto y usa Documentos → Vincular archivo.")
            return
        names = [Path(path).name for _, path in documents]
        choices = {name if names.count(name) == 1 else path: (did, name)
                   for (did, path), name in zip(documents, names)}
        choice, accepted = QInputDialog.getItem(self, "Usar documento del proyecto", "Archivo", list(choices), editable=False)
        if not accepted:
            return
        self.attach_project_document(*choices[choice])

    def attach_project_document(self, document_id, name):
        if all(file.get("project_document") != document_id for file in self.attachments.files):
            self.attachments.add_file({"name": " ".join(name.split()), "project_document": document_id})
            self.message.setFocus()

    def start_project_draft(self, project_id):
        draft = self.message.toPlainText()
        files = self.attachments.files.copy()
        self.new_project_chat(project_id)
        self.message.setPlainText(draft)
        self.message.moveCursor(QTextCursor.MoveOperation.End)
        for file in files:
            self.attachments.add_file(file)

    def new_project_chat(self, project_id):
        if self.thread is None:
            self.project = next((item for item in self.projects if item["id"] == project_id), None)
            self.render_chat(None, [])
            self.show_chat_page()

    def move_chat_to_project(self, chat_id):
        self.refresh_projects()
        choices = {"Sin proyecto": None}
        for project in self.projects:
            title = project["name"]
            while title in choices:
                title += f" · {project['id']}"
            choices[title] = project["id"]
        title, ok = QInputDialog.getItem(self, "Mover conversación", "Proyecto", list(choices), editable=False)
        if ok:
            try:
                self.history.move_chat(chat_id, choices[title])
                if chat_id == self.chat_id:
                    self.project = self.history.chat_project(chat_id)
                    self.show_chat_page()
                self.refresh_projects()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Proyectos", str(exc))

    def render_chat(self, chat_id, saved, *, keep_activity=False):
        self.chat_id = chat_id
        self.task = None
        self.task_panel = None
        self.messages = [{"role": "system", "content": SYSTEM}, *saved]
        self.message.clear()
        self.attachments.clear()
        if keep_activity and self.activity_panel is not None:
            self.transcript.removeWidget(self.activity_panel)
        else:
            self.activity_panel = None
        self.problem.hide()
        self.follow_latest = True
        for _ in range(self.transcript.count() - 1):
            item = self.transcript.takeAt(0)
            if (panel := item.widget()) is not None:
                panel.hide()
                panel.deleteLater()
                continue
            row = item.layout()
            while row.count():
                widget = row.takeAt(0).widget()
                if widget is not None:
                    widget.hide()
                    widget.deleteLater()
            row.deleteLater()
        for index, message in enumerate(saved):
            self.append_message(message["content"], user=message["role"] == "user",
                                created=message["created"], index=index, attachments=message.get("attachments"))
        if self.activity_panel is not None:
            self.transcript.insertWidget(self.transcript.count() - 1, self.activity_panel)
        elif chat_id is not None and self.history is not None:
            try:
                self.task = self.history.task(chat_id)
                if self.task is not None:
                    changed = upgrade_task(self.task)
                    if self.task["status"] == "running":
                        changed = True
                        self.task["status"] = "interrupted"
                        for step in self.task["steps"]:
                            if step["status"] == "running":
                                step["status"] = "exception"
                    if changed:
                        self.history.save_task(chat_id, self.task)
                    panel = ActivityPanel()
                    self.task_panel = panel
                    self.transcript.insertWidget(self.transcript.count() - 1, panel)
                    self.show_task_progress(panel, self.task)
                    self.update_task_correction(panel, self.task)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.show_problem("No se pudo recuperar el estado de la tarea.")
        self.refresh_history()
        self.message.setFocus()

    def rename_chat(self, chat_id, title):
        try:
            self.history.rename(chat_id, title)
            self.refresh_history()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No se pudo renombrar la conversación.")

    def delete_chat(self, chat_id):
        try:
            self.history.delete(chat_id)
            if chat_id == self.chat_id:
                self.new_chat()
            self.refresh_history()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No se pudo eliminar la conversación.")

    def save_message(self, role, text, created, attachments=None, *, task=None):
        message = {"role": role, "content": text, "created": created}
        if attachments:
            message["attachments"] = attachments
        self.messages.append(message)
        if role == "user":
            self.history_write_ok = True
        if self.history is not None and self.history_write_ok:
            try:
                self.chat_id = self.history.append(self.chat_id, role, text, created=created,
                                                   attachments=attachments, task=task,
                                                   project_id=self.project["id"] if self.project else None)
                self.refresh_history()
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.history_write_ok = False
                self.show_problem("No se pudo guardar el mensaje en el historial.")

    def show_problem(self, message):
        self.problem.setText(message)
        self.problem.show()

    def open_diagnostics(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Diagnóstico de StoneBot")
        dialog.setStyleSheet(dialog_style(self.appearance))
        newest_first = "\n".join(reversed(read_log().splitlines()))
        text = QPlainTextEdit(newest_first or "Todavía no hay eventos de diagnóstico.")
        text.setReadOnly(True)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text)
        dialog.resize(680, 420)
        dialog.exec()

    def refresh_provider(self):
        provider = PROVIDERS[self.ai.provider]
        self.sidebar_rail.set_provider(provider, self.ai.model)
        self.header_title.setToolTip(f"{provider} · {self.ai.model}")
        self.header_title.setAccessibleDescription(f"{provider}, modelo {self.ai.model}")

    def open_ai_settings(self):
        if self.thread is not None:
            return
        dialog = AISettingsDialog(self, self.appearance, self.ai)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ai = dialog.config
            self.refresh_provider()
        dialog.deleteLater()

    def open_appearance(self):
        AppearanceDialog(self, self.appearance, self.change_appearance).exec()

    def change_appearance(self, theme):
        try:
            save_appearance(theme)
        except (ValueError, OSError, RuntimeError):
            QMessageBox.warning(self, "Apariencia", "No se pudo guardar la apariencia.")
            return False
        self.appearance = theme
        self.refresh_appearance()
        return True

    def refresh_appearance(self):
        theme = self.appearance
        apply_palette(theme)
        self.centralWidget().setStyleSheet(chat_style(theme))
        self.message.set_theme(theme)
        icon_color = QColor(readable_text(theme["background"]))
        self.history_panel.refresh_icons(icon_color)
        self.sidebar_rail.refresh_icons(icon_color)
        self.settings_button.setIcon(sidebar_icon("settings", icon_color))
        for bubble in self.chat.findChildren(ChatText, "userMessage"):
            bubble.highlights.set_link_background(theme["user_message"])
            self.fit_bubble(bubble)
        for bubble in self.chat.findChildren(MarkdownText):
            bubble.set_theme(theme)
        if self.mcp_dialog is not None:
            self.mcp_dialog.set_appearance(theme)
        if QApplication.platformName() == "windows":
            for window in QApplication.topLevelWidgets():
                if window.isVisible() and self.owns_caption(window):
                    apply_native_caption(window, theme["background"])

    def owns_caption(self, window):
        if window is self:
            return True
        if isinstance(window, QDialog):
            parent = window.parentWidget()
            while parent is not None:
                if parent is self:
                    return True
                parent = parent.parentWidget()
        return False

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Show and watched is not self and QApplication.platformName() == "windows"
                and self.owns_caption(watched)):
            apply_native_caption(watched, self.appearance["background"])
        return super().eventFilter(watched, event)

    def mcp_manager(self):
        if self.mcp_dialog is None:
            self.mcp_dialog = McpDialog(self, memory=self.memory)
            self.mcp_dialog.connection_changed.connect(self.pool.invalidate)
            self.mcp_dialog.set_appearance(self.appearance)
        return self.mcp_dialog

    def open_mcp(self):
        manager = self.mcp_manager()
        manager.reload()
        manager.exec()

    def refresh_mcp_menu(self):
        self.mcp_manager().quick_switches(self.mcp_menu, self.show_problem, idle=self.thread is None)

    def open_skills(self):
        dialog = SkillsDialog(self, self.appearance)
        dialog.exec()
        dialog.deleteLater()

    def open_instructions(self):
        try:
            instructions = load_instructions()
            dialog = QInputDialog(self)
            dialog.setWindowTitle("Instrucciones generales")
            dialog.setLabelText("Preferencias para todas las conversaciones. El idioma predeterminado es español.")
            dialog.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
            dialog.setTextValue(instructions)
            dialog.setOkButtonText("Guardar")
            dialog.setCancelButtonText("Cancelar")
            dialog.setStyleSheet(dialog_style(self.appearance))
            dialog.resize(540, 260)
            try:
                while dialog.exec():
                    try:
                        save_instructions(dialog.textValue())
                    except (OSError, ValueError, RuntimeError) as exc:
                        QMessageBox.warning(self, "Instrucciones generales", str(exc))
                    else:
                        break
            finally:
                dialog.deleteLater()
        except (OSError, ValueError, RuntimeError):
            self.show_problem("No se pudieron abrir las instrucciones generales.")

    def update_composer_menu(self):
        self.memory_menu.setEnabled(not self.attachments.files)
        attached_chat = has_chat_attachments(self.messages)
        self.memory_menu.setTitle("Memoria · en un chat nuevo" if attached_chat else "Memoria")

    def update_reasoning_mode(self, action):
        self.reasoning_button.setText(action.text())
        self.reasoning_button.setAccessibleName(f"Razonamiento · {action.text()}")

    def refresh_skills_menu(self):
        self.skills_menu.clear()
        try:
            installed, _ = local_skills.discover()
            names = [name for name in installed if local_skills.enabled(name)]
        except (OSError, ValueError, RuntimeError):
            names = []
        for name in names:
            self.skills_menu.addAction(name, lambda _checked=False, value=name: self.draft_skill(value))
        if names:
            self.skills_menu.addSeparator()
        self.skills_menu.addAction("Administrar Skills…", self.open_skills)

    def draft_skill(self, name):
        self.message.moveCursor(QTextCursor.MoveOperation.Start)
        self.message.insertPlainText(f"Usa la Skill «{name}». ")
        self.message.moveCursor(QTextCursor.MoveOperation.End)
        self.message.setFocus()

    def composer_shortcuts(self, symbol):
        if symbol == "/":
            for keyword, label, takes_text in COMPOSER_COMMANDS:
                yield f"{keyword} · {label}", keyword + (" " if takes_text else ""), None
        elif symbol == "@":
            yield "Adjuntar archivos…", "", self.attachments.choose
            if self.project and self.history:
                try:
                    documents = self.history.project_documents(self.project["id"])
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    documents = []
                names = [Path(path).name for _, path in documents]
                for (document_id, _), name in zip(documents, names):
                    label = f"{name} · Documento del proyecto"
                    yield (label if names.count(name) == 1 else f"{label} {document_id}"), "", (
                        lambda did=document_id, name=name: self.attach_project_document(did, name)
                    )
            if not any("project_document" in file for file in self.attachments.files):
                titles = [project["name"] for project in self.projects]
                for project, title in zip(self.projects, titles):
                    label = f"{title} · Proyecto"
                    yield (label if titles.count(title) == 1 else f"{label} {project['id']}"), "", (
                        lambda pid=project["id"]: self.start_project_draft(pid)
                    )
        elif symbol == "#":
            if not self.attachments.files and not self.task:
                yield "Adjuntar un archivo para referenciarlo…", "", self.attachments.choose
            for file in self.attachments.files:
                yield f"{file['name']} · Adjunto", f"«{file['name']}» ", None
            if self.task:
                objective = " ".join(self.task["objective"].split())
                title = self.message.fontMetrics().elidedText(objective, Qt.TextElideMode.ElideRight, 225)
                yield f"Tarea actual · {title}", f"tarea «{objective}» ", None
        elif symbol == ">":
            yield "Adjuntar archivos…", "", self.attachments.choose
            if self.project:
                yield "Usar documento del proyecto…", "", self.choose_project_document
            yield "Buscar conversaciones", "", self.search_sidebar
            yield "Abrir proyectos", "", self.show_projects
            yield "Ver y corregir recuerdos…", "", self.open_memory
            yield "Administrar MCP…", "", self.open_mcp
        elif symbol == "!" and sys.platform == "win32":
            yield "Abrir PowerShell", "", self.open_terminal

    def open_terminal(self):
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        try:
            subprocess.Popen([str(powershell), "-NoLogo", "-NoProfile"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        except OSError:
            self.show_problem("No pude abrir PowerShell.")

    def open_memory(self):
        if self.thread is None:
            dialog = MemoryDialog(self, self.appearance, self.memory)
            dialog.exec()
            dialog.deleteLater()

    def set_automatic_memory(self, enabled):
        try:
            save_automatic_memory(enabled)
        except OSError as exc:
            self.auto_memory_action.setChecked(not enabled)
            self.show_problem(str(exc))

    def draft_memory_query(self, action):
        prefix = action.data()
        if not prefix or self.thread is not None or self.attachments.files:
            return
        if has_chat_attachments(self.messages):
            if self.message.toPlainText().strip():
                buttons = QMessageBox.StandardButton
                if QMessageBox.question(self, "Consulta de memoria",
                                        "La consulta se preparará en un chat nuevo. ¿Descartar el borrador actual?",
                                        buttons.Yes | buttons.No, buttons.No) != buttons.Yes:
                    return
            self.new_chat()
        draft = self.message.toPlainText()
        if not draft.startswith(prefix):
            self.message.setPlainText(prefix + draft)
        self.message.moveCursor(QTextCursor.MoveOperation.End)
        self.message.setFocus()

    def append_message(self, text, *, user=False, created=None, index=None, attachments=None):
        if user:
            self.follow_latest = True
        row = QHBoxLayout()
        self.transcript.insertLayout(self.transcript.count() - 1, row)
        body = ChatText(self.chat) if user else MarkdownText(self.chat, text, self.appearance)
        body.setAccessibleName("Tú" if user else "StoneBot")
        body.setObjectName("userMessage" if user else "botMessage")
        if user:
            row.addStretch(1)
        card = QWidget()
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        row.addWidget(card, 4)
        if user:
            for file in attachments or ():
                column.addWidget(AttachmentCard(file))
            bubble_row = QHBoxLayout()
            bubble_row.setContentsMargins(0, 0, 0, 0)
            bubble_row.addStretch()
            bubble_row.addWidget(body, 1)
            column.addLayout(bubble_row)
        else:
            column.addWidget(body)
        body.ensurePolished()
        if user:
            body.document().setDocumentMargin(12)
            body.highlights.set_link_background(self.appearance["user_message"])
            body.setPlainText(text)
        actions = QHBoxLayout()
        actions.setContentsMargins(4, 0, 4, 0)
        if created is not None:
            try:
                stamp = datetime.fromtimestamp(created / 1_000_000_000)
            except (OSError, OverflowError, TypeError, ValueError):
                pass
            else:
                time_label = QLabel(stamp.strftime("%H:%M"))
                time_label.setObjectName("messageTime")
                time_label.setToolTip(stamp.strftime("%d/%m/%Y %H:%M:%S"))
                actions.addWidget(time_label)
        actions.addStretch()
        actions.addWidget(self.message_button("Copiar", lambda: QApplication.clipboard().setText(text)))
        if user and index is not None and self.chat_id is not None:
            actions.addWidget(self.message_button("Editar", lambda: self.edit_message(index)))
        column.addLayout(actions)
        if user:
            self.fit_bubble(body)
        self.scroll_to_latest()

    @staticmethod
    def message_button(title, action):
        button = secondary_button(QPushButton(title))
        button.setObjectName("messageAction")
        button.clicked.connect(lambda checked=False: action())
        return button

    def fit_bubble(self, body):
        width = max(map(body.fontMetrics().horizontalAdvance, body.toPlainText().split("\n")))
        body.setMaximumWidth(width + 26)
        card = body.parentWidget()
        preview_width = 280 if card.findChild(AttachmentCard) is not None else 0
        card.setMaximumWidth(max(width + 26, card.layout().minimumSize().width(), preview_width))

    def scroll_to_latest(self):
        if self.follow_latest:
            bar = self.chat.verticalScrollBar()
            bar.setValue(bar.maximum())

    def update_scroll_preference(self):
        bar = self.chat.verticalScrollBar()
        self.follow_latest = bar.sliderPosition() == bar.maximum()

    def enviar(self):
        texto = self.message.toPlainText().strip()
        files = self.attachments.files.copy()
        if (not texto and not files) or self.thread is not None:
            return
        words = texto.split(maxsplit=1)
        command = words[0] if words else ""
        if command == "!":
            self.show_problem("Escribe ! y elige Abrir PowerShell para ejecutar comandos en su propia ventana.")
            return
        if command == "/buscar":
            self.history_button.setChecked(True)
            self.history_panel.show_search()
            self.history_panel.search.setText(words[1] if len(words) > 1 else "")
            self.message.clear()
            return
        if command == "/resumir":
            texto = "Resume los puntos principales de " + (words[1] if len(words) > 1 else
                                                         "los adjuntos o la conversación, según esté disponible.")
        task = self.task
        active_task = task is not None and task["status"] not in {"completed", "cancelled"}
        has_attachments = bool(files) or has_chat_attachments(self.messages)
        document_query = files and all("project_document" in file for file in files)
        if (not files and task and task["status"] in {"completed", "paused"} and task.get("inventory_folder")
                and HIDDEN_MISTAKE.match(texto) and "?" not in texto):
            if self.correct_task(mistake=texto[:600]):
                self.message.clear()
            return
        inventory_task = (task is not None and ranking_count(task["objective"]) is not None
                          and not uses_mcp(task["objective"]))
        setup_request = is_setup_request(texto)
        ordinary = command not in (TASK_COMMANDS | COMMANDS) and not setup_request
        new_inventory = (
            ordinary and not has_attachments and (not active_task or inventory_task) and is_ranking_request(texto)
        )
        continue_inventory = (
            ordinary and not has_attachments and inventory_task and task["status"] != "cancelled"
            and inventory_followup(texto)
        )
        task_turn = (command in TASK_COMMANDS or new_inventory or continue_inventory
                     or (active_task and not inventory_task and ordinary and not document_query))
        if task_turn:
            if has_attachments:
                self.show_problem("Usa las tareas reanudables en una conversación sin adjuntos.")
                return
            if self.history is None:
                self.show_problem("El historial debe estar disponible para guardar la tarea.")
                return
            if new_inventory:
                task = new_task(texto)
            elif command == "/tarea":
                if len(words) < 2 or active_task:
                    self.show_problem("Escribe /tarea y el objetivo. Si ya hay una tarea pendiente, usa /cancelar primero.")
                    return
                if len(words[1]) > 4000:
                    self.show_problem("El objetivo admite hasta 4 000 caracteres.")
                    return
                task = new_task(words[1])
            elif command in {"/reanudar", "/cancelar"}:
                if not active_task:
                    self.show_problem("No hay una tarea pendiente en este chat. Vuelve a pedir lo que quieres hacer.")
                    return
                if command == "/cancelar" and len(words) != 1:
                    self.show_problem("Para cerrar la tarea pendiente, escribe solo /cancelar.")
                    return
            task = dict(task, status="cancelled" if command == "/cancelar" else "running")
        elif setup_request:
            if files:
                self.show_problem("Envía la configuración MCP por separado, sin adjuntos.")
                return
            self.message.clear()
            self.message.expand_button.setChecked(False)
            self.show_problem(self.mcp_manager().install_from_chat(texto))
            return
        if files and texto and texto.split(maxsplit=1)[0] in COMMANDS:
            self.show_problem("Envía ese comando por separado, sin adjuntos.")
            return

        self.message.clear()
        self.message.expand_button.setChecked(False)
        self.attachments.clear()
        texto = texto or "Revisa los archivos adjuntos."
        created = time.time_ns()
        self.problem.hide()
        self.save_message("user", texto, created, files, task=task if task_turn else None)
        self.append_message(texto, user=True, created=created, index=len(self.messages) - 2, attachments=files)
        if task_turn:
            if not self.history_write_ok:
                self.show_problem("No se inició la tarea porque el historial no pudo guardar el estado.")
                return
            self.task = task
            if task["status"] == "cancelled":
                self.render_chat(self.chat_id, self.messages[1:])
                return
        self.start_turn(task=task if task_turn else None)

    def edit_message(self, index):
        if self.thread is not None or self.chat_id is None or self.history is None:
            return
        if self.task is not None:
            self.show_problem("La regeneración está disponible en conversaciones sin una tarea guardada.")
            return
        original = self.messages[index + 1]["content"]
        dialog = QDialog(self)
        dialog.setWindowTitle("Editar mensaje")
        dialog.setStyleSheet(dialog_style(self.appearance))
        layout = QVBoxLayout(dialog)
        note = QLabel("Al generar una respuesta nueva, se reemplazarán este mensaje y los posteriores de esta conversación.")
        note.setWordWrap(True)
        layout.addWidget(note)
        editor = QPlainTextEdit(original)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setText("Regenerar")
        save.setEnabled(False)
        editor.textChanged.connect(lambda: save.setEnabled(
            bool(editor.toPlainText().strip()) and editor.toPlainText().strip() != original.strip()))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(520, 280)
        try:
            if dialog.exec():
                self.regenerate(index, editor.toPlainText().strip())
        finally:
            dialog.deleteLater()

    def regenerate(self, index, text):
        text = text.strip()
        if self.thread is not None or not text or self.chat_id is None or self.history is None:
            return
        if self.task is not None:
            self.show_problem("La regeneración está disponible en conversaciones sin una tarea guardada.")
            return
        if is_setup_request(text):
            self.show_problem("Envía la configuración MCP desde el cuadro de mensaje.")
            return
        saved = self.messages[1:]
        if (not 0 <= index < len(saved) or saved[index]["role"] != "user"
                or text == saved[index]["content"].strip()):
            return
        edited = {**saved[index], "content": text, "created": time.time_ns()}
        self.pending_edit = (self.chat_id, index, saved, edited)
        self.render_chat(self.chat_id, [*saved[:index], edited])
        self.start_turn()

    @staticmethod
    def show_task_progress(panel, task):
        panel.add_event(f"Objetivo · {task['objective']}")
        for step in task.get("plan", []):
            panel.add_event(f"Plan · {step}")
        for reason in task.get("coverage_notes", []):
            panel.add_event(reason)
        if pending := task.get("pending"):
            panel.add_event(f"Pendiente · {pending[:500]}")
        for step in task["steps"][-30:]:
            panel.add_event(step_caption(step))
        summary = panel.task_status(TASK_LABELS[task["status"]], len(task["steps"]))
        panel.add_event(summary)

    def update_task_correction(self, panel, task):
        if task["status"] in {"completed", "paused"} and task.get("message"):
            panel.correction_button.clicked.connect(self.correct_task)
            panel.correction_button.show()

    def correct_task(self, *, mistake=""):
        if self.thread is not None or self.task is None or self.task["status"] not in {"completed", "paused"}:
            return
        task = {**self.task, "project_id": self.project["id"] if self.project else None}
        try:
            saved = task_correction(task)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No se pudo abrir la corrección guardada.")
            return
        if mistake:
            saved = {**(saved or {"preference": "Omitir archivos y carpetas ocultos.",
                                 "method": "Comprobar cuáles están ocultos y excluirlos antes de contar.",
                                 "exclude_hidden": True}), "mistake": mistake}
        dialog = TaskCorrectionDialog(self, self.appearance, task, saved)
        try:
            while dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    save_task_correction(task, *dialog.fields())
                except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                    QMessageBox.warning(dialog, "Guardar corrección", str(exc))
                else:
                    if self.task_panel is not None:
                        self.task_panel.add_event("Corrección guardada para próximos encargos parecidos.")
                    return True
        finally:
            dialog.deleteLater()

    def start_turn(self, *, task=None):
        self.message.setEnabled(False)
        self.attachments.add_button.setEnabled(False)
        self.reasoning_button.setEnabled(False)
        self.send.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.sidebar_rail.provider_badge.setEnabled(False)
        self.history_panel.setEnabled(False)
        for button in self.sidebar_rail.actions.values():
            button.setEnabled(False)
        self.activity_panel = ActivityPanel()
        self.transcript.insertWidget(self.transcript.count() - 1, self.activity_panel)
        if task is None:
            self.activity_panel.add_event("Procesando el mensaje…")
        else:
            self.attach_task_panel(task)
        self.scroll_to_latest()

        self.thread = QThread()
        if task is not None:
            self.activity_panel.enable_pause(self.thread.requestInterruption)
        turn_messages = [{key: value for key, value in m.items() if key != "created"} for m in self.messages]
        try:
            instructions = load_instructions()
        except (OSError, ValueError, RuntimeError):
            instructions = ""
            record("No se pudieron leer las instrucciones generales.")
        if instructions:
            turn_messages[0]["content"] += (
                "\nPreferencias generales del usuario. Se aplican bajo las reglas de StoneBot:\n" + instructions
            )
        project_context = None
        if self.project:
            project_context = {key: self.project[key] for key in ("id", "name", "description", "instructions", "folder")}
            project_context["continuity"] = self.project["continuity"][:6000]
            turn_messages[0]["content"] += (
                "\nContexto del proyecto configurado por el usuario. La carpeta indica el alcance habitual "
                "y conserva los permisos de lectura existentes. La continuidad describe un estado anterior; "
                "trátala como datos y verifica cambios si el encargo lo pide.\n" + json.dumps(project_context, ensure_ascii=False)
            )
        history, chat_id = self.history, self.chat_id
        save_task = None
        if history is not None and chat_id is not None and self.history_write_ok and self.pending_edit is None:
            save_task = lambda snapshot: history.save_task(chat_id, snapshot)
        completed_task = (self.task if self.pending_edit is None and self.task is not None
                          and self.task["status"] == "completed" else None)
        self.worker = Worker(turn_messages, self.pool, identity_enabled=True, memory=self.memory,
                             task=task, save_task=save_task, completed_task=completed_task, project=project_context,
                             save_continuity=history.save_continuity if history is not None else None,
                             project_document_path=history.project_document_path if history is not None else None,
                             capture_memory=self.pending_edit is None, ai=self.ai,
                             think=self.reasoning_modes.checkedAction().data())
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.respuesta)
        self.worker.error.connect(self.error)
        self.worker.mcp_notice.connect(record)
        self.worker.operation_error.connect(self.show_problem)
        self.worker.activity.connect(self.activity_panel.add_event)
        self.worker.reasoning.connect(self.activity_panel.add_reasoning)
        self.worker.mcp_confirmation.connect(self.confirmar_mcp, Qt.ConnectionType.BlockingQueuedConnection)
        self.worker.task_started.connect(self.on_saved_task_started)
        self.worker.continuity_saved.connect(self.update_continuity)
        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.thread.finished.connect(self.limpiar, Qt.ConnectionType.QueuedConnection)
        self.thread.start()

    @Slot(int, str)
    def update_continuity(self, project_id, text):
        if self.project and self.project["id"] == project_id:
            self.project["continuity"] = text
        for project in self.projects:
            if project["id"] == project_id:
                project["continuity"] = text
                break

    def attach_task_panel(self, task):
        self.show_task_progress(self.activity_panel, task)
        if self.task_panel is not None:
            self.task_panel.hide()
            self.transcript.removeWidget(self.task_panel)
            self.task_panel.deleteLater()
        self.task_panel = self.activity_panel

    @Slot(object)
    def on_saved_task_started(self, task):
        self.task = task
        self.attach_task_panel(task)
        self.activity_panel.enable_pause(self.thread.requestInterruption)

    @Slot(object)
    def confirmar_mcp(self, request):
        dialog = QMessageBox(self)
        local = request.get("local", False)
        dialog.setWindowTitle("Guardar archivo Markdown" if local else "Confirmar operación MCP")
        dialog.setStyleSheet(dialog_style(self.appearance))
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("¿Guardar este archivo?" if local else f"¿Autorizar {request['tool']} en {request['server']}?")
        arguments = json.dumps(request["arguments"], indent=2, ensure_ascii=True)
        if local:
            dialog.setInformativeText(request["arguments"]["path"])
            dialog.setDetailedText(request["arguments"]["content"])
        elif len(arguments) <= 500:
            dialog.setInformativeText(arguments)
        else:
            dialog.setInformativeText("Revisa los argumentos en «Mostrar detalles» antes de autorizar.")
            dialog.setDetailedText(arguments)
        roles = QMessageBox.ButtonRole
        once = dialog.addButton("Permitir una vez", roles.AcceptRole)
        always = dialog.addButton("Permitir siempre", roles.ActionRole) if request.get("can_remember") else None
        deny = dialog.addButton("Denegar", roles.RejectRole)
        dialog.setDefaultButton(deny)
        dialog.setEscapeButton(deny)
        dialog.exec()
        clicked = dialog.clickedButton()
        request["approved"] = clicked is once or (always is not None and clicked is always)
        request["remember"] = bool(always is not None and clicked is always)

    def closeEvent(self, event):
        if self.tray is not None and not self.exit_requested:
            self.hide()
            event.ignore()
        elif self.thread is not None:
            event.ignore()
        else:
            QApplication.instance().removeEventFilter(self)
            if self.history_width != self.saved_history_width:
                try:
                    save_history_width(self.history_width)
                    self.saved_history_width = self.history_width
                except (OSError, RuntimeError, ValueError):
                    record("No se pudo guardar el ancho del historial.")
            self.pool.close()
            self.memory.close()
            if self.tray is not None:
                self.tray.hide()
                QTimer.singleShot(0, QApplication.instance().quit)
            super().closeEvent(event)

    def respuesta(self, texto):
        created = time.time_ns()
        if self.pending_edit is None:
            task = self.worker.task if self.worker is not None else None
            self.save_message("assistant", texto, created, task=task)
            if task is not None and not self.history_write_ok:
                task["status"] = "interrupted"
        else:
            chat_id, index, saved, edited = self.pending_edit
            if not texto.strip() or texto.strip() == "(Sin respuesta)":
                self.error(f"{PROVIDERS[self.ai.provider]} no generó una respuesta nueva. Se conservó la conversación original.")
                return
            answer = {"role": "assistant", "content": texto, "created": created}
            try:
                self.history.replace_from(chat_id, index, saved, edited, answer)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.error("No se pudo guardar la regeneración. Se conservó el historial guardado.")
                return
            self.pending_edit = None
            self.messages.append(answer)
            self.refresh_history()
        self.append_message(texto, created=created)

    def error(self, detalle):
        if self.worker is not None and self.worker.task is not None:
            self.worker.task_reply("paused", detalle)
            self.respuesta(detalle)
        if self.pending_edit is not None:
            chat_id, _, saved, _ = self.pending_edit
            self.pending_edit = None
            try:
                saved = self.history.messages(chat_id)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                pass
            self.render_chat(chat_id, saved, keep_activity=True)
        self.activity_panel.add_event(f"Error del turno · {detalle}")
        self.show_problem(detalle)

    @Slot()
    def limpiar(self):
        task = self.task if self.activity_panel is self.task_panel else None
        self.thread.wait()
        self.thread.deleteLater()
        self.worker = None
        self.thread = None
        if task is not None:
            self.activity_panel.finish_task(TASK_LABELS[task["status"]], len(task["steps"]),
                                            saved=self.history_write_ok)
            if self.history_write_ok:
                self.update_task_correction(self.activity_panel, task)
        elif not self.activity_panel.latest.startswith("Error del turno"):
            self.activity_panel.add_event("Turno finalizado.")
        self.message.setEnabled(True)
        self.attachments.add_button.setEnabled(True)
        self.reasoning_button.setEnabled(True)
        self.send.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.sidebar_rail.provider_badge.setEnabled(True)
        self.history_panel.setEnabled(True)
        for button in self.sidebar_rail.actions.values():
            button.setEnabled(True)
        self.message.setFocus()
        if self.exit_requested:
            self.close()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        lock_path = data_path("assistant.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(lock_path))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(None, "StoneBot", "No se pudo iniciar otra instancia de StoneBot. "
                                    "Si ya está abierto, usa el icono SB de la bandeja.")
            return 1
    except (OSError, RuntimeError, ValueError) as exc:
        QMessageBox.warning(None, "StoneBot", str(exc))
        return 1
    use_tray = sys.platform == "win32" and QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not use_tray)
    try:
        window = StoneBot(use_tray=use_tray)
        try:
            window.show()
            return app.exec()
        finally:
            window.memory.close()
    finally:
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())

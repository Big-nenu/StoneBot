import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

from ai_provider import AISettings, DEFAULT_MODEL, PROVIDERS, load_ai
from ai_settings_ui import AISettingsDialog
from local_files import RESULT_HEADER
from local_files_ui import LocalFilesDialog
from appearance import (
    AppearanceDialog, apply_palette, dialog_style, load_appearance, readable_text, save_appearance,
    secondary_button, settings_style,
)
from attachments import FILE_FILTER, attachment_path, has_chat_attachments
from chat_markdown import CopyButton, MarkdownText
from chat_preferences import automatic_memory_enabled, load_instructions, save_automatic_memory, save_instructions
from chat_titles import generate_title
from chat_ui import (
    ActivityPanel, AttachmentCard, AttachmentTray, ChatBottomFade, ChatText, ChatTranscript, Composer, ComposerPanel,
    MessageCard, PopupButton, chat_style, style_chat_menu,
)
from diagnostics import record
from diagnostics_ui import DiagnosticsDialog
from extension_ui import Toggle
from experiences import save_task_correction, task_correction
from folder_inventory import HIDDEN_MISTAKE, inventory_followup, is_ranking_request, ranking_count, uses_mcp
from greetings import choose_greeting, format_greeting, greeting_settings
from history import History
from history_ui import SEARCH_SHORTCUT, HistoryPanel, SidebarPreview, SidebarRail, load_sidebar_pinned, save_sidebar_pinned, sidebar_icon
import local_skills
from mcp_client import data_path
from mcp_pool import McpPool
from mcp_setup import is_setup_request
from mcp_ui import McpDialog
from memory_ui import MemoryDialog
from projects_ui import ProjectDialog, ProjectPage
from stonebot_engine.safety import check_path
from sprites import SpriteLabel, SpritePlayer
from stonewave_memory import StoneWaveMemory
from tasks import LABELS as TASK_LABELS, new_task, step_caption, upgrade_task
from tasks_ui import TaskCorrectionDialog
from win_caption import apply_native_caption
from PySide6.QtCore import QEasingCurve, QEvent, QIODevice, QSettings, QVariantAnimation, QSaveFile, QLockFile, QSignalBlocker, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QActionGroup, QColor, QIcon, QKeySequence, QShortcut, QTextCursor, QTextDocument, QPdfWriter
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget, QWidgetAction,
)
from turn_worker import COMMANDS, SYSTEM, TASK_COMMANDS, Worker


MODEL = DEFAULT_MODEL
ICON_PATH = Path(__file__).resolve().parent / "assets" / "stonebot-icon.ico"
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
    title_ready = Signal(int, object, str)

    def __init__(self, *, use_tray=False):
        super().__init__()
        self.setWindowTitle("StoneBot")
        icon_path = ICON_PATH if sys.platform == "win32" else ICON_PATH.with_suffix(".png")
        icon = QIcon(str(icon_path))
        QApplication.setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.resize(1100, 740)
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
        self.inline_cancel = None
        self.chat_id = None
        self.task = None
        self.history_write_ok = True
        self.pending_edit = None
        self.last_regenerate = None
        self.stopping_turn = False
        self.pending_titles = set()
        self.title_ready.connect(self.finish_chat_title)
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
        self.history_panel = HistoryPanel()
        self.history_panel.new_chat.connect(self.new_chat)
        self.history_panel.opened.connect(self.open_chat)
        self.history_panel.renamed.connect(self.rename_chat)
        self.history_panel.deleted.connect(self.delete_chat)
        self.history_panel.pin_requested.connect(self.pin_chat)
        self.history_panel.searched.connect(self.refresh_history)
        self.history_panel.diagnostics.connect(self.open_diagnostics)
        self.history_panel.projects_requested.connect(self.show_projects)
        self.history_panel.project_opened.connect(self.show_project)
        self.history_panel.project_deleted.connect(self.delete_project)
        self.history_panel.transfer_requested.connect(self.transfer_chat)
        self.history_panel.move_requested.connect(self.move_chat_to_project)
        self.sidebar_rail = SidebarRail(self.history_panel)
        self.sidebar_rail.actions["new"].clicked.connect(self.history_panel.new_chat)
        self.sidebar_rail.actions["search"].clicked.connect(self.search_sidebar)
        QShortcut(QKeySequence(SEARCH_SHORTCUT), self).activated.connect(self.search_sidebar)
        self.sidebar_rail.actions["projects"].clicked.connect(self.history_panel.projects_requested)
        self.sidebar_rail.actions["diagnostics"].clicked.connect(self.history_panel.diagnostics)
        sidebar_slot = QWidget()
        main_layout.addWidget(sidebar_slot)
        conversation = QWidget()
        main_layout.addWidget(conversation, 1)
        self.sidebar_preview = SidebarPreview(central, sidebar_slot, self.sidebar_rail)
        layout = QVBoxLayout(conversation)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 12, 22, 12)
        header_layout.setSpacing(8)
        title = self.header_title = QLabel("StoneBot")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        title.setObjectName("chatTitle")
        self.history_button = self.sidebar_rail.toggle
        self.history_button.setShortcut("Ctrl+Shift+S")
        self.history_button.setChecked(load_sidebar_pinned())
        self.history_button.toggled.connect(self.toggle_history)
        header_layout.addWidget(title, 1)
        settings_shortcut = "Ctrl+,"
        self.settings_button = secondary_button(PopupButton(settings_shortcut, right=True))
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setShortcut(settings_shortcut)
        self.settings_button.setProperty("quiet", True)
        self.settings_button.setIconSize(QSize(20, 20))
        self.settings_button.setAccessibleName("Configuración")
        self.settings_button.setToolTip(f"Configuración ({settings_shortcut})")
        self.settings_menu = self.settings_button.menu()
        self.settings_menu.addAction("Modelo y proveedor de IA…", self.open_ai_settings)
        self.settings_menu.addAction("Apariencia…", self.open_appearance)
        self.settings_menu.addAction("Instrucciones generales…", self.open_instructions)
        self.settings_menu.addAction("Archivos locales…", self.open_local_files)
        self.chat_options = secondary_button(PopupButton(right=True))
        self.chat_options.setProperty("quiet", True)
        self.chat_options.setAccessibleName("Opciones de conversación")
        self.chat_options.setToolTip("Opciones de conversación")
        self.chat_options.setIconSize(self.settings_button.iconSize())
        self.chat_options.about_to_popup.connect(self.prepare_chat_options)
        self.chat_options.hide()
        header_layout.addWidget(self.chat_options)
        header_layout.addWidget(self.settings_button)
        self.sidebar_rail.provider_badge.clicked.connect(self.open_ai_settings)
        self.refresh_provider()
        layout.addWidget(header)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.chat_page = QWidget()
        self.chat_page.setObjectName("chatPage")
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
        canvas_layout.setContentsMargins(22, 28, 22, 18)
        transcript = ChatTranscript()
        transcript.width_changed.connect(self.fit_bubbles)
        transcript.setMaximumWidth(CHAT_WIDTH)
        self.transcript = QVBoxLayout(transcript)
        self.transcript.setContentsMargins(0, 0, 0, 0)
        self.transcript.setSpacing(24)
        self.transcript.addStretch()
        canvas_layout.addStretch(1)
        canvas_layout.addWidget(transcript, 100)
        canvas_layout.addStretch(1)
        self.chat.setWidget(canvas)
        self.chat_fade = ChatBottomFade(self.chat, self.appearance["background"])
        self.welcome_top = QWidget()
        layout.addWidget(self.welcome_top, 1)
        self.welcome = QWidget()
        greeting = QVBoxLayout(self.welcome)
        greeting.setContentsMargins(22, 0, 22, 24)
        greeting.setSpacing(24)
        self.welcome_logo = SpriteLabel(220)
        greeting.addWidget(self.welcome_logo, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.greeting_profile = greeting_settings()
        self.avatar = SpritePlayer(self, reduced=self.greeting_profile.value("reduce_animations", False, type=bool))
        self.avatar.frame_changed.connect(self.welcome_logo.set_frame)
        self.greeting_phrase = choose_greeting(self.greeting_profile)
        self.greeting_label = QLabel()
        self.greeting_label.setObjectName("welcomeGreeting")
        self.greeting_label.setTextFormat(Qt.TextFormat.PlainText)
        self.greeting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.greeting_label.setWordWrap(True)
        self.update_greeting()
        greeting.addWidget(self.greeting_label)
        layout.addWidget(self.welcome)
        layout.addWidget(self.chat, 1)

        self.activity_panel = None
        self.partial_reply = None
        self.task_panel = None

        self.message = Composer()
        self.message.textChanged.connect(self.update_typing_expression)
        composer = ComposerPanel(self.message)
        composer.setMaximumWidth(CHAT_WIDTH)
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 7, 12, 10)
        composer_layout.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.attachments = AttachmentTray()
        self.attachments.problem.connect(self.show_problem)
        self.message.shortcut_source = self.composer_shortcuts
        self.message.pasted_paths.connect(self.attachments.add_paths)
        self.message.pasted_image.connect(self.attachments.add_clipboard_image)
        menu = self.attachments.menu
        self.mcp_menu = style_chat_menu(menu.addMenu("MCP"))
        self.mcp_menu.aboutToShow.connect(self.refresh_mcp_menu)
        self.memory_menu = style_chat_menu(QMenu("Memoria", self.settings_menu))
        self.memory_menu.addAction("Consultar recuerdos…").setData("Busca en la memoria: ")
        self.memory_menu.addAction("Consultar conclusiones…").setData("Consulta las conclusiones de la memoria: ")
        self.memory_menu.addSeparator()
        self.memory_menu.addAction("Ver y corregir recuerdos…", self.open_memory)
        self.auto_memory_action = self.memory_menu.addAction("Guardar recuerdos automáticamente")
        self.auto_memory_action.setCheckable(True)
        self.auto_memory_action.setChecked(automatic_memory_enabled())
        self.auto_memory_action.triggered.connect(self.set_automatic_memory)
        self.memory_menu.triggered.connect(self.draft_memory_query)
        self.reasoning_button = secondary_button(PopupButton("Automático", above=True, right=True))
        self.reasoning_button.setObjectName("composerReasoning")
        self.reasoning_button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.reasoning_button.setProperty("quiet", True)
        self.reasoning_button.setAccessibleName("Razonamiento · Automático")
        self.reasoning_button.setToolTip("Razonamiento")
        reasoning_menu = self.reasoning_button.menu()
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
        self.skills_menu = style_chat_menu(menu.addMenu("Skills"))
        self.skills_menu.aboutToShow.connect(self.refresh_skills_menu)
        menu.addSeparator()
        memory_row = QWidget()
        memory_row.setToolTip("Comparte la preferencia de memoria automática de StoneBot.")
        memory_layout = QHBoxLayout(memory_row)
        memory_layout.setContentsMargins(9, 3, 6, 3)
        memory_label = QLabel("Guardar recuerdos en este chat")
        memory_layout.addWidget(memory_label, 1)
        self.auto_memory_switch = Toggle(self.auto_memory_action.isChecked(), memory_label.text(),
                                         self.appearance["accent"], self.appearance["background"])
        self.auto_memory_switch.setToolTip(memory_row.toolTip())
        self.auto_memory_switch.toggled.connect(self.set_automatic_memory)
        memory_layout.addWidget(self.auto_memory_switch)
        self.auto_memory_menu_action = QWidgetAction(menu)
        self.auto_memory_menu_action.setText(memory_label.text())
        self.auto_memory_menu_action.setDefaultWidget(memory_row)
        self.auto_memory_menu_action.triggered.connect(self.auto_memory_switch.toggle)
        menu.addAction(self.auto_memory_menu_action)
        self.settings_menu.addAction("Extensiones…", self.open_mcp)
        self.settings_menu.addMenu(self.memory_menu)
        # El título de Memoria puede cambiar el ancho antes de calcular la posición.
        self.settings_button.about_to_popup.connect(self.update_memory_menu)
        self.settings_menu.aboutToShow.connect(self.update_memory_menu)
        self.send = QPushButton()
        self.send.setObjectName("sendMessage")
        self.send.setAccessibleName("Enviar")
        self.send.setToolTip("Enviar")
        self.send.setIconSize(QSize(20, 20))
        self.send.setFixedSize(40, 40)
        self.send.clicked.connect(self.send_or_stop)
        self.stop_shortcut = QShortcut(QKeySequence("Esc"), self)
        self.stop_shortcut.activated.connect(self.stop_turn)
        self.stop_shortcut.setEnabled(False)
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
        self.composer_panel = composer
        layout.addLayout(footer)
        self.welcome_bottom = QWidget()
        layout.addWidget(self.welcome_bottom, 1)
        self.composer_offset = QWidget()
        self.composer_offset.setFixedHeight(0)
        layout.addWidget(self.composer_offset)
        self.composer_transition = QVariantAnimation(self)
        self.composer_transition.setDuration(200)
        self.composer_transition.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.composer_transition.valueChanged.connect(self.composer_offset.setFixedHeight)
        self.set_welcome(True, greet=True)
        self.pages.currentChanged.connect(self.update_mascot_page)
        self.refresh_appearance()
        self.chat_min_width = max(340, header.minimumSizeHint().width())
        conversation.setMinimumWidth(self.chat_min_width)
        self.toggle_history(self.history_button.isChecked(), save=False)
        self.refresh_history()
        self.refresh_projects()
        if self.history is None:
            self.show_problem("No se pudo abrir el historial. Los mensajes de esta sesión no se guardarán.")
        self.message.setFocus()
        if use_tray:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
            self.tray.setToolTip("StoneBot")
            menu = style_chat_menu(QMenu(self))
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

    def toggle_history(self, expanded, *, save=True):
        self.sidebar_preview.set_pinned(expanded)
        self.setMinimumWidth(self.sidebar_preview.slot.width() + self.chat_min_width)
        if save:
            try:
                save_sidebar_pinned(expanded)
            except (OSError, RuntimeError, ValueError):
                record("No se pudo guardar el estado de la barra lateral.")

    def search_sidebar(self):
        if not self.history_panel.isEnabled():
            return
        self.history_button.setChecked(True)
        self.history_panel.show_search()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.exit_requested:
            QApplication.instance().installEventFilter(self)
        if QApplication.platformName() == "windows":
            apply_native_caption(self, self.appearance["background"])

    def refresh_history(self, _query=None):
        if self.history is not None:
            try:
                query = self.history_panel.search.text()
                chats = self.history.project_chats() if self.projects and not query.strip() else None
                self.history_panel.fill(self.history.find(query, include_metadata=True), self.chat_id, chats)
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
        self.schedule_chat_title(chat_id, saved)
        if self.project:
            self.history_panel.expand_project(self.project["id"])
        self.show_chat_page()

    def show_chat_page(self):
        self.pages.setCurrentWidget(self.chat_page)
        self.header_title.setText(f"StoneBot  /  {self.project['name']}" if self.project else "StoneBot")
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

    def prepare_chat_options(self):
        menu = self.chat_options.menu()
        menu.clear()
        with self.history.connect() as conn:
            row = conn.execute("SELECT title, pinned FROM chat WHERE id=?", (self.chat_id,)).fetchone()
        if row:
            self.history_panel.populate_chat_menu(menu, self.chat_id, *row)

    def transfer_chat(self, chat_id, title, kind):
        try:
            sections = [f"# {title}"]
            for message in self.history.messages(chat_id):
                role = "Tú" if message["role"] == "user" else "StoneBot"
                sections.append(f"## {role}")
                sections.append(message["content"])
                for attachment in message.get("attachments", ()):
                    sections.append("Adjunto: " + attachment["name"])
            transcript = "\n\n".join(sections) + "\n"
            if kind == "copy":
                QApplication.clipboard().setText(transcript)
                return
            filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title)[:100].strip(". ") or "Conversación"
            label = "Markdown" if kind == "md" else "PDF"
            dialog = QFileDialog(self, f"Exportar a {label}")
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setNameFilter(f"{label} (*.{kind})")
            dialog.setDefaultSuffix(kind)
            dialog.selectFile(f"{filename}.{kind}")
            dialog.setLabelText(QFileDialog.DialogLabel.Accept, "Exportar")
            dialog.setLabelText(QFileDialog.DialogLabel.Reject, "Cancelar")
            dialog.setStyleSheet(settings_style(self.appearance))
            try:
                if not dialog.exec():
                    return
                output = QSaveFile(dialog.selectedFiles()[0])
            finally:
                dialog.deleteLater()
            if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                raise OSError(output.errorString())
            if kind == "md":
                data = transcript.encode("utf-8")
                if output.write(data) != len(data):
                    raise OSError(output.errorString())
            else:
                document = QTextDocument()
                document.setMarkdown(transcript)
                writer = QPdfWriter(output)
                writer.setTitle(title)
                document.print_(writer)
                del writer
            if not output.commit():
                raise OSError(output.errorString())
        except (OSError, sqlite3.Error) as exc:
            self.show_problem(str(exc))

    def move_chat_to_project(self, chat_id):
        self.refresh_projects()
        choices = {"Sin proyecto": None}
        for project in self.projects:
            title = project["name"]
            while title in choices:
                title += f" · {project['id']}"
            choices[title] = project["id"]
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Mover conversación")
        dialog.setLabelText("Proyecto")
        dialog.setComboBoxItems(list(choices))
        dialog.setCancelButtonText("Cancelar")
        dialog.setStyleSheet(settings_style(self.appearance))
        accepted = dialog.exec()
        title = dialog.textValue()
        dialog.deleteLater()
        if accepted:
            try:
                self.history.move_chat(chat_id, choices[title])
                if chat_id == self.chat_id:
                    self.project = self.history.chat_project(chat_id)
                    self.show_chat_page()
                self.refresh_projects()
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Proyectos", str(exc))

    def update_mascot_page(self, *_):
        self.avatar.set_empty(self.pages.currentWidget() is self.chat_page and not self.welcome.isHidden())

    def set_welcome(self, empty, *, animate=False, greet=False):
        show_transition = animate and not self.welcome.isHidden() and self.chat_page.isVisible()
        offset = max(0, self.chat_page.height() - self.composer_panel.geometry().bottom() - 1)
        self.composer_transition.stop()
        self.composer_offset.setFixedHeight(offset if show_transition else 0)
        for widget in (self.welcome_top, self.welcome, self.welcome_bottom):
            widget.setVisible(empty)
        self.chat.setVisible(not empty)
        self.avatar.set_empty(empty, greet=greet)
        if show_transition:
            self.composer_transition.setStartValue(offset)
            self.composer_transition.setEndValue(0)
            self.composer_transition.start()

    def render_chat(self, chat_id, saved, *, keep_activity=False):
        if self.inline_cancel:
            self.inline_cancel()
        self.chat_id = chat_id
        self.set_welcome(not saved, greet=chat_id is None)
        self.chat_options.setVisible(chat_id is not None)
        self.last_regenerate = None
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

    def pin_chat(self, chat_id, pinned):
        try:
            self.history.pin_chat(chat_id, pinned)
            self.refresh_history()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.show_problem("No se pudo cambiar la fijación de la conversación.")

    def schedule_chat_title(self, chat_id, messages):
        if self.history is None or chat_id is None or not messages or messages[0]["role"] != "user":
            return
        first = messages[0]
        answer = next((item["content"] for item in messages if item["role"] == "assistant"
                       and item["content"].strip() not in {"", "(Sin respuesta)"}), None)
        key = (chat_id, first["created"])
        if answer is None or answer.startswith(RESULT_HEADER) or key in self.pending_titles:
            return
        try:
            if not self.history.title_pending(chat_id):
                return
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return
        ai = self.ai
        self.pending_titles.add(key)

        def work():
            title = generate_title(ai, first["content"])
            try:
                self.title_ready.emit(*key, title)
            except RuntimeError:
                pass  # La ventana se cerró mientras respondía el proveedor.

        Thread(target=work, daemon=True).start()

    @Slot(int, object, str)
    def finish_chat_title(self, chat_id, created, title):
        self.pending_titles.discard((chat_id, created))
        try:
            if self.history.finish_title(chat_id, created, title):
                self.refresh_history()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            record("No se pudo guardar el título automático.")

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
                                                   project_id=self.project["id"] if self.project else None,
                                                   automatic_title=self.chat_id is None and role == "user")
                self.chat_options.show()
                self.refresh_history()
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.history_write_ok = False
                self.show_problem("No se pudo guardar el mensaje en el historial.")

    def show_problem(self, message):
        self.problem.setText(message)
        self.problem.show()

    @Slot(str)
    def show_turn_warning(self, message):
        self.show_problem(message)
        self.avatar.warning(briefly=True)

    def open_diagnostics(self):
        dialog = DiagnosticsDialog(self, self.appearance)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

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

    def open_local_files(self):
        if self.thread is not None:
            return
        try:
            dialog = LocalFilesDialog(self, self.appearance)
        except (OSError, ValueError, RuntimeError) as exc:
            self.show_problem(str(exc))
            return
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def update_typing_expression(self):
        if self.message.toPlainText():
            self.avatar.typing()
        else:
            self.avatar.end_typing()

    def update_greeting(self):
        name = self.greeting_profile.value("name", "Luis", type=str)
        self.greeting_label.setText(format_greeting(self.greeting_phrase, name))

    def open_appearance(self):
        name = self.greeting_profile.value("name", "Luis", type=str)
        dialog = AppearanceDialog(self, self.appearance, self.change_appearance, user_name=name,
                                  reduce_animations=self.avatar.reduced)
        try:
            dialog.exec()
            updated = dialog.user_name.text().strip()
            reduced = dialog.reduce_animations.isChecked()
            if updated != name or reduced != self.avatar.reduced:
                self.greeting_profile.setValue("name", updated)
                self.greeting_profile.setValue("reduce_animations", reduced)
                self.greeting_profile.sync()
                if self.greeting_profile.status() != QSettings.Status.NoError:
                    QMessageBox.warning(self, "Apariencia", "No se pudo guardar tu nombre.")
                else:
                    self.update_greeting()
                    self.avatar.set_reduced(reduced)
        finally:
            dialog.deleteLater()

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
        self.history_panel.theme = theme
        self.auto_memory_switch.accent = theme["accent"]
        self.auto_memory_switch.surface = theme["background"]
        self.auto_memory_switch.update()
        apply_palette(theme)
        stylesheet = chat_style(theme)
        self.centralWidget().setStyleSheet(stylesheet)
        self.message.set_theme(theme, stylesheet)
        icon_color = QColor(readable_text(theme["background"]))
        self.history_panel.refresh_icons(icon_color)
        self.sidebar_rail.refresh_icons(icon_color)
        self.chat_options.setIcon(sidebar_icon("more", icon_color))
        self.settings_button.setIcon(sidebar_icon("settings", icon_color))
        self.refresh_send_button()
        self.chat_fade.background = theme["background"]
        self.chat_fade.update()
        for bubble in self.chat.findChildren(ChatText, "userMessage"):
            bubble.highlights.set_link_background(theme["user_message"])
        for bubble in self.chat.findChildren(MarkdownText):
            bubble.set_theme(theme)
        self.fit_bubbles()
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
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.Wheel):
            if isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
                self.avatar.user_activity()
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
        self.mcp_manager().open_section()

    def refresh_mcp_menu(self):
        self.mcp_manager().quick_switches(self.mcp_menu, self.show_problem, idle=self.thread is None)

    def open_skills(self):
        self.mcp_manager().open_section(skills=True)

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
            layout = dialog.layout()
            layout.setContentsMargins(24, 21, 24, 20)
            layout.setSpacing(14)
            title = QLabel("Instrucciones generales")
            title.setObjectName("settingsTitle")
            layout.insertWidget(0, title)
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
            dialog.setStyleSheet(settings_style(self.appearance))
            dialog.resize(590, 360)
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

    def update_memory_menu(self):
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
        name_in_draft, _ = self.skill_in_draft()
        for name in names:
            action = self.skills_menu.addAction(name, lambda _checked=False, value=name: self.draft_skill(value))
            action.setCheckable(True)
            action.setChecked(name == name_in_draft)
        if names:
            self.skills_menu.addSeparator()
        self.skills_menu.addAction("Administrar Skills…", self.open_skills)

    def skill_in_draft(self):
        opening = "Usa la Skill «"
        text = self.message.toPlainText()
        if text.startswith(opening):
            name, separator, _ = text[len(opening):].partition("». ")
            if separator and local_skills.valid_name(name):
                return name, opening + name + separator
        return None, ""

    def draft_skill(self, name):
        _, current_prefix = self.skill_in_draft()
        self.message.moveCursor(QTextCursor.MoveOperation.Start)
        cursor = self.message.textCursor()
        cursor.setPosition(len(current_prefix), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(f"Usa la Skill «{name}». ")
        self.message.setTextCursor(cursor)
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
            enabled = not enabled
            self.show_problem(str(exc))
        self.auto_memory_action.setChecked(enabled)
        with QSignalBlocker(self.auto_memory_switch):
            self.auto_memory_switch.setChecked(enabled)

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
        if not self.welcome.isHidden():
            self.set_welcome(False, animate=user)
        if user:
            self.follow_latest = True
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.transcript.insertLayout(self.transcript.count() - 1, row)
        body = ChatText(self.chat) if user else MarkdownText(self.chat, text, self.appearance)
        body.setAccessibleName("Tú" if user else "StoneBot")
        body.setObjectName("userMessage" if user else "botMessage")
        if user:
            row.addStretch(1)
        card = MessageCard()
        column = QVBoxLayout(card)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        row.addWidget(card, 4)
        if not user:
            row.addStretch(1)
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
        card.add_action(actions, CopyButton(text))
        if user and index is not None and self.chat_id is not None:
            card.add_action(actions, self.message_button("Editar", lambda: self.edit_message(index, body)))
        elif not user and index is not None and self.chat_id is not None:
            if self.last_regenerate is not None:
                previous_card, previous_button = self.last_regenerate
                previous_card.remove_action(previous_button)
            button = self.message_button("Regenerar", lambda: self.regenerate_reply(index))
            card.add_action(actions, button)
            self.last_regenerate = card, button
        column.addLayout(actions)
        self.fit_bubble(body)
        self.scroll_to_latest()

    @staticmethod
    def message_button(title, action):
        button = secondary_button(QPushButton(title))
        button.setObjectName("messageAction")
        button.clicked.connect(lambda checked=False: action())
        return button

    def fit_bubbles(self):
        for body in self.chat.findChildren(ChatText, "userMessage"):
            self.fit_bubble(body)
        for body in self.chat.findChildren(MarkdownText, "botMessage"):
            self.fit_bubble(body)

    def fit_bubble(self, body):
        limit = max(1, self.transcript.parentWidget().width() * 7 // 10)
        card = body.parentWidget()
        if isinstance(body, MarkdownText):
            card.setMaximumWidth(limit)
            return
        if not body.isReadOnly():
            return
        width = max(map(body.fontMetrics().horizontalAdvance, body.toPlainText().split("\n"))) + 26
        body.setMaximumWidth(min(limit, width))
        preview_width = 280 if card.findChild(AttachmentCard) is not None else 0
        card.setMaximumWidth(min(limit, max(width, card.layout().minimumSize().width(), preview_width)))

    def scroll_to_latest(self):
        if self.follow_latest:
            bar = self.chat.verticalScrollBar()
            bar.setValue(bar.maximum())

    def update_scroll_preference(self):
        bar = self.chat.verticalScrollBar()
        self.follow_latest = bar.sliderPosition() == bar.maximum()

    def refresh_send_button(self):
        running = self.thread is not None
        label = "Detener" if running else "Enviar"
        self.send.setAccessibleName(label)
        self.send.setToolTip("Deteniendo…" if self.stopping_turn else
                             "Detener (Esc)" if running else label)
        self.send.setIcon(sidebar_icon("stop" if running else "send", QColor(readable_text(self.appearance["accent"]))))
        self.send.setEnabled(not self.stopping_turn)
        self.stop_shortcut.setEnabled(running and not self.stopping_turn)

    def send_or_stop(self):
        if self.thread is None:
            self.enviar()
        else:
            self.stop_turn()

    def stop_turn(self):
        if self.thread is None or self.stopping_turn:
            return
        self.stopping_turn = True
        self.refresh_send_button()
        self.thread.requestInterruption()
        self.worker.stop()

    def regenerate_reply(self, index):
        saved = self.messages[1:]
        if not 0 <= index < len(saved) or saved[index]["role"] != "assistant":
            return
        previous_user = next((position for position in range(index - 1, -1, -1)
                              if saved[position]["role"] == "user"), None)
        if previous_user is not None:
            self.regenerate(previous_user, saved[previous_user]["content"], retry_at=index)

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
            self.search_sidebar()
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

    def edit_message(self, index, body):
        if self.thread is not None or self.chat_id is None or self.history is None:
            return
        if self.task is not None:
            self.show_problem("La regeneración está disponible en conversaciones sin una tarea guardada.")
            return
        original = self.messages[index + 1]["content"]
        if self.inline_cancel:
            self.inline_cancel()
        card = body.parentWidget()
        panel = QWidget(card)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel("Al regenerar, se reemplazarán este mensaje y los posteriores.")
        note.setObjectName("messageTime")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = secondary_button(QPushButton("Cancelar"))
        save = QPushButton("Regenerar")
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        card.layout().insertWidget(card.layout().count() - 1, panel)
        body.setFixedWidth(body.width())
        card.setMaximumWidth(max(card.maximumWidth(), panel.minimumSizeHint().width()))
        body.setReadOnly(False)
        body.moveCursor(QTextCursor.MoveOperation.End)
        body.setFocus()

        def update_save():
            text = body.toPlainText().strip()
            save.setEnabled(bool(text) and text != original.strip())

        shortcuts = []

        def close_editor():
            for shortcut in shortcuts:
                shortcut.setEnabled(False)
                shortcut.deleteLater()
            self.inline_cancel = None
            body.textChanged.disconnect(update_save)
            body.setReadOnly(True)
            body.setPlainText(original)
            body.setMinimumWidth(0)
            panel.hide()
            card.layout().removeWidget(panel)
            panel.deleteLater()
            self.fit_bubble(body)

        def submit():
            text = body.toPlainText().strip()
            close_editor()
            self.regenerate(index, text)

        self.inline_cancel = close_editor
        body.textChanged.connect(update_save)
        update_save()
        cancel.clicked.connect(close_editor)
        save.clicked.connect(submit)
        for key, button in (("Esc", cancel), ("Ctrl+Return", save), ("Ctrl+Enter", save)):
            shortcut = QShortcut(QKeySequence(key), card)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(button.click)
            shortcuts.append(shortcut)

    def regenerate(self, index, text, *, retry_at=None):
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
                or (retry_at is None and text == saved[index]["content"].strip())):
            return
        edited = {**saved[index], "content": text, "created": time.time_ns()} if retry_at is None else saved[index]
        following = saved[retry_at + 1:] if retry_at is not None else []
        self.pending_edit = (self.chat_id, index, saved, edited, following)
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
        if self.inline_cancel:
            self.inline_cancel()
        self.stopping_turn = False
        self.message.setEnabled(False)
        self.attachments.add_button.setEnabled(False)
        self.reasoning_button.setEnabled(False)
        self.chat_options.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.sidebar_rail.provider_badge.setEnabled(False)
        self.history_panel.setEnabled(False)
        for button in self.sidebar_rail.actions.values():
            button.setEnabled(False)
        self.activity_panel = ActivityPanel()
        self.activity_panel.show_mascot(self.avatar)
        self.avatar.thinking()
        self.turn_failed = False
        self.transcript.insertWidget(self.transcript.count() - 1, self.activity_panel)
        if task is None:
            self.activity_panel.add_event("Procesando el mensaje…")
        else:
            self.attach_task_panel(task)
        self.scroll_to_latest()

        self.thread = QThread()
        self.refresh_send_button()
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
        self.worker.partial.connect(self.show_partial_reply)
        self.worker.interrupted_reply.connect(self.keep_interrupted_reply)
        self.worker.finished.connect(self.respuesta)
        self.worker.error.connect(self.error)
        self.worker.mcp_notice.connect(record)
        self.worker.operation_error.connect(self.show_turn_warning)
        self.worker.activity.connect(self.activity_panel.add_event)
        self.worker.reasoning.connect(self.activity_panel.add_reasoning)
        self.worker.mcp_confirmation.connect(self.confirmar_mcp, Qt.ConnectionType.BlockingQueuedConnection)
        self.worker.task_started.connect(self.on_saved_task_started)
        self.worker.continuity_saved.connect(self.update_continuity)
        self.worker.finished.connect(self.thread.quit)
        self.worker.error.connect(self.thread.quit)
        self.worker.cancelled.connect(self.thread.quit)
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
        files = request.get("local_files", False)
        dialog.setWindowTitle("Archivos locales" if files else
                              ("Guardar archivo Markdown" if local else "Confirmar operación MCP"))
        dialog.setStyleSheet(dialog_style(self.appearance))
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        arguments = json.dumps(request["arguments"], indent=2, ensure_ascii=True)
        if files:
            dialog.setText(f"¿Autorizar «{request['operation']}»?")
            dialog.setInformativeText("\n".join(f"{key}: {value}" for key, value in request["arguments"].items()))
        elif local:
            dialog.setText("¿Guardar este archivo?")
            dialog.setInformativeText(request["arguments"]["path"])
            dialog.setDetailedText(request["arguments"]["content"])
        else:
            dialog.setText(f"¿Autorizar {request['tool']} en {request['server']}?")
            if len(arguments) <= 500:
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
        self.avatar.warning()
        try:
            dialog.exec()
        finally:
            self.avatar.end_warning()
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
            self.pool.close()
            self.memory.close()
            if self.tray is not None:
                self.tray.hide()
                QTimer.singleShot(0, QApplication.instance().quit)
            super().closeEvent(event)

    @Slot(str)
    def show_partial_reply(self, text):
        if self.stopping_turn:
            return
        if not text:
            self.clear_partial_reply()
            return
        if self.partial_reply is None:
            self.partial_reply = QLabel()
            self.partial_reply.setObjectName("partialReply")
            self.partial_reply.setWordWrap(True)
            self.partial_reply.setTextFormat(Qt.TextFormat.PlainText)
            self.transcript.insertWidget(self.transcript.count() - 1, self.partial_reply)
        self.partial_reply.setText(text)
        self.scroll_to_latest()

    def clear_partial_reply(self):
        if self.partial_reply is not None:
            self.transcript.removeWidget(self.partial_reply)
            self.partial_reply.hide()
            self.partial_reply.deleteLater()
            self.partial_reply = None

    @Slot(str)
    def keep_interrupted_reply(self, text):
        self.clear_partial_reply()
        if text:
            self.respuesta(text, interrupted=True)

    def respuesta(self, texto, *, interrupted=False):
        self.clear_partial_reply()
        if self.stopping_turn and not interrupted and (self.worker is None or self.worker.task is None):
            if texto.strip() and texto.strip() != "(Sin respuesta)":
                self.keep_interrupted_reply(texto)
            return
        created = time.time_ns()
        if self.pending_edit is None:
            task = self.worker.task if self.worker is not None else None
            self.save_message("assistant", texto, created, task=task)
            if task is not None and not self.history_write_ok:
                task["status"] = "interrupted"
        else:
            chat_id, index, saved, edited, following = self.pending_edit
            if not texto.strip() or texto.strip() == "(Sin respuesta)":
                self.error(f"{PROVIDERS[self.ai.provider]} no generó una respuesta nueva. Se conservó la conversación original.")
                return
            answer = {"role": "assistant", "content": texto, "created": created}
            try:
                self.history.replace_from(chat_id, index, saved, edited, answer, following)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.error("No se pudo guardar la regeneración. Se conservó el historial guardado.")
                return
            self.pending_edit = None
            self.messages.append(answer)
            if following:
                self.render_chat(chat_id, [*self.messages[1:], *following], keep_activity=True)
                self.schedule_chat_title(chat_id, self.messages[1:])
                return
            self.refresh_history()
        self.append_message(texto, created=created, index=len(self.messages) - 2 if self.history_write_ok else None)
        if self.history_write_ok:
            self.schedule_chat_title(self.chat_id, self.messages[1:])

    def error(self, detalle):
        if self.stopping_turn and (self.worker is None or self.worker.task is None):
            return
        if self.worker is not None and self.worker.task is not None:
            self.worker.task_reply("paused", detalle)
            self.respuesta(detalle)
        self.turn_failed = True
        self.restore_pending_edit()
        self.activity_panel.add_event(f"Error del turno · {detalle}")
        self.show_problem(detalle)

    def restore_pending_edit(self):
        if self.pending_edit is not None:
            chat_id, _, saved, _, _ = self.pending_edit
            self.pending_edit = None
            try:
                saved = self.history.messages(chat_id)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                pass
            self.render_chat(chat_id, saved, keep_activity=True)

    @Slot()
    def limpiar(self):
        self.clear_partial_reply()
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
        elif self.stopping_turn:
            self.restore_pending_edit()
            self.activity_panel.add_event("Respuesta detenida.")
        elif not self.activity_panel.latest.startswith("Error del turno"):
            self.activity_panel.add_event("Turno finalizado.")
        success = not (self.stopping_turn or self.turn_failed)
        self.avatar.finish(success)
        self.activity_panel.finish_mascot(success, cancelled=self.stopping_turn)
        self.message.setEnabled(True)
        self.attachments.add_button.setEnabled(True)
        self.reasoning_button.setEnabled(True)
        self.stopping_turn = False
        self.refresh_send_button()
        self.chat_options.setEnabled(True)
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
                                    "Si ya está abierto, usa el icono de StoneBot en la bandeja.")
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

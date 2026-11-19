"""Vista del chat y estilo basado en las preferencias de apariencia."""
import base64
from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from appearance import button_style, control_colors, link_color, readable_text, secondary_button, shade
from attachments import (
    FILE_FILTER, attachment_label, clipboard_attachment, read_attachment,
)


class ChatText(QTextEdit):
    def __init__(self, scroll_area=None):
        super().__init__()
        self.scroll_area = scroll_area
        self.setAcceptRichText(False)
        self.setReadOnly(scroll_area is not None)
        self.setTabChangesFocus(True)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if scroll_area is not None:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.fit_height(self.document().size())

    def fit_height(self, size):
        height = ceil(size.height()) + 2 * self.frameWidth()
        self.setFixedHeight(max(46, min(160, height)) if self.scroll_area is None else height)

    def wheelEvent(self, event):
        if self.scroll_area is None:
            super().wheelEvent(event)
        else:
            QApplication.sendEvent(self.scroll_area.viewport(), event)


class Composer(ChatText):
    submitted = Signal()
    pasted_paths = Signal(list)
    pasted_image = Signal(QImage)

    def __init__(self):
        super().__init__()
        self.setObjectName("messageInput")
        self.setPlaceholderText("Escribe un mensaje…")
        self.setAccessibleName("Mensaje para StoneBot")
        self.document().setDocumentMargin(12)
        self.setViewportMargins(0, 0, 4, 0)
        self.verticalScrollBar().setObjectName("composerScroll")
        self.expand_button = secondary_button(QPushButton())
        self.expand_button.setObjectName("composerExpand")
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self.expand_editor)
        self.expand_editor(False)

    def expand_editor(self, expanded):
        self.expand_button.setText("⤡" if expanded else "⤢")
        label = "Reducir editor" if expanded else "Ampliar editor"
        self.expand_button.setAccessibleName(label)
        self.expand_button.setToolTip(label)
        self.fit_height(self.document().size())
        self.ensureCursorVisible()

    def fit_height(self, size):
        available = self.window().height()
        if hasattr(self, "expand_button") and self.expand_button.isChecked():
            height = max(85, min(600, available * 3 // 5))
        else:
            height = min(160, max(46, available // 3), max(46, ceil(size.height()) + 2 * self.frameWidth()))
        self.setFixedHeight(height)

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def canInsertFromMimeData(self, source):
        return (source.hasImage() or any(url.isLocalFile() for url in source.urls())
                or super().canInsertFromMimeData(source))

    def insertFromMimeData(self, source):
        paths = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
        if paths:
            self.pasted_paths.emit(paths)
        elif source.hasImage():
            image = source.imageData()
            self.pasted_image.emit(image.toImage() if isinstance(image, QPixmap) else QImage(image))
        else:
            super().insertFromMimeData(source)


class AttachmentCard(QWidget):
    def __init__(self, file):
        super().__init__()
        self.setObjectName("attachmentCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(8, 5, 8, 5)
        self.row.setSpacing(8)
        badge = QLabel()
        badge.setObjectName("attachmentBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 36)
        if encoded := file.get("image"):
            pixmap = QPixmap()
            try:
                pixmap.loadFromData(base64.b64decode(encoded, validate=True))
            except (ValueError, TypeError):
                pass
            if pixmap.isNull():
                badge.setText("IMG")
            else:
                badge.setPixmap(pixmap.scaled(badge.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        else:
            suffix = Path(file["name"]).suffix[1:].upper()
            badge.setText(suffix if suffix in {"PDF", "TXT", "MD", "CSV", "TSV", "LOG", "JSON"} else "DOC")
        self.row.addWidget(badge)
        display = attachment_label(file) + (" · parcial" if file.get("partial") else "")
        label = QLabel(display if len(display) <= 48 else display[:45] + "…")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setToolTip(display)
        self.row.addWidget(label, 1)


class AttachmentTray(QWidget):
    problem = Signal(str)

    def __init__(self):
        super().__init__()
        self.files = []
        body = QWidget()
        self.rows = QVBoxLayout(body)
        self.rows.setContentsMargins(3, 0, 3, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)
        self.add_button = secondary_button(QPushButton("+"))
        self.add_button.setAccessibleName("Opciones del chat")
        self.add_button.setToolTip("Adjuntos, MCP y memoria")
        self.menu = QMenu(self.add_button)
        self.menu.setObjectName("chatMenu")
        self.menu.addAction("Adjuntar archivos…", self.choose)
        self.add_button.setMenu(self.menu)
        self.hide()

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Adjuntar archivos", filter=FILE_FILTER)
        self.add_paths(paths)

    def add_paths(self, paths):
        for path in paths:
            try:
                self.add_file(read_attachment(path))
            except (OSError, ValueError, RuntimeError) as exc:
                self.problem.emit(f"No se pudo adjuntar {Path(path).name}. {exc}")

    def add_clipboard_image(self, image):
        try:
            self.add_file(clipboard_attachment(image))
        except ValueError as exc:
            self.problem.emit(str(exc))

    def add_file(self, file):
        self.files.append(file)
        row = AttachmentCard(file)
        remove = secondary_button(QPushButton("Quitar"))
        remove.setAccessibleName(f"Quitar {file['name']}")
        remove.clicked.connect(lambda: self.remove_row(row))
        row.row.addWidget(remove)
        self.rows.addWidget(row)
        self.scroll.setFixedHeight(min(144, self.rows.sizeHint().height() + 2))
        self.show()

    def remove_row(self, row):
        del self.files[self.rows.indexOf(row)]
        self.rows.removeWidget(row)
        self.scroll.setFixedHeight(min(144, self.rows.sizeHint().height() + 2))
        row.hide()
        row.deleteLater()
        self.setVisible(bool(self.files))

    def clear(self):
        while self.rows.count():
            self.remove_row(self.rows.itemAt(0).widget())


class ActivityPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("activityPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.latest = ""
        self.summary = QToolButton()
        self.summary.setObjectName("activitySummary")
        self.summary.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.summary.setArrowType(Qt.ArrowType.RightArrow)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.summary.setAccessibleName("Expandir o contraer actividad de este turno")
        self.summary.setCheckable(True)
        self.summary.toggled.connect(self.expand)
        self.pause_button = secondary_button(QPushButton("Pausar"))
        self.pause_button.setAccessibleName("Pausar tarea al terminar el paso actual")
        self.pause_button.hide()
        self.correction_button = secondary_button(QPushButton("Guardar corrección…"))
        self.correction_button.hide()
        self.detail = QWidget()
        self.detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setFixedHeight(74)
        self.events.setAccessibleName("Actividad de StoneBot")
        self.events.document().setMaximumBlockCount(40)
        self.show_reasoning = QCheckBox("Mostrar razonamiento de Ollama")
        self.show_reasoning.hide()
        self.reasoning = QPlainTextEdit()
        self.reasoning.setReadOnly(True)
        self.reasoning.setFixedHeight(96)
        self.reasoning.setAccessibleName("Razonamiento proporcionado por Ollama")
        self.reasoning.document().setMaximumBlockCount(400)
        self.reasoning.hide()
        self.show_reasoning.toggled.connect(self.reasoning.setVisible)
        details = QVBoxLayout(self.detail)
        details.setContentsMargins(0, 4, 0, 0)
        details.setSpacing(4)
        details.addWidget(QLabel("Actividad observable"))
        details.addWidget(self.events)
        details.addWidget(self.show_reasoning)
        details.addWidget(self.reasoning)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(3)
        controls = QHBoxLayout()
        controls.addWidget(self.summary, 1)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.correction_button)
        layout.addLayout(controls)
        layout.addWidget(self.detail)
        self.detail.hide()

    def enable_pause(self, pause):
        def request_pause():
            pause()
            self.pause_button.setEnabled(False)
            self.add_event("Pausa solicitada · esperando el paso actual…")

        self.pause_button.clicked.connect(request_pause)
        self.pause_button.show()

    @staticmethod
    def task_status(label, steps):
        return f"{label} · {steps} pasos registrados"

    def finish_task(self, label, steps, *, saved):
        self.pause_button.hide()
        self.add_event(self.task_status(label, steps) if saved else "No se pudo guardar el cierre de la tarea")

    def expand(self, expanded):
        self.summary.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.detail.setVisible(expanded)

    def add_event(self, text):
        self.latest = text
        self.events.appendPlainText(text)
        self.update_summary()

    def update_summary(self):
        text = f"Actividad · {self.latest}"
        self.summary.setToolTip(text)
        self.summary.setText(self.summary.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, max(60, self.summary.width() - 30)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_summary()

    def add_reasoning(self, text):
        if text.strip():
            self.show_reasoning.show()
            self.reasoning.appendPlainText(text)


def chat_style(theme):
    background, accent = theme["background"], theme["accent"]
    accent_text = readable_text(accent)
    user, bot = theme["user_message"], theme["bot_message"]
    sidebar = shade(background, .035)
    subtle_edge = shade(background, .16)
    muted = shade(background, .63)
    surface, edge, _, text = control_colors(background)
    return button_style(theme) + f"""
            QWidget#chatWindow, QWidget#chatCanvas {{ background: {background}; }}
            QLabel, QTextEdit {{
                color: {readable_text(background)}; font-family: "Segoe UI"; font-size: 15px;
            }}
            QPushButton {{ font-family: "Segoe UI"; font-size: 15px; }}
            QWidget#chatHeader {{ border-bottom: 1px solid {subtle_edge}; }}
            QWidget#chatHeader QPushButton {{ padding: 4px 8px; font-size: 14px; }}
            QPushButton[quiet="true"]:checked:enabled:!hover:!pressed {{ background: {shade(background, .09)}; }}
            QWidget#historyPanel {{ background: {sidebar}; }}
            QWidget#sidebarRail {{ background: {sidebar}; border-right: 1px solid {subtle_edge}; }}
            QWidget#sidebarRail QPushButton#sidebarToggle {{ padding: 0; }}
            QWidget#sidebarRail QPushButton[sidebarAction="true"] {{ text-align: left; padding: 0 0 0 7px; }}
            QWidget#historyPanel QListWidget, QWidget#historyPanel QLineEdit {{
                color: {text}; font-family: "Segoe UI"; font-size: 14px;
            }}
            QWidget#historyPanel QLineEdit {{
                background: {surface}; color: {text};
                border: 1px solid {subtle_edge}; border-radius: 7px;
                selection-background-color: {accent}; selection-color: {accent_text}; padding: 6px 8px;
            }}
            QWidget#historyPanel QLineEdit:focus {{ border-color: {accent}; }}
            QWidget#historyPanel QListWidget {{ background: transparent; border: 0; outline: 0; }}
            QWidget#historyPanel QListWidget::item {{ padding: 5px 30px 5px 8px; border: 1px solid transparent; border-radius: 7px; }}
            QWidget#historyPanel QListWidget::item:disabled {{ color: {muted}; padding-top: 8px; }}
            QWidget#historyPanel QListWidget::item:hover {{ background: {shade(sidebar, .07)}; }}
            QWidget#historyPanel QListWidget::item:selected {{
                background: {shade(sidebar, .14)}; color: {text}; border-left-color: {link_color(background)};
            }}
            QWidget#historyPanel QListWidget::item:focus {{ border-color: {link_color(background)}; }}
            QWidget#historyPanel QPushButton {{ padding: 6px 8px; }}
            QScrollArea#projectPage, QWidget#projectCanvas {{ background: {background}; border: 0; }}
            QLabel#projectTitle {{ color: {text}; font-family: "Georgia"; font-size: 28px; font-weight: 600; }}
            QLabel#projectSection {{ color: {text}; font-size: 14px; font-weight: 600; }}
            QLabel#projectMeta {{ color: {muted}; font-size: 13px; }}
            QWidget#projectCard {{ background: {sidebar}; border-radius: 10px; }}
            QPushButton#projectLink {{ text-align: left; padding: 8px; border-radius: 7px; }}
            QPushButton#historyRowOptions {{ padding: 0; border: none; border-radius: 6px; }}
            QSplitter::handle:horizontal {{ background: {sidebar}; border-right: 1px solid {subtle_edge}; }}
            QSplitter::handle:horizontal:hover {{ background: {edge}; }}
            QLabel#chatTitle {{ font-weight: 700; }}
            QLabel#chatStatus {{ font-size: 14px; }}
            QLabel#messageTime {{ font-size: 12px; color: {muted}; }}
            QPushButton#messageAction {{
                font-size: 12px; border-radius: 6px; padding: 2px 6px;
            }}
            QWidget#activityPanel {{ border-top: 1px solid {edge}; }}
            QToolButton#activitySummary {{
                border-width: 2px; border-style: solid; border-radius: 6px; padding: 3px 8px;
                text-align: left;
            }}
            QWidget#activityPanel QPlainTextEdit {{
                background: {surface}; color: {text};
                border: 1px solid {edge};
            }}
            QScrollArea, QTextEdit {{ background: transparent; border: 0; }}
            QScrollBar:vertical {{ width: 10px; background: {background}; }}
            QScrollBar::handle:vertical {{
                min-height: 28px; background: {shade(background, .4)}; border-radius: 5px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QTextEdit {{
                font-size: {theme['font_size']}px; selection-background-color: {accent};
                selection-color: {accent_text};
            }}
            QTextEdit#userMessage {{
                background: {user}; color: {readable_text(user)}; border-radius: 14px;
                border-bottom-right-radius: 5px;
            }}
            QWidget#botMessage {{
                background: {bot}; color: {readable_text(bot)}; border-radius: 14px;
                border-bottom-left-radius: 5px;
                font-family: "Segoe UI"; font-size: {theme['font_size']}px;
            }}
            QTextBrowser#responseProse, QTextBrowser#codeText {{ color: {readable_text(bot)}; }}
            QWidget#codeCard {{ background: {shade(bot, .08)}; border: 1px solid {shade(bot, .20)}; border-radius: 9px; }}
            QLabel#codeLanguage {{ font-size: 13px; font-weight: 600; color: {readable_text(bot)}; }}
            QTextBrowser#codeText QScrollBar:horizontal {{ height: 9px; background: transparent; }}
            QTextBrowser#codeText QScrollBar::handle:horizontal {{
                min-width: 25px; background: {shade(bot, .28)}; border-radius: 4px;
            }}
            QTextBrowser#codeText QScrollBar::add-line:horizontal, QTextBrowser#codeText QScrollBar::sub-line:horizontal {{ width: 0; }}
            QWidget#composerPanel {{
                background: {surface}; border: 1px solid {subtle_edge}; border-radius: 16px;
            }}
            QWidget#attachmentCard {{ background: {surface}; border: 1px solid {edge}; border-radius: 8px; }}
            QLabel#attachmentBadge {{
                background: {shade(surface, .09)}; color: {text}; border-radius: 5px; font-size: 12px;
            }}
            QMenu#chatMenu {{
                background: {surface}; color: {text}; border: 1px solid {edge}; padding: 4px;
            }}
            QMenu#chatMenu::item {{ padding: 6px 24px 6px 10px; }}
            QMenu#chatMenu::item:selected {{ background: {accent}; color: {accent_text}; }}
            QMenu#chatMenu::item:disabled {{ color: {muted}; }}
            QPushButton#sendMessage {{ padding: 5px 13px; font-size: 14px; }}
            QPushButton#composerExpand {{ padding: 2px 7px; }}
            QTextEdit#messageInput {{ color: {text}; placeholder-text-color: {shade(surface, .7)}; }}
            QScrollBar#composerScroll:vertical {{ width: 10px; background: transparent; }}
            QScrollBar#composerScroll::handle:vertical {{ margin: 2px; }}
        """

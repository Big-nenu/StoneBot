"""Vista del chat y estilo basado en las preferencias de apariencia."""
import re
from collections import deque
from math import ceil
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument, QTextFormat, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QTextBrowser, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from appearance import button_style, control_colors, link_color, readable_text, secondary_button, shade
from attachments import FILE_FILTER, MAX_FILES, read_attachment


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

    def __init__(self):
        super().__init__()
        self.setObjectName("messageInput")
        self.setPlaceholderText("Escribe un mensaje…")
        self.setAccessibleName("Mensaje para StoneBot")
        self.document().setDocumentMargin(12)

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AttachmentTray(QWidget):
    problem = Signal(str)

    def __init__(self):
        super().__init__()
        self.files = []
        self.rows = QVBoxLayout(self)
        self.rows.setContentsMargins(3, 0, 3, 0)
        self.add_button = secondary_button(QPushButton("+"))
        self.add_button.setAccessibleName("Adjuntar archivos")
        self.add_button.setToolTip("Adjuntar imágenes, PDF o texto")
        self.add_button.clicked.connect(self.choose)
        self.hide()

    def choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Adjuntar archivos", filter=FILE_FILTER)
        for path in paths:
            if len(self.files) >= MAX_FILES:
                self.problem.emit(f"Puedes adjuntar hasta {MAX_FILES} archivos por mensaje.")
                break
            try:
                self.add_file(read_attachment(path))
            except (OSError, ValueError, RuntimeError) as exc:
                self.problem.emit(f"No se pudo adjuntar {Path(path).name}. {exc}")

    def add_file(self, file):
        self.files.append(file)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        name = file["name"]
        label = QLabel((name if len(name) <= 40 else name[:37] + "…") + (" (parcial)" if file.get("partial") else ""))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setToolTip(name)
        remove = secondary_button(QPushButton("Quitar"))
        remove.setAccessibleName(f"Quitar {name}")
        remove.clicked.connect(lambda: self.remove_row(row))
        layout.addWidget(label, 1)
        layout.addWidget(remove)
        self.rows.addWidget(row)
        self.show()

    def remove_row(self, row):
        del self.files[self.rows.indexOf(row)]
        self.rows.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.setVisible(bool(self.files))

    def clear(self):
        while self.rows.count():
            self.remove_row(self.rows.itemAt(0).widget())


FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")


def fenced_code(source):
    fence = ""
    lines = []
    indent = 0
    for line in source.splitlines():
        match = FENCE.match(line)
        if not fence:
            if match and not (match[2][0] == "`" and "`" in match[3]):
                indent, fence = len(match[1]), match[2]
        elif match and match[2].startswith(fence) and not match[3].strip():
            yield "\n".join(lines)
            fence, lines = "", []
        else:
            trim = min(indent, len(line) - len(line.lstrip(" ")))
            lines.append(line[trim:])
    if fence:
        yield "\n".join(lines)


class MarkdownText(QTextBrowser):
    def __init__(self, scroll_area, source):
        super().__init__()
        self.scroll_area = scroll_area
        self.setOpenLinks(False)
        self.anchorClicked.connect(self.open_link)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        features = QTextDocument.MarkdownFeature
        self.document().setMarkdown(source, features.MarkdownDialectGitHub | features.MarkdownNoHTML)
        groups = []
        group = None
        block = self.document().begin()
        while block.isValid():
            fmt = block.blockFormat()
            if fmt.hasProperty(QTextFormat.Property.BlockCodeLanguage):
                kind = (fmt.stringProperty(QTextFormat.Property.BlockCodeFence),
                        fmt.stringProperty(QTextFormat.Property.BlockCodeLanguage))
                if group is None or group[0] != kind:
                    group = kind, []
                    groups.append(group)
                group[1].append(block.text())
                fmt.setNonBreakableLines(False)
                QTextCursor(block).setBlockFormat(fmt)
            else:
                group = None
            block = block.next()
        # Qt agrupa cercas contiguas iguales; el original conserva sus límites.
        candidates = deque(filter(None, fenced_code(source)))
        self.code = []
        for (fence, _), lines in groups:
            text = "\n".join(lines)
            while fence and candidates and (text == candidates[0] or text.startswith(candidates[0] + "\n")):
                original = candidates.popleft()
                self.code.append(original)
                text = text[len(original) + 1:]
            if text:
                self.code.append(text)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.fit_height(self.document().size())

    def loadResource(self, kind, url):
        return None

    def open_link(self, url):
        if url.scheme() in ("http", "https") and url.host():
            QDesktopServices.openUrl(url)

    def fit_height(self, size):
        self.setFixedHeight(ceil(size.height()) + 2 * self.frameWidth())

    def wheelEvent(self, event):
        QApplication.sendEvent(self.scroll_area.viewport(), event)


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
        layout.addWidget(self.summary)
        layout.addWidget(self.detail)
        self.detail.hide()

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
            text, Qt.TextElideMode.ElideRight, max(60, self.width() - 48)))

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
            QWidget#historyPanel QListWidget::item {{ padding: 7px 8px; border: 1px solid transparent; border-radius: 7px; }}
            QWidget#historyPanel QListWidget::item:hover {{ background: {shade(sidebar, .07)}; }}
            QWidget#historyPanel QListWidget::item:selected {{
                background: {shade(sidebar, .14)}; color: {text}; border-left-color: {link_color(background)};
            }}
            QWidget#historyPanel QListWidget::item:focus {{ border-color: {link_color(background)}; }}
            QLabel#historyHeading {{ color: {muted}; font-size: 13px; font-weight: 600; padding: 0 7px; }}
            QWidget#historyPanel QPushButton {{ padding: 6px 8px; }}
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
            QTextEdit#botMessage {{
                background: {bot}; color: {readable_text(bot)}; border-radius: 14px;
                border-bottom-left-radius: 5px;
            }}
            QWidget#composerPanel {{
                background: {surface}; border: 1px solid {subtle_edge}; border-radius: 16px;
            }}
            QPushButton#sendMessage {{ padding: 5px 13px; font-size: 14px; }}
            QTextEdit#messageInput {{ color: {text}; placeholder-text-color: {shade(surface, .7)}; }}
        """

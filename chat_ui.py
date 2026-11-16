"""Vista del chat y estilo basado en las preferencias de apariencia."""
import re
from collections import deque
from math import ceil

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices, QTextCursor, QTextDocument, QTextFormat, QTextOption
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QLabel, QPlainTextEdit, QSizePolicy, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from appearance import readable_text, shade


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
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.setMaximumHeight(84)
        self.events.setAccessibleName("Actividad de StoneBot")
        self.events.document().setMaximumBlockCount(40)
        self.show_reasoning = QCheckBox("Mostrar razonamiento de Ollama")
        self.reasoning = QPlainTextEdit()
        self.reasoning.setReadOnly(True)
        self.reasoning.setMaximumHeight(100)
        self.reasoning.setAccessibleName("Razonamiento proporcionado por Ollama")
        self.reasoning.setPlaceholderText("Ollama aún no ha enviado razonamiento para este turno.")
        self.reasoning.document().setMaximumBlockCount(400)
        self.reasoning.hide()
        self.show_reasoning.toggled.connect(self.reasoning.setVisible)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Actividad de este turno"))
        layout.addWidget(self.events)
        layout.addWidget(self.show_reasoning)
        layout.addWidget(self.reasoning)
        self.hide()

    def reset(self):
        self.events.clear()
        self.reasoning.clear()


def chat_style(theme):
    background, accent = theme["background"], theme["accent"]
    accent_text = readable_text(accent)
    user, bot = theme["user_message"], theme["bot_message"]
    surface = shade(background, .06)
    edge = shade(background, .22)
    return f"""
            QWidget#chatWindow, QWidget#chatCanvas {{ background: {background}; }}
            QLabel, QTextEdit, QPushButton {{
                color: {readable_text(background)}; font-family: "Segoe UI"; font-size: 15px;
            }}
            QWidget#chatHeader {{ border-bottom: 1px solid {edge}; }}
            QWidget#historyPanel {{ border-right: 1px solid {edge}; }}
            QWidget#historyPanel QListWidget, QWidget#historyPanel QLineEdit {{
                background: {background}; color: {readable_text(background)};
                font-family: "Segoe UI"; font-size: 14px; border: 1px solid {edge};
                selection-background-color: {accent}; selection-color: {accent_text}; padding: 4px;
            }}
            QWidget#historyPanel QPushButton {{ padding: 6px 8px; }}
            QLabel#chatTitle {{ font-weight: 700; }}
            QLabel#chatModel, QLabel#chatStatus {{ font-size: 14px; }}
            QLabel#messageTime {{ font-size: 12px; }}
            QPushButton#messageAction {{
                background: {surface}; color: {readable_text(surface)};
                font-size: 12px; border-radius: 6px; padding: 2px 6px;
            }}
            QWidget#activityPanel {{ border-top: 1px solid {edge}; }}
            QWidget#activityPanel QPlainTextEdit {{
                background: {surface}; color: {readable_text(surface)};
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
                background: {user}; color: {readable_text(user)}; border-radius: 16px;
            }}
            QTextEdit#botMessage {{
                background: {bot}; color: {readable_text(bot)}; border-radius: 12px;
            }}
            QWidget#composerPanel {{
                background: {surface}; border: 1px solid {edge}; border-radius: 18px;
            }}
            QTextEdit#messageInput {{ color: {readable_text(surface)}; placeholder-text-color: {shade(surface, .7)}; }}
            QPushButton {{
                background: {accent}; color: {accent_text}; border: 2px solid transparent;
                border-radius: 12px; padding: 6px 13px; font-weight: 600;
            }}
            QPushButton:hover, QPushButton:focus {{ border-color: {accent_text}; }}
            QPushButton:disabled {{ background: {surface}; color: {shade(surface, .55)}; }}
        """

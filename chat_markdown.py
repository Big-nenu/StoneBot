"""Presentación de respuestas Markdown y bloques copiables."""
import re
from html import escape
from math import ceil

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices, QTextOption
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget

from appearance import link_color, readable_text, secondary_button, shade


MATH = re.compile(r"\$(?![\s$])((?:\\.|[^$\n\\])+?)(?<!\s)\$(?![\d$])|\\\(([^\n]+?)\\\)")
SYMBOLS = {r"\times": "×", r"\cdot": "·", r"\leq": "≤", r"\geq": "≥", r"\neq": "≠",
           r"\pm": "±", r"\in": "∈", r"\rightarrow": "→", r"\ldots": "…"}


def inline_math(state, silent):
    match = MATH.match(state.src, state.pos, state.posMax)
    if not match:
        return False
    if not silent:
        state.push("simple_math", "span", 0).content = match[1] or match[2]
    state.pos = match.end()
    return True


def render_math(tokens, index, _options, _env):
    value = re.sub(r"\\[a-zA-Z]+", lambda m: SYMBOLS.get(m[0], m[0]), tokens[index].content)
    value = re.sub(r"(?<=\w)-(?=\w)", "−", value)
    value = escape(value)
    value = re.sub(r"([_^])(?:\{([\w+−-]+)\}|(\w))",
                   lambda m: f"<{'sup' if m[1] == '^' else 'sub'}>{m[2] or m[3]}</{'sup' if m[1] == '^' else 'sub'}>", value)
    return f"<span>{value}</span>"


MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])
MARKDOWN.inline.ruler.before("escape", "simple_math", inline_math)
MARKDOWN.renderer.rules["simple_math"] = render_math

PROSE_STYLE = """
    p { margin-top: 0; margin-bottom: 9px; }
    h1, h2, h3, h4, h5, h6 { margin-top: 12px; margin-bottom: 6px; }
    ul, ol, blockquote { margin-top: 3px; margin-bottom: 9px; }
    li { margin-bottom: 4px; }
    code { font-family: Consolas, monospace; }
"""


def open_web_link(url):
    if url.isValid() and url.scheme() in ("http", "https") and url.host():
        QDesktopServices.openUrl(url)


def response_parts(source):
    env = {}
    pending, opened = [], []
    for token in MARKDOWN.parse(source, env):
        if token.type in ("fence", "code_block"):
            if any(part.nesting == 0 for part in pending):
                closing = [Token(part.type.removesuffix("_open") + "_close", part.tag, -1,
                                 block=part.block, hidden=part.hidden) for part in reversed(opened)]
                yield MARKDOWN.renderer.render(pending + closing, MARKDOWN.options, env), None
            language = token.info.strip().split(maxsplit=1)
            yield token.content.removesuffix("\n"), language[0] if language else ""
            pending = list(opened)
        else:
            pending.append(token)
            if token.nesting == 1:
                opened.append(token)
            elif token.nesting == -1:
                opened.pop()
    if any(part.nesting == 0 for part in pending):
        yield MARKDOWN.renderer.render(pending, MARKDOWN.options, env), None


class ResponseText(QTextBrowser):
    def __init__(self, scroll_area, *, code=False, horizontal=False):
        super().__init__()
        self.scroll_area = scroll_area
        self.setOpenLinks(False)
        self.anchorClicked.connect(open_web_link)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if code or horizontal else
                                          Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(6 if code else 0)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.horizontalScrollBar().rangeChanged.connect(self.fit_height)
        self.fit_height()

    def loadResource(self, kind, url):
        return None

    def fit_height(self, *_):
        bar = self.horizontalScrollBar()
        height = ceil(self.document().size().height()) + 2 * self.frameWidth()
        self.setFixedHeight(max(1, height + (bar.sizeHint().height() if bar.maximum() else 0)))

    def wheelEvent(self, event):
        if self.horizontalScrollBar().maximum() and (event.angleDelta().x() or event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            super().wheelEvent(event)
        else:
            QApplication.sendEvent(self.scroll_area.viewport(), event)


class CopyButton(QPushButton):
    def __init__(self, source):
        super().__init__("Copiar")
        secondary_button(self)
        self.setObjectName("messageAction")
        self.source = source
        self.reset_label = QTimer(self, singleShot=True, interval=1500)
        self.reset_label.timeout.connect(lambda: self.setText("Copiar"))
        self.clicked.connect(self.copy)

    def sizeHint(self):
        size = super().sizeHint()
        metrics = self.fontMetrics()
        size.setWidth(size.width() + max(0, metrics.horizontalAdvance("Copiado") - metrics.horizontalAdvance(self.text())))
        return size

    def copy(self):
        QApplication.clipboard().setText(self.source)
        self.setText("Copiado")
        self.reset_label.start()


class CodeCard(QWidget):
    def __init__(self, scroll_area, source, language, theme):
        super().__init__()
        self.setObjectName("codeCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.source = source
        try:
            self.lexer = get_lexer_by_name(language) if language else None
        except ClassNotFound:
            self.lexer = None
        caption = self.lexer.name if self.lexer else language or "Texto"
        label = QLabel(caption)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setObjectName("codeLanguage")
        self.copy = CopyButton(source)
        self.copy.setAccessibleName(f"Copiar bloque de {caption}")
        header = QHBoxLayout()
        header.addWidget(label)
        header.addStretch()
        header.addWidget(self.copy)
        self.text = ResponseText(scroll_area, code=True)
        self.text.setObjectName("codeText")
        self.text.setLineWrapMode(QTextBrowser.LineWrapMode.NoWrap)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 6)
        layout.setSpacing(4)
        layout.addLayout(header)
        layout.addWidget(self.text)
        self.set_theme(theme)

    def set_theme(self, theme):
        style = "friendly" if readable_text(theme["bot_message"]) == "#000000" else "monokai"
        if style != getattr(self, "highlight_style", None):
            self.highlight_style = style
            code = highlight(self.source, self.lexer, HtmlFormatter(style=style, noclasses=True, nowrap=True)) if self.lexer else escape(self.source)
            self.text.setHtml(f'<pre style="font-family: Consolas, monospace; margin: 0;">{code}</pre>')


class MarkdownText(QWidget):
    def __init__(self, scroll_area, source, theme):
        super().__init__()
        self.setObjectName("botMessage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAccessibleName("StoneBot")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 10, 11, 10)
        layout.setSpacing(10)
        self.parts = []
        for content, language in response_parts(source):
            if language is None:
                part = ResponseText(scroll_area, horizontal="<table>" in content)
                part.setObjectName("responseProse")
                part.html = content
            else:
                part = CodeCard(scroll_area, content, language, theme)
            self.parts.append(part)
            layout.addWidget(part)
        self.set_theme(theme)

    def toPlainText(self):
        return "\n".join(part.source if isinstance(part, CodeCard) else part.toPlainText() for part in self.parts)

    def set_theme(self, theme):
        color = link_color(theme["bot_message"])
        background = theme["bot_message"]
        old_background = getattr(self, "prose_background", None)
        for part in self.parts:
            if isinstance(part, CodeCard):
                part.set_theme(theme)
            elif background != old_background:
                part.document().setDefaultStyleSheet(PROSE_STYLE + f" a {{ color: {color}; }}")
                table = f'<table border="1" cellspacing="0" cellpadding="6" bordercolor="{shade(background, .28)}">'
                cell = f'<th bgcolor="{shade(background, .12)}"'
                part.setHtml(re.sub(r"<th(?=[ >])", cell, part.html.replace("<table>", table)))
        self.prose_background = background

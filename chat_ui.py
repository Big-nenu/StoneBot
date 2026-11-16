"""Vista del chat y estilo basado en las preferencias de apariencia."""
from math import ceil

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QApplication, QSizePolicy, QTextEdit

from appearance import readable_text


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


def chat_style(theme):
    background, accent = theme["background"], theme["accent"]
    accent_text = readable_text(accent)
    user, bot = theme["user_message"], theme["bot_message"]
    return f"""
            QWidget#chatWindow, QWidget#chatCanvas {{ background: {background}; }}
            QLabel, QTextEdit, QPushButton {{
                color: {readable_text(background)}; font-family: "Segoe UI"; font-size: 15px;
            }}
            QWidget#chatHeader {{ border-bottom: 1px solid #55515f; }}
            QWidget#historyPanel {{ border-right: 1px solid #55515f; }}
            QWidget#historyPanel QListWidget, QWidget#historyPanel QLineEdit {{
                background: {background}; color: {readable_text(background)};
                font-family: "Segoe UI"; font-size: 14px; border: 1px solid #55515f;
                selection-background-color: {accent}; selection-color: {accent_text}; padding: 4px;
            }}
            QWidget#historyPanel QPushButton {{ padding: 6px 8px; }}
            QLabel#chatTitle {{ font-weight: 700; }}
            QLabel#chatModel, QLabel#chatStatus {{ font-size: 14px; }}
            QScrollArea, QTextEdit {{ background: transparent; border: 0; }}
            QScrollBar:vertical {{ width: 10px; background: {background}; }}
            QScrollBar::handle:vertical {{
                min-height: 28px; background: #777281; border-radius: 5px;
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
                background: #25252d; border: 1px solid #41404f; border-radius: 18px;
            }}
            QTextEdit#messageInput {{ color: #f3f0f7; placeholder-text-color: #b8b2c4; }}
            QPushButton {{
                background: {accent}; color: {accent_text}; border: 2px solid transparent;
                border-radius: 12px; padding: 6px 13px; font-weight: 600;
            }}
            QPushButton:hover, QPushButton:focus {{ border-color: {accent_text}; }}
            QPushButton:disabled {{ background: #383541; color: #b1a8be; }}
        """

"""Vista del chat y estilo basado en las preferencias de apariencia."""
import base64
import re
from math import ceil
from pathlib import Path
from string import Template

from PySide6.QtCore import QEvent, QPoint, Qt, QStringListModel, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QContextMenuEvent, QImage, QLinearGradient, QPainter, QPixmap, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor, QTextOption,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QCompleter, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLayout, QMenu, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QStyle, QStyleOptionButton, QStylePainter, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from sprites import SpriteLabel
from appearance import DEFAULT_FONT_SIZE, control_colors, link_color, readable_text, secondary_button, shade
from attachments import (
    FILE_FILTER, attachment_label, clipboard_attachment, read_attachment,
)
from chat_markdown import open_web_link
from spellcheck import WindowsSpellChecker


WEB_URL = r"""\bhttps?://[^\s<>"`]+"""
UNCHECKED = re.compile(rf"`[^`]*`|(?P<url>{WEB_URL})|\b[A-Za-z]:[\\/]\S+|^/\w+", re.I)
SHORTCUT_TOKEN = re.compile(r"(?:^|\s)([/@#>!])([^\s/@#>!]*)$")
MENU_GAP = 8


def utf16_length(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def style_chat_menu(menu):
    menu.setObjectName("chatMenu")
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    return menu


class PopupButton(QPushButton):
    about_to_popup = Signal()

    def __init__(self, text="", *, above=False, right=False):
        super().__init__(text)
        self.above = above
        self.right = right
        self._menu = style_chat_menu(QMenu(self))
        self.clicked.connect(self.popup_menu)

    def menu(self):
        return self._menu

    def popup_menu(self):
        menu = self._menu
        self.about_to_popup.emit()
        menu.ensurePolished()
        size = menu.sizeHint()
        top_left = self.mapToGlobal(QPoint())
        x = top_left.x() + (self.width() - size.width() if self.right else 0)
        y = top_left.y() - size.height() - MENU_GAP if self.above else top_left.y() + self.height()
        menu.popup(QPoint(x, y))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Down:
            self.popup_menu()
            event.accept()
        else:
            super().keyPressEvent(event)

    def sizeHint(self):
        size = super().sizeHint()
        if self.text():
            option = QStyleOptionButton()
            self.initStyleOption(option)
            option.features |= QStyleOptionButton.ButtonFeature.HasMenu
            indicator = self.style().pixelMetric(QStyle.PixelMetric.PM_MenuButtonIndicator, option, self)
            size.setWidth(size.width() + indicator)
        return size

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.features |= QStyleOptionButton.ButtonFeature.HasMenu
        with QStylePainter(self) as painter:
            painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class ChatTranscript(QWidget):
    width_changed = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.width_changed.emit()


class MessageCard(QWidget):
    def __init__(self):
        super().__init__()
        self.hover_actions = []

    def add_action(self, row, button):
        policy = button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        button.setSizePolicy(policy)
        self.hover_actions.append(button)
        row.addWidget(button)
        button.setVisible(self.underMouse())

    def remove_action(self, button):
        self.hover_actions.remove(button)
        button.hide()
        button.setParent(None)
        button.deleteLater()

    def enterEvent(self, event):
        super().enterEvent(event)
        for button in self.hover_actions:
            button.show()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        for button in self.hover_actions:
            button.hide()


class ChatBottomFade(QWidget):
    def __init__(self, scroll_area, background):
        super().__init__(scroll_area.viewport())
        self.background = background
        self.bar = scroll_area.verticalScrollBar()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.parentWidget().installEventFilter(self)
        self.bar.rangeChanged.connect(self.refresh)
        self.bar.valueChanged.connect(self.refresh)
        self.refresh()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize and hasattr(self, "bar"):
            self.refresh()
        return super().eventFilter(watched, event)

    def refresh(self, *_):
        viewport = self.parentWidget()
        self.setGeometry(0, max(0, viewport.height() - 18), viewport.width(), 18)
        self.setVisible(self.bar.value() < self.bar.maximum())
        self.raise_()

    def paintEvent(self, event):
        solid = QColor(self.background)
        transparent = QColor(solid)
        transparent.setAlpha(0)
        fade = QLinearGradient(0, 0, 0, self.height())
        fade.setColorAt(0, transparent)
        fade.setColorAt(1, solid)
        with QPainter(self) as painter:
            painter.fillRect(self.rect(), fade)


class ComposerPanel(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.setObjectName("composerPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        editor.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("editing", event.type() == QEvent.Type.FocusIn)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        return super().eventFilter(watched, event)


class ChatHighlights(QSyntaxHighlighter):
    def __init__(self, editor, *, spelling):
        super().__init__(editor.document())
        self.checker = WindowsSpellChecker() if spelling else None
        if self.checker is not None:
            editor.destroyed.connect(self.checker.close)
        self.mark = QTextCharFormat()
        self.mark.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        self.mark.setUnderlineColor(QColor("#e45b68"))
        self.link = QTextCharFormat()
        self.link.setAnchor(True)
        self.link.setFontUnderline(True)
        self.link.setForeground(editor.palette().link())

    def set_link_background(self, background):
        self.link.setForeground(QColor(link_color(background)))
        self.rehighlight()

    def highlightBlock(self, text):
        # shortcut: limita cada párrafo para mantener la escritura fluida al pegar texto largo.
        if self.checker is not None and len(text) <= 4000:
            prose = UNCHECKED.sub(lambda match: " " * utf16_length(match[0]), text)
            for start, length in self.checker.errors(prose):
                self.setFormat(start, length, self.mark)
        for match in UNCHECKED.finditer(text):
            if (address := match["url"]) is None:
                continue
            address = address.rstrip(".,;:!?")
            for opening, closing in ("()", "[]", "{}"):
                while address.endswith(closing) and address.count(closing) > address.count(opening):
                    address = address[:-1].rstrip(".,;:!?")
            url = QUrl(address, QUrl.ParsingMode.StrictMode)
            if url.isValid() and url.host():
                self.link.setAnchorHref(address)
                self.setFormat(utf16_length(text[:match.start()]), utf16_length(address), self.link)


class ChatText(QTextEdit):
    def __init__(self, scroll_area=None):
        super().__init__()
        self.scroll_area = scroll_area
        self.setAcceptRichText(False)
        self.setReadOnly(scroll_area is not None)
        self.highlights = ChatHighlights(self, spelling=scroll_area is None)
        self.pressed_link = None
        self.setTabChangesFocus(True)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if scroll_area is not None:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.fit_height(self.document().size())

    @staticmethod
    def highlight_at(cursor):
        position = cursor.positionInBlock()
        return next((item for item in cursor.block().layout().formats()
                     if item.start <= position < item.start + item.length), None)

    def link_at(self, position):
        item = self.highlight_at(self.cursorForPosition(position))
        return item.format.anchorHref() if item else ""

    def mousePressEvent(self, event):
        self.pressed_link = None
        if event.button() == Qt.MouseButton.LeftButton and (
            self.isReadOnly() or event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            point = event.position().toPoint()
            if link := self.link_at(point):
                self.pressed_link = point, link
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        pressed, self.pressed_link = self.pressed_link, None
        super().mouseReleaseEvent(event)
        if pressed and event.button() == Qt.MouseButton.LeftButton:
            start, link = pressed
            point = event.position().toPoint()
            if (point - start).manhattanLength() < QApplication.startDragDistance() and self.link_at(point) == link:
                open_web_link(QUrl(link))

    def contextMenuEvent(self, event):
        menu = style_chat_menu(self.createStandardContextMenu(event.pos()))
        cursor = (self.textCursor() if event.reason() == QContextMenuEvent.Reason.Keyboard
                  else self.cursorForPosition(event.pos()))
        item = self.highlight_at(cursor)
        first = next(iter(menu.actions()), None)
        if item and (link := item.format.anchorHref()):
            action = menu.addAction("Abrir enlace", lambda: open_web_link(QUrl(link)))
            menu.insertAction(first, action)
            menu.insertSeparator(first)
        elif item and self.highlights.checker is not None:
            start = cursor.block().position() + item.start
            cursor.setPosition(start)
            cursor.setPosition(start + item.length, QTextCursor.MoveMode.KeepAnchor)
            choices = self.highlights.checker.suggestions(cursor.selectedText())
            for choice in choices:
                action = menu.addAction(choice.replace("&", "&&"),
                                        lambda _checked=False, value=choice: cursor.insertText(value))
                menu.insertAction(first, action)
            if choices:
                menu.insertSeparator(first)
        menu.exec(event.globalPos())
        menu.deleteLater()

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
        self.expand_button.setProperty("quiet", True)
        self.expand_button.setCheckable(True)
        self.expand_button.toggled.connect(self.expand_editor)
        self.expand_editor(False)
        self.shortcut_source = None
        self.shortcut_choices = {}
        self.shortcut_model = QStringListModel(self)
        self.shortcuts = QCompleter(self.shortcut_model, self)
        self.shortcuts.setWidget(self)
        self.shortcuts.setMaxVisibleItems(7)
        self.shortcuts.popup().setObjectName("composerSuggestions")
        self.shortcuts.popup().setAccessibleName("Sugerencias del chat")
        self.shortcuts.activated[str].connect(self.apply_shortcut)

    def expand_editor(self, expanded):
        self.expand_button.setText("⤡" if expanded else "⤢")
        label = "Reducir editor" if expanded else "Ampliar editor"
        self.expand_button.setAccessibleName(label)
        self.expand_button.setToolTip(label)
        self.fit_height(self.document().size())
        self.ensureCursorVisible()

    def set_theme(self, theme, stylesheet):
        self.highlights.set_link_background(control_colors(theme["background"])[0])
        self.shortcuts.popup().setStyleSheet(stylesheet)

    def fit_height(self, size):
        available = self.window().height()
        if hasattr(self, "expand_button") and self.expand_button.isChecked():
            height = max(105, min(600, available * 3 // 5))
        else:
            height = min(160, max(68, available // 3), max(68, ceil(size.height()) + 2 * self.frameWidth()))
        self.setFixedHeight(height)

    def keyPressEvent(self, event):
        if self.shortcuts.popup().isVisible() and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape,
        ):
            event.ignore()
            return
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        if event.text() or event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.suggest_shortcuts()

    def shortcut_token(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            return None
        prefix = QTextCursor(cursor)
        prefix.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        match = SHORTCUT_TOKEN.search(prefix.selectedText())
        if match is None or (match[1] in "/>!" and cursor.position() != utf16_length(match[1] + match[2])):
            return None
        return match

    def suggest_shortcuts(self):
        popup = self.shortcuts.popup()
        match = self.shortcut_token()
        if not match or self.shortcut_source is None:
            popup.hide()
            return
        symbol, query = match[1], match[2].casefold()
        self.shortcut_choices = {}
        for label, replacement, action in self.shortcut_source(symbol):
            name = label.casefold()
            matches = name.startswith("/" + query) if symbol == "/" else query in name
            if matches:
                self.shortcut_choices[label] = replacement, action
        if not self.shortcut_choices:
            popup.hide()
            return
        self.shortcut_model.setStringList(list(self.shortcut_choices))
        rect = self.cursorRect()
        rect.setWidth(min(360, max(210, self.width())))
        self.shortcuts.complete(rect)
        popup.setCurrentIndex(self.shortcuts.completionModel().index(0, 0))

    def apply_shortcut(self, label):
        match = self.shortcut_token()
        choice = self.shortcut_choices.get(label)
        if match is None or choice is None:
            return
        self.shortcuts.popup().hide()
        replacement, action = choice
        cursor = self.textCursor()
        cursor.setPosition(cursor.position() - utf16_length(match[1] + match[2]), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        self.setTextCursor(cursor)
        if action is not None:
            action()

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
    def __init__(self, file, *, draft=False):
        super().__init__()
        self.setObjectName("draftAttachmentCard" if draft else "attachmentCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        badge = QLabel()
        badge.setObjectName("attachmentBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(138 if draft else 44, 65 if draft else 36)
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
            badge.setText(suffix if suffix in {"PDF", "TXT", "MD", "CSV", "TSV", "LOG", "JSON", "DOCX", "XLSX", "PPTX"}
                          else "DOC")
        display = attachment_label(file) + (" · parcial" if file.get("partial") else "")
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        label.setToolTip(display)
        label.setAccessibleName(display)
        if draft:
            self.setFixedSize(152, 100)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(7, 5, 7, 5)
            layout.setSpacing(3)
            preview = QGridLayout()
            preview.addWidget(badge, 0, 0)
            self.remove = secondary_button(QPushButton("×"))
            self.remove.setObjectName("removeDraftAttachment")
            self.remove.setAccessibleName(f"Quitar {file['name']}")
            self.remove.setToolTip("Quitar adjunto")
            self.remove.setFixedSize(22, 22)
            preview.addWidget(self.remove, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            self.remove.raise_()
            layout.addLayout(preview)
            label.setObjectName("draftAttachmentName")
            label.setText(label.fontMetrics().elidedText(display, Qt.TextElideMode.ElideRight, 132))
            layout.addWidget(label, 1)
        else:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(8, 5, 8, 5)
            layout.setSpacing(8)
            label.setText(display if len(display) <= 48 else display[:45] + "…")
            layout.addWidget(badge)
            layout.addWidget(label, 1)


class AttachmentStrip(QScrollArea):
    def wheelEvent(self, event):
        bar = self.horizontalScrollBar()
        if event.angleDelta().y() and not event.angleDelta().x() and bar.maximum():
            bar.setValue(bar.value() - event.angleDelta().y())
            event.accept()
        else:
            super().wheelEvent(event)


class AttachmentTray(QWidget):
    problem = Signal(str)

    def __init__(self):
        super().__init__()
        self.files = []
        body = QWidget()
        body.setObjectName("attachmentStripBody")
        self.rows = QHBoxLayout(body)
        self.rows.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.rows.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.scroll = AttachmentStrip()
        self.scroll.setObjectName("attachmentStrip")
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(110)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(body)
        self.scroll.viewport().setAutoFillBackground(False)
        body.setAutoFillBackground(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)
        self.add_button = secondary_button(PopupButton("+", above=True))
        self.add_button.setObjectName("composerAdd")
        self.add_button.setProperty("quiet", True)
        self.add_button.setAccessibleName("Opciones del chat")
        self.add_button.setToolTip("Adjuntos, MCP y memoria")
        self.menu = self.add_button.menu()
        self.menu.addAction("Adjuntar archivos…", self.choose)
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
        row = AttachmentCard(file, draft=True)
        row.remove.clicked.connect(lambda: self.remove_row(row))
        self.rows.addWidget(row)
        self.show()
        self.scroll.ensureWidgetVisible(row, 0, 0)

    def remove_row(self, row):
        del self.files[self.rows.indexOf(row)]
        self.rows.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.setVisible(bool(self.files))

    def clear(self):
        while self.rows.count():
            self.remove_row(self.rows.itemAt(0).widget())

    def clear_project_documents(self):
        for index in reversed(range(len(self.files))):
            if "project_document" in self.files[index]:
                self.remove_row(self.rows.itemAt(index).widget())


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
        self.mascot_row = QWidget()
        mascot_layout = QHBoxLayout(self.mascot_row)
        mascot_layout.setContentsMargins(0, 0, 0, 0)
        mascot_layout.setSpacing(8)
        self.mascot = SpriteLabel(40)
        self.mascot_caption = QLabel("StoneBot está pensando…")
        mascot_layout.addWidget(self.mascot)
        mascot_layout.addWidget(self.mascot_caption, 1)
        self.mascot_row.hide()
        self.mascot_timer = QTimer(self)
        self.mascot_timer.setSingleShot(True)
        self.mascot_timer.timeout.connect(self.hide_mascot)
        layout.addWidget(self.mascot_row)
        layout.addLayout(controls)
        layout.addWidget(self.detail)
        self.detail.hide()

    def show_mascot(self, animation):
        self.mascot_animation = animation
        animation.frame_changed.connect(self.mascot.set_frame)
        self.mascot_row.show()

    def hide_mascot(self):
        self.mascot_animation.frame_changed.disconnect(self.mascot.set_frame)
        self.mascot_row.hide()

    def finish_mascot(self, success, *, cancelled):
        if success:
            caption = "Respuesta lista"
        elif cancelled:
            caption = "Respuesta detenida"
        else:
            caption = "Error en la respuesta"
        self.mascot_caption.setText(caption)
        self.mascot_timer.start(2000)

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


CHAT_STYLESHEET = Template(Path(__file__).with_name("chat.qss").read_text(encoding="utf-8"))


def chat_style(theme):
    background, accent = theme["background"], theme["accent"]
    user, bot = theme["user_message"], theme["bot_message"]
    size = theme["font_size"]
    message_font = "11pt" if size == DEFAULT_FONT_SIZE else f"{size}px"
    sidebar = shade(background, .035)
    surface, edge, secondary, text = control_colors(background)
    menu_surface = shade(surface, .075)
    border_ink = QColor(readable_text(menu_surface))
    colors = dict(
        background=background, surface=surface, text=text, accent=accent,
        window_text=readable_text(background), accent_text=readable_text(accent),
        user=user, user_text=readable_text(user), bot=bot, bot_text=readable_text(bot),
        secondary=secondary, edge=edge, subtle_edge=shade(background, .13),
        muted=shade(background, .63), focus=link_color(background), disabled_text=shade(surface, .55),
        sidebar=sidebar, sidebar_hover=shade(sidebar, .07), sidebar_active=shade(sidebar, .14),
        quiet_checked=shade(background, .09), scroll_thumb=shade(background, .28),
        shared_scroll_thumb=shade(background, .4),
        code_surface=shade(bot, .08), code_edge=shade(bot, .20), code_thumb=shade(bot, .28),
        draft_surface=shade(surface, .045), draft_thumb=shade(surface, .25),
        badge=shade(surface, .09), placeholder=shade(surface, .65),
        status_ok="#86efac" if readable_text(surface) == "#ffffff" else "#126133",
        status_error="#fca5a5" if readable_text(surface) == "#ffffff" else "#a32929",
        menu_surface=menu_surface,
        menu_border=f"rgba({border_ink.red()}, {border_ink.green()}, {border_ink.blue()}, 48)",
    )
    for name, color, amount in (
        ("primary_hover", accent, .09), ("primary_pressed", accent, .16),
        ("secondary_hover", secondary, .10), ("secondary_pressed", secondary, .18),
        ("quiet_hover", background, .11), ("quiet_pressed", background, .17),
    ):
        colors[name] = shade(color, amount)
        colors[f"{name}_text"] = readable_text(colors[name])
    return CHAT_STYLESHEET.substitute(colors, message_font=message_font)

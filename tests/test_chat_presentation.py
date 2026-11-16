"""Pruebas de apariencia, Markdown y regeneración transaccional."""
import json
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMessageBox, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import mcp_client
from chat_markdown import CodeCard
from appearance import (
    AppearanceDialog, ColorEditor, ORIGINAL, PRESETS, XCODE, appearance_settings, control_colors,
    custom_themes, link_color, load_appearance, shade,
)
from history import History
from win_caption import CAPTION_COLOR, SYSTEM_COLOR, TEXT_COLOR, colorref, set_caption_colors


def test_default_and_legacy():
    original = {key: load_appearance()[key] for key in PRESETS[ORIGINAL]}
    assert original == dict(accent="#5d8cc2", background="#222831", user_message="#294461", bot_message="#282f38")
    settings = appearance_settings()
    settings.setValue("theme", "StoneBot")
    settings.setValue("accent", "#AA8844")
    settings.setValue("font_size", 20)
    settings.sync()
    old = load_appearance()
    assert old["accent"] == "#aa8844" and old["background"] == "#19191e" and old["font_size"] == 20
    assert settings.value("theme") == "StoneBot"
    settings.clear()
    settings.sync()


def test_caption_colors():
    calls = []

    def set_attribute(attribute, color):
        calls.append((attribute, color))
        return -1 if (attribute, color) == (CAPTION_COLOR, colorref("#222831")) else 0

    assert not set_caption_colors(set_attribute, "#222831")
    assert calls == [(TEXT_COLOR, colorref("#ffffff")), (CAPTION_COLOR, colorref("#222831")),
                     (CAPTION_COLOR, SYSTEM_COLOR), (TEXT_COLOR, SYSTEM_COLOR)]


def test_existing_theme_named_xcode():
    settings = appearance_settings()
    previous = dict(PRESETS[ORIGINAL], accent="#446688")
    settings.setValue("custom_themes", json.dumps({XCODE: previous}))
    settings.setValue("theme", XCODE)
    for key, color in previous.items():
        settings.setValue(key, color)
    settings.sync()
    alias = "Xcode (personalizado)"
    assert custom_themes()[alias] == previous
    assert load_appearance()["named_theme"] == alias
    settings.clear()
    settings.sync()


def wait_for_turn(window):
    loop = QEventLoop()
    window.thread.finished.connect(loop.quit)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(15_000)
    loop.exec()
    assert window.thread is None


def test_appearance(window):
    panel = AppearanceDialog(window, window.appearance, window.change_appearance)
    for name, palette in PRESETS.items():
        index = panel.preset.findText(name)
        assert not panel.preset.itemIcon(index).isNull()
        panel.preset.setCurrentIndex(index)
        panel.select_preset(index)
        assert all(load_appearance()[key] == color for key, color in palette.items())
        assert panel.preset.currentText() == name
        if name == XCODE:
            reopened = app.StoneBot()
            assert all(reopened.appearance[key] == color for key, color in palette.items())
            assert reopened.settings_button.property("quiet")
            reopened.close()
    reopened = AppearanceDialog(window, load_appearance(), window.change_appearance)
    assert reopened.preset.currentText() == "SynthWave '84"
    reopened.set_color("accent", "#113355")
    with patch.object(QInputDialog, "getText", return_value=("Acero", True)):
        reopened.save_theme.click()
    reopened.set_color("accent", "#224488")
    with patch.object(QInputDialog, "getText", return_value=("Azul", True)):
        reopened.save_theme.click()
    reopened.apply_named("Acero")
    with patch.object(QInputDialog, "getText", return_value=("Medianoche", True)):
        reopened.rename_theme.click()
    assert set(custom_themes()) == {"Medianoche", "Azul"}
    assert load_appearance()["named_theme"] == "Medianoche"
    with (patch.object(QInputDialog, "getText", return_value=("stonebot original", True)),
          patch.object(QMessageBox, "warning") as warning):
        reopened.save_theme.click()
    warning.assert_called_once()
    assert set(custom_themes()) == {"Medianoche", "Azul"}
    reopened.apply_named("Azul")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        reopened.delete_theme.click()
    assert set(custom_themes()) == {"Medianoche"}
    assert "named_theme" not in load_appearance()
    reopened.apply_named(ORIGINAL)
    assert not reopened.rename_theme.isEnabled() and not reopened.delete_theme.isEnabled()
    reopened.apply_named("Medianoche")
    editor = ColorEditor(window, "Acento", "#ffffff", window.appearance)
    editor.slots.button(3).click()
    assert editor.color.name() == "#ffffff" and "Vacío" in editor.slots.button(3).text()
    editor.save_slot.click()
    assert editor.favorite(3) == "#ffffff" and "Vacío" not in editor.slots.button(3).text()
    editor.color = QColor("#00aa88")
    editor.refresh()
    editor.slots.button(3).click()
    assert editor.color.name() == "#00aa88"
    restored = ColorEditor(window, "Acento", "#000000", window.appearance)
    restored.slots.button(3).click()
    assert restored.color.name() == "#000000"
    restored.use_slot.click()
    assert restored.color.name() == "#ffffff"
    restored.slots.button(4).click()
    restored.save_slot.click()
    restored.set_color(QColor("#990088"))
    restored.save_slot.click()
    assert restored.favorite(4) == "#990088"
    restored.clear_slot.click()
    assert not restored.favorite(4) and restored.color.name() == "#990088"
    subprocess.run([sys.executable, "-B", "-c", """
import sys
from pathlib import Path
from unittest.mock import patch
import mcp_client
from appearance import appearance_settings, custom_themes, load_appearance, preset_name
with patch.object(mcp_client, "default_root", return_value=Path(sys.argv[1])):
    assert preset_name(load_appearance()) == "Medianoche"
    assert custom_themes()["Medianoche"]["accent"] == "#113355"
    assert appearance_settings().value("favorites/3") == "#ffffff"
    assert not appearance_settings().value("favorites/4")
""", str(window.history.path.parent)], cwd=Path(__file__).resolve().parents[1], check=True, timeout=15)


def test_markdown(window):
    source = ("### Título\n\n**Negrita** y *cursiva* con `inline` y [enlace](https://example.test).\n\n"
              "1. Uno\n2. Dos\n\n- Viñeta\n\nSi hay $N$ elementos, el límite es $N-1$. El precio es $10.\n\n"
              "```python\ndef ejemplo():\n    return 1 < 2\n```\n\n"
              "Otra sección con `$N$`.\n\n```python\nprint('segundo')\n```")
    chat = window.history.append(None, "user", "Prueba Markdown")
    window.history.append(chat, "assistant", source)
    window.open_chat(chat)
    body = window.chat.findChild(app.MarkdownText)
    prose = body.parts[0]
    document = prose.document()
    assert document.firstBlock().blockFormat().headingLevel() == 3
    assert document.find("Negrita").charFormat().fontWeight() >= 700
    assert document.find("cursiva").charFormat().fontItalic()
    assert document.find("enlace").charFormat().anchorHref() == "https://example.test"
    assert document.find("Uno").block().textList() and document.find("Viñeta").block().textList()
    assert document.find("inline").charFormat().fontFixedPitch() or document.find("inline").charFormat().fontFamilies()
    first, second = body.findChildren(CodeCard)
    assert [part.source for part in (first, second)] == ["def ejemplo():\n    return 1 < 2", "print('segundo')"]
    assert first.text.document().find("def").charFormat().foreground().color() != first.text.document().find("ejemplo").charFormat().foreground().color()
    assert first.findChild(QLabel, "codeLanguage").text() == "Python"
    mixed = app.MarkdownText(window.chat, "    a = 0\n\n```py\nb = 1\n```\n```py\nc = 2\n```", window.appearance)
    assert [part.source for part in mixed.parts] == ["a = 0", "b = 1", "c = 2"]
    assert "**Negrita**" not in body.toPlainText()
    assert "límite es N−1" in prose.toPlainText() and "precio es $10" in prose.toPlainText()
    assert "$N$" in body.parts[2].toPlainText()
    first.copy.click()
    assert QApplication.clipboard().text() == first.source
    second.copy.click()
    assert QApplication.clipboard().text() == second.source
    buttons = window.chat.findChildren(QPushButton)
    assert not any(button.text().startswith("Copiar código") for button in buttons)
    next(button for button in buttons if button.text() == "Copiar" and button.parent() is body.parent()).click()
    assert QApplication.clipboard().text() == source
    with patch.object(QDesktopServices, "openUrl") as browser:
        prose.anchorClicked.emit(QUrl("file:///tmp/blocked"))
        browser.assert_not_called()
        prose.anchorClicked.emit(QUrl("https://example.test"))
        browser.assert_called_once()
    window.new_chat()
    QTest.qWait(10)
    window.open_chat(chat)
    reopened = window.chat.findChild(app.MarkdownText)
    assert [card.source for card in reopened.findChildren(CodeCard)] == [part.source for part in (first, second)]


def test_regeneration(window):
    db = window.history
    chat = db.append(None, "user", "Primera pregunta")
    db.append(chat, "assistant", "Primera respuesta")
    db.append(chat, "user", "Pregunta anterior")
    db.append(chat, "assistant", "Respuesta anterior")
    other = db.append(None, "user", "Otra conversación")
    window.open_chat(chat)
    before = db.messages(chat)
    assert before[-1]["created"] and window.activity_panel is None

    def reply(**kwargs):
        assert [m["content"] for m in kwargs["messages"][1:]] == [
            "Primera pregunta", "Primera respuesta", "Pregunta editada"
        ]
        assert db.messages(chat) == before
        return SimpleNamespace(message=Message(role="assistant", content="Respuesta nueva", thinking="Traza del modelo"))

    with (patch.object(app, "load_servers", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=reply))):
        window.regenerate(2, "Pregunta editada")
        pending = window.activity_panel
        assert window.transcript.itemAt(window.transcript.count() - 2).widget() is pending
        assert "Procesando" in pending.summary.toolTip() and not pending.detail.isVisible()
        wait_for_turn(window)
    after = db.messages(chat)
    assert [item["content"] for item in after] == [
        "Primera pregunta", "Primera respuesta", "Pregunta editada", "Respuesta nueva"
    ]
    assert after[:2] == before[:2] and db.messages(other)[0]["content"] == "Otra conversación"
    assert window.transcript.itemAt(window.transcript.count() - 3).widget() is pending
    assert not pending.detail.isVisible()
    assert "Traza del modelo" in pending.reasoning.toPlainText()
    pending.summary.click()
    assert pending.detail.isVisible() and not pending.reasoning.isVisible()
    window.activity_panel.show_reasoning.click()
    assert window.activity_panel.reasoning.isVisible()
    assert "Esperando" in window.activity_panel.events.toPlainText()

    with (patch.object(app, "load_servers", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(
              chat=lambda **kw: SimpleNamespace(message=Message(role="assistant", content=""))))):
        window.regenerate(2, "Edición sin respuesta")
        wait_for_turn(window)
    assert db.messages(chat) == after and window.messages[1:] == after
    assert "conservó" in window.problem.text()
    assert "Error del turno" in window.activity_panel.summary.toolTip()
    assert window.activity_panel.show_reasoning.isHidden()
    window.open_chat(other)
    assert window.activity_panel is None


def test_button_styles(window):
    window.activateWindow()
    recent = window.history.append(None, "user", "Control de apariencia")
    window.open_chat(recent)
    QApplication.processEvents()
    actions = {button.text(): button for button in window.chat.findChildren(QPushButton)
               if button.isVisible()}
    assert actions["Editar"].focusPolicy() == Qt.FocusPolicy.TabFocus
    copy = actions["Copiar"]

    def sample(button, *, border=False):
        QApplication.processEvents()
        image = button.grab().toImage()
        x, y = (button.width() // 2, 1) if border else (4, button.height() // 2)
        scale = image.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale)).name()

    for palette in PRESETS.values():
        window.change_appearance(dict(window.appearance, **palette))
        QTest.mouseMove(window.message, window.message.rect().center())
        normal = control_colors(palette["background"])[2]
        assert sample(copy) == normal

    palette = PRESETS[ORIGINAL]
    window.change_appearance(dict(window.appearance, **palette))
    field, edge, normal, _ = control_colors(palette["background"])
    window.message.setFocus()
    QTest.mouseMove(copy, copy.rect().center())
    assert sample(copy) == shade(normal, .10)
    QTest.mousePress(copy, Qt.MouseButton.LeftButton, pos=copy.rect().center())
    assert sample(copy) == shade(normal, .18)
    QTest.mouseRelease(copy, Qt.MouseButton.LeftButton, pos=copy.rect().center())
    assert not copy.isDown() and not copy.hasFocus()
    assert QApplication.clipboard().text() == "Control de apariencia"
    QTest.mouseMove(window.message, window.message.rect().center())
    assert sample(copy) == normal and sample(copy, border=True) == edge
    copy.setFocus(Qt.FocusReason.TabFocusReason)
    assert copy.hasFocus() and sample(copy, border=True) == link_color(palette["background"])
    copy.setEnabled(False)
    assert sample(copy) == field
    copy.setEnabled(True)
    window.message.clear()
    QTest.qWait(50)
    controls = window.attachments.add_button, window.send
    def positions():
        return [button.mapTo(window, QPoint()) for button in controls]

    anchors = positions()
    script = "def prueba():\n" + "".join(f"    print({n})\n" for n in range(300))
    QApplication.clipboard().setText(script)
    window.message.paste()
    QTest.qWait(50)
    assert window.message.toPlainText() == script and positions() == anchors
    bar = window.message.verticalScrollBar()
    assert bar.maximum() > 0
    assert window.message.viewport().mapTo(window.message, QPoint()).x() + window.message.viewport().width() <= bar.mapTo(window.message, QPoint()).x()
    collapsed = window.message.height()
    window.message.expand_button.click()
    QTest.qWait(50)
    assert window.message.height() > collapsed and positions() == anchors
    bar.setValue(0)
    assert positions() == anchors and window.message.toPlainText() == script
    window.message.expand_button.click()
    QTest.qWait(50)
    assert window.message.height() == collapsed and positions() == anchors
    window.message.clear()


def test_history_panel_and_timestamps(window):
    window.open_chat(1)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not window.chat.findChildren(QLabel, "messageTime")
    assert History().messages(1)[0]["created"] is None

    recent = window.history.append(None, "user", "Hora disponible")
    title = "Una conversación con un título largo " * 30
    window.history.rename(recent, title.strip())
    window.open_chat(recent)
    QApplication.processEvents()
    assert any(label.isVisible() and ":" in label.text() for label in window.chat.findChildren(QLabel, "messageTime"))

    history_list = window.history_panel.list
    item = history_list.currentItem()
    assert item.toolTip() == title.strip()
    assert history_list.textElideMode() == Qt.TextElideMode.ElideRight
    assert history_list.horizontalScrollBar().maximum() == 0
    assert history_list.visualItemRect(item).width() <= history_list.viewport().width()
    before = window.history_panel.width()
    handle = window.history_splitter.handle(1)
    point = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(handle, point + QPoint(90, 0))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point)
    QApplication.processEvents()
    width = window.history_panel.width()
    assert width > before and window.history_width == width
    assert history_list.visualItemRect(item).width() <= history_list.viewport().width()
    window.history_button.click()
    window.history_button.click()
    assert window.history_panel.width() == width
    window.close()
    assert appearance_settings().value("history_width", type=int) == width
    reopened = app.StoneBot()
    reopened.show()
    QApplication.processEvents()
    assert reopened.history_panel.width() == width
    reopened.close()


if __name__ == "__main__":
    qt = QApplication([])
    qt.setStyle("Fusion")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with closing(sqlite3.connect(root / "conversations.sqlite3")) as conn, conn:
            conn.executescript("""
                CREATE TABLE chat(id INTEGER PRIMARY KEY, title TEXT, updated INTEGER);
                CREATE TABLE message(id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT);
                INSERT INTO chat VALUES (1, 'Anterior', 0);
                INSERT INTO message VALUES (1, 1, 'user', 'Mensaje anterior');
            """)
        with patch.object(mcp_client, "default_root", return_value=root):
            test_default_and_legacy()
            test_existing_theme_named_xcode()
            test_caption_colors()
            assert History().messages(1)[0]["created"] is None
            window = app.StoneBot()
            window.show()
            test_appearance(window)
            test_markdown(window)
            test_regeneration(window)
            test_button_styles(window)
            test_history_panel_and_timestamps(window)
    print("PASS: apariencia, Markdown, actividad, historial, botón Enviar, estados, ancho y horas.")

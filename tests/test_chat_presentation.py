"""Pruebas de apariencia, Markdown y regeneración transaccional."""
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import mcp_client
from appearance import AppearanceDialog, ColorEditor, PRESETS, load_appearance
from history import History


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
    reopened = AppearanceDialog(window, load_appearance(), window.change_appearance)
    assert reopened.preset.currentText() == "SynthWave '84"
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
    subprocess.run([sys.executable, "-B", "-c", """
import sys
from pathlib import Path
from unittest.mock import patch
import mcp_client
from appearance import appearance_settings, load_appearance, preset_name
with patch.object(mcp_client, "default_root", return_value=Path(sys.argv[1])):
    assert preset_name(load_appearance()) == "SynthWave '84"
    assert appearance_settings().value("favorites/3") == "#ffffff"
""", str(window.history.path.parent)], cwd=Path(__file__).resolve().parents[1], check=True, timeout=15)


def test_markdown(window):
    source = ("### Título\n\n**Negrita** y *cursiva* con `inline` y [enlace](https://example.test).\n\n"
              "1. Uno\n2. Dos\n\n- Viñeta\n\n```python\nx = 1\n```\n\n~~~text\ny = 2\n~~~")
    window.append_message(source)
    body = window.chat.findChild(app.MarkdownText)
    document = body.document()
    assert document.firstBlock().blockFormat().headingLevel() == 3
    assert document.find("Negrita").charFormat().fontWeight() >= 700
    assert document.find("cursiva").charFormat().fontItalic()
    assert document.find("enlace").charFormat().anchorHref() == "https://example.test"
    assert document.find("Uno").block().textList() and document.find("Viñeta").block().textList()
    assert document.find("inline").charFormat().fontFixedPitch() or document.find("inline").charFormat().fontFamilies()
    assert body.code == ["x = 1", "y = 2"]
    mixed = app.MarkdownText(window.chat, "    a = 0\n\n```py\nb = 1\n```\n\n```py\nc = 2\n```")
    assert mixed.code == ["a = 0", "b = 1", "c = 2"]
    assert "**Negrita**" not in body.toPlainText()
    buttons = {button.text(): button for button in window.chat.findChildren(QPushButton)}
    buttons["Copiar código 2"].click()
    assert QApplication.clipboard().text() == "y = 2"
    buttons["Copiar"].click()
    assert QApplication.clipboard().text() == source
    with patch.object(QDesktopServices, "openUrl") as browser:
        body.anchorClicked.emit(QUrl("file:///tmp/blocked"))
        browser.assert_not_called()
        body.anchorClicked.emit(QUrl("https://example.test"))
        browser.assert_called_once()


def test_regeneration(window):
    db = window.history
    chat = db.append(None, "user", "Primera pregunta")
    db.append(chat, "assistant", "Primera respuesta")
    db.append(chat, "user", "Pregunta anterior")
    db.append(chat, "assistant", "Respuesta anterior")
    other = db.append(None, "user", "Otra conversación")
    window.open_chat(chat)
    before = db.messages(chat)
    assert before[-1]["created"] and not window.activity_panel.isVisible()

    def reply(**kwargs):
        assert [m["content"] for m in kwargs["messages"][1:]] == [
            "Primera pregunta", "Primera respuesta", "Pregunta editada"
        ]
        assert db.messages(chat) == before
        return SimpleNamespace(message=Message(role="assistant", content="Respuesta nueva", thinking="Traza del modelo"))

    with (patch.object(app, "load_servers", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=reply))):
        window.regenerate(2, "Pregunta editada")
        wait_for_turn(window)
    after = db.messages(chat)
    assert [item["content"] for item in after] == [
        "Primera pregunta", "Primera respuesta", "Pregunta editada", "Respuesta nueva"
    ]
    assert after[:2] == before[:2] and db.messages(other)[0]["content"] == "Otra conversación"
    assert not window.activity_panel.isVisible()
    assert "Traza del modelo" in window.activity_panel.reasoning.toPlainText()
    window.activity_button.click()
    assert window.activity_panel.isVisible() and not window.activity_panel.reasoning.isVisible()
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


if __name__ == "__main__":
    qt = QApplication([])
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
            assert History().messages(1)[0]["created"] is None
            window = app.StoneBot()
            window.show()
            test_appearance(window)
            test_markdown(window)
            test_regeneration(window)
            window.close()
    print("PASS: temas, favoritos, Markdown, copia, actividad, migración y edición del historial.")

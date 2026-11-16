"""Historial, permisos y sesiones reutilizadas de StoneBot."""
import asyncio
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from threading import Event
from unittest.mock import AsyncMock, patch

from mcp.types import Tool, ToolAnnotations
from ollama import Message
from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QPushButton

from test_mcp import example_stdio
from test_chat_presentation import wait_for_turn
import app
import stonebot_service as memory_service
import mcp_client
from diagnostics import read_log
from history import History
from mcp_permissions import allowed, list_permissions, permission_signature, remember, revoke, safe_read
from mcp_pool import McpPool


def test_sueno_espera_inactividad_y_se_serializa_con_el_turno():
    window = app.StoneBot()
    sueno_iniciado, liberar_sueno, conversacion = Event(), Event(), Event()

    def dream(scope):
        assert scope == "memoria"
        sueno_iniciado.set()
        liberar_sueno.wait(10)

    async def chat(worker):
        conversacion.set()
        return "Turno sintético."

    try:
        window.show()
        with (patch.object(memory_service, "dream_if_due", side_effect=dream) as automatic,
              patch.object(app.Worker, "chat", chat)):
            window.check_automatic_dream()
            automatic.assert_not_called()
            window.last_activity = time.monotonic() - window.dream_idle_seconds - 1
            window.dream_timer.timeout.emit()
            assert sueno_iniciado.wait(5)
            window.check_automatic_dream()
            automatic.assert_called_once()

            window.message.setPlainText("Mensaje durante un sueño")
            window.enviar()
            assert not conversacion.wait(0.1)
            liberar_sueno.set()
            wait_for_turn(window)
            assert conversacion.is_set()
            assert History().messages(window.chat_id)[-1]["content"] == "Turno sintético."

            conversacion.clear()
            window.message.setPlainText("Segundo mensaje")
            window.enviar()
            window.last_activity = time.monotonic() - window.dream_idle_seconds - 1
            window.check_automatic_dream()
            automatic.assert_called_once()
            wait_for_turn(window)
            assert time.monotonic() - window.last_activity < 5
    finally:
        liberar_sueno.set()
        if window.dream_thread is not None:
            window.dream_thread.join()
        if window.thread is not None:
            wait_for_turn(window)
        window.close()
    assert not window.dream_timer.isActive()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_history_and_gui(qt):
    db = History()
    first = db.append(None, "user", "  Consulta   técnica sobre Qt")
    db.append(first, "assistant", "Usa QVBoxLayout para la distribución.")
    recent = db.append(None, "user", "Otra conversación")
    assert [chat_id for chat_id, _ in db.find()] == [recent, first]
    assert db.find("TÉCNICA") == [(first, "Consulta técnica sobre Qt")]
    assert db.find("QVBoxLAYOUT")[0][0] == first
    assert db.find("%") == []

    window = app.StoneBot()
    window.show()
    for can_remember, choice in ((True, "Permitir siempre"), (False, "Denegar")):
        request = {"server": "web", "tool": "search", "arguments": {}, "approved": False,
                   "remember": False, "can_remember": can_remember}
        options = []

        def decide():
            dialog = QApplication.activeModalWidget()
            options.extend(button.text() for button in dialog.buttons())
            button = next((button for button in dialog.buttons() if button.text() == choice), None)
            if button is not None:
                button.click()
            else:
                dialog.reject()

        QTimer.singleShot(0, decide)
        window.confirmar_mcp(request)
        assert request["approved"] is can_remember and request["remember"] is can_remember
        assert ("Permitir siempre" in options) is can_remember
    window.history_panel.search.setText("qvboxlayout")
    assert window.history_panel.list.count() == 1
    window.open_chat(first)
    assert [message["role"] for message in window.messages] == ["system", "user", "assistant"]
    saved = []
    original = app.Worker.chat

    async def instrument(worker):
        worker.mcp_notice.emit("Diagnóstico sintético de prueba")
        return await original(worker)

    def chat(**kwargs):
        saved.extend(kwargs["messages"])
        return SimpleNamespace(message=Message(role="assistant", content="Seguimos con el layout."))

    with (patch.object(app.Worker, "chat", instrument),
          patch.object(app, "load_servers", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
          patch.object(memory_service, "get_memory", side_effect=AssertionError("El historial no debe acceder a memoria."))):
        window.message.setPlainText("Continúa con el ejemplo")
        window.send.click()
        loop = QEventLoop()
        window.thread.finished.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(30_000)
        loop.exec()
    assert window.thread is None
    assert saved[-2]["content"] == "Usa QVBoxLayout para la distribución."
    assert History().messages(first)[-1]["content"] == "Seguimos con el layout."
    assert "Diagnóstico sintético" in read_log()
    bubbles = window.chat.findChildren(app.ChatText) + window.chat.findChildren(app.MarkdownText)
    assert all("Diagnóstico sintético" not in w.toPlainText() for w in bubbles)

    window.history_panel.search.clear()
    view = window.history_panel.list
    assert not any(button.text() in ("Renombrar", "Eliminar") for button in window.history_panel.findChildren(QPushButton))

    def hover_second_chat():
        item = next(view.item(row) for row in range(view.count())
                    if view.item(row).data(Qt.ItemDataRole.UserRole) == recent)
        center = view.visualItemRect(item).center()
        QTest.mouseMove(view.viewport(), view.viewport().rect().bottomLeft())
        QTest.mouseMove(view.viewport(), center)
        QApplication.processEvents()
        assert view.options.isVisible() and view.hovered is item

    def choose(text):
        selected = []

        def select():
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                menu.setActiveAction(next(action for action in menu.actions() if action.text() == text))
                selected.append(text)
                QTest.keyClick(menu, Qt.Key.Key_Return)

        QTimer.singleShot(0, select)
        view.options.click()
        assert selected == [text]

    assert view.options.isHidden()
    hover_second_chat()
    with patch.object(QInputDialog, "getText", return_value=("Nuevo título", True)) as dialog:
        choose("Renombrar")
        assert dialog.call_args.kwargs["text"] == "Otra conversación"
    assert History().find("nuevo título") == [(recent, "Nuevo título")]
    assert window.chat_id == first
    window.history_button.click()
    assert not window.history_panel.isVisible()
    window.history_button.click()
    assert window.history_panel.isVisible()
    hover_second_chat()
    QApplication.sendEvent(view.viewport(), QEvent(QEvent.Type.Leave))
    assert view.options.isHidden()
    hover_second_chat()
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        choose("Eliminar")
    assert len(db.find()) == 2
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        choose("Eliminar")
    assert len(db.find()) == 1 and window.chat_id == first
    window.new_chat()
    assert window.chat_id is None and len(window.messages) == 1
    with closing(sqlite3.connect(db.path)) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not (db.path.parent / "memoria.db").exists()
    window.close()
    window.deleteLater()
    qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt.processEvents()


async def test_permissions():
    config = {"transport": "http", "url": "https://example.test/mcp"}
    hints = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
    reader = Tool(name="search", inputSchema={"type": "object"}, annotations=hints)
    danger = Tool(name="delete_file", inputSchema={"type": "object"}, annotations=hints)
    signature = permission_signature(config, reader)
    assert safe_read(reader) and not safe_read(danger)
    assert not safe_read(reader, {"params": {"action": "delete"}})
    assert not safe_read(Tool(name="search", inputSchema={"type": "object"}))

    worker = app.Worker([])
    requests = []

    def decision(request):
        requests.append(request.copy())
        request.update(approved=True, remember=len(requests) == 2)

    worker.mcp_confirmation.connect(decision, Qt.ConnectionType.DirectConnection)
    worker.permission = signature
    assert await worker.confirm_external("web", "search", {})
    assert not list_permissions("web")
    assert await worker.confirm_external("web", "search", {})
    assert len(requests) == 2 and all(r["can_remember"] for r in requests)
    restarted = app.Worker([])
    restarted.permission = signature
    assert await restarted.confirm_external("web", "search", {})
    assert list_permissions("web") == ["search"]
    assert not allowed("web", "search", permission_signature(dict(config, url="https://other.test/mcp"), reader))
    revoke("web", "search")
    assert not await restarted.confirm_external("web", "search", {})

    remember("web", "delete_file", permission_signature(config, danger))
    session = SimpleNamespace(call_tool=AsyncMock())
    denied = AsyncMock(return_value=False)
    assert "no autorizó" in await mcp_client.call_external((session, "web", danger, True), {}, denied)
    denied.assert_awaited_once()
    session.call_tool.assert_not_awaited()


async def test_pool(pool):
    args = example_stdio()
    cfg = dict(transport="stdio", command=sys.executable, args=["-B", "-c", args[-1]],
               enabled=True, read_tools=["echo"])
    await pool.prepare({"example": cfg})
    initial = await pool.entries("example", cfg)
    echo = next(entry for entry in initial.values() if entry[2].name == "echo")
    assert "Eco MCP: uno" in await mcp_client.call_external(echo, {"text": "uno"}, None)
    await pool.prepare({"example": cfg})
    assert await pool.entries("example", cfg) is initial
    assert "Eco MCP: dos" in await mcp_client.call_external(echo, {"text": "dos"}, None)
    changed = dict(cfg, disabled_tools=["mark"])
    await pool.prepare({"example": changed})
    updated = await pool.entries("example", changed)
    assert updated is not initial and [entry[2].name for entry in updated.values()] == ["echo"]
    await pool.prepare({})
    assert await pool.submit(check_closed(pool))


async def check_closed(pool):
    return not pool.slots


if __name__ == "__main__":
    qt_app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(mcp_client, "default_root", return_value=Path(directory)):
        test_history_and_gui(qt_app)
        test_sueno_espera_inactividad_y_se_serializa_con_el_turno()
        asyncio.run(test_permissions())
        client = McpPool()
        try:
            asyncio.run(test_pool(client))
        finally:
            client.close()
        assert not client.thread.is_alive()
    print("PASS: historial, búsqueda, registro técnico, permisos seguros y reutilización de sesiones.")

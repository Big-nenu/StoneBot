"""Historial, permisos y sesiones reutilizadas de StoneBot."""
import asyncio
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import Tool, ToolAnnotations
from ollama import Message
from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from test_mcp import example_stdio
import app
import mcp_client
from diagnostics import read_log
from history import History
from mcp_permissions import allowed, list_permissions, permission_signature, remember, revoke, safe_read
from mcp_pool import McpPool


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
          patch.object(app, "get_memory", side_effect=AssertionError("El historial no debe acceder a memoria."))):
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

    window.rename_chat(first, "Nuevo título")
    assert History().find("nuevo título") == [(first, "Nuevo título")]
    window.history_button.click()
    assert not window.history_panel.isVisible()
    window.history_button.click()
    assert window.history_panel.isVisible()
    window.new_chat()
    assert window.chat_id is None and len(window.messages) == 1
    window.history_panel.list.setCurrentRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        window.history_panel.remove.click()
    assert len(db.find()) == 2
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window.history_panel.remove.click()
    assert len(db.find()) == 1
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
        asyncio.run(test_permissions())
        client = McpPool()
        try:
            asyncio.run(test_pool(client))
        finally:
            client.close()
        assert not client.thread.is_alive()
    print("PASS: historial, búsqueda, registro técnico, permisos seguros y reutilización de sesiones.")

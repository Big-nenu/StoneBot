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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMenu, QMessageBox, QPushButton

from test_mcp import example_stdio
from test_chat_presentation import wait_for_turn
import app
import turn_worker
import stonebot_service as memory_service
import mcp_client
from diagnostics import read_log
from experiences import record_task_result, task_results
from history import History
from history_ui import NESTED_ROLE, PROJECT_ROLE, RAIL_WIDTH
from mcp_permissions import allowed, list_permissions, permission_signature, remember, revoke, safe_read
from mcp_pool import McpPool


def test_turno_no_activa_el_motor_anterior():
    window = app.StoneBot()

    async def chat(worker):
        return "Turno sintético."

    try:
        window.show()
        with (patch.object(memory_service, "get_memory", side_effect=AssertionError("Motor anterior")),
              patch.object(app.Worker, "chat", chat),
              patch.object(app.Worker, "capture_user_memories")):
            window.message.setPlainText("Mensaje de prueba")
            window.enviar()
            wait_for_turn(window)
            assert History().messages(window.chat_id)[-1]["content"] == "Turno sintético."
    finally:
        window.close()
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
          patch.object(turn_worker, "load_servers", return_value={}),
          patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=chat)),
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


def test_projects():
    window = app.StoneBot()
    window.show()

    def create(dialog):
        dialog.name.setText("Atom-Fusion")
        dialog.description.setPlainText("Juego local")
        dialog.instructions.setPlainText("Cita README y cambios recientes.")
        dialog.folder.setText(str(window.history.path.parent))
        return QDialog.DialogCode.Accepted

    async def reply(worker):
        assert worker.project["name"] == "Atom-Fusion"
        assert "Cita README y cambios recientes." in worker.messages[0]["content"]
        assert "Falta probar la receta de oxígeno" in worker.messages[0]["content"]
        return "Documentación revisada."

    try:
        icons = window.sidebar_rail.actions
        assert all(not btn.icon().isNull() and btn.toolTip() for btn in icons.values())
        for button in icons.values():
            assert button.text() == button.accessibleName()
            assert sum(candidate.accessibleName() == button.accessibleName()
                       for candidate in window.findChildren(QPushButton)) == 1
        expanded_positions = {name: button.mapTo(window, button.rect().topLeft()) for name, button in icons.items()}
        assert window.history_panel.search.isHidden()
        window.history_button.click()
        QApplication.processEvents()
        assert window.history_panel.isHidden()
        assert window.sidebar_rail.width() == RAIL_WIDTH
        assert all(btn.isVisible() and not btn.text() for btn in icons.values())
        assert {name: button.mapTo(window, button.rect().topLeft()) for name, button in icons.items()} == expanded_positions
        icons["search"].click()
        assert not window.history_panel.isHidden()
        assert not window.history_panel.search.isHidden()
        assert icons["search"].text() == "Buscar conversaciones"
        icons["search"].click()
        icons["projects"].click()
        assert window.pages.currentWidget() is window.project_page
        with patch.object(app.ProjectDialog, "exec", create):
            window.project_page.created.emit()
        project = History().projects()[0]
        pid = project["id"]
        assert project["folder"] == str(window.history.path.parent.resolve())
        window.project_page.pinned.emit(pid, True)
        assert History().projects()[0]["pinned"]
        with patch.object(QInputDialog, "getMultiLineText", return_value=("Falta probar la receta de oxígeno", True)):
            window.project_page.continuity_requested.emit(pid)
        assert History().projects()[0]["continuity"] == "Falta probar la receta de oxígeno"

        window.project_page.chat_started.emit(pid)
        with patch.object(app.Worker, "chat", reply):
            window.message.setPlainText("Revisa cómo va.")
            window.send.click()
            wait_for_turn(window)
        chat = window.chat_id
        assert History().chat_project(chat)["id"] == pid
        assert History().find(project_id=pid) == [(chat, "Revisa cómo va.")]
        panel = window.history_panel
        row = next(panel.list.item(i) for i in range(panel.list.count())
                   if panel.list.item(i).data(PROJECT_ROLE) == pid)
        panel.activate_row(row)
        assert not any(panel.list.item(i).data(NESTED_ROLE) for i in range(panel.list.count()))
        row = next(panel.list.item(i) for i in range(panel.list.count())
                   if panel.list.item(i).data(PROJECT_ROLE) == pid)
        panel.activate_row(row)
        assert any(panel.list.item(i).data(NESTED_ROLE) and panel.list.item(i).data(Qt.ItemDataRole.UserRole) == chat
                   for i in range(panel.list.count()))
        assert any(panel.list.item(i).text() == "Recientes" for i in range(panel.list.count()))

        completed = app.new_task("Revisa Atom-Fusion")
        completed.update(status="completed", message="Siguiente paso: probar oxígeno en móvil.")
        History().save_task(chat, completed)
        window.new_chat()
        window.open_chat(chat)
        assert window.project["id"] == pid
        window.message.setPlainText("Guarda el resumen")
        window.send.click()
        wait_for_turn(window)
        assert "probar oxígeno en móvil" in History().projects()[0]["continuity"]
        assert window.project["continuity"] == History().projects()[0]["continuity"]
        with patch.object(QInputDialog, "getItem", return_value=("Sin proyecto", True)):
            window.move_chat_to_project(chat)
        assert History().chat_project(chat) is None

        record_task_result({"objective": "Revisa este repositorio", "project_id": pid,
                            "steps": [{"tool": "local / read_file", "status": "response"}]}, "completo")
        related = task_results({"objective": "¿Dónde me quedé?", "project_id": pid + 1})
        assert related[0]["mismo_encargo"] == 0 and "read_file" in related[0]["methods"]
        assert not task_results({"objective": "Busca el pronóstico del clima"})

        history = History()
        attached = history.append(None, "user", "Conversación que debe conservarse", project_id=pid)
        path = history.path.parent / "original.md"
        path.write_text("Documento original", encoding="utf-8")
        history.link_project_document(pid, str(path))
        window.show_project(pid)
        options, = (button for button in window.project_page.findChildren(QPushButton)
                    if button.menu() and button.isVisible())
        remove = options.menu().actions()[-1]
        assert remove.text() == "Eliminar proyecto…"

        def confirm(role):
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, QMessageBox)
            next(button for button in dialog.buttons() if dialog.buttonRole(button) == role).click()

        QTimer.singleShot(0, lambda: confirm(QMessageBox.ButtonRole.RejectRole))
        remove.trigger()
        assert history.chat_project(attached)["id"] == pid
        QTimer.singleShot(0, lambda: confirm(QMessageBox.ButtonRole.DestructiveRole))
        remove.trigger()
        assert history.projects() == [] and not history.project_documents(pid)
        assert history.chat_project(attached) is None and history.messages(attached)[0]["content"].startswith("Conversación")
        assert path.read_text(encoding="utf-8") == "Documento original"
        assert History().save_project("Atom-Fusion", "", "", "") > pid
    finally:
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
        test_projects()
        test_turno_no_activa_el_motor_anterior()
        asyncio.run(test_permissions())
        client = McpPool()
        try:
            asyncio.run(test_pool(client))
        finally:
            client.close()
        assert not client.thread.is_alive()
    print("PASS: historial, búsqueda, registro técnico, permisos seguros y reutilización de sesiones.")

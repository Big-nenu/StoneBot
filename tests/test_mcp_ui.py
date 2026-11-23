"""Prueba la administración gráfica con Qt y una conexión STDIO real."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from mcp.types import Tool
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from test_mcp import example_stdio
import app
import mcp_client
from appearance import (
    AppearanceDialog, COLORS, ColorEditor, DEFAULT_FONT_SIZE, PRESETS, XCODE,
    control_colors, readable_text, shade,
)
from mcp_ui import INTEGRATED_MEMORY, McpDialog, ServerForm, Toggle
from stonewave_memory import load_settings


def assert_controls_fit(window, controls):
    for control in controls:
        if control.isVisible():
            top_left = control.mapTo(window, QPoint(0, 0))
            bottom_right = control.mapTo(window, control.rect().bottomRight())
            assert window.rect().contains(top_left) and window.rect().contains(bottom_right), control


def submit_form(dialog, button, callback):
    button.click()
    form = dialog.editor
    assert isinstance(form, ServerForm) and not form.isWindow()
    callback(form)
    form.accept()
    assert dialog.editor is None, form.error.text()


def test_integrated_memory_catalog():
    qt = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(mcp_client, "default_root", return_value=Path(directory)):
        window = app.StoneBot()
        dialog = window.mcp_manager()
        catalog = {name: (None, "stonewave", Tool(name=name, description="Descripción de prueba", inputSchema={}), False)
                   for name in ["query_memory", "force_dream", "sync_memory"] + [f"fixture_{i}" for i in range(15)]}
        with (patch.object(window.memory, "entries", new=AsyncMock(return_value=catalog)) as entries,
              patch("mcp_ui.probe_server", new=AsyncMock()) as external_probe):
            assert dialog.selected() == INTEGRATED_MEMORY
            dialog.show()
            assert not dialog.controls.isVisible()
            for _ in range(100):
                qt.processEvents()
                if dialog.test is None:
                    break
                QTest.qWait(20)
            assert dialog.test is None
            entries.assert_awaited_once()
            external_probe.assert_not_awaited()
            dialog.memory_panel.sections.setCurrentRow(4)
            assert dialog.tools.isVisible() and dialog.tools.topLevelItemCount() == 18
            displayed = {dialog.tools.topLevelItem(i).text(0): dialog.tools.topLevelItem(i)
                         for i in range(dialog.tools.topLevelItemCount())}
            assert displayed["query_memory"].text(2) == "Chat"
            assert displayed["query_memory"].toolTip(1) == "Descripción de prueba"
            assert displayed["force_dream"].text(2) == "/sueno memoria"
            assert displayed["sync_memory"].text(2) == "Ajustes de StoneWave"
            assert not (Path(directory) / "mcp_servers.json").exists()
        notes = Path(directory) / "notas"
        notes.mkdir()

        def finish_job(settings):
            for _ in range(100):
                qt.processEvents()
                if settings.job is None:
                    return
                QTest.qWait(20)
            raise AssertionError("La operación de StoneWave no terminó.")

        def configure(settings):
            assert settings.sections.count() == 5 and not settings.isWindow()
            settings.sections.setCurrentRow(2)
            settings.fields["NOTES"].setText(str(notes))
            settings.dream.setChecked(False)
            assert not settings.fields["DREAM_HOURS"].isEnabled()
            assert not settings.actions["export_notes"].isEnabled()
            assert dialog.apply_button.isEnabled()
            dialog.apply_button.click()
            finish_job(settings)
            assert settings.actions["export_notes"].isEnabled()
            assert "guardados y aplicados" in settings.status.text()
            settings.actions["export_notes"].click()
            assert dialog.editor is not None and not dialog.editor.isWindow()
            next(button for button in dialog.editor.findChildren(QPushButton) if button.text() == "Continuar").click()
            finish_job(settings)
            assert settings.status.text() == "Exportación de prueba completada."

        with (patch.object(window.memory, "restart", new=AsyncMock(return_value=catalog)) as restart,
              patch.object(window.memory, "call", new=AsyncMock(return_value="Exportación de prueba completada.")) as call):
            configure(dialog.memory_panel)
            restart.assert_awaited_once()
            call.assert_awaited_once_with("export_notes")
        assert load_settings()["NOTES"] == str(notes)
        assert not (Path(directory) / "mcp_servers.json").exists()
        window.close()


def test_manager():
    qt = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with (patch.object(mcp_client, "default_root", return_value=root),
              patch.object(mcp_client, "read_key", return_value=None)):
            window = app.StoneBot()
            window.mcp_dialog = McpDialog(window)
            window.mcp_dialog.connection_changed.connect(window.pool.invalidate)
            with patch.object(McpDialog, "exec", return_value=0) as open_dialog:
                next(action for action in window.settings_menu.actions() if action.text() == "Extensiones…").trigger()
            open_dialog.assert_called_once()
            dialog = window.mcp_dialog
            dialog.show()
            cmd = example_stdio()

            def stdio(form):
                form.name.setText("ejemplo")
                form.command.setText(sys.executable)
                form.arguments.setPlainText(json.dumps(["-B", "-c", cmd[-1]]))
                form.reads.setPlainText("echo")

            submit_form(dialog, dialog.add, stdio)
            assert dialog.selected() == "ejemplo"
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert dialog.badge.text() == "Sin probar"

            def switch(manager):
                return manager.server_switch.findChild(Toggle)

            def tool_item(name):
                for row in range(dialog.tools.topLevelItemCount()):
                    group = dialog.tools.topLevelItem(row)
                    for index in range(group.childCount()):
                        item = group.child(index)
                        if item.text(0) == name:
                            return item
                raise AssertionError(name)

            def status():
                return dialog.badge

            def wait_for_probe():
                for _ in range(300):
                    QTest.qWait(100)
                    if dialog.test is None:
                        return
                raise AssertionError("La prueba de conexión no terminó.")

            QTest.mouseClick(switch(dialog), Qt.MouseButton.LeftButton)
            assert mcp_client.load_servers()["ejemplo"]["enabled"]
            dialog.hide()
            window.show()
            menu = window.mcp_menu
            menu.popup(window.attachments.add_button.mapToGlobal(QPoint()))
            QTest.qWait(50)
            quick = menu.actions()[0].defaultWidget().findChild(Toggle)
            assert menu.isVisible() and quick.accessibleName() == "Servidor ejemplo" and quick.isChecked()
            QTest.mouseClick(quick, Qt.MouseButton.LeftButton)
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert not switch(dialog).isChecked()
            menu.close()
            dialog.show()
            QTest.mouseClick(switch(dialog), Qt.MouseButton.LeftButton)
            menu.aboutToShow.emit()
            assert menu.actions()[0].defaultWidget().findChild(Toggle).isChecked()
            assert mcp_client.load_servers()["ejemplo"]["enabled"]
            dialog.probe.click()
            assert not dialog.edit.isEnabled()
            wait_for_probe()
            assert "Conectado" in status().text() and status().property("connection") == "connected", (
                dialog.selected(), status().text(), status().toolTip())
            assert tool_item("echo").text(1) == "Lectura automática"
            assert tool_item("mark").text(1) == "Requiere confirmación"
            assert dialog.tools.itemWidget(tool_item("echo"), 0).findChild(QLabel, "mcpCardState").text() == "Activo"
            widths = []
            for width in (780, 1060):
                dialog.resize(width, 510)
                qt.processEvents()
                widths.append([tree.viewport().width() for tree in (dialog.table, dialog.tools)])
                assert_controls_fit(dialog, (dialog.add, dialog.edit, dialog.remove, dialog.api_key, dialog.probe, switch(dialog)))
                for tree in (dialog.table, dialog.tools):
                    assert tree.isHeaderHidden() and tree.horizontalScrollBar().maximum() == 0
                for row in range(dialog.tools.topLevelItemCount()):
                    item = dialog.tools.topLevelItem(row)
                    toggle = dialog.tools.itemWidget(item, 0).findChild(Toggle)
                    cell = dialog.tools.visualItemRect(item)
                    assert cell.contains(toggle.mapTo(dialog.tools.viewport(), QPoint()))
                    assert cell.contains(toggle.mapTo(dialog.tools.viewport(), toggle.rect().bottomRight()))
            assert widths[0][0] == widths[1][0] and widths[0][1] < widths[1][1]
            QTest.mouseClick(dialog.tools.itemWidget(tool_item("mark"), 0).findChild(Toggle), Qt.MouseButton.LeftButton)
            assert mcp_client.load_servers()["ejemplo"]["disabled_tools"] == ["mark"]
            assert tool_item("mark").text(1) == "Requiere confirmación"
            assert dialog.tools.itemWidget(tool_item("mark"), 0).findChild(QLabel, "mcpCardState").text() == "Inactivo"
            assert not dialog.tools.itemWidget(tool_item("mark"), 0).findChild(Toggle).isChecked()
            QTest.mouseClick(switch(dialog), Qt.MouseButton.LeftButton)
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert "Conectado" in status().text()

            reopened = McpDialog(window)
            assert not switch(reopened).isChecked()
            assert reopened.servers["ejemplo"]["disabled_tools"] == ["mark"]
            reopened.deleteLater()
            QTest.mouseClick(switch(dialog), Qt.MouseButton.LeftButton)

            def http(form):
                assert form.name.isReadOnly()
                form.transport.setCurrentIndex(form.transport.findData("http"))
                form.url.setText("https://example.test/mcp")
                form.token_env.setText("STONEBOT_MCP_PRUEBA_TOKEN")
                form.resize(360, form.sizeHint().height())
                qt.processEvents()
                assert_controls_fit(form, form.findChildren(QLineEdit) + form.findChildren(QPushButton))

            submit_form(dialog, dialog.edit, http)
            server = mcp_client.load_servers()["ejemplo"]
            assert server["transport"] == "http" and server["token_env"] == "STONEBOT_MCP_PRUEBA_TOKEN"
            assert not server["read_tools"] and not server["enabled"]
            assert dialog.tools.topLevelItemCount() == 0
            assert "Sin probar" in status().text()
            variable = server["token_env"]
            with patch.dict(os.environ, {variable: ""}):
                dialog.probe.click()
                wait_for_probe()
            assert "variable de entorno" in dialog.notice.text()

            secret = "synthetic-tavily-key"
            client = httpx.AsyncClient

            def probe_http(handler, env_value=secret):
                def mock_client(**kwargs):
                    return client(transport=httpx.MockTransport(handler), **kwargs)

                with (patch.dict(os.environ, {variable: env_value}),
                      patch.object(httpx, "AsyncClient", side_effect=mock_client)):
                    dialog.probe.click()
                    wait_for_probe()
                assert secret not in dialog.notice.text()
                assert secret not in status().toolTip()

            def fail_http(code):
                def handler(request):
                    assert request.headers["Authorization"] == f"Bearer {secret}"
                    return httpx.Response(code, text=secret)

                return handler

            for code in (401, 403, 404):
                probe_http(fail_http(code))
                assert f"HTTP {code}" in dialog.notice.text(), dialog.notice.text()
                assert f"HTTP {code}" in status().toolTip()
                assert status().property("connection") == "error"

            def timeout(request):
                raise httpx.ReadTimeout(secret, request=request)

            probe_http(timeout)
            assert "Tiempo de espera" in dialog.notice.text()

            def authenticated(request):
                assert request.headers["Authorization"] == f"Bearer {secret}"
                body = json.loads(request.content)
                if "id" not in body:
                    return httpx.Response(202)
                if body["method"] == "initialize":
                    result = {"protocolVersion": body["params"]["protocolVersion"], "capabilities": {"tools": {}},
                              "serverInfo": {"name": "fixture", "version": "1"}}
                else:
                    assert body["method"] == "tools/list"
                    result = {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

            probe_http(authenticated)
            assert "Conectado" in status().text()
            assert tool_item("search").text(0) == "search"
            with patch.object(mcp_client, "read_key", side_effect=mcp_client.CredentialAccessError):
                probe_http(authenticated)
            assert "Conectado" in status().text()

            target = mcp_client.credential_target("ejemplo", server)
            vault = {}

            def save_masked(popup):
                entry = popup.findChild(QLineEdit)
                assert not entry.text() and entry.echoMode() == QLineEdit.EchoMode.Password
                entry.setText(secret)
                assert secret not in entry.displayText()
                next(button for button in popup.findChildren(QPushButton) if button.text() == "Guardar").click()
                return 1

            with (patch("mcp_ui.read_key", side_effect=vault.get),
                  patch("mcp_ui.store_key", side_effect=vault.__setitem__)):
                dialog.api_key.click()
                assert dialog.editor is not None and not dialog.editor.isWindow()
                save_masked(dialog.editor)
            assert vault == {target: secret}
            assert secret not in (root / "mcp_servers.json").read_text(encoding="utf-8")
            assert secret not in dialog.notice.text()
            with patch.object(mcp_client, "read_key", side_effect=vault.get):
                probe_http(authenticated, env_value="")
            assert "Conectado" in status().text()
            assert mcp_client.credential_target("ejemplo", dict(server, url="https://other.test/mcp")) != target
            with patch.object(McpDialog, "exec", return_value=0):
                next(action for action in window.settings_menu.actions() if action.text() == "Extensiones…").trigger()
            assert window.mcp_dialog is dialog and dialog.selected() == "ejemplo"
            with patch("mcp_ui.delete_key", side_effect=lambda key: vault.pop(key, None)):
                dialog.remove.click()
                next(button for button in dialog.editor.findChildren(QPushButton) if button.text() == "Eliminar").click()
            assert mcp_client.load_servers() == {}
            assert not vault
            dialog.close()
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_appearance():
    qt = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with patch.object(mcp_client, "default_root", return_value=root):
            window = app.StoneBot()
            window.show()
            window.append_message("Una pregunta", user=True)
            window.append_message("Una respuesta")
            assert window.appearance == dict(COLORS, font_size=DEFAULT_FONT_SIZE)
            user = window.findChild(app.ChatText, "userMessage")
            bot = window.findChild(app.MarkdownText, "botMessage")
            original_width = user.maximumWidth()
            colors = dict(accent="#00bb99", background="#eeeeee", user_message="#333366", bot_message="#e7e7f2")

            def customize(dialog):
                for key, color in colors.items():
                    def choose(editor):
                        editor.set_color(QColor(color))
                        return 1

                    with patch.object(ColorEditor, "exec", choose):
                        dialog.swatches[key].click()
                    assert window.appearance[key] == color
                    assert color in window.centralWidget().styleSheet()
                dialog.font_size.setValue(23)
                qt.processEvents()
                assert all(w.font().pixelSize() == 23 for w in (user, bot, window.message))
                assert user.maximumWidth() > original_width
                return 0

            with patch.object(AppearanceDialog, "exec", customize):
                next(action for action in window.settings_menu.actions() if action.text() == "Apariencia…").trigger()
            assert (root / "appearance.ini").is_file()
            reopened = app.StoneBot()
            reopened.show()
            qt.processEvents()
            assert reopened.appearance == dict(colors, font_size=23)
            assert reopened.message.font().pixelSize() == 23
            reopened.resize(340, 360)
            qt.processEvents()
            assert_controls_fit(reopened, (reopened.settings_button, reopened.sidebar_rail.provider_badge, reopened.send))
            panel = AppearanceDialog(reopened, reopened.appearance, reopened.change_appearance)
            panel.show()
            for width in (340, 780):
                panel.resize(width, panel.sizeHint().height())
                qt.processEvents()
                assert_controls_fit(panel, panel.findChildren(QPushButton) + [panel.font_size])
            for key, color in colors.items():
                before = reopened.appearance.copy()
                panel.restore_colors[key].click()
                assert reopened.appearance == dict(before, **{key: COLORS[key]})
                assert not panel.restore_colors[key].isEnabled()
                assert app.load_appearance() == reopened.appearance
                panel.set_color(key, color)
            panel.restore_colors["background"].click()
            after_restart = app.StoneBot()
            assert after_restart.appearance == dict(colors, background=COLORS["background"], font_size=23)
            panel.restore.click()
            assert reopened.appearance == dict(COLORS, font_size=23)
            assert app.load_appearance() == reopened.appearance
            after_restart.close()
            window.close()
            reopened.close()
            for widget in (after_restart, window, reopened):
                widget.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_toggle_contrast():
    qt = QApplication.instance() or QApplication([])
    samples = [*PRESETS.values(), dict(COLORS, background="#ffffff", accent="#f0f0f0")]
    for theme in samples:
        surface = control_colors(theme["background"])[0]
        for checked in (False, True):
            control = Toggle(checked, "Interruptor de prueba", theme["accent"], surface)
            track = theme["accent"] if checked else shade(surface, .16)
            image = control.grab().toImage()
            thumb_x = 27 if checked else 10
            assert image.pixelColor(thumb_x, 12).name() == readable_text(track)
            assert image.pixelColor(10 if checked else 27, 12).name() == QColor(track).name()
    qt.processEvents()


def test_xcode_manager_layout():
    qt = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(
        mcp_client, "default_root", return_value=Path(directory)
    ):
        window = app.StoneBot()
        dialog = McpDialog(window)
        dialog.set_appearance(PRESETS[XCODE])
        dialog.resize(dialog.minimumSize())
        dialog.show()
        qt.processEvents()
        assert dialog.add.geometry().top() >= dialog.table.geometry().bottom()
        assert dialog.table.parentWidget().width() == 208
        assert not dialog.apply_button.isEnabled()
        assert_controls_fit(dialog, dialog.findChildren(QPushButton))
        dialog.close()
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    qt = QApplication([])
    test_integrated_memory_catalog()
    test_manager()
    test_appearance()
    test_toggle_contrast()
    test_xcode_manager_layout()
    print("PASS: colores de estado, interruptores MCP, catálogo STDIO y apariencia persistente.")

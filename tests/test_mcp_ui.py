"""Prueba la administración gráfica con Qt y una conexión STDIO real."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QMessageBox, QPushButton

from test_mcp import example_stdio
import app
import mcp_client
from appearance import AppearanceDialog, COLORS, ColorEditor, DEFAULT_FONT_SIZE, PRESETS, readable_text, shade
from mcp_ui import McpDialog, ServerForm, Toggle


def assert_controls_fit(window, controls):
    for control in controls:
        if control.isVisible():
            top_left = control.mapTo(window, QPoint(0, 0))
            bottom_right = control.mapTo(window, control.rect().bottomRight())
            assert window.rect().contains(top_left) and window.rect().contains(bottom_right), control


def submit_form(button, callback):
    errors = []

    def fill():
        form = QApplication.activeModalWidget()
        try:
            assert isinstance(form, ServerForm)
            callback(form)
            form.accept()
        except Exception as exc:
            errors.append(exc)
            if form is not None:
                form.reject()

    with patch.object(QMessageBox, "warning", side_effect=AssertionError("El formulario rechazó la configuración.")):
        QTimer.singleShot(0, fill)
        button.click()
    if errors:
        raise errors[0]


def test_manager():
    qt = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        with (patch.object(mcp_client, "default_root", return_value=root),
              patch.object(mcp_client, "read_key", return_value=None)):
            window = app.StoneBot()
            with patch.object(McpDialog, "exec", return_value=0) as open_dialog:
                window.mcp_button.click()
            open_dialog.assert_called_once()
            dialog = window.mcp_dialog
            dialog.show()
            cmd = example_stdio()

            def stdio(form):
                form.name.setText("ejemplo")
                form.command.setText(sys.executable)
                form.arguments.setPlainText(json.dumps(["-B", "-c", cmd[-1]]))
                form.reads.setPlainText("echo")

            submit_form(dialog.add, stdio)
            assert dialog.selected() == "ejemplo"
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert "#b8b2c4" in dialog.table.itemWidget(dialog.table.currentItem(), 3).styleSheet()

            def switch(tree, row=0):
                holder = tree.itemWidget(tree.topLevelItem(row), 2)
                return holder.findChild(Toggle)

            def status():
                return dialog.table.itemWidget(dialog.table.currentItem(), 3)

            def wait_for_probe():
                for _ in range(300):
                    QTest.qWait(100)
                    if dialog.test is None:
                        return
                raise AssertionError("La prueba de conexión no terminó.")

            QTest.mouseClick(switch(dialog.table), Qt.MouseButton.LeftButton)
            assert mcp_client.load_servers()["ejemplo"]["enabled"]
            dialog.probe.click()
            assert not dialog.edit.isEnabled()
            assert not dialog.close()
            wait_for_probe()
            assert "Correcta" in status().text() and "#86efac" in status().styleSheet()
            assert dialog.tools.topLevelItemCount() == 2
            assert dialog.tools.topLevelItem(0).text(1) == "Lectura automática"
            assert dialog.tools.topLevelItem(1).text(1) == "Requiere confirmación"
            assert dialog.tools.itemWidget(dialog.tools.topLevelItem(0), 2).findChild(QLabel).text() == "Activo"
            widths = []
            for width in (380, 980):
                dialog.resize(width, 460)
                qt.processEvents()
                widths.append([tree.columnWidth(0) for tree in (dialog.table, dialog.tools)])
                assert_controls_fit(dialog, (dialog.add, dialog.edit, dialog.remove, dialog.api_key, dialog.probe))
                for tree in (dialog.table, dialog.tools):
                    assert tree.horizontalScrollBar().maximum() == 0
                    for row in range(tree.topLevelItemCount()):
                        item = tree.topLevelItem(row)
                        toggle = switch(tree, row)
                        assert not item.text(2)
                        cell = tree.visualItemRect(item)
                        start = tree.header().sectionViewportPosition(2)
                        top = toggle.mapTo(tree.viewport(), QPoint(0, 0))
                        end = toggle.mapTo(tree.viewport(), toggle.rect().bottomRight())
                        assert start <= top.x() <= end.x() < start + tree.columnWidth(2)
                        assert cell.top() <= top.y() <= end.y() <= cell.bottom()
                        if tree is dialog.table:
                            label = tree.itemWidget(item, 2).findChild(QLabel)
                            label_start = label.mapTo(tree.viewport(), QPoint(0, 0)).x()
                            assert label.text() == "Activo"
                            assert end.x() < label_start and label_start + label.width() <= start + tree.columnWidth(2)
            assert all(narrow < wide for narrow, wide in zip(*widths))
            QTest.mouseClick(switch(dialog.tools, 1), Qt.MouseButton.LeftButton)
            assert mcp_client.load_servers()["ejemplo"]["disabled_tools"] == ["mark"]
            assert dialog.tools.topLevelItem(1).text(1) == "Deshabilitada"
            assert dialog.tools.itemWidget(dialog.tools.topLevelItem(1), 2).findChild(QLabel).text() == "Inactivo"
            assert not switch(dialog.tools, 1).isChecked()
            QTest.mouseClick(switch(dialog.table), Qt.MouseButton.LeftButton)
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert "Correcta" in status().text()

            reopened = McpDialog(window)
            assert not switch(reopened.table).isChecked()
            assert reopened.servers["ejemplo"]["disabled_tools"] == ["mark"]
            reopened.deleteLater()
            QTest.mouseClick(switch(dialog.table), Qt.MouseButton.LeftButton)

            def http(form):
                assert form.name.isReadOnly()
                form.transport.setCurrentIndex(form.transport.findData("http"))
                form.url.setText("https://example.test/mcp")
                form.token_env.setText("STONEBOT_MCP_PRUEBA_TOKEN")
                form.resize(360, form.sizeHint().height())
                qt.processEvents()
                assert_controls_fit(form, form.findChildren(QLineEdit) + form.findChildren(QPushButton))

            with patch.object(QMessageBox, "information"):
                submit_form(dialog.edit, http)
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
                assert "#fca5a5" in status().styleSheet()

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
            assert "Correcta" in status().text()
            assert dialog.tools.topLevelItem(0).text(0) == "search"
            with patch.object(mcp_client, "read_key", side_effect=mcp_client.CredentialAccessError):
                probe_http(authenticated)
            assert "Correcta" in status().text()

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
                  patch("mcp_ui.store_key", side_effect=vault.__setitem__),
                  patch.object(QDialog, "exec", save_masked)):
                dialog.api_key.click()
            assert vault == {target: secret}
            assert secret not in (root / "mcp_servers.json").read_text(encoding="utf-8")
            assert secret not in dialog.notice.text()
            with patch.object(mcp_client, "read_key", side_effect=vault.get):
                probe_http(authenticated, env_value="")
            assert "Correcta" in status().text()
            assert mcp_client.credential_target("ejemplo", dict(server, url="https://other.test/mcp")) != target
            with patch.object(McpDialog, "exec", return_value=0):
                window.mcp_button.click()
            assert window.mcp_dialog is dialog and dialog.selected() == "ejemplo"
            with (patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
                  patch("mcp_ui.delete_key", side_effect=lambda key: vault.pop(key, None))):
                dialog.remove.click()
            assert mcp_client.load_servers() == {}
            assert not vault
            dialog.close()
            window.close()
            qt.processEvents()


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
                window.settings_button.click()
            assert (root / "appearance.ini").is_file()
            reopened = app.StoneBot()
            reopened.show()
            qt.processEvents()
            assert reopened.appearance == dict(colors, font_size=23)
            assert reopened.message.font().pixelSize() == 23
            reopened.resize(340, 360)
            qt.processEvents()
            assert_controls_fit(reopened, (reopened.mcp_button, reopened.settings_button, reopened.send))
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
            window.close()
            reopened.close()
            qt.processEvents()


def test_toggle_contrast():
    qt = QApplication.instance() or QApplication([])
    samples = [*PRESETS.values(), dict(COLORS, background="#ffffff", accent="#f0f0f0")]
    for theme in samples:
        surface = shade(theme["background"], .06)
        for checked in (False, True):
            control = Toggle(checked, "Interruptor de prueba", theme["accent"], surface)
            track = theme["accent"] if checked else shade(surface, .25)
            image = control.grab().toImage()
            thumb_x = 27 if checked else 10
            assert image.pixelColor(thumb_x, 12).name() == readable_text(track)
            assert image.pixelColor(10 if checked else 27, 12).name() == QColor(track).name()
    qt.processEvents()


if __name__ == "__main__":
    test_manager()
    test_appearance()
    test_toggle_contrast()
    print("PASS: colores de estado, interruptores MCP, catálogo STDIO y apariencia persistente.")

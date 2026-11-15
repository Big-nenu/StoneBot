"""Prueba la administración gráfica con Qt y una conexión STDIO real."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QLabel, QLineEdit, QMessageBox, QPushButton

from test_mcp import example_stdio
import app
import mcp_client
from appearance import AppearanceDialog, COLORS, DEFAULT_FONT_SIZE
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
        with patch.object(mcp_client, "default_root", return_value=root):
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
            widths = []
            for width in (380, 980):
                dialog.resize(width, 460)
                qt.processEvents()
                widths.append([tree.columnWidth(0) for tree in (dialog.table, dialog.tools)])
                assert_controls_fit(dialog, (dialog.add, dialog.edit, dialog.remove, dialog.probe))
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
            with patch("mcp_ui.probe_server", AsyncMock(side_effect=OSError)):
                dialog.probe.click()
                wait_for_probe()
            assert "#fca5a5" in dialog.table.itemWidget(dialog.table.currentItem(), 3).styleSheet()
            with patch.object(McpDialog, "exec", return_value=0):
                window.mcp_button.click()
            assert window.mcp_dialog is dialog and dialog.selected() == "ejemplo"
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                dialog.remove.click()
            assert mcp_client.load_servers() == {}
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
            bot = window.findChild(app.ChatText, "botMessage")
            original_width = user.maximumWidth()
            colors = dict(accent="#00bb99", background="#eeeeee", user_message="#333366", bot_message="#e7e7f2")

            def customize(dialog):
                for key, color in colors.items():
                    with patch.object(QColorDialog, "getColor", return_value=QColor(color)) as picker:
                        dialog.swatches[key].click()
                    picker.assert_called_once()
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


if __name__ == "__main__":
    test_manager()
    test_appearance()
    print("PASS: colores de estado, interruptores MCP, catálogo STDIO y apariencia persistente.")

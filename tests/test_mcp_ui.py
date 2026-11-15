"""Prueba la administración gráfica con Qt y una conexión STDIO real."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_mcp import example_stdio
import app
import mcp_client
from mcp_ui import McpDialog, ServerForm


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
            dialog.toggle.click()
            assert mcp_client.load_servers()["ejemplo"]["enabled"]
            dialog.probe.click()
            assert not dialog.edit.isEnabled()
            assert not dialog.close()
            for _ in range(300):
                QTest.qWait(100)
                if dialog.test is None:
                    break
            assert dialog.test is None and dialog.table.currentItem().text(3) == "Correcta"
            assert dialog.tools.count() == 2
            assert "Lectura automática" in dialog.tools.item(0).text()
            assert "Requiere confirmación" in dialog.tools.item(1).text()
            dialog.toggle.click()
            assert not mcp_client.load_servers()["ejemplo"]["enabled"]
            assert dialog.table.currentItem().text(3) == "Correcta"
            dialog.toggle.click()

            def http(form):
                assert form.name.isReadOnly()
                form.transport.setCurrentIndex(form.transport.findData("http"))
                form.url.setText("https://example.test/mcp")
                form.token_env.setText("STONEBOT_MCP_PRUEBA_TOKEN")

            with patch.object(QMessageBox, "information"):
                submit_form(dialog.edit, http)
            server = mcp_client.load_servers()["ejemplo"]
            assert server["transport"] == "http" and server["token_env"] == "STONEBOT_MCP_PRUEBA_TOKEN"
            assert not server["read_tools"] and not server["enabled"]
            assert dialog.tools.count() == 0
            assert dialog.table.currentItem().text(3) == "Sin probar"
            with patch.object(McpDialog, "exec", return_value=0):
                window.mcp_button.click()
            assert window.mcp_dialog is dialog and dialog.selected() == "ejemplo"
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                dialog.remove.click()
            assert mcp_client.load_servers() == {}
            dialog.close()
            window.close()
            qt.processEvents()


if __name__ == "__main__":
    test_manager()
    print("PASS: botón MCP, formularios, persistencia, activación, catálogo STDIO y eliminación.")

"""Alta desde el chat con un servidor STDIO de prueba, sin instalar paquetes."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import mcp
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import mcp_client
import mcp_setup
from mcp_ui import Toggle


def submit(window, text, decision=None):
    review = []
    if decision is not None:
        def decide():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                review.append(dialog.text())
                dialog.button(decision).click()
        QTimer.singleShot(0, decide)
    window.message.setPlainText(text)
    window.enviar()
    if decision is not None:
        assert review and "guardar el servidor desactivado" in review[0]
    return window.problem.text()


def plan(name, script):
    return "Instala este MCP:\n```json\n" + json.dumps({"mcpServers": {
        name: {"command": sys.executable, "args": ["-B", str(script)]},
    }}) + "\n```"


def test_install(root):
    example = Path(__file__).with_name("mcp_example.py").resolve()
    packages = Path(mcp.__file__).resolve().parents[1]
    trusted = root / "prueba.py"
    trusted.write_text(f"import runpy, site\nsite.addsitedir({str(packages)!r})\n"
                       f"runpy.run_path({str(example)!r}, run_name='__main__')\n", encoding="utf-8")
    broken = root / "sin_conexion.py"
    broken.write_text("raise SystemExit(1)\n", encoding="utf-8")
    window = app.StoneBot()
    window.show()
    buttons = QMessageBox.StandardButton
    try:
        text = plan("configurable", trusted)
        assert "cancelada" in submit(window, text, buttons.No)
        assert not mcp_client.load_servers() and not (root / "mcp").exists()
        assert "No se guardó fallo" in submit(window, plan("fallo", broken), buttons.Yes)
        assert not mcp_client.load_servers()
        assert "verificado y guardado desactivado" in submit(window, text, buttons.Yes)
        assert "Herramientas encontradas: 2" in window.problem.text()
        saved = mcp_client.load_servers()
        assert set(saved) == {"configurable"} and not saved["configurable"]["enabled"]
        assert saved["configurable"]["read_tools"] == []
        assert "ya existe" in submit(window, plan("otro_nombre", trusted))
        assert mcp_client.load_servers() == saved
        window.mcp_menu.aboutToShow.emit()
        switch = window.mcp_menu.actions()[0].defaultWidget().findChild(Toggle)
        assert not switch.isChecked()
        switch.click()
        assert mcp_client.load_servers()["configurable"]["enabled"]

        raw = "NO-GUARDAR-493"
        credentials = {"mcpServers": {"privado": {"url": "https://example.test/mcp",
                         "headers": {"Authorization": f"Bearer {raw}"}}}}
        assert "sin pegar su valor" in submit(window, "/mcp instalar\n" + json.dumps(credentials))
        assert raw not in window.problem.text() and raw not in (root / "conversations.sqlite3").read_bytes().decode("latin1")
        assert len(window.messages) == 1 and window.history.find() == []
    finally:
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


if __name__ == "__main__":
    qt = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root):
            test_install(root)
    assert mcp_setup.extract_server("/mcp instalar\n```sh\nnpx -y @org/ejemplo-mcp@1.2.3\n```") == (
        "ejemplo-mcp", {"command": "npx", "args": ["@org/ejemplo-mcp@1.2.3"]})
    _, http, download = mcp_setup.prepare('/mcp instalar {"mcpServers":{"ejemplo":{"url":"https://example.test/mcp",'
                                           '"headers":{"Authorization":"Bearer ${API_KEY}"}}}}')
    assert http["token_env"] == "STONEBOT_MCP_EJEMPLO_TOKEN" and not download
    node = {"transport": "stdio", "command": "node.exe", "args": ["npx-cli.js", "-y", "@wonderwhy-er/desktop-commander@latest"]}
    assert mcp_client.is_desktop_commander(node) and mcp_client.startup_timeout(node) > 90
    assert mcp_client.startup_timeout({**node, "args": ["npx-cli.js", "-y", "other-package"]}) == 25
    assert mcp_client.startup_timeout(http) == 25
    closed = McpError(ErrorData(code=-32000, message="Connection closed"))
    assert "canal MCP se cerró" in mcp_client.connection_error(closed)
    with patch.object(mcp_setup.shutil, "which", return_value=None):
        try:
            mcp_setup.prepare('/mcp instalar {"mcpServers":{"falta":{"command":"uvx","args":["example-mcp"]}}}')
        except ValueError as exc:
            assert "Falta el ejecutable" in str(exc)
        else:
            raise AssertionError("La falta del ejecutable debe detectarse antes de solicitar aprobación.")
    print("PASS: aprobación, rechazo, error, duplicados, credenciales y persistencia MCP.")

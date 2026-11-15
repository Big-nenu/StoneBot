"""Administrador gráfico de las configuraciones MCP."""
import asyncio
import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from mcp_client import load_servers, probe_server, save_servers, validate_server


TRANSPORTS = {"stdio": "STDIO", "http": "Streamable HTTP"}


class ServerForm(QDialog):
    def __init__(self, parent, name=None, server=None):
        super().__init__(parent)
        self.setWindowTitle("Editar servidor MCP" if server else "Agregar servidor MCP")
        old = server or {}
        self.name = QLineEdit(name or "")
        self.name.setReadOnly(name is not None)
        self.transport = QComboBox()
        for key, label in TRANSPORTS.items():
            self.transport.addItem(label, key)
        self.transport.setCurrentIndex(self.transport.findData(old.get("transport", "stdio")))
        self.command = QLineEdit(old.get("command", ""))
        self.arguments = QPlainTextEdit(json.dumps(old.get("args", []), ensure_ascii=False))
        self.arguments.setMaximumHeight(86)
        self.url = QLineEdit(old.get("url", ""))
        self.token_env = QLineEdit(old.get("token_env") or "")
        self.token_env.setPlaceholderText("STONEBOT_MCP_SERVIDOR_TOKEN (opcional)")
        self.reads = QPlainTextEdit("\n".join(old.get("read_tools", [])))
        self.reads.setMaximumHeight(65)
        self.reads.setPlaceholderText("Una herramienta por línea")

        self.form = QFormLayout(self)
        self.form.addRow("Nombre", self.name)
        self.form.addRow("Transporte", self.transport)
        self.form.addRow("Ejecutable absoluto", self.command)
        self.form.addRow("Argumentos JSON sin credenciales", self.arguments)
        self.form.addRow("URL del servidor", self.url)
        self.form.addRow("Nombre de variable del token", self.token_env)
        self.form.addRow("Lecturas automáticas", self.reads)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)
        self.transport.currentIndexChanged.connect(self.show_transport_fields)
        self.show_transport_fields()
        self.resize(600, self.sizeHint().height())
        self.old = old

    def show_transport_fields(self):
        stdio = self.transport.currentData() == "stdio"
        for field in (self.command, self.arguments):
            self.form.setRowVisible(field, stdio)
        for field in (self.url, self.token_env):
            self.form.setRowVisible(field, not stdio)

    def accept(self):
        transport = self.transport.currentData()
        name = self.name.text().strip()
        reads = [line.strip() for line in self.reads.toPlainText().splitlines() if line.strip()]
        server = {"transport": transport, "enabled": self.old.get("enabled", False), "read_tools": reads}
        try:
            if transport == "stdio":
                server.update(command=self.command.text().strip(), args=json.loads(self.arguments.toPlainText()))
            else:
                server.update(url=self.url.text().strip(), token_env=self.token_env.text().strip() or None)
            validate_server(name, server)
        except ValueError as exc:
            QMessageBox.warning(self, "Configuración MCP", str(exc))
            return
        except (OSError, RuntimeError):
            QMessageBox.warning(self, "Configuración MCP", "Revisa las rutas del servidor.")
            return
        changed = self.old and any(
            server.get(key) != self.old.get(key) for key in ("transport", "command", "args", "url", "token_env")
        )
        if changed:
            server.update(enabled=False, read_tools=[])
            QMessageBox.information(self, "Configuración MCP",
                                    "La conexión cambió. Vuelve a activar el servidor y autorizar sus lecturas.")
        self.configuration = name, server
        super().accept()


class ConnectionTest(QThread):
    result = Signal(object)

    def __init__(self, parent, name, server):
        super().__init__(parent)
        self.name = name
        self.server = server

    async def probe(self):
        async with asyncio.timeout(25):
            return await probe_server(self.name, self.server)

    def run(self):
        try:
            tools = asyncio.run(self.probe())
        except Exception:
            tools = None
        self.result.emit(tools)


class McpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Servidores MCP")
        self.resize(700, 480)
        self.setStyleSheet("""
            QDialog { background: #19191e; }
            QLabel, QTreeWidget, QListWidget, QLineEdit, QPlainTextEdit, QComboBox, QPushButton {
                color: #f3f0f7; font-family: "Segoe UI"; font-size: 14px;
            }
            QTreeWidget, QListWidget, QLineEdit, QPlainTextEdit, QComboBox, QComboBox QAbstractItemView {
                background: #25252d; color: #f3f0f7; border: 1px solid #41404f;
                selection-background-color: #4e2d7e; selection-color: #ffffff;
            }
            QHeaderView::section { background: #30303a; color: #f3f0f7; padding: 5px; border: 0; }
            QPushButton {
                background: #363043; border: 1px solid #51475f; border-radius: 7px; padding: 6px 10px;
            }
            QPushButton:hover { background: #4e2d7e; }
            QPushButton:focus { border-color: #c8a7ff; }
            QPushButton:disabled { color: #aba4b5; background: #27262e; }
        """)
        self.servers = {}
        self.results = {}
        self.test = None

        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Servidor", "Transporte", "Activación", "Última prueba"])
        self.table.setRootIsDecorated(False)
        self.table.currentItemChanged.connect(self.refresh_selection)
        self.tools = QListWidget()
        self.tools.setAccessibleName("Herramientas del servidor")
        self.notice = QLabel("Probar conexión descubre herramientas. En STDIO también inicia el ejecutable.")
        self.notice.setWordWrap(True)

        controls = QHBoxLayout()
        self.add = QPushButton("Agregar")
        self.edit = QPushButton("Editar")
        self.toggle = QPushButton("Activar")
        self.remove = QPushButton("Eliminar")
        self.probe = QPushButton("Probar conexión")
        for button, callback in ((self.add, self.add_server), (self.edit, self.edit_server),
                                 (self.toggle, self.toggle_server), (self.remove, self.remove_server),
                                 (self.probe, self.test_connection)):
            button.clicked.connect(callback)
            controls.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 2)
        layout.addLayout(controls)
        layout.addWidget(QLabel("Herramientas descubiertas"))
        layout.addWidget(self.tools, 1)
        layout.addWidget(self.notice)
        self.reload()

    def reload(self):
        selected = self.selected()
        try:
            current = load_servers()
            self.results = {name: result for name, result in self.results.items()
                            if current.get(name) == self.servers.get(name)}
            self.servers = current
        except (ValueError, OSError, RuntimeError):
            self.notice.setText("No se pudo leer la configuración MCP.")
        self.refresh(selected)

    def selected(self):
        item = self.table.currentItem()
        return item.text(0) if item else None

    def refresh(self, selected=None):
        self.table.clear()
        for name, server in sorted(self.servers.items()):
            status, _ = self.results.get(name, ("Sin probar", []))
            item = QTreeWidgetItem([name, TRANSPORTS[server["transport"]],
                                    "Activo" if server["enabled"] else "Inactivo", status])
            self.table.addTopLevelItem(item)
            if name == selected:
                self.table.setCurrentItem(item)
        if self.table.currentItem() is None and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        for column in range(3):
            self.table.resizeColumnToContents(column)
        self.refresh_selection()

    def refresh_selection(self):
        name = self.selected()
        idle = self.test is None
        self.add.setEnabled(idle)
        for button in (self.edit, self.toggle, self.remove, self.probe):
            button.setEnabled(idle and name is not None)
        self.toggle.setText("Desactivar" if name and self.servers[name]["enabled"] else "Activar")
        self.tools.clear()
        _, tools = self.results.get(name, ("", []))
        for tool, auto in tools:
            permission = "Lectura automática" if auto else "Requiere confirmación"
            self.tools.addItem(f"{tool}  ·  {permission}")

    def commit(self, name, server):
        try:
            current = load_servers()
            if current != self.servers:
                self.servers = current
                self.results.clear()
                self.refresh(name)
                self.notice.setText("La configuración cambió fuera de esta ventana. Intenta de nuevo.")
                return
            if server is None:
                del current[name]
            else:
                current[name] = server
            save_servers(current)
        except (ValueError, OSError, RuntimeError):
            self.notice.setText("No se pudo guardar la configuración MCP.")
            return
        old = self.servers.get(name)
        self.servers = current
        if old is None or server is None or dict(old, enabled=server["enabled"]) != server:
            self.results.pop(name, None)
        self.refresh(name)
        self.notice.setText("Cambios guardados. Se aplican al siguiente turno del chat.")

    def add_server(self):
        form = ServerForm(self)
        if form.exec():
            name, server = form.configuration
            if name in self.servers:
                self.notice.setText("Ya existe un servidor con ese nombre.")
            else:
                self.commit(name, server)

    def edit_server(self):
        name = self.selected()
        form = ServerForm(self, name, self.servers[name])
        if form.exec():
            self.commit(*form.configuration)

    def toggle_server(self):
        name = self.selected()
        current = self.servers[name]
        self.commit(name, dict(current, enabled=not current["enabled"]))

    def remove_server(self):
        name = self.selected()
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Eliminar servidor MCP", f"¿Eliminar la configuración de {name}?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.commit(name, None)

    def test_connection(self):
        name = self.selected()
        if self.test is not None or name is None:
            return
        self.test = ConnectionTest(self, name, self.servers[name])
        self.test.result.connect(self.show_result)
        self.test.finished.connect(self.finish_test)
        self.results[name] = ("Probando…", [])
        self.refresh(name)
        self.notice.setText(f"Probando conexión con {name}…")
        self.test.start()

    def show_result(self, tools):
        name = self.test.name
        status = "Falló" if tools is None else "Correcta"
        self.results[name] = (status, tools or [])
        self.refresh(self.selected())
        self.notice.setText(f"No se pudo conectar con {name}." if tools is None
                            else f"Conexión correcta con {name}. Herramientas: {len(tools)}.")

    def finish_test(self):
        self.test.deleteLater()
        self.test = None
        self.refresh_selection()

    def reject(self):
        if self.test is None:
            super().reject()

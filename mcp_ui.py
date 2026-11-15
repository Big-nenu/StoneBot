"""Administrador gráfico de las configuraciones MCP."""
import asyncio
import json

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from appearance import COLORS, dialog_style, readable_text
from mcp_client import load_servers, probe_server, save_servers, validate_server


TRANSPORTS = {"stdio": "STDIO", "http": "Streamable HTTP"}
STATUS_COLORS = {"Correcta": "#86efac", "Falló": "#fca5a5"}


class Toggle(QCheckBox):
    def __init__(self, checked, label, accent):
        super().__init__()
        self.accent = accent
        self.setAccessibleName(label)
        self.setChecked(checked)
        self.setFixedSize(QSize(38, 24))

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        checked = self.isChecked()
        track = self.accent if checked else "#484452"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(1 if self.isEnabled() else 0.5)
        painter.setPen(QPen(QColor("#ffffff"), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(self.rect().adjusted(2, 3, -2, -3), 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(readable_text(track)))
        painter.drawEllipse(22 if checked else 5, 6, 12, 12)


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
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
        self.setMinimumWidth(420)
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
        if "disabled_tools" in self.old:
            server["disabled_tools"] = self.old["disabled_tools"]
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
        self.setMinimumSize(560, 360)
        self.theme = COLORS
        self.setStyleSheet(dialog_style(self.theme))
        self.servers = {}
        self.results = {}
        self.test = None

        self.table = QTreeWidget()
        self.table.setHeaderLabels(["Servidor", "Transporte", "Activación", "Última prueba"])
        self.table.setRootIsDecorated(False)
        self.table.currentItemChanged.connect(self.refresh_selection)
        self.tools = QTreeWidget()
        self.tools.setHeaderLabels(["Herramienta", "Permiso", "Activación"])
        self.tools.setRootIsDecorated(False)
        self.tools.setAccessibleName("Herramientas del servidor")
        for tree in (self.table, self.tools):
            header = tree.header()
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.notice = QLabel("Probar conexión descubre herramientas. En STDIO también inicia el ejecutable.")
        self.notice.setWordWrap(True)

        controls = QHBoxLayout()
        self.add = QPushButton("Agregar")
        self.edit = QPushButton("Editar")
        self.remove = QPushButton("Eliminar")
        self.probe = QPushButton("Probar conexión")
        for button, callback in ((self.add, self.add_server), (self.edit, self.edit_server),
                                 (self.remove, self.remove_server),
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

    def set_appearance(self, theme):
        self.theme = theme
        self.setStyleSheet(dialog_style(theme))
        self.refresh(self.selected())

    def add_toggle(self, tree, item, column, checked, label, on_change, *, show_state=False):
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        switch = Toggle(checked, label, self.theme["accent"])
        switch.setEnabled(self.test is None)
        switch.toggled.connect(on_change)
        layout.addWidget(switch)
        if show_state:
            state = QLabel("Activo" if checked else "Inactivo")
            state.setStyleSheet("background: #25252d;")
            layout.addWidget(state)
        tree.setItemWidget(item, column, holder)
        if show_state:
            state.ensurePolished()
            state.setMinimumWidth(state.fontMetrics().horizontalAdvance("Inactivo"))
        item.setSizeHint(column, holder.sizeHint().expandedTo(QSize(70, 30)))

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
            item = QTreeWidgetItem([name, TRANSPORTS[server["transport"]]])
            item.setToolTip(0, name)
            self.table.addTopLevelItem(item)
            self.add_toggle(self.table, item, 2, server["enabled"], f"Servidor {name}",
                            lambda checked, name=name: self.toggle_server(name, checked), show_state=True)
            label = QLabel(f"●  {status}")
            color = STATUS_COLORS.get(status, "#b8b2c4")
            label.setStyleSheet(f"color: {color}; background: #25252d; padding-left: 5px;")
            self.table.setItemWidget(item, 3, label)
            label.ensurePolished()
            status_width = max(label.fontMetrics().horizontalAdvance(f"●  {text}")
                               for text in ("Sin probar", "Probando…", "Correcta", "Falló"))
            item.setSizeHint(3, QSize(status_width + 12, 30))
            if name == selected:
                self.table.setCurrentItem(item)
        if self.table.currentItem() is None and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        self.refresh_selection()

    def refresh_selection(self):
        name = self.selected()
        idle = self.test is None
        self.add.setEnabled(idle)
        for button in (self.edit, self.remove, self.probe):
            button.setEnabled(idle and name is not None)
        self.tools.clear()
        _, tools = self.results.get(name, ("", []))
        for tool, auto in tools:
            permission = "Lectura automática" if auto else "Requiere confirmación"
            checked = tool not in self.servers[name].get("disabled_tools", [])
            item = QTreeWidgetItem([tool, permission if checked else "Deshabilitada", ""])
            item.setToolTip(0, tool)
            self.tools.addTopLevelItem(item)
            self.add_toggle(self.tools, item, 2, checked, f"Herramienta {tool}",
                            lambda enabled, name=name, tool=tool: self.toggle_tool(name, tool, enabled))

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
            self.refresh(name)
            return
        old = self.servers.get(name)
        self.servers = current
        transient = {"enabled", "disabled_tools"}
        if (old is None or server is None or
                any(old.get(key) != server.get(key) for key in (old.keys() | server.keys()) - transient)):
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

    def toggle_server(self, name, checked):
        self.commit(name, dict(self.servers[name], enabled=checked))

    def toggle_tool(self, name, tool, enabled):
        server = self.servers[name]
        disabled = set(server.get("disabled_tools", []))
        (disabled.discard if enabled else disabled.add)(tool)
        self.commit(name, dict(server, disabled_tools=sorted(disabled)))

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
        self.refresh(self.selected())

    def reject(self):
        if self.test is None:
            super().reject()

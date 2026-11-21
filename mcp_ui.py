"""Administrador gráfico de las configuraciones MCP."""
import asyncio
import json
import os
import sqlite3
from collections import defaultdict

from PySide6.QtCore import QSize, QSignalBlocker, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QWidgetAction,
)

from appearance import COLORS, control_colors, dialog_style, link_color, readable_text, shade
from mcp_client import (
    connection_error, is_desktop_commander, load_servers, probe_server, save_servers, startup_timeout, validate_server,
)
from mcp_credentials import credential_target, delete_key, read_key, store_key
from mcp_permissions import list_permissions, permission_signature, remember_many, revoke, revoke_many, safe_read, saved_permissions
from mcp_setup import ensure_new, prepare
from mcp_tool_groups import category, operation
from stonewave_memory import MemoryUnavailable, REVIEWED_WRITES, TOOLS
from stonewave_settings_ui import StoneWaveSettingsDialog


TRANSPORTS = {"stdio": "STDIO", "http": "Streamable HTTP"}
STATUS_COLORS = {"Correcta": "#86efac", "Falló": "#fca5a5"}
TOOL_NAMES = Qt.ItemDataRole.UserRole
INTEGRATED_MEMORY = "StoneWave · Integrado"


class Toggle(QCheckBox):
    def __init__(self, checked, label, accent, surface=COLORS["background"]):
        super().__init__()
        self.accent = accent
        self.surface = surface
        self.setAccessibleName(label)
        self.setChecked(checked)
        self.setFixedSize(QSize(38, 24))

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        checked = self.isChecked()
        enabled = self.isEnabled()
        track = self.accent if checked and enabled else shade(self.surface, .16 if enabled else .07)
        if enabled and (self.underMouse() or self.isDown()):
            track = shade(track, .18 if self.isDown() else .09)
        edge = link_color(self.surface) if self.hasFocus() else shade(self.surface, .42 if enabled else .26)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(edge), 2 if self.hasFocus() else 1))
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(self.rect().adjusted(2, 3, -2, -3), 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(readable_text(track) if enabled else shade(self.surface, .42)))
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

    def __init__(self, parent, name, server, *, memory=None):
        super().__init__(parent)
        self.name = name
        self.server = server
        self.memory = memory

    async def probe(self):
        if self.memory is not None:
            return [entry[2] for entry in (await self.memory.entries()).values()]
        async with asyncio.timeout(startup_timeout(self.server)):
            return await probe_server(self.name, self.server, include_definitions=True)

    def run(self):
        try:
            tools = asyncio.run(self.probe())
        except MemoryUnavailable as exc:
            self.result.emit(([], str(exc)))
        except Exception as exc:
            self.result.emit(([], connection_error(exc)))
        else:
            self.result.emit((tools, ""))


class McpDialog(QDialog):
    connection_changed = Signal(str)

    def __init__(self, parent, *, memory=None):
        super().__init__(parent)
        self.setObjectName("mcpManager")
        self.setWindowTitle("Servidores MCP")
        self.resize(700, 510)
        self.setMinimumSize(560, 410)
        self.theme = COLORS
        self.setStyleSheet(dialog_style(self.theme))
        self.servers = {}
        self.memory = memory
        self.results = {}
        self.test = None

        self.table = QTreeWidget()
        self.table.setAccessibleName("Servidores MCP")
        self.table.setHeaderLabels(["Servidor", "Transporte", "Activación", "Última prueba"])
        self.table.setRootIsDecorated(False)
        self.table.currentItemChanged.connect(self.refresh_selection)
        self.tools = QTreeWidget()
        self.tools.setHeaderLabels(["Herramienta", "Permiso", "Activación", "Tipo"])
        self.tools.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tools.setAccessibleName("Herramientas del servidor")
        self.tools.itemSelectionChanged.connect(self.update_tool_actions)
        self.tools_server = None
        for tree in (self.table, self.tools):
            tree.setAlternatingRowColors(True)
            tree.setUniformRowHeights(True)
            header = tree.header()
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tools.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.notice = QLabel("Probar conexión descubre herramientas. En STDIO también inicia el ejecutable.")
        self.notice.setWordWrap(True)
        self.notice.setObjectName("mcpNotice")

        servers_header = QHBoxLayout()
        servers_title = QLabel("Servidores MCP")
        servers_title.setProperty("sectionHeading", True)
        servers_header.addWidget(servers_title)
        servers_header.addStretch()
        self.add = QPushButton("Agregar")
        servers_header.addWidget(self.add)
        controls = QHBoxLayout()
        self.edit = QPushButton("Editar")
        self.remove = QPushButton("Eliminar")
        self.api_key = QPushButton("Clave API…")
        self.memory_settings = QPushButton("Ajustes de StoneWave…")
        self.memory_settings.clicked.connect(self.open_memory_settings)
        self.probe = QPushButton("Probar conexión")
        for button, callback in ((self.add, self.add_server), (self.edit, self.edit_server),
                                 (self.remove, self.remove_server),
                                 (self.api_key, self.manage_credential),
                                 (self.probe, self.test_connection)):
            button.clicked.connect(callback)
        for button in (self.edit, self.remove, self.api_key):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.memory_settings)
        self.probe.setProperty("primary", True)
        controls.addWidget(self.probe)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        layout.addLayout(servers_header)
        layout.addWidget(self.table, 2)
        layout.addLayout(controls)
        layout.addSpacing(4)
        tools_header = QHBoxLayout()
        tools_title = QLabel("Herramientas descubiertas")
        tools_title.setProperty("sectionHeading", True)
        tools_header.addWidget(tools_title)
        tools_header.addStretch()
        self.selection_permissions = QPushButton("Permisos de selección…")
        self.selection_permissions.clicked.connect(self.review_selection_permissions)
        tools_header.addWidget(self.selection_permissions)
        self.permissions = QPushButton("Permisos guardados…")
        self.permissions.clicked.connect(self.review_permissions)
        tools_header.addWidget(self.permissions)
        layout.addLayout(tools_header)
        layout.addWidget(self.tools, 2)
        layout.addWidget(self.notice)
        self.reload()

    def set_appearance(self, theme):
        self.theme = theme
        self.setStyleSheet(dialog_style(theme))
        self.refresh(self.selected())

    def add_toggle(self, tree, item, column, checked, label, on_change, *, show_state=False, state_text=None):
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        surface, _, _, text = control_colors(self.theme["background"])
        switch = Toggle(checked, label, self.theme["accent"], surface)
        switch.setEnabled(self.test is None)
        switch.toggled.connect(on_change)
        layout.addWidget(switch)
        if show_state or state_text is not None:
            state = QLabel(state_text if state_text is not None else ("Activo" if checked else "Inactivo"))
            state.setStyleSheet(f"background: transparent; color: {text};")
            layout.addWidget(state)
        tree.setItemWidget(item, column, holder)
        if show_state or state_text is not None:
            state.ensurePolished()
            state.setMinimumWidth(state.fontMetrics().horizontalAdvance("Inactivo"))
        item.setSizeHint(column, holder.sizeHint().expandedTo(QSize(70, 30)))

    def reload(self):
        selected = self.selected()
        try:
            current = load_servers()
            self.results = {name: result for name, result in self.results.items()
                            if name == INTEGRATED_MEMORY or current.get(name) == self.servers.get(name)}
            self.servers = current
        except (ValueError, OSError, RuntimeError):
            self.notice.setText("No se pudo leer la configuración MCP.")
            self.refresh(selected)
            return False
        self.refresh(selected)
        return True

    def selected(self):
        item = self.table.currentItem()
        return item.text(0) if item else None

    def refresh(self, selected=None):
        blocker = QSignalBlocker(self.table)
        self.table.clear()
        rows = sorted(self.servers.items())
        if self.memory is not None:
            rows.append((INTEGRATED_MEMORY, None))
        for name, server in rows:
            status, _, detail = self.results.get(name, ("Sin probar", [], ""))
            item = QTreeWidgetItem([name, TRANSPORTS[server["transport"]] if server else "STDIO",
                                    "" if server else "Integrada"])
            item.setToolTip(0, name)
            self.table.addTopLevelItem(item)
            if server:
                self.add_toggle(self.table, item, 2, server["enabled"], f"Servidor {name}",
                                lambda checked, name=name: self.toggle_server(name, checked), show_state=True)
            label = QLabel(f"●  {status}")
            label.setToolTip(detail)
            color = STATUS_COLORS.get(status, "#b8b2c4")
            background, _, _, _ = control_colors(self.theme["background"])
            if readable_text(background) == "#000000":
                color = {"Correcta": "#126133", "Falló": "#a32929"}.get(status, "#52525b")
            label.setStyleSheet(f"color: {color}; background: transparent; padding-left: 5px;")
            self.table.setItemWidget(item, 3, label)
            label.ensurePolished()
            status_width = max(label.fontMetrics().horizontalAdvance(f"●  {text}")
                               for text in ("Sin probar", "Probando…", "Correcta", "Falló"))
            item.setSizeHint(3, QSize(status_width + 12, 30))
            if name == selected:
                self.table.setCurrentItem(item)
        if self.table.currentItem() is None and self.table.topLevelItemCount():
            self.table.setCurrentItem(self.table.topLevelItem(0))
        blocker.unblock()
        self.refresh_selection()

    def refresh_selection(self):
        name = self.selected()
        idle = self.test is None
        integrated = name == INTEGRATED_MEMORY
        self.add.setEnabled(idle)
        for button in (self.edit, self.remove, self.permissions):
            button.setEnabled(idle and name in self.servers)
        self.probe.setEnabled(idle and name is not None)
        self.probe.setText("Consultar catálogo" if integrated else "Probar conexión")
        self.memory_settings.setVisible(integrated)
        self.memory_settings.setEnabled(integrated and idle)
        self.api_key.setEnabled(idle and name in self.servers and bool(credential_target(name, self.servers[name])))
        if integrated and idle:
            _, tools, detail = self.results.get(name, ("Sin probar", [], ""))
            self.notice.setText(detail or (f"{len(tools)} herramientas en la conexión integrada de StoneBot." if tools else
                                           "Consulta el catálogo de la conexión que StoneBot usa para su memoria."))
        self.refresh_tools(name)

    def refresh_tools(self, name):
        integrated = name == INTEGRATED_MEMORY
        self.tools.setRootIsDecorated(not integrated)
        self.tools.setHeaderLabels(["Herramienta", "Descripción", "Uso en StoneBot", "Permiso"] if integrated else
                                   ["Herramienta", "Permiso", "Activación", "Tipo"])
        old_groups = [self.tools.topLevelItem(i) for i in range(self.tools.topLevelItemCount())]
        same_server = self.tools_server == name and bool(old_groups)
        expanded = {group.text(0) for group in old_groups if group.isExpanded()} if same_server else set()
        selected = {(item.parent() is None, tuple(item.data(0, TOOL_NAMES)))
                    for item in self.tools.selectedItems()} if same_server else set()
        self.tools_server = name
        self.tools.clear()
        _, tools, _ = self.results.get(name, ("", [], ""))
        if integrated:
            for tool in sorted(tools, key=lambda tool: tool.name):
                usage, permission = "Reservada", ""
                if tool.name in TOOLS:
                    usage = "Chat"
                    permission = ("Confirmación" if tool.name in REVIEWED_WRITES else
                                  "Según el turno" if tool.name in {"inject_memory", "update_memory"} else "Directo")
                elif tool.name == "force_dream":
                    usage = "/sueno memoria"
                elif tool.name == "dream_activity":
                    usage, permission = "Consulta de actividad en el chat", "Directo"
                elif tool.name in {"export_notes", "sync_memory"}:
                    usage, permission = "Ajustes de StoneWave", "Confirmación"
                description = (tool.description or "").strip()
                item = QTreeWidgetItem([tool.name, " ".join(description.split()), usage, permission])
                item.setData(0, TOOL_NAMES, (tool.name,))
                item.setToolTip(0, description)
                item.setToolTip(1, description)
                if usage == "Chat":
                    item.setToolTip(2, "Disponible según el turno y la configuración de memoria del proveedor.")
                self.tools.addTopLevelItem(item)
            self.update_tool_actions()
            return
        if not tools:
            self.update_tool_actions()
            return
        server = self.servers[name]
        disabled = set(server.get("disabled_tools", []))
        configured = set(server["read_tools"])
        try:
            granted = saved_permissions(name)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            granted = {}
        groups = defaultdict(list)
        for tool in tools:
            groups[category(tool)].append(tool)
        colors = ({"Lectura": "#16723f", "Cambios": "#906100", "Ejecución": "#a32929"}
                  if readable_text(self.theme["background"]) == "#000000" else
                  {"Lectura": "#86efac", "Cambios": "#fcd38b", "Ejecución": "#fca5a5"})
        for label, members in sorted(groups.items()):
            names = tuple(tool.name for tool in members)
            active_count = len(names) - len(disabled.intersection(names))
            group = QTreeWidgetItem([label, "", "", ""])
            group.setData(0, TOOL_NAMES, names)
            group.setToolTip(0, f"{active_count} de {len(names)} herramientas activas")
            self.tools.addTopLevelItem(group)
            self.add_toggle(self.tools, group, 2, active_count == len(names), f"Todas las herramientas de {label}",
                            lambda active, names=names: self.toggle_tools(name, names, active),
                            state_text=f"{active_count}/{len(names)}")
            for tool in members:
                automatic = safe_read(tool) and (
                    tool.name in configured or granted.get(tool.name) == permission_signature(server, tool))
                checked = tool.name not in disabled
                kind = operation(tool)
                permission = "Lectura automática" if automatic else "Requiere confirmación"
                item = QTreeWidgetItem([tool.name, permission, "", kind])
                item.setData(0, TOOL_NAMES, (tool.name,))
                item.setToolTip(0, tool.name)
                item.setToolTip(1, permission if checked else f"{permission} cuando la herramienta esté activa.")
                item.setToolTip(3, kind)
                if kind in colors:
                    item.setForeground(3, QColor(colors[kind]))
                group.addChild(item)
                self.add_toggle(self.tools, item, 2, checked, f"Herramienta {tool.name}",
                                lambda active, tool=tool.name: self.toggle_tools(name, (tool,), active), show_state=True)
                item.setSelected((False, (tool.name,)) in selected)
            group.setExpanded(label in expanded if same_server else len(tools) <= 8)
            group.setSelected((True, names) in selected)
        self.update_tool_actions()

    def update_tool_actions(self):
        self.selection_permissions.setEnabled(self.test is None and self.selected() in self.servers
                                              and bool(self.tools.selectedItems()))

    def review_selection_permissions(self):
        name = self.selected()
        if self.test is not None or name not in self.servers or not self.tools.selectedItems():
            return
        names = {tool for item in self.tools.selectedItems() for tool in item.data(0, TOOL_NAMES)}
        tools = [tool for tool in self.results[name][1] if tool.name in names]
        eligible = [tool for tool in tools if safe_read(tool)]
        dialog = QMessageBox(QMessageBox.Icon.Question, "Permisos de la selección",
                             f"{len(tools)} herramientas seleccionadas · {len(eligible)} lecturas compatibles.", parent=self)
        dialog.setInformativeText("Las operaciones de cambio, ejecución o riesgo desconocido requieren confirmación.")
        automatic = dialog.addButton("Autorizar lecturas compatibles", QMessageBox.ButtonRole.AcceptRole)
        require = dialog.addButton("Pedir confirmación", QMessageBox.ButtonRole.ActionRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        automatic.setEnabled(bool(eligible))
        dialog.setDefaultButton(cancel)
        dialog.exec()
        choice = dialog.clickedButton()
        dialog.deleteLater()
        try:
            server = self.servers[name]
            if choice is automatic:
                remember_many(name, [(tool.name, permission_signature(server, tool)) for tool in eligible])
                self.notice.setText(f"{len(eligible)} permisos de lectura guardados.")
            elif choice is require:
                remaining = [tool for tool in server["read_tools"] if tool not in names]
                if remaining != server["read_tools"] and not self.commit(name, dict(server, read_tools=remaining)):
                    return
                revoke_many(name, names)
                self.notice.setText("La selección volverá a pedir confirmación.")
            else:
                return
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            self.notice.setText("No se pudieron guardar todos los cambios de permisos.")
        self.refresh_tools(name)

    def commit(self, name, server):
        try:
            current = load_servers()
            if current != self.servers:
                self.servers = current
                self.results.clear()
                self.refresh(name)
                self.notice.setText("La configuración cambió fuera de esta ventana. Intenta de nuevo.")
                return False
            if server is None:
                del current[name]
            else:
                current[name] = server
            save_servers(current)
        except (ValueError, OSError, RuntimeError):
            self.notice.setText("No se pudo guardar la configuración MCP.")
            self.refresh(name)
            return False
        old = self.servers.get(name)
        self.servers = current
        transient = {"enabled", "disabled_tools", "read_tools"}
        if (old is None or server is None or
                any(old.get(key) != server.get(key) for key in (old.keys() | server.keys()) - transient)):
            self.results.pop(name, None)
        self.refresh(name)
        self.notice.setText("Cambios guardados. Se aplican al siguiente turno del chat.")
        old_target = credential_target(name, old)
        if old_target != credential_target(name, server):
            try:
                delete_key(old_target)
            except (OSError, ImportError):
                self.notice.setText("Cambios guardados. Windows no pudo quitar la clave de la URL anterior.")
        if old and server is None:
            try:
                revoke(name)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                self.notice.setText("Servidor eliminado. No se pudieron limpiar sus permisos guardados.")
        return True

    def review_permissions(self):
        name = self.selected()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Permisos de {name}")
        tools = QListWidget()
        remove = QPushButton("Revocar permiso")
        notice = QLabel("Los permisos guardados solo se aplican a herramientas de lectura que sigan siendo válidas.")
        notice.setWordWrap(True)

        def refresh():
            tools.clear()
            remove.setEnabled(False)
            try:
                tools.addItems(list_permissions(name))
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                notice.setText("No se pudieron leer los permisos guardados.")

        def remove_selected():
            try:
                revoke(name, tools.currentItem().text())
                refresh()
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                notice.setText("No se pudo revocar el permiso.")

        tools.currentItemChanged.connect(lambda current, previous: remove.setEnabled(current is not None))
        remove.clicked.connect(remove_selected)
        layout = QVBoxLayout(dialog)
        layout.addWidget(notice)
        layout.addWidget(tools)
        layout.addWidget(remove)
        dialog.resize(430, 290)
        refresh()
        dialog.exec()
        dialog.deleteLater()

    def manage_credential(self):
        name = self.selected()
        target = credential_target(name, self.servers[name])
        try:
            saved = bool(read_key(target))
        except (OSError, ValueError, ImportError):
            self.notice.setText("No se pudo abrir el Administrador de credenciales de Windows.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Clave API de {name}")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Hay una clave guardada." if saved else "Aún no hay una clave guardada."))
        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        entry.setAccessibleName("Nueva clave API")
        entry.setPlaceholderText("Nueva clave API")
        layout.addWidget(entry)
        buttons = QDialogButtonBox()
        save = buttons.addButton("Guardar", QDialogButtonBox.ButtonRole.AcceptRole)
        remove = buttons.addButton("Quitar clave", QDialogButtonBox.ButtonRole.DestructiveRole)
        remove.setEnabled(saved)
        buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def change(button):
            if button not in (save, remove):
                return
            try:
                if load_servers().get(name) != self.servers[name]:
                    raise ValueError("La configuración cambió. Vuelve a abrir el panel MCP.")
                revoke(name)
                if button == save:
                    store_key(target, entry.text())
                else:
                    delete_key(target)
            except ValueError as exc:
                QMessageBox.warning(dialog, "Clave API", str(exc))
                return
            except (OSError, ImportError, RuntimeError, sqlite3.Error):
                QMessageBox.warning(dialog, "Clave API", "Windows no pudo actualizar la clave.")
                return
            self.results.pop(name, None)
            self.connection_changed.emit(name)
            self.refresh(name)
            self.notice.setText("Clave guardada en Windows." if button == save else "Clave quitada de Windows.")
            dialog.accept()

        buttons.clicked.connect(change)
        try:
            dialog.exec()
        finally:
            entry.clear()
            dialog.deleteLater()

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
        return self.commit(name, dict(self.servers[name], enabled=checked))

    def quick_switches(self, menu, on_error, *, idle):
        menu.clear()
        if not self.reload():
            menu.addAction("No se pudo leer la configuración").setEnabled(False)
            return
        if not self.servers:
            menu.addAction("No hay servidores configurados").setEnabled(False)
            return
        surface, _, _, color = control_colors(self.theme["background"])
        for name, server in sorted(self.servers.items()):
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(9, 1, 6, 1)
            label = QLabel(name)
            label.setStyleSheet(f"color: {color};")
            layout.addWidget(label, 1)
            switch = Toggle(server["enabled"], f"Servidor {name}", self.theme["accent"], surface)
            switch.setEnabled(idle and self.test is None)
            switch.toggled.connect(lambda active, name=name, switch=switch:
                                   self.change_quick_switch(name, switch, active, on_error))
            layout.addWidget(switch)
            action = QWidgetAction(menu)
            action.setDefaultWidget(row)
            menu.addAction(action)

    def change_quick_switch(self, name, switch, active, on_error):
        if self.test is None and self.toggle_server(name, active):
            return
        with QSignalBlocker(switch):
            switch.setChecked(self.servers.get(name, {}).get("enabled", False))
        on_error(self.notice.text())

    def install_from_chat(self, text):
        try:
            name, server, download = prepare(text)
            ensure_new(load_servers(), name, server)
            if server.get("token_env") and not os.environ.get(server["token_env"]):
                raise ValueError(f"Falta la variable {server['token_env']}. Configúrala fuera del chat y reinicia StoneBot.")
        except (ValueError, RuntimeError, OSError) as exc:
            return str(exc) if isinstance(exc, ValueError) else "No se pudo preparar la configuración MCP."

        if server["transport"] == "http":
            review = f"Conectar por Streamable HTTP a {server['url']} para listar herramientas."
            if server["token_env"]:
                review += f"\nUsar la variable {server['token_env']} para autenticación."
        else:
            review = "Iniciar este ejecutable con los argumentos indicados para listar herramientas:\n"
            review += server["command"] + "\n" + json.dumps(server["args"], ensure_ascii=False)
            if download:
                review += "\nEl lanzador puede descargar e instalar el paquete en su caché antes de iniciarlo."
        review += "\n\nSi la prueba funciona, guardar el servidor desactivado y sin permisos automáticos."
        if is_desktop_commander(server):
            review += ("\nSus herramientas también quedarán desactivadas hasta que las habilites. "
                       "La primera prueba puede tardar unos dos minutos.")
        dialog = QMessageBox(QMessageBox.Icon.Question, f"Revisar MCP · {name}", review,
                             QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self.parentWidget())
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Autorizar y probar")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancelar")
        approved = dialog.exec() == QMessageBox.StandardButton.Yes
        dialog.deleteLater()
        if not approved:
            return "Configuración MCP cancelada."

        results = []
        test = self.test = ConnectionTest(self, name, server)
        test.result.connect(results.append)
        test.finished.connect(self.accept)
        self.refresh(self.selected())
        self.notice.setText(f"Verificando la conexión de {name} antes de guardarlo…")
        test.start()
        self.exec()
        test.wait()
        self.test = None
        test.deleteLater()
        self.refresh(self.selected())
        tools, error = results[0] if results else ([], "La prueba no devolvió un resultado.")
        if error:
            return f"No se guardó {name}. {error}"
        try:
            if not self.reload():
                return self.notice.text()
            ensure_new(self.servers, name, server)
        except ValueError as exc:
            return str(exc)
        if is_desktop_commander(server):
            server["disabled_tools"] = [tool.name for tool in tools]
        if not self.commit(name, server):
            return self.notice.text()
        self.results[name] = ("Correcta", tools, "")
        self.refresh(name)
        return f"{name} verificado y guardado desactivado. Herramientas encontradas: {len(tools)}."

    def toggle_tools(self, name, tools, enabled):
        server = self.servers[name]
        disabled = set(server.get("disabled_tools", []))
        (disabled.difference_update if enabled else disabled.update)(tools)
        self.commit(name, dict(server, disabled_tools=sorted(disabled)))

    def remove_server(self):
        name = self.selected()
        buttons = QMessageBox.StandardButton
        if QMessageBox.question(self, "Eliminar servidor MCP", f"¿Eliminar la configuración de {name}?",
                                buttons.Yes | buttons.No, buttons.No) == buttons.Yes:
            self.commit(name, None)

    def open_memory_settings(self):
        if self.selected() != INTEGRATED_MEMORY or self.test is not None:
            return
        try:
            dialog = StoneWaveSettingsDialog(self, self.memory, self.theme)
        except (OSError, RuntimeError, ValueError) as exc:
            self.notice.setText(f"No se pudieron abrir los ajustes de StoneWave: {exc}")
            return
        dialog.session_changed.connect(self.refresh_memory_session)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def refresh_memory_session(self, entries, error):
        tools = [entry[2] for entry in entries.values()] if entries else []
        self.results[INTEGRATED_MEMORY] = ("Falló" if error else "Correcta", tools, error)
        self.refresh(INTEGRATED_MEMORY)

    def test_connection(self):
        name = self.selected()
        if self.test is not None or name is None:
            return
        self.test = ConnectionTest(self, name, self.servers.get(name),
                                   memory=self.memory if name == INTEGRATED_MEMORY else None)
        self.test.result.connect(self.show_result)
        self.test.finished.connect(self.finish_test)
        self.results[name] = ("Probando…", [], "")
        self.refresh(name)
        self.notice.setText(f"Probando conexión con {name}…")
        self.test.start()

    def show_result(self, result):
        name = self.test.name
        if name != INTEGRATED_MEMORY:
            self.connection_changed.emit(name)
        tools, detail = result
        status = "Falló" if detail else "Correcta"
        self.results[name] = (status, tools, detail)
        self.refresh(self.selected())
        self.notice.setText(f"{name}. {detail}" if detail
                            else f"Conexión correcta con {name}. Herramientas: {len(tools)}.")

    def finish_test(self):
        self.test.deleteLater()
        self.test = None
        self.refresh(self.selected())

    def reject(self):
        if self.test is None:
            super().reject()

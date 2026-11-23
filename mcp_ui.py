"""Administrador gráfico de las configuraciones MCP."""
import asyncio
import json
import os
import sqlite3
from collections import defaultdict

from PySide6.QtCore import QSize, QSignalBlocker, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabBar,
    QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetAction,
)

from appearance import COLORS, SettingsComboBox, control_colors, readable_text
from extension_ui import CardDelegate, CardTree, Toggle, extension_style
from mcp_client import (
    connection_error, is_desktop_commander, load_servers, probe_server, save_servers, startup_timeout, validate_server,
)
from mcp_credentials import credential_target, delete_key, read_key, store_key
from mcp_permissions import list_permissions, permission_signature, remember_many, revoke, revoke_many, safe_read, saved_permissions
from mcp_setup import ensure_new, prepare
from mcp_tool_groups import category, operation
from skills_ui import SkillsPanel
from stonewave_memory import MemoryUnavailable, REVIEWED_WRITES, TOOLS
from stonewave_settings_ui import StoneWaveSettingsPanel


TRANSPORTS = {"stdio": "STDIO", "http": "Streamable HTTP"}
TOOL_NAMES = Qt.ItemDataRole.UserRole
INTEGRATED_MEMORY = "StoneWave · Integrado"


class ServerForm(QDialog):
    def __init__(self, parent, name=None, server=None):
        super().__init__(parent)
        self.setWindowTitle("Editar servidor MCP" if server else "Agregar servidor MCP")
        old = server or {}
        self.name = QLineEdit(name or "")
        self.name.setReadOnly(name is not None)
        self.transport = SettingsComboBox()
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
        self.form.setContentsMargins(24, 20, 24, 20)
        self.form.setVerticalSpacing(10)
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
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("primary", True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.form.addRow(self.error)
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
            self.error.setText(str(exc))
            return
        except (OSError, RuntimeError):
            self.error.setText("Revisa las rutas del servidor.")
            return
        changed = self.old and any(
            server.get(key) != self.old.get(key) for key in ("transport", "command", "args", "url", "token_env")
        )
        if changed:
            server.update(enabled=False, read_tools=[])
        self.connection_reset = bool(changed)
        self.configuration = name, server
        super().accept()


class ConnectionTest(QThread):
    result = Signal(object)

    def __init__(self, parent, name, server, *, memory=None):
        super().__init__(parent)
        self.name = name
        self.server = server
        self.memory = memory
        self.loop = None
        self.task = None

    async def probe(self):
        if self.memory is not None:
            return [entry[2] for entry in (await self.memory.entries()).values()]
        async with asyncio.timeout(startup_timeout(self.server)):
            return await probe_server(self.name, self.server, include_definitions=True)

    def run(self):
        try:
            tools = asyncio.run(self.run_probe())
        except asyncio.CancelledError:
            return
        except MemoryUnavailable as exc:
            self.result.emit(([], str(exc)))
        except Exception as exc:
            self.result.emit(([], connection_error(exc)))
        else:
            self.result.emit((tools, ""))

    async def run_probe(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if self.isInterruptionRequested():
            raise asyncio.CancelledError
        return await self.probe()

    def cancel(self):
        self.requestInterruption()
        if self.loop is not None and self.task is not None:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass


class McpDialog(QDialog):
    connection_changed = Signal(str)

    def __init__(self, parent, *, memory=None):
        super().__init__(parent)
        self.setObjectName("extensionsWindow")
        self.setWindowTitle("Extensiones de StoneBot")
        self.resize(1010, 650)
        self.setMinimumSize(780, 480)
        self.theme = COLORS
        self.setStyleSheet(extension_style(self.theme))
        self.servers = {}
        self.memory = memory
        self.memory_panel = None
        self.results = {}
        self.test = None
        self.pending_tests = []
        self.close_requested = False
        self.editor = None

        self.table = CardTree()
        self.table.setAccessibleName("Servidores MCP")
        self.table.setRootIsDecorated(False)
        self.table.currentItemChanged.connect(self.refresh_selection)
        self.tools = CardTree()
        self.tools.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tools.setAccessibleName("Herramientas del servidor")
        self.tools.itemSelectionChanged.connect(self.update_tool_actions)
        self.tools_server = None
        for tree in (self.table, self.tools):
            tree.setProperty("extensionCards", True)
            tree.setMouseTracking(True)
            tree.setColumnCount(4)
            tree.setHeaderHidden(True)
            for column in range(1, tree.columnCount()):
                tree.setColumnHidden(column, True)
            tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            tree.setItemDelegate(CardDelegate(tree, self.theme))
        self.notice = QLabel()
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        self.notice.setObjectName("mcpNotice")

        self.add = QPushButton("Agregar servidor…")
        self.add.clicked.connect(self.add_server)
        sidebar = QWidget()
        sidebar.setObjectName("extensionSidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        sidebar.setFixedWidth(208)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.addWidget(self.table, 1)
        sidebar_layout.addWidget(self.add)

        self.server_title = QLabel()
        self.server_title.setObjectName("extensionTitle")
        self.server_title.setTextFormat(Qt.TextFormat.PlainText)
        self.server_summary = QLabel()
        self.server_summary.setProperty("muted", True)
        self.server_summary.setWordWrap(True)
        self.badge = QLabel()
        self.badge.setObjectName("extensionBadge")
        title = QVBoxLayout()
        title.setSpacing(3)
        title.addWidget(self.server_title)
        title.addWidget(self.server_summary)
        heading = QHBoxLayout()
        heading.addLayout(title, 1)
        heading.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
        self.probe = QPushButton("↻")
        self.probe.setObjectName("extensionReload")
        self.probe.setProperty("quiet", True)
        self.probe.setAccessibleName("Recargar servidor")
        self.probe.setToolTip("Recargar conexión y herramientas")
        self.probe.clicked.connect(lambda: self.test_connection())
        heading.addWidget(self.probe, alignment=Qt.AlignmentFlag.AlignTop)

        self.edit = QPushButton("Editar")
        self.remove = QPushButton("Eliminar")
        self.api_key = QPushButton("Clave API…")
        for button, callback in ((self.edit, self.edit_server), (self.remove, self.remove_server),
                                 (self.api_key, self.manage_credential)):
            button.clicked.connect(callback)
        self.server_switch = QWidget()
        switch_layout = QHBoxLayout(self.server_switch)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        self.active_switch = self.card_switch(False, "Servidor MCP", self.change_server_activation)
        self.active_state = QLabel()
        switch_layout.addWidget(self.active_switch)
        switch_layout.addWidget(self.active_state)
        self.controls = QWidget()
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.server_switch)
        controls.addStretch()
        for button in (self.edit, self.remove, self.api_key):
            controls.addWidget(button)
        self.tools_panel = QWidget()
        tools_layout = QVBoxLayout(self.tools_panel)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_header = QHBoxLayout()
        tools_title = QLabel("Herramientas")
        tools_title.setProperty("sectionHeading", True)
        tools_header.addWidget(tools_title, 1)
        self.selection_permissions = QPushButton("Permisos de selección…")
        self.selection_permissions.clicked.connect(self.review_selection_permissions)
        tools_header.addWidget(self.selection_permissions)
        self.permissions = QPushButton("Permisos guardados…")
        self.permissions.clicked.connect(self.review_permissions)
        tools_header.addWidget(self.permissions)
        tools_layout.addLayout(tools_header)
        self.tools_empty = QLabel()
        self.tools_empty.setObjectName("extensionEmpty")
        self.tools_empty.setProperty("muted", True)
        self.tools_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tools_empty.setWordWrap(True)
        self.tools_view = QStackedWidget()
        self.tools_view.addWidget(self.tools)
        self.tools_view.addWidget(self.tools_empty)
        tools_layout.addWidget(self.tools_view, 1)
        self.server_pages = QStackedWidget()
        external_tools = QWidget()
        self.external_tools_layout = QVBoxLayout(external_tools)
        self.external_tools_layout.setContentsMargins(0, 0, 0, 0)
        self.external_tools_layout.addWidget(self.tools_panel)
        self.server_pages.addWidget(external_tools)

        self.detail_pages = QStackedWidget()
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addLayout(heading)
        detail_layout.addSpacing(8)
        detail_layout.addWidget(self.controls)
        detail_layout.addWidget(self.server_pages, 1)
        self.detail_pages.addWidget(detail)

        mcp_page = QWidget()
        layout = QHBoxLayout(mcp_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(sidebar)
        layout.addWidget(self.detail_pages, 1)

        self.skills_panel = SkillsPanel(self, self.theme)
        self.pages = QStackedWidget()
        self.pages.addWidget(mcp_page)
        self.pages.addWidget(self.skills_panel)
        self.tabs = QTabBar()
        self.tabs.setObjectName("extensionTabs")
        self.tabs.setAccessibleName("Secciones de extensiones")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.addTab("MCP")
        self.tabs.addTab("Skills")
        self.tabs.currentChanged.connect(self.show_section)

        brand = QLabel("StoneBot")
        brand.setObjectName("extensionBrand")
        self.route = QLabel("Configuración › Servidores MCP")
        self.route.setProperty("muted", True)
        header = QHBoxLayout()
        header.addWidget(brand, 1)
        header.addWidget(self.route)
        divider = QFrame()
        divider.setObjectName("extensionDivider")
        divider.setFixedHeight(1)
        footer = QHBoxLayout()
        self.footer_status = QStackedWidget()
        self.footer_status.addWidget(self.notice)
        self.footer_status.addWidget(self.skills_panel.status)
        footer.addWidget(self.footer_status, 1)
        self.apply_button = QPushButton("Aplicar cambios")
        self.apply_button.setProperty("primary", True)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_memory)
        footer.addWidget(self.apply_button)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(20, 14, 20, 14)
        shell.setSpacing(10)
        shell.addLayout(header)
        shell.addWidget(self.tabs)
        shell.addWidget(divider)
        shell.addWidget(self.pages, 1)
        shell.addLayout(footer)
        self.reload()

    def show_section(self, index):
        if self.pages.widget(index) is self.skills_panel:
            self.skills_panel.refresh()
        self.pages.setCurrentIndex(index)
        self.footer_status.setCurrentIndex(index)
        self.route.setText("Configuración › Skills" if index else "Configuración › Servidores MCP")
        self.refresh_apply()

    def open_section(self, *, skills=False):
        index = self.pages.indexOf(self.skills_panel) if skills else 0
        if not skills:
            self.reload()
        if self.tabs.currentIndex() == index:
            self.show_section(index)
        else:
            self.tabs.setCurrentIndex(index)
        self.exec()

    def showEvent(self, event):
        super().showEvent(event)
        if self.memory_panel is not None:
            try:
                self.memory_panel.reset()
            except (OSError, RuntimeError, ValueError) as exc:
                self.notice.setText(str(exc))
        enabled = [name for name, server in self.servers.items() if server["enabled"]]
        if self.memory is not None:
            enabled.append(INTEGRATED_MEMORY)
        if self.selected() in enabled:
            enabled.remove(self.selected())
            enabled.insert(0, self.selected())
        self.queue_checks(enabled)

    def set_appearance(self, theme):
        self.theme = theme
        self.active_switch.accent = theme["accent"]
        self.active_switch.surface = control_colors(theme["background"])[0]
        self.setStyleSheet(extension_style(theme))
        self.table.itemDelegate().theme = theme
        self.tools.itemDelegate().theme = theme
        self.skills_panel.set_appearance(theme)
        if self.memory_panel is not None:
            self.memory_panel.set_appearance(theme)
        self.refresh(self.selected())

    def card_switch(self, checked, label, on_change):
        surface = control_colors(self.theme["background"])[0]
        switch = Toggle(checked, label, self.theme["accent"], surface)
        switch.toggled.connect(on_change)
        return switch

    def set_card(self, tree, item, detail="", *, title=None, description="", tag=None, switch=None, state_text=None):
        card = QWidget()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(13, 7, 13, 7)
        layout.setSpacing(11)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        for value, object_name in ((title or item.text(0), "mcpCardTitle"), (detail, "mcpCardDetail"),
                                   (description, "mcpCardDetail")):
            if value:
                label = QLabel(value)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setObjectName(object_name)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                copy.addWidget(label)
        layout.addLayout(copy, 1)
        card.setToolTip("\n".join(filter(None, (item.text(0), detail, description, tag.toolTip() if tag else ""))))
        if tag is not None:
            tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(tag)
        if switch is not None:
            state = QLabel(state_text if state_text is not None else ("Activo" if switch.isChecked() else "Inactivo"))
            state.setObjectName("mcpCardState")
            state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(state)
            layout.addWidget(switch)
            state.ensurePolished()
            state.setMinimumWidth(state.fontMetrics().horizontalAdvance("Inactivo"))
        tree.setItemWidget(item, 0, card)
        card.ensurePolished()
        item.setSizeHint(0, QSize(0, max(48, card.sizeHint().height() + 8)))

    def reload(self):
        selected = self.selected()
        try:
            current = load_servers()
            self.results = {name: result for name, result in self.results.items()
                            if name == INTEGRATED_MEMORY or current.get(name) == self.servers.get(name)}
            self.servers = current
        except (ValueError, OSError, RuntimeError):
            self.refresh(selected)
            self.notice.setText("No se pudo leer la configuración MCP.")
            return False
        self.refresh(selected)
        return True

    def selected(self):
        item = self.table.currentItem()
        return item.text(0) if item else None

    def refresh(self, selected=None):
        with QSignalBlocker(self.table):
            self.table.clear()
            rows = sorted(self.servers)
            if self.memory is not None:
                rows.append(INTEGRATED_MEMORY)
            for name in rows:
                item = QTreeWidgetItem([name])
                item.setToolTip(0, name)
                self.table.addTopLevelItem(item)
                integrated = name == INTEGRATED_MEMORY
                self.set_card(self.table, item, "Integrado" if integrated else "",
                              title="StoneWave" if integrated else name)
                if name == selected:
                    self.table.setCurrentItem(item)
            if self.table.currentItem() is None and self.table.topLevelItemCount():
                self.table.setCurrentItem(self.table.topLevelItem(0))
        self.refresh_selection()

    def refresh_selection(self):
        name = self.selected()
        integrated = name == INTEGRATED_MEMORY
        external = name in self.servers
        server = self.servers.get(name, {})
        status, _, detail = self.results.get(name, ("Sin probar", [], ""))
        loading = status == "Probando…"
        self.server_title.setText("StoneWave" if integrated else name or "Servidores MCP")
        self.server_summary.setText("Memoria integrada de StoneBot en este equipo." if integrated else
                                    f"Conexión MCP · {TRANSPORTS[server['transport']]}" if external else
                                    "Agrega un servidor para administrar su conexión y sus herramientas.")
        self.badge.setVisible(name is not None)
        self.badge.setText({"Correcta": "● Conectado", "Falló": "● Error", "Probando…": "Cargando…"}.get(status, status))
        self.badge.setToolTip(detail)
        self.badge.setProperty("connection", {"Correcta": "connected", "Falló": "error"}.get(status, "idle"))
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.probe.setVisible(name is not None)
        self.probe.setEnabled(not loading)
        self.controls.setVisible(external)
        self.permissions.setVisible(external)
        self.selection_permissions.setVisible(external)
        self.edit.setEnabled(not loading)
        self.remove.setEnabled(not loading)
        self.api_key.setEnabled(external and not loading and bool(credential_target(name, server)))
        if external:
            active = server["enabled"]
            self.active_switch.setAccessibleName(f"Servidor {name}")
            self.active_switch.setEnabled(not loading)
            with QSignalBlocker(self.active_switch):
                self.active_switch.setChecked(active)
            self.active_state.setText("Activo" if active else "Inactivo")
        if name != self.tools_server:
            self.notice.setText(detail or ("Aplicar cambios reinicia la sesión integrada de StoneWave." if integrated else ""))
        if integrated and self.ensure_memory_panel():
            if self.memory_panel.catalog_layout.indexOf(self.tools_panel) == -1:
                self.memory_panel.catalog_layout.addWidget(self.tools_panel)
            self.server_pages.setCurrentWidget(self.memory_panel)
        else:
            if self.external_tools_layout.indexOf(self.tools_panel) == -1:
                self.external_tools_layout.addWidget(self.tools_panel)
            self.server_pages.setCurrentIndex(0)
        self.refresh_tools(name)
        self.refresh_apply()

    def refresh_tools(self, name):
        integrated = name == INTEGRATED_MEMORY
        self.tools.setRootIsDecorated(not integrated)
        old_groups = [self.tools.topLevelItem(i) for i in range(self.tools.topLevelItemCount())]
        same_server = self.tools_server == name and bool(old_groups)
        expanded = {group.text(0) for group in old_groups if group.isExpanded()} if same_server else set()
        selected = {(item.parent() is None, tuple(item.data(0, TOOL_NAMES)))
                    for item in self.tools.selectedItems()} if same_server else set()
        self.tools_server = name
        self.tools.clear()
        status, tools, _ = self.results.get(name, ("", [], ""))
        if name is None:
            empty_message = "Agrega un servidor MCP para ver sus herramientas."
        elif status == "Probando…":
            empty_message = "Consultando herramientas…"
        elif status == "Falló":
            empty_message = "La conexión falló antes de obtener las herramientas."
        elif name in self.results:
            empty_message = "No se encontraron herramientas para esta conexión."
        else:
            empty_message = ("El catálogo de StoneWave se carga al abrir Extensiones." if integrated else
                             "Activa el servidor o pulsa Recargar para cargar sus herramientas.")
        self.tools_empty.setText(empty_message)
        self.tools_view.setCurrentWidget(self.tools if tools else self.tools_empty)
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
                elif tool.name == "recent_notes":
                    usage, permission = "Lectura de notas en el chat", "Directo"
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
                self.set_card(self.tools, item, " · ".join(filter(None, (usage, permission))), description=item.text(1))
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
            group_switch = self.card_switch(active_count == len(names), f"Todas las herramientas de {label}",
                                            lambda active, names=names: self.toggle_tools(name, names, active))
            self.set_card(self.tools, group, switch=group_switch, state_text=f"{active_count}/{len(names)}")
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
                group.addChild(item)
                tag = QLabel(kind)
                tag.setObjectName("mcpCardStatus")
                if kind in colors:
                    tag.setStyleSheet(f"color: {colors[kind]};")
                switch = self.card_switch(checked, f"Herramienta {tool.name}",
                                          lambda active, tool=tool.name: self.toggle_tools(name, (tool,), active))
                self.set_card(self.tools, item, permission, description=" ".join((tool.description or "").split()), tag=tag, switch=switch)
                item.setSelected((False, (tool.name,)) in selected)
            group.setExpanded(label in expanded if same_server else len(tools) <= 8)
            group.setSelected((True, names) in selected)
        self.update_tool_actions()

    def update_tool_actions(self):
        self.selection_permissions.setEnabled(self.selected() in self.servers
                                              and bool(self.tools.selectedItems()))

    def open_editor(self, editor, finish=None):
        self.editor = editor
        editor.setWindowFlags(Qt.WindowType.Widget)
        pane = QWidget()
        pane.setProperty("extensionCanvas", True)
        pane.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel(editor.windowTitle())
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setObjectName("extensionTitle")
        layout.addWidget(heading)
        layout.addWidget(editor)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(pane)
        self.detail_pages.addWidget(scroll)
        self.detail_pages.setCurrentWidget(scroll)
        self.tabs.setEnabled(False)
        self.table.setEnabled(False)
        self.add.setEnabled(False)
        self.refresh_apply()

        def closed(result):
            self.editor = None
            self.detail_pages.setCurrentIndex(0)
            self.detail_pages.removeWidget(scroll)
            scroll.deleteLater()
            self.tabs.setEnabled(True)
            self.table.setEnabled(True)
            self.add.setEnabled(True)
            if finish is not None:
                finish(result)
            self.refresh_apply()

        editor.finished.connect(closed)

    def prompt(self, title, text):
        editor = QDialog(self)
        editor.setWindowTitle(title)
        layout = QVBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        description = QLabel(text)
        description.setTextFormat(Qt.TextFormat.PlainText)
        description.setWordWrap(True)
        layout.addWidget(description)
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancelar", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.clicked.connect(editor.reject)
        layout.addWidget(buttons)
        return editor, buttons

    def review_selection_permissions(self):
        name = self.selected()
        if name not in self.servers or not self.tools.selectedItems():
            return
        names = {tool for item in self.tools.selectedItems() for tool in item.data(0, TOOL_NAMES)}
        tools = [tool for tool in self.results[name][1] if tool.name in names]
        eligible = [tool for tool in tools if safe_read(tool)]
        dialog, buttons = self.prompt(
            "Permisos de la selección",
            f"{len(tools)} herramientas seleccionadas · {len(eligible)} lecturas compatibles.\n"
            "Las operaciones de cambio, ejecución o riesgo desconocido requieren confirmación.",
        )
        automatic = buttons.addButton("Autorizar lecturas compatibles", QDialogButtonBox.ButtonRole.AcceptRole)
        require = buttons.addButton("Pedir confirmación", QDialogButtonBox.ButtonRole.ActionRole)
        automatic.setEnabled(bool(eligible))

        def choose(allow):
            dialog.accept()
            self.save_selection_permissions(name, names, eligible, allow=allow)

        automatic.clicked.connect(lambda: choose(True))
        require.clicked.connect(lambda: choose(False))
        self.open_editor(dialog)

    def save_selection_permissions(self, name, names, eligible, *, allow):
        try:
            server = self.servers[name]
            if allow:
                remember_many(name, [(tool.name, permission_signature(server, tool)) for tool in eligible])
                self.notice.setText(f"{len(eligible)} permisos de lectura guardados.")
            else:
                remaining = [tool for tool in server["read_tools"] if tool not in names]
                if remaining != server["read_tools"] and not self.commit(name, dict(server, read_tools=remaining)):
                    return
                revoke_many(name, names)
                self.notice.setText("La selección volverá a pedir confirmación.")
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
        close = QPushButton("Volver")
        close.clicked.connect(dialog.reject)
        layout.addWidget(close)
        refresh()
        self.open_editor(dialog, lambda _: self.refresh_tools(self.selected()))

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
        error = QLabel()
        error.setTextFormat(Qt.TextFormat.PlainText)
        error.setWordWrap(True)
        layout.addWidget(error)
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
                error.setText(str(exc))
                return
            except (OSError, ImportError, RuntimeError, sqlite3.Error):
                error.setText("Windows no pudo actualizar la clave.")
                return
            self.results.pop(name, None)
            self.connection_changed.emit(name)
            self.refresh(name)
            self.notice.setText("Clave guardada en Windows." if button == save else "Clave quitada de Windows.")
            dialog.accept()

        buttons.clicked.connect(change)
        self.open_editor(dialog, lambda _: entry.clear())

    def add_server(self):
        form = ServerForm(self)

        def save(result):
            if not result:
                return
            name, server = form.configuration
            if name in self.servers:
                self.notice.setText("Ya existe un servidor con ese nombre.")
            else:
                self.commit(name, server)
        self.open_editor(form, save)

    def edit_server(self):
        name = self.selected()
        form = ServerForm(self, name, self.servers[name])

        def save(result):
            if result and self.commit(*form.configuration) and form.connection_reset:
                self.notice.setText("La conexión cambió. Vuelve a activar el servidor y autorizar sus lecturas.")

        self.open_editor(form, save)

    def toggle_server(self, name, checked):
        return self.commit(name, dict(self.servers[name], enabled=checked))

    def change_server_activation(self, checked):
        name = self.selected()
        if name in self.servers:
            self.toggle_server(name, checked)

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
        dialog, buttons = self.prompt("Eliminar servidor MCP", f"¿Eliminar la configuración de {name}?")
        remove = buttons.addButton("Eliminar", QDialogButtonBox.ButtonRole.DestructiveRole)
        remove.clicked.connect(dialog.accept)
        self.open_editor(dialog, lambda result: self.commit(name, None) if result else None)

    def ensure_memory_panel(self):
        if self.memory_panel is not None:
            return True
        try:
            self.memory_panel = StoneWaveSettingsPanel(self, self.memory, self.notice, self.confirm_memory_action, self.theme)
        except (OSError, RuntimeError, ValueError) as exc:
            self.notice.setText(f"No se pudieron abrir los ajustes de StoneWave: {exc}")
            return False
        self.memory_panel.session_changed.connect(self.refresh_memory_session)
        self.memory_panel.activity_changed.connect(self.refresh_apply)
        self.server_pages.addWidget(self.memory_panel)
        return True

    def confirm_memory_action(self, title, explanation, run):
        dialog, buttons = self.prompt(title, explanation)
        confirm = buttons.addButton("Continuar", QDialogButtonBox.ButtonRole.AcceptRole)
        confirm.clicked.connect(dialog.accept)
        self.open_editor(dialog, lambda result: run() if result else None)

    def refresh_apply(self):
        if self.selected() == INTEGRATED_MEMORY and self.memory_panel is not None:
            checking = self.test is not None and self.test.name == INTEGRATED_MEMORY
            self.probe.setEnabled(not checking and self.memory_panel.job is None)
        self.apply_button.setEnabled(
            self.tabs.currentIndex() == 0 and self.selected() == INTEGRATED_MEMORY and self.editor is None
            and self.memory_panel is not None and self.memory_panel.can_apply()
            and (self.test is None or self.test.name != INTEGRATED_MEMORY)
        )

    def apply_memory(self):
        if self.apply_button.isEnabled():
            self.memory_panel.apply()

    def refresh_memory_session(self, entries, error):
        tools = [entry[2] for entry in entries.values()] if entries else []
        self.results[INTEGRATED_MEMORY] = ("Falló" if error else "Correcta", tools, error)
        if self.selected() == INTEGRATED_MEMORY:
            self.refresh_selection()

    def test_connection(self):
        name = self.selected()
        if name is not None:
            self.queue_checks((name,), manual=True)

    def queue_checks(self, names, *, manual=False):
        for name in names:
            if (self.test is None or self.test.name != name) and not any(key == name for key, _ in self.pending_tests):
                self.pending_tests.append((name, manual))
        self.start_next_check()

    def start_next_check(self):
        if self.test is not None or self.close_requested:
            return
        while self.pending_tests:
            name, manual = self.pending_tests.pop(0)
            server = self.servers.get(name)
            if name == INTEGRATED_MEMORY and self.memory_panel is not None and self.memory_panel.job is not None:
                continue
            if name != INTEGRATED_MEMORY and (server is None or not (manual or server["enabled"])):
                continue
            self.test = ConnectionTest(self, name, server, memory=self.memory if name == INTEGRATED_MEMORY else None)
            self.test.manual = manual
            self.test.result.connect(self.show_result)
            self.test.finished.connect(self.finish_test)
            self.results[name] = ("Probando…", [], "")
            if self.selected() == name:
                self.refresh_selection()
                self.notice.setText(f"Cargando herramientas de {self.server_title.text()}…")
            self.test.start()
            return

    def show_result(self, result):
        name = self.test.name
        if name != INTEGRATED_MEMORY and self.servers.get(name) != self.test.server:
            return
        if self.test.manual and name != INTEGRATED_MEMORY:
            self.connection_changed.emit(name)
        tools, detail = result
        self.results[name] = ("Falló" if detail else "Correcta", tools, detail)
        if self.selected() == name:
            self.refresh_selection()
            self.notice.setText(detail or f"Herramientas disponibles: {len(tools)}.")

    def finish_test(self):
        name = self.test.name
        canceled = self.results.get(name, ("",))[0] == "Probando…"
        if canceled:
            self.results.pop(name, None)
        self.test.deleteLater()
        self.test = None
        self.refresh_apply()
        if self.close_requested:
            self.close_requested = False
            self.reject()
        else:
            if canceled and self.selected() == name:
                self.refresh_selection()
            self.start_next_check()

    def reject(self):
        self.pending_tests.clear()
        if self.test is not None:
            self.close_requested = True
            self.test.cancel()
            return
        if self.memory_panel is not None and self.memory_panel.job is not None:
            return
        if self.editor is not None:
            self.editor.reject()
        super().reject()

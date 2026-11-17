"""Comprueba las acciones por lote del panel Qt con un perfil temporal."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mcp.types import Tool
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

import mcp_client
from mcp_permissions import permission_signature, safe_read, saved_permissions
from mcp_ui import McpDialog, Toggle


def check_groups(qt, catalog):
    with TemporaryDirectory() as directory, patch.object(mcp_client, "default_root", return_value=Path(directory)):
        name = "example"
        names = {tool.name for tool in catalog}
        legacy = next(tool.name for tool in catalog if safe_read(tool))
        server = dict(transport="stdio", command=sys.executable, args=[], enabled=False,
                      read_tools=[legacy], disabled_tools=sorted(names))
        mcp_client.save_servers({name: server})
        dialog = McpDialog(None)
        dialog.results[name] = ("Correcta", catalog, "")
        dialog.refresh(name)
        dialog.show()
        qt.processEvents()
        tree = dialog.tools

        def groups():
            return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

        def children(group):
            return [group.child(i) for i in range(group.childCount())]

        def toggle(item):
            return tree.itemWidget(item, 2).findChild(Toggle)

        def rows():
            return {item.text(0): item for group in groups() for item in children(group)}

        def choose(label):
            assert dialog.selection_permissions.isEnabled()

            def click():
                box = QApplication.activeModalWidget()
                button = next((button for button in box.buttons() if button.text() == label), None)
                if button is not None and button.isEnabled():
                    button.click()
                else:
                    box.reject()
            QTimer.singleShot(0, click)
            dialog.selection_permissions.click()

        assert set(rows()) == names and len(groups()) > 1
        if len(catalog) > 8:
            assert all(not group.isExpanded() for group in groups())
        group = max(groups(), key=lambda item: item.childCount())
        label = group.text(0)
        members = {item.text(0) for item in children(group)}
        group.setExpanded(True)
        group.setSelected(True)
        QTest.mouseClick(toggle(group), Qt.MouseButton.LeftButton)
        reduced = mcp_client.load_servers()[name]
        assert set(reduced["disabled_tools"]) == names - members
        assert reduced["read_tools"] == [legacy] and not saved_permissions(name)
        group = next(item for item in groups() if item.text(0) == label)
        assert group.isExpanded() and group.isSelected()
        assert tree.itemWidget(group, 2).findChild(QLabel).text() == f"{len(members)}/{len(members)}"
        QTest.mouseClick(toggle(group), Qt.MouseButton.LeftButton)
        assert set(mcp_client.load_servers()[name]["disabled_tools"]) == names

        compatible = {tool.name: permission_signature(server, tool) for tool in catalog if safe_read(tool)}
        risk = next(tool.name for tool in catalog if not safe_read(tool))
        tree.clearSelection()
        rows()[legacy].setSelected(True)
        rows()[risk].setSelected(True)
        choose("Autorizar lecturas compatibles")
        assert saved_permissions(name) == {legacy: compatible[legacy]}
        assert rows()[risk].text(1) == "Requiere confirmación"
        choose("Pedir confirmación")
        assert not saved_permissions(name) and not mcp_client.load_servers()[name]["read_tools"]
        assert rows()[legacy].text(1) == "Requiere confirmación"

        tree.clearSelection()
        read_group = rows()[legacy].parent()
        read_group.setExpanded(True)
        read_group.setSelected(True)
        expected = {item.text(0): compatible[item.text(0)] for item in children(read_group)
                    if item.text(0) in compatible}
        choose("Autorizar lecturas compatibles")
        assert saved_permissions(name) == expected
        tree.scrollToItem(rows()[legacy])
        QTest.mouseClick(toggle(rows()[legacy]), Qt.MouseButton.LeftButton)
        reopened = McpDialog(None)
        reopened.results[name] = ("Correcta", catalog, "")
        reopened.refresh(name)
        assert set(reopened.servers[name]["disabled_tools"]) == names - {legacy}
        assert not reopened.servers[name]["enabled"] and saved_permissions(name) == expected
        assert {item.text(3) for item in rows().values()} >= {"Lectura", "Cambios", "Ejecución"}
        reopened.close()
        dialog.close()


if __name__ == "__main__":
    qt = QApplication([])
    fixture = [
        Tool(name=name, inputSchema={"type": "object"}, annotations={"readOnlyHint": read})
        for name, read in (("read_file", True), ("list_directory", True), ("write_file", True), ("run_command", False))
    ]
    check_groups(qt, fixture)
    if len(sys.argv) > 1:
        catalog = [Tool.model_validate(row) for row in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))]
        assert len(catalog) == 25
        check_groups(qt, catalog)
        print("PASS: catálogo real de Desktop Commander, 25 herramientas.")
    print("PASS: grupos, permisos por lote y persistencia.")

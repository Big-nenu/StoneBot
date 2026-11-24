"""Comprueba edición de recuerdos y aplicación de correcciones con un perfil temporal."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

import app
import mcp_client
from experiences import save_task_correction, task_correction


def wait_for_memories(dialog):
    if dialog.busy:
        loop = QEventLoop()
        dialog.loaded.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        dialog.loaded.disconnect(loop.quit)
    assert not dialog.busy


def test_memory_editor(root):
    old = "La carpeta de mis proyectos está en Carpeta Antigua"
    new = "La carpeta de mis proyectos está en Carpeta Nueva"
    memory = SimpleNamespace(call=AsyncMock(side_effect=[
        f"Memoria (1 recuerdos):\n- [ID 1] {old}",
        "Recuerdo actualizado.", f"Memoria (1 recuerdos):\n- [ID 2] {new}",
        "Olvidado: [ID 2]", "La memoria está vacía todavía.",
    ]))
    dialog = app.MemoryDialog(None, app.load_appearance(), memory)
    try:
        wait_for_memories(dialog)
        assert old in dialog.list.toPlainText()
        with (patch.object(QInputDialog, "getInt", return_value=(1, True)),
              patch.object(QInputDialog, "getMultiLineText", return_value=(new, True))):
            dialog.edit.click()
        wait_for_memories(dialog)
        assert new in dialog.list.toPlainText()
        with (patch.object(QInputDialog, "getInt", return_value=(2, True)),
              patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)):
            dialog.remove.click()
        wait_for_memories(dialog)
        assert new not in dialog.list.toPlainText()
        assert memory.call.await_args_list == [
            call("list_memories", limit=1000),
            call("update_memory", fact_id=1, new_content=new),
            call("list_memories", limit=1000),
            call("forget_memory", fact_id=2),
            call("list_memories", limit=1000),
        ]
    finally:
        dialog.close()


async def test_inventory_correction(root):
    folder = root / "inventario"
    hidden = folder / ".oculta"
    hidden.mkdir(parents=True)
    (hidden / "invisible.bin").write_bytes(bytes(20))
    (folder / "visible.txt").write_bytes(bytes(10))
    events = []

    async def inventory(text, *, project=1):
        task = app.new_task(text)
        worker = app.Worker([{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": text}],
                            task=task, project={"id": project}, save_task=lambda _: None)
        worker.activity.connect(events.append)
        return await worker.chat(), task

    objective = f'Encuentra los cinco archivos más pesados de "{folder}".'
    answer, prior = await inventory(objective)
    assert "invisible.bin" in answer and "**2 archivos**" in answer
    window = app.StoneBot()
    try:
        window.project, window.task = {"id": 1}, prior
        window.message.setPlainText("Ese conteo incluía carpetas ocultas")

        def confirm(dialog):
            assert dialog.mistake.toPlainText() == "Ese conteo incluía carpetas ocultas"
            assert dialog.preference.toPlainText() and dialog.method.toPlainText()
            assert dialog.hidden.currentData() is True
            return QDialog.DialogCode.Accepted

        with patch.object(app.TaskCorrectionDialog, "exec", confirm):
            window.enviar()
        assert task_correction(prior)["exclude_hidden"] == 1
        assert not window.message.toPlainText()
    finally:
        window.close()

    similar = f'Revisa los dos archivos más grandes de "{folder}".'
    answer, _ = await inventory(similar)
    assert "visible.txt" in answer and "invisible.bin" not in answer and "sin ocultos" in answer
    assert any("Corrección guardada aplicada" in event for event in events)
    assert "invisible.bin" in (await inventory(similar, project=2))[0]
    assert "invisible.bin" in (await inventory(f'{similar} Incluye carpetas ocultas.'))[0]


async def test_planner_uses_correction():
    prior = {**app.new_task("Revisa el estado del proyecto"), "project_id": 7}
    save_task_correction(prior, "Inventó resultados", "Citar archivos", "Contrastar README con cambios")
    similar = {**app.new_task("Resume los avances del proyecto"), "project_id": 7}

    def reply(**request):
        text = request["messages"][-1]["content"]
        assert "fallo_anterior" in text and "preferencia" in text and "método_correctivo" in text
        assert "Inventó resultados" in text and "Citar archivos" in text and "Contrastar README" in text
        return SimpleNamespace(message=SimpleNamespace(content='{"pasos":["Contrastar README con cambios"]}'))

    worker = app.Worker([], task=similar, save_task=lambda _: None)
    await worker.plan_task(SimpleNamespace(chat=reply), {})
    assert similar["plan"] == ["Contrastar README con cambios"]
    assert task_correction({**similar, "project_id": 8}) is None


if __name__ == "__main__":
    qt = QApplication([])
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root / "perfil"):
            test_memory_editor(root)
            asyncio.run(test_inventory_correction(root))
            asyncio.run(test_planner_uses_correction())
    print("PASS: edición y retiro de recuerdos, correcciones de tareas y recorrido de carpetas.")

"""Tareas reanudables. Con --desktop NODE JS usa Desktop Commander y Ollama reales."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import mcp_client
from experiences import task_results
from history import History
from tasks import COVERAGE_STATUS, PLAN_STATUS, REPORT, START_TASK, new_task
from test_mcp import example_stdio


OBJECTIVE = ("Encuentra los cinco archivos más grandes de una carpeta con Desktop Commander. Solo archivos directos. "
             "Si falta la ruta, pídemela antes de usar herramientas. Comprueba el tamaño de cada archivo con las herramientas "
             "y entrega los cinco en orden descendente, con el tamaño exacto en bytes.")
FILES = {"alfa.txt": 6213, "bravo.txt": 1905, "cobre.txt": 7637, "delta.txt": 3189, "este.txt": 4871, "faro.txt": 9073}


def report(status, text):
    return Message(role="assistant", tool_calls=[{
        "function": {"name": REPORT.function.name, "arguments": {"estado": status, "mensaje": text}}
    }])


def stage(root, phase, live):
    folder = root / "archivos"
    objective = OBJECTIVE if live else "Revisa la documentación del proyecto, contrasta los avances y dime qué sigue."
    approvals = []

    def approve():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QMessageBox) or dialog.windowTitle() != "Confirmar operación MCP":
            return
        tool = dialog.text().split()[1]
        path = json.loads(dialog.informativeText()).get("path")
        permitted = ((path and (Path(path) == folder or Path(path).parent == folder))
                     if live else tool == "echo")
        if permitted:
            approvals.append(tool)
        label = "Permitir una vez" if permitted else "Denegar"
        next(button for button in dialog.buttons() if button.text() == label).click()

    def mock_chat(**call):
        transcript = call["messages"]
        if call.get("format") == PLAN_STATUS:
            assert phase in {"ask", "pause"}
            assert "Preferencia de prueba" in transcript[-1]["content"]
            return SimpleNamespace(message=Message(role="assistant", content=json.dumps(
                {"pasos": ["Obtener la ruta", "Revisar los tamaños", "Ordenar los resultados"]})))
        if call.get("format") == COVERAGE_STATUS:
            assert phase == "answer" and "Eco MCP" in transcript[-1]["content"]
            return SimpleNamespace(message=Message(role="assistant", content='{"verificada":true,"faltante":""}'))
        if call.get("format"):
            assert phase == "recover" and "Resultado de prueba verificado." in transcript[-1]["content"]
            return SimpleNamespace(message=Message(role="assistant", content='{"estado":"completada"}'))
        if phase == "ask":
            if START_TASK in call["tools"]:
                return SimpleNamespace(message=Message(role="assistant", tool_calls=[{
                    "function": {"name": START_TASK.function.name, "arguments": {"objetivo": objective}},
                }]))
            return SimpleNamespace(message=report("espera", "¿Cuál es la ruta absoluta de la carpeta?"))
        assert objective in transcript[-1]["content"] or transcript[-1]["role"] == "tool"
        if transcript[-1]["role"] == "tool":
            assert "Eco MCP" in transcript[-1]["content"]
            answer = (Message(role="assistant", content="Resultado de prueba verificado.") if phase == "recover"
                      else report("completada", "Resultado de prueba verificado."))
            return SimpleNamespace(message=answer)
        if phase == "recover":
            assert str(folder) in transcript[-1]["content"]
        alias, = [tool.function.name for tool in call["tools"] if tool.function.name.startswith("mcp_")]
        return SimpleNamespace(message=Message(role="assistant", tool_calls=[
            {"function": {"name": alias, "arguments": {"text": "lectura"}}}
        ]))

    actual = app.Client(host="http://localhost:11434", timeout=120) if live else None

    def chat(**call):
        if actual is None:
            return mock_chat(**call)
        response = actual.chat(**call)
        print("Ollama:", response.message.content,
              [tool.function.name for tool in response.message.tool_calls or []], flush=True)
        return response

    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
          patch.object(app.memory_service, "query_memory", return_value="Preferencia de prueba")):
        window = app.StoneBot()
        window.show()
        approval_timer = QTimer(window)
        approval_timer.timeout.connect(approve)
        approval_timer.start(100)
        try:
            if phase in {"ask", "pause"}:
                text = objective if phase == "ask" and not live else f"/tarea {objective}"
                expected = "paused" if phase == "pause" else "waiting"
            else:
                window.open_chat(window.history.find()[0][0])
                assert window.task["status"] == ("interrupted" if phase == "recover" else "waiting")
                assert objective == window.task["objective"]
                assert window.task["plan"]
                assert f"Plan · {window.task['plan'][-1]}" in window.task_panel.events.toPlainText()
                if phase == "recover":
                    assert "Resultado guardado" in window.task_panel.events.toPlainText()
                    assert "Resultado incierto" in window.task_panel.events.toPlainText()
                text = f"/reanudar\n\n{folder}" if phase == "recover" else str(folder)
                expected = "paused" if phase == "recover" else "completed"
            window.message.setPlainText(text)
            window.send.click()
            if phase != "ask" or live:
                assert not window.activity_panel.pause_button.isHidden()
            if phase == "pause":
                window.activity_panel.pause_button.click()
            loop = QEventLoop()
            window.thread.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(180_000)
            loop.exec()
            assert window.thread is None, window.activity_panel.events.toPlainText()
            task = History().task(window.chat_id)
            assert task["status"] == expected, (task, window.problem.text())
            assert window.task_panel.pause_button.isHidden()
            assert task["message"] == window.history.messages(window.chat_id)[-1]["content"]
            assert "pasos registrados" in window.task_panel.latest
            if phase == "ask":
                assert "ruta" in task["message"].casefold() and not approvals
            elif phase == "recover":
                assert [step["status"] for step in task["steps"]] == ["response", "exception"] and not approvals
                assert "Falta una lectura verificable" in task["message"]
            elif phase == "pause":
                assert not approvals and "/reanudar" in task["message"]
                window.message.setPlainText("/cancelar")
                window.send.click()
                assert window.thread is None and window.task["status"] == "cancelled"
                assert History().task(window.chat_id)["status"] == "cancelled"
            else:
                assert task["steps"] and approvals and all(step["status"] == "response" for step in task["steps"])
                assert task["clarifications"] == [str(folder)]
                if not live:
                    assert task_results(task)[0]["outcome"] == "completo"
                if not live:
                    with patch.object(app.memory_service, "inject_memory", return_value="📍 NUEVA ONDA.") as save:
                        window.message.setPlainText("Guarda el resumen")
                        window.send.click()
                        window.thread.finished.connect(loop.quit)
                        timer.start(10_000)
                        loop.exec()
                        assert window.thread is None
                        assert "Resultado de prueba verificado." in save.call_args.args[0]
                        assert History().task(window.chat_id)["status"] == "completed"
                if live:
                    names = re.findall(r"\b[a-z]+\.txt\b", task["message"].casefold())
                    expected_names = sorted(FILES, key=FILES.get, reverse=True)[:5]
                    assert list(dict.fromkeys(names))[:5] == expected_names, task["message"]
                    for name in expected_names:
                        lines = [line for line in task["message"].casefold().splitlines() if name in line]
                        assert any(FILES[name] in {int(re.sub(r"\D", "", number))
                                                  for number in re.findall(r"\b\d{1,4}(?:[., ]\d{3})?\b", line)}
                                   for line in lines), (name, task["message"])
                    assert approvals.count("list_directory") >= 1 and approvals.count("get_file_info") >= 6
                    print(task["message"], flush=True)
        finally:
            window.pool.close()
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def inventory_stage(root, phase):
    objective = "¿Puedes revisar Descargas y decirme cuáles son los cinco archivos más pesados? Solo archivos directos."
    largest = root / "archivos" / "subcarpeta" / "mayor.bin"
    if phase == "inventory":
        largest.parent.mkdir()
        largest.write_bytes(b"x" * 20_000)
    assert not app.is_ranking_request("¿Cómo puedo encontrar los archivos más pesados?")
    assert not app.is_ranking_request("Busca los cinco archivos más pesados usando Desktop Commander.")
    with (patch.object(mcp_client, "default_root", return_value=root),
          patch("folder_inventory.downloads_folder", return_value=root / "archivos"),
          patch.object(app, "Client", side_effect=AssertionError("La clasificación local no necesita Ollama."))):
        window = app.StoneBot()
        try:
            first = phase == "inventory"
            if not first:
                window.open_chat(History().find(objective)[0][0])
                assert window.task["status"] == "completed" and not window.task["inventory_recursive"]
            window.message.setPlainText(objective if first else "Incluye las subcarpetas también.")
            window.send.click()
            assert window.thread is not None
            loop = QEventLoop()
            window.thread.finished.connect(loop.quit)
            QTimer.singleShot(10_000, loop.quit)
            loop.exec()
            assert window.thread is None
            saved = History().task(window.chat_id)
            assert saved["objective"] == objective and saved["status"] == "completed"
            assert saved["inventory_recursive"] == (not first)
            assert ("mayor.bin" in saved["message"]) == (not first)
            assert (str(largest) in saved["message"]) == (not first)
        finally:
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def run(desktop):
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        folder = root / "archivos"
        folder.mkdir()
        for name, size in FILES.items():
            (folder / name).write_bytes(b"a" * size)
        with patch.object(mcp_client, "default_root", return_value=root):
            name = "desktop_commander" if desktop else "ejemplo"
            config = dict(transport="stdio", command=desktop[0] if desktop else sys.executable,
                          args=desktop[1:] if desktop else ["-B", "-c", example_stdio()[-1]],
                          enabled=True, read_tools=[], disabled_tools=["mark"])
            if desktop:
                if cache := os.getenv("STONEBOT_TEST_CHROME_CACHE"):
                    shutil.copytree(cache, root / "mcp" / name / ".claude-server-commander" / "puppeteer-cache")
                tools = asyncio.run(mcp_client.probe_server(name, config, include_definitions=True))
                assert {"list_directory", "get_file_info"} <= {tool.name for tool in tools}
                config["disabled_tools"] = [tool.name for tool in tools
                                            if tool.name not in {"list_directory", "get_file_info"}]
            mcp_client.save_servers({name: config})
        env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
        for phase in ("ask", "answer", "recover", "pause") if not desktop else ("ask", "answer"):
            if phase == "recover":
                with patch.object(mcp_client, "default_root", return_value=root):
                    history = History()
                    chat_id = history.find()[0][0]
                    task = dict(history.task(chat_id), status="running")
                    task["steps"].append({"key": "interrupted-read", "tool": "ejemplo / echo", "status": "running"})
                    history.save_task(chat_id, task)
            subprocess.run([sys.executable, "-B", __file__, str(root), phase, str(bool(desktop))],
                           check=True, env=env, timeout=210)
        with patch.object(mcp_client, "default_root", return_value=root):
            assert mcp_client.load_servers()[name] == config
            history = History()
            chat_id = history.find()[0][0]
            history.delete(chat_id)
            assert history.task(chat_id) is None
        if not desktop:
            for phase in ("inventory", "inventory-followup"):
                subprocess.run([sys.executable, "-B", __file__, str(root), phase, "False"],
                               check=True, env=env, timeout=30)
    print("PASS: tarea guardada, reinicio, permisos y resultado.", flush=True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] != "--desktop":
        qt = QApplication([])
        if sys.argv[2].startswith("inventory"):
            inventory_stage(Path(sys.argv[1]), sys.argv[2])
        else:
            stage(Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "True")
    else:
        run(sys.argv[2:] if sys.argv[1:2] == ["--desktop"] else [])

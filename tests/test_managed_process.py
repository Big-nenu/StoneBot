"""Prueba del supervisor y del recorrido desde el chat con un modelo simulado."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import managed_process as jobs
import mcp_client
import turn_worker
from chat_execution import ChatExecution
from ollama import Message


def poll(folder, run_id, until):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = jobs.inspect_run(folder, run_id)
        if until(result):
            return result
        time.sleep(.1)
    raise AssertionError(result)


def lifecycle(root):
    run_id = uuid4().hex
    child = "import time; time.sleep(60)"
    parent = ("import os,sys,subprocess,time; p=subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
              "os.write(1, str(p.pid).encode()); time.sleep(60)")
    command = [sys.executable, "-u", "-c", parent, child] if os.name == "nt" else [
        sys.executable, "-c", "import os,time; os.write(1,b'primera'); time.sleep(60)"]
    # El lanzador termina antes de la primera consulta.
    subprocess.run([sys.executable, "-B", "-c",
                    "from managed_process import start; from pathlib import Path; import sys; "
                    "start(Path(sys.argv[1]), sys.argv[2], dict(cwd=sys.argv[1], argv=sys.argv[3:]))",
                    str(root), run_id, *command], cwd=Path(__file__).resolve().parents[1], check=True)
    first = poll(root, run_id, lambda row: row["salida"] and row["estado"] == "ejecutando")
    if os.name == "nt":
        import win32api
        import win32event
        descendant = win32api.OpenProcess(0x100000, False, int(first["salida"]))
    assert not jobs.inspect_run(root, run_id, first["cursor"])["salida"]
    # Otro intérprete consulta y cancela el trabajo sin heredar handles del lanzador.
    subprocess.run([sys.executable, "-B", "-c",
                    "from managed_process import inspect_run; from pathlib import Path; import sys; "
                    "assert inspect_run(Path(sys.argv[1]), sys.argv[2], cancel=True)['cancelacion_solicitada']",
                    str(root), run_id], cwd=Path(__file__).resolve().parents[1], check=True)
    final = poll(root, run_id, lambda row: row["estado"] == "cancelado")
    assert final["codigo"] is not None
    if os.name == "nt":
        assert win32event.WaitForSingleObject(descendant, 0) == 0
        descendant.Close()
    jobs.location(root, run_id).rename(root / "cerrado.sqlite3")


async def chat(root, approved):
    execution = ChatExecution(1, None, lambda mid, version, state: version + 1, "prueba", ["local"])
    execution.chat_id = 1
    worker = turn_worker.Worker([{"role": "system", "content": "Usa el resultado."},
                                 {"role": "user", "content": "Ejecuta la prueba del proyecto."}],
                                execution=execution)
    command = [sys.executable, "-c", "import os,sys; print(os.path.basename(os.getcwd())); sys.exit(7)"]
    def call(name, **args):
        return SimpleNamespace(message=Message(role="assistant", tool_calls=[
            {"function": {"name": name, "arguments": args}}]))

    output = []
    async def model(**request):
        row = request["messages"][-1]
        if row["role"] != "tool":
            assert any(getattr(t, "function", None) and t.function.name == "iniciar_proceso" for t in request["tools"])
            return call("iniciar_proceso", argv=command, cwd=str(root))
        if not approved:
            assert "denegada" in row["content"]
            answer = "Denegada"
        else:
            data = json.loads(row["content"])
            output.append(data["salida"])
            assert data["estado"] != "fallido", data
            if data["estado"] != "terminado":
                await asyncio.sleep(.5)
                return call("consultar_proceso", id=data["id"])
            assert root.name in "".join(output) and data["codigo"] == 7
            answer = "El programa terminó con código 7."
        return SimpleNamespace(message=Message(role="assistant", content=answer))

    with (patch.object(jobs, "WINDOWS_BACKEND", True),
          patch.object(turn_worker, "ollama_model_is_local", return_value=True),
          patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(worker, "confirm_external", new=AsyncMock(return_value=approved)) as approval,
          patch.object(mcp_client, "default_root", return_value=root / "perfil")):
        answer = await worker.chat()
    approval.assert_awaited_once()
    first = execution.state["steps"][0]
    if approved:
        assert "código 7" in answer and first["run_id"] in execution.context()
        assert execution.repeated_effect("iniciar_proceso", first["arguments"]) is first
    else:
        assert "Denegada" in answer and first["status"] == "sin ejecutar", (answer, first)
        assert not list(root.rglob("*.sqlite3"))


def desktop(root, stage, live):
    import app
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    qt = QApplication([])
    command = [sys.executable, str(root / "trabajo.py")]
    with ExitStack() as stack:
        stack.enter_context(patch.object(mcp_client, "default_root", return_value=root / "perfil"))
        stack.enter_context(patch.object(app, "generate_title", return_value="Proceso temporal"))
        stack.enter_context(patch.object(turn_worker, "automatic_memory_enabled", return_value=False))
        stack.enter_context(patch.object(app.Worker, "enabled_skills", return_value={}))
        window = app.StoneBot()
        window.ai = app.AISettings("ollama", "nemotron-3.5-bolt:e4b" if live else "simulado")
        if stage in ("start", "deny"):
            prompt = (f"Inicia un proceso de Windows con argv {json.dumps(command, ensure_ascii=False)} "
                      f"y directorio de trabajo {root}. Consulta su primera línea y dímela. "
                      "Deja el programa en ejecución.")
        else:
            window.open_chat(window.history.find()[0][0])
            prompt = ("Cancela el único proceso de Windows de este chat y verifica que terminó."
                      if stage == "cancel" else "Consulta el único proceso de Windows que iniciamos en este chat. "
                      "Dime su nueva línea de salida y el código de terminación.")

        approvals = []
        original = QMessageBox.exec
        def dialog(box):
            args = box.detailedText() or box.informativeText()
            details = json.loads(args) if box.windowTitle() == "Terminal de Windows" else {}
            approved = (details.get("argv") == command and details.get("cwd") == str(root)
                        and ((stage == "start" and "iniciar_proceso" in box.text())
                             or (stage == "cancel" and "cancelar_proceso" in box.text())))
            label = "Permitir una vez" if approved else "Denegar"
            button = next(b for b in box.buttons() if b.text() == label)
            QTimer.singleShot(0, button.click)
            approvals.append(approved)
            return original(box)
        stack.enter_context(patch.object(QMessageBox, "exec", dialog))

        async def model(**request):
            row = request["messages"][-1]
            def call(name, **args):
                return SimpleNamespace(message=Message(role="assistant", tool_calls=[
                    {"function": {"name": name, "arguments": args}}]))
            if row["role"] != "tool":
                return call("iniciar_proceso", argv=command, cwd=str(root)) if stage in ("start", "deny") else call("consultar_proceso")
            if stage == "deny":
                assert "denegada" in row["content"]
                return SimpleNamespace(message=Message(role="assistant", content="Denegada"))
            data = json.loads(row["content"])
            if "ejecuciones_recientes" in data:
                return call("cancelar_proceso" if stage == "cancel" else "consultar_proceso", id=data["ejecuciones_recientes"][0])
            if stage == "cancel" and data["estado"] == "cancelado":
                return SimpleNamespace(message=Message(role="assistant", content="Cancelado"))
            if not data["salida"]:
                await asyncio.sleep(.3)
                return call("consultar_proceso", id=data["id"])
            return SimpleNamespace(message=Message(role="assistant", content=f"{data['salida']} {data['codigo']}"))
        if not live:
            stack.enter_context(patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)))
            stack.enter_context(patch.object(turn_worker, "ollama_model_is_local", return_value=True))
        window.message.setPlainText(prompt)
        window.send.click()
        loop = QEventLoop()
        window.thread.finished.connect(loop.quit)
        QTimer.singleShot(175000, loop, loop.quit)
        loop.exec()
        assert window.thread is None, window.problem.text()
        reply = window.history.messages(window.chat_id)[-1]["content"]
        assert approvals == {"start": [True], "reopen": [], "cancel": [True], "deny": [False]}[stage], approvals
        with window.history.connect() as db:
            records = db.execute("SELECT snapshot FROM chat_execution ORDER BY message_id").fetchall()
        pages = [json.loads(s["result"]) for s in json.loads(records[-1][0])["steps"] if s.get("page")]
        if stage == "deny":
            assert not list((root / "perfil" / "procesos").rglob("*.sqlite3"))
        elif stage == "cancel":
            steps = json.loads(records[-1][0])["steps"]
            assert any('"estado": "cancelado"' in s.get("result", "") for s in steps)
        else:
            marker = "CEDRO" if stage == "start" else "CAOBA"
            assert marker in reply and [p["salida"] for p in pages] == [marker], (reply, pages)
        if stage == "reopen":
            assert "7" in reply
            assert pages[-1]["codigo"] == 7
        window.request_exit()
        qt.processEvents()


if __name__ == "__main__":
    if len(sys.argv) > 2:
        desktop(Path(sys.argv[1]), sys.argv[2], "--live" in sys.argv)
        sys.exit(0)
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        asyncio.run(chat(root, False))
        asyncio.run(chat(root, True))
        lifecycle(root)
        if os.name == "nt":
            (root / "trabajo.py").write_text(
                "from pathlib import Path\nimport os,time,sys\n"
                "with open('inicios','a') as f: f.write('1')\n"
                "os.write(1,b'CEDRO')\n"
                "for _ in range(1200):\n if Path('continuar').exists(): break\n time.sleep(.2)\n"
                "os.write(1,b'CAOBA')\nsys.exit(7)\n", encoding="utf-8")
            for stage in ("start", "reopen"):
                if stage == "reopen":
                    (root / "continuar").touch()
                try:
                    subprocess.run([sys.executable, "-B", __file__, str(root), stage, *sys.argv[1:]],
                                   check=True, timeout=185)
                finally:
                    (root / "continuar").touch()
            assert (root / "inicios").read_text() == "1"
            import win32api
            import win32event
            tree = root / "arbol"
            tree.mkdir()
            (tree / "trabajo.py").write_text(
                "import os,subprocess,sys,time\nfrom pathlib import Path\n"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(180)'])\n"
                "Path('pid').write_text(str(p.pid))\nos.write(1,b'CEDRO')\ntime.sleep(180)\n", encoding="utf-8")
            for stage in ("deny", "start", "cancel"):
                subprocess.run([sys.executable, "-B", __file__, str(tree), stage], check=True, timeout=185)
                if stage == "deny":
                    assert not (tree / "pid").exists()
                if stage == "start":
                    child = win32api.OpenProcess(0x100000, False, int((tree / "pid").read_text()))
            assert win32event.WaitForSingleObject(child, 0) == 0
            child.Close()
    print("PASS: permiso, ejecución desde el chat, código final, salida incremental y cancelación.")

"""Reinicio de dos procesos de escritorio y recuperación de contexto con datos temporales."""
import asyncio
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ollama import Message
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

import app
import chat_execution
import mcp_client
import turn_worker
from history import History
from engine_harness import call


def stage(root, phase, live):
    qt = QApplication([])
    incoming, archive = root / "entrada", root / "archivo"
    objective = (f'Encuentra el archivo más pesado de "{incoming}", busca una copia con ese nombre en '
                 f'"{archive}" incluyendo subcarpetas y dime dónde está.')
    with ExitStack() as stack:
        stack.enter_context(patch.object(mcp_client, "default_root", return_value=root / "perfil"))
        stack.enter_context(patch.object(app, "generate_title", return_value="Ranking"))
        stack.enter_context(patch.object(turn_worker, "automatic_memory_enabled", return_value=False))
        stack.enter_context(patch.object(app.Worker, "enabled_skills", return_value={}))
        window = app.StoneBot()
        window.ai = app.AISettings("ollama", "nemotron-3.5-bolt:e4b" if live else "simulado")
        if phase == "interrupt":
            persist = chat_execution.ChatExecution.observe
            def stop_after_commit(execution, step, result, status):
                persist(execution, step, result, status)
                if step["tool"] == "rank_local_files" and "viejo.bin" in result:
                    os._exit(73)  # Corte abrupto después del commit y antes de responder.
            stack.enter_context(patch.object(chat_execution.ChatExecution, "observe", stop_after_commit))
        if phase == "resume":
            window.open_chat(window.history.find()[0][0])
            _, previous = window.history.execution_context(window.chat_id)
            assert previous[2]["objective"] == objective
            assert "viejo.bin" in previous[2]["steps"][0]["result"]

        async def model(**request):
            row = request["messages"][-1]
            if phase == "resume" and any(getattr(t, "function", None) and t.function.name == "resume_chat_work"
                                         for t in request["tools"]):
                return call("resume_chat_work")
            if row["role"] != "tool":
                assert objective in row["content"]
                return call("rank_local_files", target=str(incoming), limit=1)
            result = json.loads(row["content"])
            if row["tool_name"] == "rank_local_files":
                first = Path(result["entradas"][0]["ruta"]).name
                assert first == "nuevo.bin"
                return call("inspect_local_files", operation="search", target=str(archive), recursive=True, name_contains=first)
            return SimpleNamespace(message=Message(role="assistant", content=result["entradas"][0]["ruta"]))

        if not live:
            stack.enter_context(patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)))
            stack.enter_context(patch.object(turn_worker, "ollama_model_is_local", return_value=True))
        window.message.setPlainText(objective if phase == "interrupt" else "Continúa con el encargo interrumpido.")
        window.send.click()
        loop = QEventLoop()
        window.thread.finished.connect(loop.quit)
        QTimer.singleShot(180_000, loop, loop.quit)
        loop.exec()
        assert window.thread is None, window.problem.text()
        result = window.history.messages(window.chat_id)[-1]["content"]
        assert phase == "resume" and "nuevo.bin" in result and "entregas" in result, (result, window.problem.text())
        assert window.history.execution_context(window.chat_id)[1] is None
        with window.history.connect() as conn:
            [(snapshot,)] = conn.execute("SELECT snapshot FROM chat_execution WHERE finished=1")
        steps = json.loads(snapshot)["steps"]
        assert any(s["tool"] == "rank_local_files" and "nuevo.bin" in s["result"] for s in steps)
        assert any(s["tool"] == "inspect_local_files" and "entregas" in s["result"] for s in steps)
        window.pool.close()
        window.close()


async def compact_round():
    marker = "LIRIO-554"
    transcript = [{"role": "system", "content": "Responde en español."},
                  {"role": "user", "content": "a" * 30000 + marker + "b" * 30000},
                  {"role": "assistant", "content": "Recibido."},
                  {"role": "user", "content": "Busca el código que empieza con LIRIO."}]
    worker = turn_worker.Worker(transcript)
    async def decide(**request):
        rows = request["messages"]
        if rows[0]["content"].startswith("Resume el historial"):
            return SimpleNamespace(message=Message(role="assistant", content="El usuario compartió un código; véase la referencia 2."))
        assert len(str(rows)) < 16000
        assert rows[0]["content"].startswith(transcript[0]["content"])
        if rows[-1]["role"] == "user":
            return call("read_chat_context", search="LIRIO")
        data = json.loads(rows[-1]["content"])
        if "coincidencias" in data:
            return call("read_chat_context", **data["coincidencias"][0])
        assert marker in data["texto"]
        return SimpleNamespace(message=Message(role="assistant", content=marker))
    with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=decide)):
        assert await worker.chat() == marker
    assert marker in transcript[1]["content"]


async def check_saved_state():
    history = History()
    cid = history.append(None, "user", "Encargo", created=7)
    origin, previous = history.execution_context(cid)
    execution = chat_execution.ChatExecution(origin, previous, history.save_execution, "Encargo", ["local"])
    step = execution.start("guardar", {"nombre": "a"}, True, ["leer"])
    assert not execution.repeated_effect("guardar", {"nombre": "a"})
    execution.dispatched()
    _, pending = History().execution_context(cid)
    resumed = chat_execution.ChatExecution(origin, pending, history.save_execution, "", ["local"])
    assert resumed.repeated_effect("guardar", {"nombre": "a"})
    resumed.resume("continúa")
    assert resumed.repeated_effect("guardar", {"nombre": "a"}) and not resumed.repeated_effect("leer", {})
    try:
        execution.observe(step, "respuesta tardía", "respuesta recibida")
    except ValueError:
        pass
    else:
        raise AssertionError("Un escritor antiguo sobrescribió un encargo reanudado.")

    with TemporaryDirectory() as folder:
        target = Path(folder).resolve() / "prueba.md"
        args = {"path": str(target), "content": "Prueba de recuperación"}
        resumed.start("save_markdown", args, True, [])
        resumed.dispatched(target)
        target.write_text("contenido diferente", encoding="utf-8")
        _, saved = History().execution_context(cid)
        recovered = chat_execution.ChatExecution(origin, saved, history.save_execution, "", ["local"])
        recovered.resume("continúa")
        assert recovered.state["steps"][-1]["status"] == "sin confirmar"
        assert target.read_text(encoding="utf-8") == "contenido diferente"
        target.write_text(args["content"], encoding="utf-8")
        _, saved = History().execution_context(cid)
        recovered = chat_execution.ChatExecution(origin, saved, history.save_execution, "", ["local"])
        recovered.resume("comprueba otra vez")
        assert recovered.state["steps"][-1]["status"] == "verificada en disco"
        assert recovered.repeated_effect("save_markdown", args)
        assert [s["tool"] for s in recovered.unconfirmed()] == ["guardar"]

    scope = ["ollama", "modelo", True, None]
    messages = [{"role": "user", "content": "Primera decisión. " * 4000}, {"role": "user", "content": "Sigue."}]
    calls = []
    async def summarize(prior, parts):
        calls.append(parts)
        return "Se acordó revisar la primera decisión."
    context = chat_execution.ChatContext()
    context.view(messages)
    summary = await context.summarize(scope, None, summarize)
    history.save_summary(cid, summary)
    count = len(calls)
    context.view(messages)
    assert await context.summarize(scope, History().summary(cid), summarize) == summary and len(calls) == count
    messages[0]["content"] += "Corrección"
    context.view(messages)
    assert (await context.summarize(scope, summary, summarize))["digest"] != summary["digest"]
    history.replace_from(cid, 0, history.messages(cid), {"role": "user", "content": "Editado", "created": 8},
                         {"role": "assistant", "content": "Nueva respuesta", "created": 9})
    assert history.summary(cid) is None and history.execution_context(cid)[1] is None


async def compact_live():
    marker = "CEIBA-643"
    messages = [{"role": "system", "content": turn_worker.SYSTEM},
                {"role": "user", "content": "Conserva el código de aceptación del proyecto. " +
                 "Antecedente de la reunión. " * 170 + f" La decisión final fue usar exactamente {marker}. " +
                 "Se revisó el calendario. " * 170},
                {"role": "assistant", "content": "Registré la decisión en este chat."},
                {"role": "user", "content": "¿Qué código de aceptación decidimos? Responde con el código exacto."}]
    worker = turn_worker.Worker(messages, ai=app.AISettings("ollama", "nemotron-3.5-bolt:e4b"), think=False)
    with (patch.object(turn_worker, "ChatContext", side_effect=lambda _: chat_execution.ChatContext(8000)),
          patch.object(worker, "enabled_skills", return_value={})):
        with patch.object(worker, "summarize_chat_context", wraps=worker.summarize_chat_context) as compact:
            result = await worker.run_chat()
            assert compact.await_count >= 1 and marker in result, result


if __name__ == "__main__":
    if len(sys.argv) > 2:
        stage(Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "live")
    else:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "entrada").mkdir()
            (root / "archivo" / "entregas").mkdir(parents=True)
            (root / "entrada" / "viejo.bin").write_bytes(b"abc")
            for phase in ("interrupt", "resume"):
                if phase == "resume":
                    for folder in ("entrada", "archivo/entregas"):
                        (root / folder / "nuevo.bin").write_bytes(b"x" * 137)
                process = subprocess.run([sys.executable, "-B", __file__, str(root), phase,
                                          "live" if "--live" in sys.argv else "simulado"], timeout=205)
                assert process.returncode == (73 if phase == "interrupt" else 0), (phase, process.returncode)
            with patch.object(mcp_client, "default_root", return_value=root / "perfil"):
                asyncio.run(compact_round())
                asyncio.run(check_saved_state())
                if "--live" in sys.argv:
                    asyncio.run(compact_live())
        print("PASS: reapertura del chat, ranking actualizado, búsqueda dependiente y contexto recuperable.")

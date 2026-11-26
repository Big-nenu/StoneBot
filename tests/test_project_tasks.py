"""Tareas de proyecto con pausa, reapertura y revalidación de lecturas."""
import asyncio
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import mcp_client
import turn_worker
from engine_harness import finished_text
from ai_provider import AISettings
from history import History
from local_files import LocalFiles, RESULT_HEADER
from tasks import COVERAGE_STATUS, PLAN_STATUS, completion_evidence, new_task
from test_project_reads import reply


OBJECTIVE = "Revisa el README y contrasta sus decisiones con StoneWave."


def answer(text):
    response = reply()
    response.message.content = text
    return response


def run_turn(chat_id, history, project, task, memory, model, approvals, *, provider="ollama", live_model=None):
    messages = [{"role": "system", "content": turn_worker.SYSTEM}, *history.messages(chat_id)]
    worker = turn_worker.Worker(messages, project=project, task=task, memory=memory,
                                ai=AISettings(provider, live_model or "demo"), think=False,
                                save_task=lambda snapshot: history.save_task(chat_id, snapshot))
    if live_model is None:
        worker.local_ollama = provider == "ollama"
    answers = []

    def approve(request):
        approvals.append(request["arguments"]["Ruta"])
        request["approved"] = True

    def finish(text):
        answers.append(text)
        history.append(chat_id, "assistant", text, task=task)

    worker.events.confirm = AsyncMock(side_effect=approve)
    with (nullcontext() if live_model else patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(turn_worker, "OpenRouter", return_value=SimpleNamespace(chat=model)),
          patch.object(turn_worker, "load_servers", return_value={})):
        finish(finished_text(worker))
    assert len(answers) == 1, answers
    return answers[0]


def check_resume(folder, *, changed, live_model=None):
    folder.mkdir()
    readme = folder / "README.md"
    readme.write_text("Formato de informes: PDF.", encoding="utf-8")
    history = History()
    pid = history.save_project(folder.name, "", "", str(folder))
    project = {"id": pid, "name": folder.name, "folder": str(folder)}
    task = new_task(OBJECTIVE)
    chat_id = history.append(None, "user", "/tarea " + OBJECTIVE, task=task, project_id=pid)
    memory = SimpleNamespace(call=AsyncMock(return_value="La decisión registrada fue usar Markdown."))
    approvals = []

    async def pause_after_file(**kwargs):
        if kwargs.get("format") == PLAN_STATUS:
            plan, _ = json.JSONDecoder().raw_decode(kwargs["messages"][-1]["content"])
            assert {"read_project_file", "search_stonewave_memory"} <= set(plan["herramientas"])
            return answer('{"pasos":["Leer README","Contrastar en StoneWave"]}')
        if kwargs["messages"][-1]["role"] == "tool":
            assert "PDF" in kwargs["messages"][-1]["content"]
            raise asyncio.CancelledError
        return reply("read_project_file", path="README.md")

    paused = run_turn(chat_id, history, project, task, memory, pause_after_file, approvals)
    assert "pausada" in paused, paused
    memory.call.assert_not_awaited()
    assert approvals == [str(readme)]
    history = History()
    task = history.task(chat_id)
    assert task["status"] == "paused"
    assert task["steps"][0]["status"] == "response" and "PDF" in task["steps"][0]["result"]
    history.append(chat_id, "user", "/reanudar")
    cloud = AsyncMock(side_effect=AssertionError("La evidencia privada debe quedarse en el equipo"))
    assert "Ollama local" in run_turn(chat_id, history, project, task, memory, cloud, approvals,
                                       provider="openrouter")
    cloud.assert_not_awaited()

    if changed:
        original = readme.stat()
        readme.write_text("Formato de informes: CSV.", encoding="utf-8")
        os.utime(readme, ns=(original.st_atime_ns, original.st_mtime_ns))
    expected = "CSV" if changed else "PDF"

    async def resume(**kwargs):
        if kwargs.get("format") == COVERAGE_STATUS:
            readings = json.loads(kwargs["messages"][-1]["content"])["lecturas"]
            assert {item["project_read"] for item in readings} == {"file", "memory"}
            assert expected in readings[0]["result"] and readings[0]["cobertura_archivo"] == "completo"
            return answer('{"verificada":true,"faltante":""}')
        transcript = kwargs["messages"]
        assert {"read_project_file", "search_stonewave_memory", "informar_estado_tarea"} <= {
            tool.function.name for tool in kwargs["tools"]}
        if transcript[-1]["role"] != "tool":
            context = transcript[-1]["content"]
            if changed:
                assert "PDF" not in context and "dejó de ser válida" in context
            else:
                assert "PDF" in context
            return reply("read_project_file", path="README.md", offset=0)
        result = json.loads(transcript[-1]["content"])
        if "archivo" in result:
            assert expected in result["contenido"]
            return reply("search_stonewave_memory", text=result["contenido"])
        assert "Markdown" in result["contenido"]
        return reply("informar_estado_tarea", estado="completada", mensaje=f"El README dice {expected} y StoneWave dice Markdown.")

    history.append(chat_id, "user", "/reanudar")
    if changed:
        final = run_turn(chat_id, history, project, task, memory, resume, approvals)
    else:
        with patch.object(LocalFiles, "read_text", side_effect=AssertionError("El archivo guardado sigue vigente.")):
            final = run_turn(chat_id, history, project, task, memory, resume, approvals, live_model=live_model)
    assert final.startswith(RESULT_HEADER) and expected in final and "Markdown" in final, final
    assert history.task(chat_id)["status"] == "completed", final
    assert approvals == [str(readme)] * (2 if changed else 1)
    if live_model:
        assert any("informes" in call.kwargs["text"].casefold() for call in memory.call.await_args_list), final
    else:
        memory.call.assert_awaited_once_with("query_memory", text=f"Formato de informes: {expected}.")


def check_inventory_resume(folder):
    folder.mkdir()
    (folder / "primero.bin").write_bytes(b"abc")
    objective = f'Encuentra los archivos más pesados de "{folder}" y comprueba las propiedades del primero.'
    history = History()
    task = new_task(objective)
    chat_id = history.append(None, "user", "/tarea " + objective, task=task)

    def decide(request, *, pause):
        if request.get("format") == PLAN_STATUS:
            return answer('{"pasos":["Clasificar","Comprobar propiedades"]}')
        if request.get("format") == COVERAGE_STATUS:
            data = json.loads(request["messages"][-1]["content"])
            assert [step["tool"] for step in data["lecturas"]] == ["rank_local_files", "inspect_local_files"]
            assert "nuevo.bin" in data["lecturas"][0]["result"]
            return answer('{"verificada":true,"faltante":""}')
        last = request["messages"][-1]
        if last["role"] != "tool":
            return reply("rank_local_files", target=str(folder), limit=1)
        data = json.loads(last["content"])
        if last["tool_name"] == "rank_local_files":
            if pause:
                raise asyncio.CancelledError
            return reply("inspect_local_files", operation="info", target=data["entradas"][0]["ruta"])
        return reply("informar_estado_tarea", estado="completada", mensaje=f"{data['ruta']} pesa {data['tamaño_bytes']} bytes.")

    run_turn(chat_id, history, None, task, None, lambda **kw: decide(kw, pause=True), [])
    task = history.task(chat_id)
    assert task["status"] == "paused" and task["local_inventory_reads"]
    (folder / "nuevo.bin").write_bytes(b"x" * 91)
    history.append(chat_id, "user", "/reanudar")
    cloud = AsyncMock(side_effect=AssertionError("El inventario debe quedarse en el equipo."))
    assert "Ollama local" in run_turn(chat_id, history, None, task, None, cloud, [], provider="openrouter")
    cloud.assert_not_called()
    history.append(chat_id, "user", "/reanudar")
    final = run_turn(chat_id, history, None, task, None, lambda **kw: decide(kw, pause=False), [])
    assert history.task(chat_id)["status"] == "completed" and "nuevo.bin" in final and "91 bytes" in final, final


def check_pages():
    task = new_task(OBJECTIVE)
    first = {"key": "first", "tool": "Archivo del proyecto", "project_read": "file", "resource": "README.md",
             "arguments": {"path": "README.md", "offset": 0}, "revision": [1, 2], "status": "response",
             "partial": "Falta una página.", "next_offset": 12000}
    task["steps"].append(first)
    missing, evidence = completion_evidence(task)
    assert missing and json.loads(evidence)["lecturas"][0]["cobertura_archivo"] == "parcial"
    task["steps"].append({key: value for key, value in first.items() if key not in {"partial", "next_offset"}} |
                         {"key": "last", "arguments": {"path": "README.md", "offset": 12000}})
    missing, evidence = completion_evidence(task)
    assert not missing and all(page["cobertura_archivo"] == "completo" for page in json.loads(evidence)["lecturas"])


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root / "perfil"):
            check_inventory_resume(root / "inventario")
            check_resume(root / "vigente", changed=False)
            check_resume(root / "modificado", changed=True)
            check_pages()
            if sys.argv[1:2] == ["--live"]:
                model = sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:4b"
                check_resume(root / "ollama", changed=False, live_model=model)
                print(f"PASS: {model} reanudó y contrastó el archivo guardado con StoneWave simulado.")
    print("PASS: pausa, reapertura, caché vigente, relectura, privacidad y páginas del archivo.")

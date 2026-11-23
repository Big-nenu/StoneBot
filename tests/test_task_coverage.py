"""Cobertura de tareas, con un modelo que intenta dar por completo un subconjunto."""
import asyncio
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from ollama import Message

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import turn_worker
import app
import mcp_client
from experiences import ranking_evidence, ranking_scope
from history import History
from tasks import COVERAGE_STATUS, LIMIT_REASON, PLAN_STATUS, new_task, upgrade_task
from test_tasks import report


async def check(root, desktop):
    folder = root / "archivos"
    folder.mkdir()
    files = [folder / f"archivo-{i:02d}.txt" for i in range(16)]
    for i, path in enumerate(files, 1):
        path.write_bytes(b"a" * (i * 2048))
    assert max(files, key=lambda path: path.stat().st_size) not in files[:11]
    name = "desktop_commander" if desktop else "prueba"
    config = dict(enabled=True, transport="stdio", command=desktop[0] if desktop else sys.executable,
                  args=desktop[1:], read_tools=[], disabled_tools=[])
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    catalog = [Tool(name=name, inputSchema=schema, annotations={"readOnlyHint": True})
               for name in ("list_directory", "get_file_info")]

    async def local_result(tool, arguments):
        path = Path(arguments["path"])
        result = ("\n".join(f"[FILE] {item.name}" for item in sorted(path.iterdir())) if tool == "list_directory"
                  else f"size: {path.stat().st_size}")
        return CallToolResult(content=[TextContent(type="text", text=result)])

    @asynccontextmanager
    async def fake_session(*args):
        yield SimpleNamespace(list_tools=AsyncMock(return_value=ListToolsResult(tools=catalog)), call_tool=local_result)

    if desktop:
        if cache := os.getenv("STONEBOT_TEST_CHROME_CACHE"):
            shutil.copytree(cache, root / "mcp" / name / ".claude-server-commander" / "puppeteer-cache")
        catalog = await mcp_client.probe_server(name, config, include_definitions=True)
    config["disabled_tools"] = [tool.name for tool in catalog if tool.name not in {"list_directory", "get_file_info"}]
    mcp_client.save_servers({name: config})
    objective = f'Devuelve los cinco archivos más grandes tras revisar todos los archivos de "{folder}" con MCP.'
    history = History()
    task = new_task(objective)
    chat_id = history.append(None, "user", objective, task=task)
    approvals = []
    real_audit = turn_worker.Client(host="http://localhost:11434", timeout=60) if desktop else None

    async def approve(server, tool, arguments):
        approvals.append(Path(arguments["path"]))
        return approvals[-1] in [folder, *files]

    def model_for(paths, *, audit=False, repair=False, verified=False, resume_count=None):
        def chat(**call):
            if call.get("format") == PLAN_STATUS:
                return SimpleNamespace(message=Message(role="assistant", content=json.dumps(
                    {"pasos": ["Reunir los tamaños", "Comprobar y comparar los resultados"]})))
            if call.get("format") == COVERAGE_STATUS:
                assert audit
                evidence = json.loads(call["messages"][-1]["content"])["lecturas"]
                if resume_count is not None:
                    assert len(evidence) == resume_count
                    complete = resume_count == 17
                    return SimpleNamespace(message=Message(role="assistant", content=json.dumps({
                        "verificada": complete, "faltante": "" if complete else "Faltan cuatro archivos.",
                    })))
                if verified:
                    assert len(evidence) == 2 and "mayor.bin" in evidence[0]["result"]
                    return SimpleNamespace(message=Message(role="assistant", content='{"verificada":true,"faltante":""}'))
                if repair:
                    assert len(evidence) in {1, 2}
                    if len(evidence) == 1:
                        paths.append(files[1])
                        return SimpleNamespace(message=Message(role="assistant", content=json.dumps(
                            {"verificada": False, "faltante": "Falta comprobar archivo-01.txt."})))
                    return SimpleNamespace(message=Message(role="assistant", content='{"verificada":true,"faltante":""}'))
                assert len(evidence) == 6
                assert "archivo-15.txt" in evidence[0]["result"]
                if real_audit is not None:
                    return real_audit.chat(**call)
                return SimpleNamespace(message=Message(role="assistant", content=json.dumps(
                    {"verificada": False, "faltante": "Quedan once archivos sin comprobar."})))
            if paths:
                path = paths.pop(0)
                if repair and path == files[1]:
                    assert "Falta comprobar archivo-01.txt" in call["messages"][-1]["content"]
                tool_name = "list_directory" if path.is_dir() else "get_file_info"
                alias, = [tool.function.name for tool in call["tools"] if tool_name in tool.function.name]
                return SimpleNamespace(message=Message(role="assistant", tool_calls=[
                    {"function": {"name": alias, "arguments": {"path": str(path)}}}
                ]))
            result = ("archivo-01.txt es el mayor (4096 bytes)." if repair else
                      "Los cinco están verificados; archivo-04.txt es el mayor.")
            if resume_count == 17:
                result = "Los mayores son archivo-15.txt, archivo-14.txt, archivo-13.txt, archivo-12.txt y archivo-11.txt."
            return SimpleNamespace(message=report("completada", result))
        return chat

    async def run_turn(snapshot, text, paths, *, audit=False, repair=False, verified=False, events=None,
                       resume_count=None):
        pool = app.McpPool() if desktop else None
        worker = app.Worker([{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": text}],
                            pool, task=snapshot, save_task=lambda value: history.save_task(chat_id, value))
        if events is not None:
            worker.activity.connect(events.append)
        model = model_for(paths, audit=audit, repair=repair, verified=verified, resume_count=resume_count)
        with (patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
              patch.object(worker, "confirm_external", side_effect=approve),
              nullcontext() if desktop else patch.object(turn_worker, "session_for", fake_session)):
            try:
                answer = await worker.chat()
            except turn_worker.TaskPaused as exc:
                answer = worker.task_reply("paused", str(exc))
            finally:
                if pool is not None:
                    await asyncio.to_thread(pool.close)
        history.append(chat_id, "assistant", answer, task=snapshot)
        return answer

    await run_turn(task, objective, [folder, *files])
    task = History().task(chat_id)
    assert task["status"] == "paused" and task["coverage_notes"] == [LIMIT_REASON]
    assert len(task["steps"]) == len(approvals) == 12
    scope = ranking_scope(folder, 5, True)
    assert ranking_evidence(scope)[0]["outcome"] == "presupuesto agotado"
    answer = await run_turn(task, "/reanudar", [files[0], files[11]], audit=True, resume_count=13)
    assert task["status"] == "paused" and "Faltan cuatro archivos" in answer and "archivo-04.txt" not in answer
    assert len(task["steps"]) == len(approvals) == 13 and approvals[-1] == files[11]
    assert "Faltan cuatro archivos" in History().task(chat_id)["pending"]
    answer = await run_turn(History().task(chat_id), "/reanudar", files[12:], audit=True, resume_count=17)
    assert History().task(chat_id)["status"] == "completed" and "archivo-15.txt" in answer
    assert LIMIT_REASON not in History().task(chat_id)["coverage_notes"]

    task = new_task(objective)
    answer = await run_turn(task, objective, [folder, *files[:5]], audit=True)
    assert task["status"] == "paused" and "La tarea sigue pendiente" in answer
    if real_audit is None:
        assert "once archivos" in answer
    else:
        print(answer, flush=True)

    objective = "Compara los tamaños de archivo-00.txt y archivo-01.txt e identifica el mayor."
    task = new_task(objective)
    answer = await run_turn(task, objective, [files[0]], audit=True, repair=True)
    saved = History().task(chat_id)
    assert saved["status"] == "completed" and len(saved["steps"]) == 2
    assert saved["plan"] == ["Reunir los tamaños", "Comprobar y comparar los resultados"]
    assert answer == "archivo-01.txt es el mayor (4096 bytes)."

    nested = folder / "subcarpeta"
    nested.mkdir()
    biggest = nested / "mayor.bin"
    biggest.write_bytes(b"a" * 60_000)
    inventory = new_task("Revisa mi carpeta Descargas y encuentra los 5 archivos más grandes con subcarpetas.")
    inventory_chat = history.append(None, "user", inventory["objective"], task=inventory)
    activity = []
    with (patch("folder_inventory.downloads_folder", return_value=folder),
          patch.object(turn_worker, "Client", side_effect=AssertionError("La clasificación local no requiere Ollama."))):
        answer = await run_inventory(inventory, inventory["objective"], History(), inventory_chat, activity)
    assert inventory["status"] == "completed"
    assert any("Experiencias recuperadas" in event and "mcp:" in event for event in activity)
    assert ranking_evidence(scope)[0]["method"] == "local"
    assert "17 archivos" in answer and "2 carpetas" in answer and str(biggest) in answer
    assert answer.index("mayor.bin") < answer.index("archivo-15.txt")

    with patch("stonebot_engine.safety.protected_paths", return_value=[nested]):
        answer = await run_inventory(inventory, "/reanudar", history, chat_id)
    assert inventory["status"] == "paused" and "Revisión parcial" in answer and str(nested) in answer
    assert ranking_evidence(scope)[0]["omitted"] == 1

    inventory["status"] = "paused"
    answer = await run_inventory(inventory, f"/reanudar\n\n{nested}", history, chat_id)
    assert inventory["status"] == "completed" and "1 archivos" in answer and "archivo-15.txt" not in answer

    if not desktop:
        config["read_tools"] = ["list_directory", "get_file_info"]
        mcp_client.save_servers({name: config})
        forced = f'Encuentra los cinco archivos más pesados de "{nested}" usando MCP.'
        await run_turn(new_task(forced), forced, [nested, biggest], audit=True, verified=True)
        natural = f'Encuentra los cinco archivos más pesados de "{nested}".'
        # Las comillas delimitan la ruta cuando la petición termina con puntuación.
        learned = new_task(natural)
        events = []
        with patch.object(turn_worker, "is_desktop_commander", return_value=True):
            await run_turn(learned, natural, [nested, biggest], audit=True, verified=True, events=events)
        assert learned["status"] == "completed" and len(learned["steps"]) == 2
        assert any("Método elegido por experiencia · MCP" in event for event in events)

    legacy = dict(status="completed", steps=[{}])
    assert upgrade_task(legacy) and legacy["status"] == "paused" and legacy["coverage_notes"]

    for reply in (
        CallToolResult(content=[TextContent(type="text", text="x" * 8001)]),
        CallToolResult(content=[], structuredContent={"nextCursor": "otra página"}),
        CallToolResult(content=[TextContent(type="text", text="[WARNING] carpeta: 50 items hidden")]),
    ):
        flags = []
        session = SimpleNamespace(call_tool=AsyncMock(return_value=reply))
        listing = next(tool for tool in catalog if tool.name == "list_directory")
        await mcp_client.call_external((session, name, listing, False), {"path": str(folder)},
                                       AsyncMock(return_value=True), on_partial=flags.append)
        assert len(flags) == 1, reply


async def run_inventory(task, text, history, chat_id, events=None):
    worker = app.Worker([{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": text}],
                        task=task, save_task=lambda value: history.save_task(chat_id, value))
    if events is not None:
        worker.activity.connect(events.append)
    return await worker.chat()


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root):
            asyncio.run(check(root, sys.argv[1:]))
    print("PASS: cobertura, pausas, recortes y páginas pendientes.")

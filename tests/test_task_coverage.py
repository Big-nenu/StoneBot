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

import app
import mcp_client
from history import History
from tasks import COVERAGE_STATUS, LIMIT_REASON, new_task, upgrade_task
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
    objective = "Devuelve los cinco archivos más grandes tras revisar todos los archivos de la carpeta."
    history = History()
    task = new_task(objective)
    chat_id = history.append(None, "user", objective, task=task)
    approvals = []
    real_audit = app.Client(host="http://localhost:11434", timeout=60) if desktop else None

    async def approve(server, tool, arguments):
        approvals.append(Path(arguments["path"]))
        return approvals[-1] in [folder, *files]

    def model_for(paths, *, audit=False):
        def chat(**call):
            if call.get("format") == COVERAGE_STATUS:
                assert audit
                evidence = json.loads(call["messages"][-1]["content"])["lecturas"]
                assert len(evidence) == 6
                assert "archivo-15.txt" in evidence[0]["result"]
                if real_audit is not None:
                    return real_audit.chat(**call)
                return SimpleNamespace(message=Message(role="assistant", content=json.dumps(
                    {"verificada": False, "faltante": "Quedan once archivos sin comprobar."})))
            if paths:
                path = paths.pop(0)
                tool_name = "list_directory" if path == folder else "get_file_info"
                alias, = [tool.function.name for tool in call["tools"] if tool_name in tool.function.name]
                return SimpleNamespace(message=Message(role="assistant", tool_calls=[
                    {"function": {"name": alias, "arguments": {"path": str(path)}}}
                ]))
            return SimpleNamespace(message=report("completada", "Los cinco están verificados; archivo-04.txt es el mayor."))
        return chat

    async def run_turn(snapshot, text, paths, *, audit=False):
        pool = app.McpPool() if desktop else None
        worker = app.Worker([{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": text}],
                            pool, task=snapshot, save_task=lambda value: history.save_task(chat_id, value))
        with (patch.object(app, "Client", return_value=SimpleNamespace(chat=model_for(paths, audit=audit))),
              patch.object(worker, "confirm_external", side_effect=approve),
              nullcontext() if desktop else patch.object(app, "session_for", fake_session)):
            try:
                answer = await worker.chat()
            except app.TaskPaused as exc:
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
    answer = await run_turn(task, "/reanudar", [files[0], files[11]])
    assert task["status"] == "paused" and LIMIT_REASON in answer and "archivo-04.txt" not in answer
    assert len(task["steps"]) == len(approvals) == 13 and approvals[-1] == files[11]

    task = new_task(objective)
    answer = await run_turn(task, objective, [folder, *files[:5]], audit=True)
    assert task["status"] == "paused" and "La tarea sigue pendiente" in answer
    if real_audit is None:
        assert "once archivos" in answer
    else:
        print(answer, flush=True)

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


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root):
            asyncio.run(check(root, sys.argv[1:]))
    print("PASS: cobertura, pausas, recortes y páginas pendientes.")

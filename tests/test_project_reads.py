"""Prueba del encadenamiento de archivos del proyecto y consultas de StoneWave."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from ollama import Message
from PySide6.QtCore import Qt

import mcp_client
import turn_worker
from attachments import read_attachment
from ai_provider import AISettings, OpenRouter
from local_files import OPERATIONS, RESULT_HEADER, load_settings, save_settings
from read_tools import PAGE_CHARS
from stonewave_memory import MemoryUnavailable


def reply(name=None, **arguments):
    calls = [{"function": {"name": name, "arguments": arguments}}] if name else None
    return SimpleNamespace(message=Message(role="assistant", content="" if calls else "Resultado del encargo.",
                                           tool_calls=calls))


def worker_for(folder, memory, *, provider="ollama"):
    messages = [{"role": "system", "content": turn_worker.SYSTEM}, {
        "role": "user", "content": "Lee el README del proyecto y dime si contradice alguna decisión que recuerdes.",
    }]
    worker = turn_worker.Worker(messages, project={"id": 1, "folder": str(folder)}, memory=memory,
                               ai=AISettings(provider, "demo"))
    worker.local_ollama = True
    return worker


async def check_project_read(folder, *, select_source=False, mention_stonewave=False):
    memory = SimpleNamespace(call=AsyncMock(return_value="Acordamos mantener informes en Markdown."),
                             entries=AsyncMock(return_value={}))
    worker = worker_for(folder, memory)
    if mention_stonewave:
        worker.messages[-1]["content"] = "Lee el README del proyecto y consulta en StoneWave si contradice una decisión anterior."
    confirmations = []

    def approve(request):
        confirmations.append(request)
        request["approved"] = True

    worker.mcp_confirmation.connect(approve, Qt.ConnectionType.DirectConnection)
    rounds = 0

    async def model(**kwargs):
        nonlocal rounds
        tools = {tool.function.name for tool in kwargs["tools"] if not callable(tool)}
        assert {"read_project_file", "search_stonewave_memory"} <= tools
        if select_source and "elegir_fuente" in tools:
            return reply("elegir_fuente", fuente="archivos")
        rounds += 1
        if rounds == 1:
            memory.call.assert_not_awaited()
            return reply("read_project_file", path="README.md")
        last = json.loads(kwargs["messages"][-1]["content"])
        if rounds == 2:
            assert last == {"estado": "ok", "archivo": "README.md", "contenido": "Los informes se entregan en PDF.",
                            "parcial": False, "desplazamiento_siguiente": None}, last
            return reply("search_stonewave_memory", text=last["contenido"])
        assert last["estado"] == "ok" and "Markdown" in last["contenido"]
        return SimpleNamespace(message=Message(role="assistant", content="El README dice PDF y StoneWave dice Markdown."))

    with (patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(turn_worker, "load_servers", side_effect=AssertionError("El piloto solo usa conexiones locales")),
          patch.object(worker, "enabled_skills", return_value={})):
        answer = await worker.chat()
    assert answer == RESULT_HEADER + "El README dice PDF y StoneWave dice Markdown."
    assert len(confirmations) == 1 and confirmations[0]["operation"] == OPERATIONS["read"]
    memory.call.assert_awaited_once_with("query_memory", text="Los informes se entregan en PDF.")
    assert rounds == 3
    assert "PDF" not in OpenRouter.messages_for_api([{"role": "assistant", "content": answer}])[0]["content"]


async def check_project_web(folder):
    link = "https://example.test/entregables"
    worker = worker_for(folder, memory=None)
    worker.messages[-1]["content"] = f"Abre {link} y verifica lo que indica el README del proyecto."
    worker.confirm_external = AsyncMock(return_value=True)
    session = SimpleNamespace(
        list_tools=AsyncMock(return_value=ListToolsResult(tools=[
            Tool(name="web_fetch_exa", inputSchema={"type": "object"})])),
        call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="Se exige PDF.")])),
    )

    @asynccontextmanager
    async def connected(name, config):
        yield session

    rounds = 0

    async def model(**kwargs):
        nonlocal rounds
        rounds += 1
        assert {tool.function.name for tool in kwargs["tools"]} == {"read_project_link", "read_project_file"}
        if rounds == 1:
            return reply("read_project_link", url="https://example.test/otro")
        evidence = json.loads(kwargs["messages"][-1]["content"])
        if rounds == 2:
            assert evidence["estado"] == "error"
            session.call_tool.assert_not_awaited()
            return reply("read_project_link")
        if rounds == 3:
            assert evidence["enlace"] == link and "PDF" in evidence["contenido"]
            return reply("read_project_file", path="README.md")
        assert rounds == 4 and "PDF" in evidence["contenido"]
        return reply()

    def approve(request):
        request["approved"] = True

    worker.mcp_confirmation.connect(approve, Qt.ConnectionType.DirectConnection)
    config = {"web": {"enabled": True, "transport": "http", "read_tools": []}}
    with (patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(turn_worker, "session_for", connected),
          patch.object(turn_worker, "load_servers", return_value=config)):
        assert await worker.chat() == RESULT_HEADER + "Resultado del encargo."
    worker.confirm_external.assert_awaited_once_with("web", "web_fetch_exa", {"urls": [link]})
    session.call_tool.assert_awaited_once_with("web_fetch_exa", {"urls": [link]})


async def check_read_failures(folder):
    memory = SimpleNamespace(call=AsyncMock(side_effect=MemoryUnavailable("sin servicio")))
    worker = worker_for(folder, memory)
    confirmations = []
    worker.mcp_confirmation.connect(confirmations.append, Qt.ConnectionType.DirectConnection)
    denied = json.loads(await worker.read_project_file({"path": "README.md"}))
    assert denied["estado"] == "error" and "denegada" in denied["mensaje"]
    assert len(confirmations) == 1
    for path in ("../README.md", str(folder / "README.md"), ".env.production.txt", "oculta/dato.txt"):
        error = json.loads(await worker.read_project_file({"path": path}))
        assert error["estado"] == "error", path
    assert len(confirmations) == 1
    assert json.loads(await worker.search_project_memory({"text": "informes"}))["estado"] == "error"

    modes = load_settings().modes
    save_settings({**modes, "read": "allow"}, [folder / "oculta"])
    assert json.loads(await worker.read_project_file({"path": "enlace.txt"}))["estado"] == "error"
    first = json.loads(await worker.read_project_file({"path": "largo.txt"}))
    assert first["parcial"] and first["desplazamiento_siguiente"] == PAGE_CHARS
    last = json.loads(await worker.read_project_file({"path": "largo.txt", "offset": PAGE_CHARS}))
    assert last["contenido"] == "fin" and not last["parcial"]

    cloud = worker_for(folder, memory, provider="openrouter")
    async def cloud_model(**kwargs):
        tools = {tool.function.name for tool in kwargs["tools"] if not callable(tool)}
        assert "read_project_file" not in tools and "search_stonewave_memory" not in tools
        return reply()

    with patch.object(turn_worker, "OpenRouter", return_value=SimpleNamespace(chat=cloud_model)):
        assert await cloud.chat() == "Resultado del encargo."

    remote = worker_for(folder, memory)
    remote.local_ollama = False
    remote.messages.insert(-1, {"role": "assistant", "content": RESULT_HEADER + "Resultado privado"})

    async def remote_model(**kwargs):
        assert "Resultado privado" not in str(kwargs["messages"])
        return await cloud_model(**kwargs)

    with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=remote_model)):
        assert await remote.chat() == "Resultado del encargo."
    assert memory.call.await_count == 1


async def check_live_project(folder, model):
    memory = SimpleNamespace(call=AsyncMock(return_value="Acordamos que los informes se entregan en Markdown, no en PDF."))
    worker = worker_for(folder, memory)
    worker.ai = AISettings("ollama", model)
    worker.local_ollama = None
    worker.think = False
    with patch.object(worker, "enabled_skills", return_value={}):
        answer = await worker.chat()
    assert memory.call.await_count == 1, answer
    assert "informe" in memory.call.await_args.kwargs["text"].casefold(), memory.call.await_args
    assert answer.startswith(RESULT_HEADER) and "PDF" in answer and "Markdown" in answer, answer
    print(f"PASS: Ollama ({model}) leyó el README y contrastó la decisión con StoneWave simulado.")


async def check_attachment_and_notes(folder, live_model=None):
    manifest = folder / "encargo.txt"
    manifest.write_text("Archivo que hay que consultar en el proyecto: entrega.md", encoding="utf-8")
    (folder / "entrega.md").write_text("Código de entrega: PINO-348.", encoding="utf-8")
    report = {"status": "ok", "notes": [{"path": "recuerdos/entrega.md", "folder": "recuerdos",
              "modified": "2026-11-25T08:00:00Z", "content": "Código de entrega aprobado: PINO-917."}]}
    memory = SimpleNamespace(call=AsyncMock(return_value=json.dumps(report)))
    worker = worker_for(folder, memory)
    worker.messages[-1].update(content="Lee el adjunto para identificar el archivo del proyecto. Lee ese archivo "
                               "y la nota más reciente de StoneWave. Compara los dos códigos de entrega.",
                               attachments=[read_attachment(manifest)])
    worker.mcp_confirmation.connect(lambda request: request.update(approved=True), Qt.ConnectionType.DirectConnection)

    async def decide(**request):
        available = {tool.function.name for tool in request["tools"]}
        assert {"read_project_file", "recent_notes"} <= available
        assert "elegir_fuente" not in available and "inject_memory" not in available
        last = request["messages"][-1]
        if last["role"] != "tool":
            assert "entrega.md" in last["content"]
            return reply("read_project_file", path="entrega.md")
        if last["tool_name"] == "read_project_file":
            assert "PINO-348" in last["content"]
            return reply("recent_notes", limit=1)
        assert "PINO-917" in last["content"]
        return SimpleNamespace(message=Message(role="assistant", content="PINO-348 difiere de PINO-917."))

    with patch.object(worker, "read_project_file", wraps=worker.read_project_file) as read:
        if live_model:
            worker.ai = AISettings("ollama", live_model)
            worker.local_ollama = None
            worker.think = False
            answer = await worker.run_chat()
        else:
            with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=decide)):
                answer = await worker.chat()
        assert any(call.args[0].get("path") == "entrega.md" for call in read.await_args_list), answer
    memory.call.assert_awaited()
    assert answer.startswith(RESULT_HEADER) and "PINO-348" in answer and "PINO-917" in answer, answer
    print(f"PASS: {live_model or 'modelo simulado'} comparó el archivo identificado por el adjunto con StoneWave.")


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        project = root / "proyecto"
        project.mkdir()
        (project / "README.md").write_text("Los informes se entregan en PDF.", encoding="utf-8")
        (project / "largo.txt").write_text("ñ" * PAGE_CHARS + "fin", encoding="utf-8")
        (project / "oculta").mkdir()
        (project / "oculta" / "dato.txt").write_text("excluido", encoding="utf-8")
        (project / ".env.production.txt").write_text("protegido", encoding="utf-8")
        (root / "fuera.txt").write_text("fuera del proyecto", encoding="utf-8")
        os.link(root / "fuera.txt", project / "enlace.txt")
        with patch.object(mcp_client, "default_root", return_value=root / "perfil"):
            assert load_settings().modes["read"] == "ask"
            save_settings(load_settings().modes, [project / "oculta"])
            asyncio.run(check_project_read(project))
            asyncio.run(check_project_read(project, select_source=True))
            asyncio.run(check_project_read(project, mention_stonewave=True))
            asyncio.run(check_project_web(project))
            asyncio.run(check_read_failures(project))
            asyncio.run(check_attachment_and_notes(project))
            if sys.argv[1:2] == ["--live"]:
                asyncio.run(check_attachment_and_notes(project, sys.argv[2] if len(sys.argv) > 2 else "nemotron-3.5-bolt:e4b"))
                asyncio.run(check_live_project(project, sys.argv[2] if len(sys.argv) > 2 else "qwen3.5:4b"))
    print("PASS: proyecto, StoneWave, enlace MCP, permisos, privacidad y paginación.")

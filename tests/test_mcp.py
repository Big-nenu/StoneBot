"""Ejecutar con python -B tests/test_mcp.py."""
import asyncio
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from ollama import Message

import app
import mcp_client
from ai_provider import AISettings


def example_stdio():
    # El servidor recibe un perfil aislado y no usa el directorio de paquetes de ese perfil.
    packages = str(Path(mcp.__file__).resolve().parents[1])
    example = str(Path(__file__).with_name("mcp_example.py").resolve())
    code = f"import runpy,site;site.addsitedir({packages!r});runpy.run_path({example!r},run_name='__main__')"
    return ["--command", sys.executable, "--arg=-B", "--arg=-c", "--arg", code]


def test_reads_link_referenced_in_chat():
    url = "https://example.test/proyecto"
    history = [{"role": "system", "content": app.SYSTEM},
               {"role": "assistant", "content": f"El repositorio es **{url}**. [README]({url})."}]
    question = {"role": "user", "content": "no puedes entrar al Enlace porque ahi viene el readme de que es"}
    assert app.requested_web_link([*history, question]) == url
    assert app.requested_web_link([*history, {**question, "content": "No abras el enlace."}]) is None
    assert app.requested_web_link([*history, {**question, "content": "No puedes entrar al enlace porque es privado."}]) is None
    assert app.requested_web_link([*history, {**question, "content": "El enlace tiene un README."}]) is None
    ambiguous = {"role": "assistant", "content": f"{url} o https://example.test/otro"}
    assert app.requested_web_link([ambiguous, question]) == ""

    fetch = Tool(name="web_fetch_exa", inputSchema={"type": "object", "required": ["urls"],
                "properties": {"urls": {"type": "array", "items": {"type": "string"}}}})
    disk = Tool(name="list_directory", inputSchema={"type": "object"})
    session = SimpleNamespace(list_tools=AsyncMock(return_value=ListToolsResult(tools=[fetch, disk])),
                              call_tool=AsyncMock(return_value=CallToolResult(content=[
                                  TextContent(type="text", text="README: descripción sintética"),
                              ])))

    @contextlib.asynccontextmanager
    async def connected(name, _):
        assert name == "exa"
        yield session

    def summarize(**kwargs):
        assert kwargs["tools"] == []
        assert url in kwargs["messages"][-1]["content"] and "README: descripción sintética" in kwargs["messages"][-1]["content"]
        return SimpleNamespace(message=Message(role="assistant", content="Resumen del README."))

    with (patch.object(app, "load_servers", return_value={"exa": {"enabled": True, "read_tools": []}}),
          patch.object(app, "session_for", connected), patch.object(app, "OpenRouter") as client,
          patch.object(app.Worker, "enabled_skills", return_value={})):
        client.return_value.chat.side_effect = summarize
        worker = app.Worker([*history, question], ai=AISettings("openrouter", "nvidia/nemotron-3.5-lightning:free"))
        worker.confirm_external = AsyncMock(return_value=True)
        assert asyncio.run(worker.chat()) == "Resumen del README."
        session.call_tool.assert_awaited_once_with("web_fetch_exa", {"urls": [url]})
        worker.confirm_external.assert_awaited_once_with("exa", "web_fetch_exa", {"urls": [url]})

        worker.confirm_external.return_value = False
        assert "no autorizó" in asyncio.run(worker.chat())
        session.call_tool.assert_awaited_once()
        client.return_value.chat.assert_called_once()


def test_cloud_chat_keeps_mcp_out_of_conversation_and_stops_repeated_calls():
    search = Tool(name="web_search_exa", inputSchema={"type": "object"})
    session = SimpleNamespace(list_tools=AsyncMock(return_value=ListToolsResult(tools=[search])),
                              call_tool=AsyncMock(return_value=CallToolResult(content=[
                                  TextContent(type="text", text="Fuente encontrada"),
                              ])))

    @contextlib.asynccontextmanager
    async def connected(name, _):
        assert name == "exa"
        yield session

    ai = AISettings("openrouter", "nvidia/nemotron-3.5-lightning")

    def worker(text):
        return app.Worker([{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": text}], ai=ai)

    config = {"exa": {"enabled": True, "read_tools": []}}
    with (patch.object(app, "load_servers", return_value=config) as load,
          patch.object(app, "session_for", connected), patch.object(app, "OpenRouter") as client,
          patch.object(app.Worker, "enabled_skills", return_value={})):
        def conversation(**kwargs):
            assert all(not spec.function.name.startswith("mcp_") for spec in kwargs["tools"])
            return SimpleNamespace(message=Message(role="assistant", content="Qué interesante."))

        client.return_value.chat.side_effect = conversation
        assert asyncio.run(worker("Empecé a trabajar con IA y así surgieron mis proyectos.").chat()) == "Qué interesante."
        load.assert_not_called()
        session.list_tools.assert_not_awaited()

        requests = []

        def repeating(**kwargs):
            requests.append(kwargs)
            if not kwargs["tools"]:
                assert kwargs["messages"][-1]["content"] == "Fuente encontrada"
                return SimpleNamespace(message=Message(role="assistant", content="Aquí está la fuente."))
            alias, = (spec.function.name for spec in kwargs["tools"] if spec.function.name.startswith("mcp_"))
            arguments = {"query": "PySide6", "max": 1} if len(requests) == 1 else {"max": 1, "query": "PySide6"}
            return SimpleNamespace(message=Message(role="assistant", tool_calls=[{"function": {
                "name": alias, "arguments": arguments,
            }}]))

        client.return_value.chat.side_effect = repeating
        research = worker("Busca en internet sobre PySide6.")
        research.confirm_external = AsyncMock(return_value=True)
        assert asyncio.run(research.chat()) == "Aquí está la fuente."
        assert len(requests) == 3
        research.confirm_external.assert_awaited_once()
        session.call_tool.assert_awaited_once_with("web_search_exa", {"query": "PySide6", "max": 1})

    assert not app.requests_external_tools([{"role": "user", "content": "Busca en mi memoria mis archivos de GitHub."}])
    followup = [{"role": "user", "content": "¿Me puedes ayudar a buscar en internet sobre Qt?"},
                {"role": "assistant", "content": "¿Qué versión?"}, {"role": "user", "content": "La 6.10"}]
    assert app.requests_external_tools(followup)
    followup[1]["content"] = "Encontré la versión. ¿Quieres hablar de algo más?"
    assert not app.requests_external_tools(followup)


def test_switch_from_memory_to_local_project():
    path = str(Path(tempfile.gettempdir()) / "Proyecto de prueba")
    messages = [{"role": "system", "content": app.SYSTEM},
                {"role": "user", "content": "¿Cómo funcionan las hipótesis de StoneWave?"},
                {"role": "assistant", "content": "¿Quieres que revisemos los recuerdos de tu memoria?"},
                {"role": "user", "content": f'No, ahorita así lo dejamos.\nOtra duda, esta es la ruta de un proyecto:\n'
                                            f'"{path}"\n¿Puedes entrar y revisar de qué era ese proyecto?'}]
    assert app.requests_external_tools(messages)
    assert not app.requests_local_read([{"role": "user", "content": f'Mi proyecto está en "{path}".'}])
    assert not app.requests_local_read([{"role": "user", "content": f'No abras "{path}".'}])
    assert not app.requests_local_read([{"role": "user", "content": f'Busca en mi memoria la ruta "{path}".'}])

    config = {"enabled": True, "read_tools": [], "transport": "stdio", "command": "npx",
              "args": ["@wonderwhy-er/desktop-commander"]}
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    session = SimpleNamespace(
        list_tools=AsyncMock(return_value=ListToolsResult(tools=[
            Tool(name=name, inputSchema=schema) for name in ("list_directory", "write_file")
        ])),
        call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="README.md")])),
    )

    @contextlib.asynccontextmanager
    async def connected(name, _):
        assert name == "desktop"
        yield session

    def chat(**kwargs):
        alias, = (tool.function.name for tool in kwargs["tools"])
        if kwargs["messages"][-1]["role"] == "tool":
            assert kwargs["messages"][-1]["content"] == "README.md"
            reply = Message(role="assistant", content="Encontré README.md.")
        else:
            assert "/ list_directory." in kwargs["tools"][0].function.description
            reply = Message(role="assistant", tool_calls=[
                {"function": {"name": alias, "arguments": {"path": path}}},
            ])
        return SimpleNamespace(message=reply)

    ai = AISettings("openrouter", "test/model", cloud_memory=True)
    memory = SimpleNamespace(entries=AsyncMock(), call=AsyncMock())
    with (patch.object(app, "load_servers", return_value={"desktop": config, "exa": {
              "enabled": True, "read_tools": [], "transport": "http",
          }}) as load,
          patch.object(app, "session_for", connected), patch.object(app, "OpenRouter") as client,
          patch.object(app.Worker, "enabled_skills", return_value={})):
        client.return_value.chat.side_effect = chat
        worker = app.Worker(messages, ai=ai, memory=memory)
        worker.confirm_external = AsyncMock(return_value=True)
        assert asyncio.run(worker.chat()) == "Encontré README.md."
        session.call_tool.assert_awaited_once_with("list_directory", {"path": path})
        worker.confirm_external.assert_awaited_once_with("desktop", "list_directory", {"path": path})
        memory.call.assert_not_awaited()
        memory.entries.assert_not_awaited()

        load.return_value = {}
        client.return_value.chat.reset_mock()
        assert "Desktop Commander" in asyncio.run(worker.chat())
        client.return_value.chat.assert_not_called()


def test_context7_results_are_used_to_finish_after_empty_ollama_response():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    names = ["resolve-library-id", "query-docs"]
    doc = ("### QVBoxLayout: usa addWidget() para añadir controles.\n" * 160)[:8000]
    session = SimpleNamespace(
        list_tools=AsyncMock(return_value=ListToolsResult(tools=[
            Tool(name=name, inputSchema=schema) for name in names
        ])),
        call_tool=AsyncMock(side_effect=[
            CallToolResult(content=[], structuredContent={"libraryId": "/qt/pyside6"}),
            CallToolResult(content=[TextContent(type="text", text=doc)]),
        ]),
    )

    @contextlib.asynccontextmanager
    async def connected(name, server):
        yield session

    messages = [{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": "Consulta PySide6."}]
    rounds = 0

    def chat(**kwargs):
        nonlocal rounds
        rounds += 1
        assert kwargs["options"]["num_ctx"] == (4096 if rounds <= 2 else 8192)
        transcript = kwargs["messages"]
        if rounds == 4:
            assert kwargs["tools"] == [] and kwargs["think"] is False
            assert len(transcript) == 6, transcript
            assert transcript[3]["content"] == '{"libraryId": "/qt/pyside6"}'
            assert transcript[5]["content"] == doc
            return SimpleNamespace(message=Message(role="assistant", content="Usa QVBoxLayout.addWidget()."))
        if rounds == 3:
            assert transcript[-1]["content"] == doc
            return SimpleNamespace(done_reason="length",
                                   message=Message(role="assistant", content="", thinking="Revisando los ejemplos."))
        name = names[rounds - 1]
        tool, = [tool for tool in kwargs["tools"] if not callable(tool) and f" / {name}." in tool.function.description]
        call = Message.ToolCall(function=Message.ToolCall.Function(name=tool.function.name, arguments={"query": "PySide6"}))
        return SimpleNamespace(message=Message(role="assistant", tool_calls=[call]))

    worker = app.Worker(messages)
    outputs, errors = [], []
    worker.finished.connect(outputs.append)
    worker.error.connect(errors.append)
    confirm = AsyncMock(return_value=True)
    with (patch.object(app, "load_servers", return_value={"context7": {"enabled": True, "read_tools": []}}),
          patch.object(app, "session_for", connected),
          patch.object(worker, "enabled_skills", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
          patch.object(worker, "confirm_external", confirm)):
        worker.run()
    assert not errors, errors
    assert outputs == ["Usa QVBoxLayout.addWidget()."] and rounds == 4
    assert [call.args[1] for call in confirm.await_args_list] == names
    assert [call.args[0] for call in session.call_tool.await_args_list] == names


def test_empty_reply_retries_selection_across_active_servers():
    fixtures = {
        name: SimpleNamespace(
            list_tools=AsyncMock(return_value=ListToolsResult(tools=[
                Tool(name="search", inputSchema={"type": "object"}),
            ])),
            call_tool=AsyncMock(return_value=CallToolResult(content=[TextContent(type="text", text="Fuente web")])),
        )
        for name in ("docs", "web")
    }

    @contextlib.asynccontextmanager
    async def connected(name, server):
        if name == "offline":
            raise mcp_client.MissingTokenError()
        yield fixtures[name]

    rounds = 0

    def chat(**kwargs):
        nonlocal rounds
        tools = {tool.function.description.split(" / ")[0]: tool.function.name
                 for tool in kwargs["tools"] if not callable(tool)}
        assert set(tools) == {"docs", "web"} and tools["docs"] != tools["web"]
        rounds += 1
        if rounds == 1:
            assert kwargs["options"]["num_ctx"] == 8192
            return SimpleNamespace(message=Message(role="assistant", content="", thinking="Buscando una herramienta."))
        if rounds == 2:
            assert kwargs["think"] is False and kwargs["options"]["num_ctx"] == 8192
            call = Message.ToolCall(function=Message.ToolCall.Function(name=tools["web"], arguments={}))
            return SimpleNamespace(message=Message(role="assistant", tool_calls=[call]))
        assert kwargs["messages"][-1]["content"] == "Fuente web"
        return SimpleNamespace(message=Message(role="assistant", content="Encontré una fuente."))

    worker = app.Worker([{"role": "user", "content": "Busca en la web. " + "Referencia previa. " * 400}])
    outputs, errors, notices = [], [], []
    activity = []
    worker.finished.connect(outputs.append)
    worker.error.connect(errors.append)
    worker.mcp_notice.connect(notices.append)
    worker.activity.connect(activity.append)
    confirm = AsyncMock(return_value=True)
    servers = {name: {"enabled": name != "disabled", "read_tools": []}
               for name in ("docs", "offline", "web", "disabled")}
    with (patch.object(app, "load_servers", return_value=servers),
          patch.object(app, "session_for", connected),
          patch.object(worker, "enabled_skills", return_value={}),
          patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
          patch.object(worker, "confirm_external", confirm)):
        worker.run()
    assert not errors and outputs == ["Encontré una fuente."], errors
    confirm.assert_awaited_once_with("web", "search", {})
    fixtures["web"].call_tool.assert_awaited_once_with("search", {})
    fixtures["docs"].call_tool.assert_not_awaited()
    assert any("offline" in notice and "variable de entorno" in notice for notice in notices)
    assert any("web" in notice and "solicitó search" in notice for notice in notices)
    assert next(i for i, event in enumerate(activity) if "En ejecución · web / search" in event) < next(
        i for i, event in enumerate(activity) if "Finalizó search" in event)


def test_stdio_chat_and_permissions():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        with (patch.object(mcp_client, "default_root", return_value=folder),
              patch.dict(os.environ, {"STONEBOT_TEST_PARENT_ONLY": "not inherited"})):
            def manage(*args):
                with patch.object(sys, "argv", ["mcp_client.py", *args]), contextlib.redirect_stdout(io.StringIO()) as out:
                    mcp_client.main()
                return out.getvalue()

            manage("add", "example", *example_stdio())
            assert not mcp_client.load_servers()["example"]["enabled"]
            manage("enable", "example")
            manage("allow-read", "example", "echo")
            assert '"echo"' in manage("list")
            manage("disable", "example")
            assert not mcp_client.load_servers()["example"]["enabled"]
            manage("enable", "example")

            marker = folder / "mcp" / "example" / "mcp-test-marker.txt"
            protected = folder / "protected"
            protected.mkdir()
            personal = protected / "memoria.db"
            personal.write_text("datos de prueba", encoding="utf-8")
            messages = [{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": "Prueba MCP"}]
            rounds = 0
            aliases = {}

            def chat(**kwargs):
                nonlocal rounds
                rounds += 1
                tools = {tool.function.name: tool.function.description for tool in kwargs["tools"]
                         if not callable(tool)}
                assert len(tools) == 2, tools
                echo, = [alias for alias, desc in tools.items() if " / echo." in desc]
                mark, = [alias for alias, desc in tools.items() if " / mark." in desc]
                aliases["mark"] = mark
                transcript = kwargs["messages"]
                if rounds == 1:
                    assert {tool.__name__ for tool in kwargs["tools"] if callable(tool)} == {
                        "query_experiences",
                    }
                    requests = [(echo, {}), (echo, {"text": str(personal)}),
                                (echo, {"text": "hola"}), (mark, {"text": "rechazado"})]
                elif rounds == 2:
                    assert "esquema" in transcript[-4]["content"]
                    assert "bloqueada" in transcript[-3]["content"]
                    assert "Eco MCP: hola" in transcript[-2]["content"]
                    assert "no autorizó" in transcript[-1]["content"]
                    assert not marker.exists()
                    requests = [(mark, {"text": "aprobado"})]
                else:
                    assert "Marca escrita" in transcript[-1]["content"]
                    return SimpleNamespace(message=Message(role="assistant", content="Terminado"))
                calls = [Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=args))
                         for name, args in requests]
                return SimpleNamespace(message=Message(role="assistant", tool_calls=calls))

            worker = app.Worker(messages)
            outputs, errors = [], []
            worker.finished.connect(outputs.append)
            worker.error.connect(errors.append)
            confirm = AsyncMock(side_effect=[False, True])
            with (patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
                  patch("stonebot_engine.safety.protected_paths", return_value=[protected]),
                  patch.object(worker, "confirm_external", confirm)):
                worker.run()
            assert not errors, errors
            assert outputs == ["Terminado"]
            assert confirm.await_count == 2
            assert personal.read_text(encoding="utf-8") == "datos de prueba"
            assert marker.read_text(encoding="utf-8") == "aprobado"

            servers = mcp_client.load_servers()
            servers["example"]["disabled_tools"] = ["mark"]
            mcp_client.save_servers(servers)

            def stale_call(**kwargs):
                exposed = [tool.function.description for tool in kwargs["tools"] if not callable(tool)]
                assert len(exposed) == 1 and " / echo." in exposed[0]
                if len(kwargs["messages"]) == 2:
                    call = Message.ToolCall(function=Message.ToolCall.Function(
                        name=aliases["mark"], arguments={"text": "no disponible"}))
                    reply = Message(role="assistant", tool_calls=[call])
                else:
                    assert "desconocida" in kwargs["messages"][-1]["content"]
                    reply = Message(role="assistant", content="Excluida")
                return SimpleNamespace(message=reply)

            with (patch.object(app, "Client", return_value=SimpleNamespace(chat=stale_call)),
                  patch.object(worker, "confirm_external", confirm)):
                worker.run()
            assert not errors, errors
            assert outputs == ["Terminado", "Excluida"]
            assert confirm.await_count == 2 and marker.read_text(encoding="utf-8") == "aprobado"
            manage("revoke-read", "example", "echo")
            assert mcp_client.load_servers()["example"]["read_tools"] == []
            manage("remove", "example")
            assert not mcp_client.load_servers()


if __name__ == "__main__":
    test_reads_link_referenced_in_chat()
    print("PASS: enlace contextual, lectura web exacta y autorización.")
    test_cloud_chat_keeps_mcp_out_of_conversation_and_stops_repeated_calls()
    print("PASS: chat sin MCP externo y cierre de solicitudes repetidas en OpenRouter simulado.")
    test_switch_from_memory_to_local_project()
    print("PASS: cambio de tema a una ruta local, herramientas de lectura y permisos.")
    test_context7_results_are_used_to_finish_after_empty_ollama_response()
    print("PASS: Context7 entrega ambos resultados y Ollama sintetiza tras una respuesta vacía.")
    test_empty_reply_retries_selection_across_active_servers()
    print("PASS: descubrimiento multiservidor y autorización tras reintentar una respuesta vacía.")
    test_stdio_chat_and_permissions()
    print("PASS: configuración, chat MCP STDIO, lectura autorizada, validación y confirmación de escritura.")

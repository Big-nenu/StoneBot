"""Regresiones de descubrimiento MCP con el mismo Worker de CLI y Desktop."""
import asyncio
import hashlib
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.types import Tool, ToolAnnotations
from ollama import Message

from ai_provider import AISettings
from mcp_permissions import independent_read_requests
from mcp_pool import McpPool
from mcp_visibility import DISCOVER, McpVisibility
from turn_events import NullEvents
from turn_worker import Worker


SERVER = {"enabled": True, "transport": "stdio", "command": sys.executable, "args": [], "read_tools": []}
DISCOVER_NAME = DISCOVER.function.name
MESSAGES = [{"role": "system", "content": "Prueba"}, {"role": "user", "content": "Consulta el catálogo Sierra."}]


def tool(name, **kwargs):
    return Tool(name=name, inputSchema={"type": "object", "additionalProperties": False}, **kwargs)


def response(*calls, final=""):
    return SimpleNamespace(message=Message(role="assistant", content=final,
                           tool_calls=[{"function": {"name": name, "arguments": args}} for name, args in calls]))


class Approvals(NullEvents):
    def __init__(self):
        self.confirmations = []

    async def confirm(self, request):
        self.confirmations.append((request["server"], request["tool"], request["arguments"]))
        request["approved"] = request["tool"] == "autorizar"


async def test_shared_worker():
    events = Approvals()
    session = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(
        tools=[tool("autorizar"), tool("denegar"), tool("oculta"), tool("medir", description="C:\\datos privados")],
        nextCursor=None)), call_tool=AsyncMock(return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="dato de prueba")], structuredContent=None, isError=False)))

    @asynccontextmanager
    async def open_session(name, cfg, **kwargs):
        yield session

    pool = McpPool(open_session=open_session)
    sources = {"sierra": {**SERVER, "disabled_tools": ["oculta"]}, "privado": {**SERVER, "enabled": False}}
    aliases = {}

    async def chat(**kwargs):
        names = [item.__name__ if callable(item) else item.function.name for item in kwargs["tools"]]
        system = kwargs["messages"][0]["content"]
        assert "privado" not in system and "C:\\datos privados" not in str(kwargs["tools"])
        assert all("oculta" not in name for name in names)
        if len(kwargs["messages"]) > 4:
            assert not names
            return response(final="Revisado.")
        assert DISCOVER_NAME in names
        aliases.update({name.split("_")[2]: name for name in names if name.startswith("mcp_sierra_")})
        if len(kwargs["messages"]) == 2:
            return response((DISCOVER_NAME, {"servidor": "sierra"}))
        if len(kwargs["messages"]) == 4:
            assert session.call_tool.await_count == 0 and not events.confirmations
            return response((aliases["autorizar"], {}), (aliases["denegar"], {}), (aliases["medir"], {}))

    try:
        with (patch.dict("os.environ", {"STONEBOT_DISCOVER_MCP": "1"}),
              patch("turn_worker.load_servers", return_value=sources),
              patch("turn_worker.requests_external_tools", return_value=False)):
            worker = Worker([], pool=pool, events=events)
            worker.local_ollama = True
            assert await worker.chat_with_tools(SimpleNamespace(chat=chat), list(MESSAGES), {}) == "Revisado."
            assert events.confirmations == [("sierra", "autorizar", {}), ("sierra", "denegar", {})]
            session.call_tool.assert_awaited_once_with("autorizar", {})
            session.list_tools.assert_awaited_once()

            client = SimpleNamespace(chat=AsyncMock(return_value=response(final="Directo.")))
            with patch.dict("os.environ", {"STONEBOT_DISCOVER_MCP": "0"}):
                assert await worker.chat_with_tools(client, list(MESSAGES), {}) == "Directo."
            assert DISCOVER not in client.chat.await_args.kwargs["tools"]

            for settings in (AISettings("ollama", "no-verificado"), AISettings("openrouter", "simulado")):
                worker = Worker([], pool=pool, ai=settings)
                worker.local_ollama = False
                assert await worker.chat_with_tools(client, list(MESSAGES), {}) == "Directo."
                assert DISCOVER not in client.chat.await_args.kwargs["tools"]
            session.list_tools.assert_awaited_once()

            worker = Worker([], pool=pool)
            worker.local_ollama = True
            calls = [response(("inspect_local_files", {"target": "prueba"}), (aliases["autorizar"], {})),
                     response(final="Lista.")]
            client = SimpleNamespace(chat=AsyncMock(side_effect=calls))
            with patch.object(worker, "inspect_local_files", new=AsyncMock(return_value='{"estado":"ok"}')):
                assert await worker.chat_with_tools(client, list(MESSAGES), {}) == "Lista."
            assert all(getattr(spec, "function", None) != DISCOVER.function
                       for spec in client.chat.await_args.kwargs["tools"])
            session.call_tool.assert_awaited_once()
    finally:
        pool.close()


async def test_bounded_catalog():
    @asynccontextmanager
    async def open_session(name, cfg, **kwargs):
        if name == "fallido":
            raise ConnectionError("dato privado")
        if name == "lento":
            await asyncio.sleep(10)
        definitions = [tool(f"actividad_{i:02}", annotations=ToolAnnotations(readOnlyHint=True)) for i in range(10)]
        definitions.append(Tool(name="privada", inputSchema={"enum": ["https://privado.example"]}))
        yield SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=definitions, nextCursor=None)))

    pool = McpPool(open_session=open_session)
    trace = []
    with patch("mcp_visibility.STARTUP_WAIT", 0.3):
        catalog = McpVisibility(pool, {key: SERVER for key in ("rapido", "fallido", "lento")},
                                lambda event, **fields: trace.append((event, fields)))
        try:
            await catalog.collect(wait=True)
            assert len(catalog.offered(None)) == 8
            assert all("privada" not in name for name in catalog.entries)
            first = json.loads(await catalog.find({"servidor": "rapido"}, None))
            second = json.loads(await catalog.find({"servidor": "rapido", "pagina": first["pagina_siguiente"]}, None))
            assert len(second["herramientas"]) == 2
            assert catalog.offered(None) == [item["alias"] for item in second["herramientas"]]
            assert catalog.offered(set()) == []
            assert catalog.failed == {"fallido"} and set(catalog.pending) == {"lento"}
            assert "dato privado" not in str(trace)
        finally:
            await catalog.close()
            pool.close()


async def test_hidden_tool_is_offered_next_round():
    name = "zeta_informe"
    alias = f"mcp_sierra_{name}_{hashlib.sha256(name.encode()).hexdigest()[:12]}"
    definitions = [tool(f"actividad_{i}") for i in range(8)] + [tool(name, annotations=ToolAnnotations(readOnlyHint=True))]
    session = SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=definitions, nextCursor=None)),
                              call_tool=AsyncMock(return_value=SimpleNamespace(content=[], structuredContent={}, isError=False)))

    @asynccontextmanager
    async def open_session(*args, **kwargs):
        yield session

    pool = McpPool(open_session=open_session)

    async def chat(**kwargs):
        offered = {spec.function.name for spec in kwargs["tools"] if not callable(spec)}
        if len(kwargs["messages"]) == 2:
            assert alias not in offered
            return response((DISCOVER_NAME, {"consulta": "zeta"}), (alias, {}))
        if len(kwargs["messages"]) == 5:
            assert alias in offered and session.call_tool.await_count == 0
            return response((alias, {}))
        return response(final="Informe consultado.")

    try:
        with (patch.dict("os.environ", {"STONEBOT_DISCOVER_MCP": "1"}),
              patch("turn_worker.load_servers", return_value={"sierra": {**SERVER, "read_tools": [name]}}),
              patch("turn_worker.requests_external_tools", return_value=False)):
            worker = Worker([], pool=pool)
            worker.local_ollama = True
            assert await worker.chat_with_tools(SimpleNamespace(chat=chat), list(MESSAGES), {}) == "Informe consultado."
            session.call_tool.assert_awaited_once_with(name, {})
    finally:
        pool.close()



async def test_independent_read_after_denial():
    assert not list(independent_read_requests("No uses el eco del MCP catalogo.", "catalogo", "eco"))
    assert not list(independent_read_requests("Consulta el origen con eco y excluye catalogo.", "catalogo", "eco"))
    schema = {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"], "additionalProperties": False}
    def definition(name, read=False):
        return Tool(name=name, inputSchema=schema, annotations=ToolAnnotations(readOnlyHint=read))

    for in_same_batch in (True, False):
        events = Approvals()
        answer = SimpleNamespace(content=[SimpleNamespace(type="text", text="Dato comprobado")],
                                 structuredContent=None, isError=False)
        definitions = {"origen": [definition("publicar"), definition("buscar", True)],
                       "catalogo": [definition("autorizar", True), definition("insertar")]}
        sessions = {name: SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools, nextCursor=None)),
                                          call_tool=AsyncMock(return_value=answer)) for name, tools in definitions.items()}

        @asynccontextmanager
        async def open_session(name, *_args, **_kwargs):
            yield sessions[name]

        pool = McpPool(open_session=open_session)
        messages = [MESSAGES[0], {"role": "user", "content":
                    "Usa publicar del MCP origen con PRIVADO-127. Independientemente, usa autorizar del "
                    "MCP catalogo con PUBLICO-483. No uses las herramientas insertar y buscar."}]
        aliases = {}
        rounds = 0

        def independent_calls():
            return ((aliases["publicar"], {"text": "PRIVADO-127"}),
                    (aliases["insertar"], {"text": "PRIVADO-127"}),
                    (aliases["autorizar"], {"text": "PRIVADO-127"}),
                    (aliases["autorizar"], {"text": "PUBLICO-483"}))

        async def chat(**request):
            nonlocal rounds
            names = [spec.function.name for spec in request["tools"] if not callable(spec)]
            rounds += 1
            if rounds == 1:
                aliases.update({name.split("_")[2]: name for name in names if name.startswith("mcp_")})
                denial = (aliases["publicar"], {"text": "PRIVADO-127"})
                if in_same_batch:
                    return response(denial, *independent_calls()[1:])
                return response(denial)
            assert names == [aliases["autorizar"]]
            if rounds == 2 and not in_same_batch:
                return response(*independent_calls())
            return response(final="Revisé el catálogo.")

        try:
            sources = {name: {**SERVER, "read_tools": ["autorizar"] if in_same_batch and name == "catalogo" else []}
                       for name in sessions}
            with (patch.dict("os.environ", {"STONEBOT_DISCOVER_MCP": "1"}),
                  patch("turn_worker.load_servers", return_value=sources),
                  patch("turn_worker.requests_external_tools", return_value=False)):
                worker = Worker(messages, pool=pool, events=events)
                worker.local_ollama = True
                assert await worker.chat_with_tools(SimpleNamespace(chat=chat), list(messages), {}) == "Revisé el catálogo."
            assert worker.operation_denied
            sessions["origen"].call_tool.assert_not_awaited()
            sessions["catalogo"].call_tool.assert_awaited_once_with("autorizar", {"text": "PUBLICO-483"})
            expected = [("origen", "publicar", {"text": "PRIVADO-127"})]
            if not in_same_batch:
                expected.append(("catalogo", "autorizar", {"text": "PUBLICO-483"}))
            assert events.confirmations == expected
            assert any(entry.code == "DESTINO_BLOQUEADO" for entry in worker.calls.entries)
        finally:
            pool.close()


if __name__ == "__main__":
    asyncio.run(test_shared_worker())
    asyncio.run(test_independent_read_after_denial())
    asyncio.run(test_bounded_catalog())
    asyncio.run(test_hidden_tool_is_offered_next_round())
    print("PASS: manifiesto, catálogo acotado, permisos y privacidad de MCP")

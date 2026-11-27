"""Validación, recuperación de lecturas y tratamiento de efectos de MCP."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.types import Tool, ToolAnnotations

from chat_execution import ChatExecution
from engine_harness import call, reply
from mcp_client import call_external
from read_tools import read_tool
from tool_loop import ToolLoop, ToolResult, TurnTools
from turn_events import RecordingEvents
from turn_worker import Worker


def result(text, *, error=False, metadata=None):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], structuredContent=metadata, isError=error)


def definition(name, *, read=False):
    schema = {"type": "object", "properties": {"cursor": {"type": "integer", "minimum": 0}},
              "required": ["cursor"], "additionalProperties": False}
    return Tool(name=name, inputSchema=schema, annotations=ToolAnnotations(readOnlyHint=read))


async def test_validation_and_retry():
    view = definition("consultar", read=True)
    session = SimpleNamespace(call_tool=AsyncMock(side_effect=[result("Error transitorio", error=True), result("Evidencia")]))
    entry = (session, "ejemplo", view, False)
    confirm = AsyncMock(return_value=True)
    retry = Mock()
    reject = Mock()
    start = Mock()
    invalid = await call_external(entry, {"cursor": "dato privado"}, confirm, on_start=start,
                                  on_rejected=reject, on_retry=retry)
    assert "cursor" in invalid and "dato privado" not in invalid
    reject.assert_called_once_with("ARGUMENTOS_INVALIDOS")
    confirm.assert_not_awaited()
    start.assert_not_called()
    session.call_tool.assert_not_awaited()

    observed = await call_external(entry, {"cursor": 4}, confirm, on_start=start, on_retry=retry)
    assert observed == "Evidencia"
    confirm.assert_awaited_once_with("ejemplo", "consultar", {"cursor": 4})
    start.assert_called_once()
    retry.assert_called_once_with("error_transitorio")
    assert [c.args for c in session.call_tool.await_args_list] == [("consultar", {"cursor": 4})] * 2

    session.call_tool.reset_mock(side_effect=True)
    session.call_tool.return_value = result("Falló", error=True, metadata={"retryable": True})
    retry.reset_mock()
    effect = (session, "ejemplo", definition("cambiar"), True)
    assert (await call_external(effect, {"cursor": 1}, confirm, on_retry=retry)).startswith("Error MCP:")
    session.call_tool.assert_awaited_once()
    retry.assert_not_called()

    session.call_tool.reset_mock()
    session.call_tool.side_effect = ConnectionError("socket")
    next_session = SimpleNamespace(call_tool=AsyncMock(return_value=result("Recuperada")))
    reconnect = AsyncMock(return_value=next_session)
    assert await call_external(entry, {"cursor": 4}, confirm, on_retry=retry, reconnect=reconnect) == "Recuperada"
    reconnect.assert_awaited_once()
    next_session.call_tool.assert_awaited_once_with("consultar", {"cursor": 4})


async def test_effect_uncertain():
    import turn_worker
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    operations = [definition(name) for name in ("cambiar", "modificar")]
    operations.append(definition("consultar", read=True))
    transport = AsyncMock(side_effect=[TimeoutError("timeout"), result("Estado leído")])
    session = SimpleNamespace(call_tool=transport, list_tools=AsyncMock(
        return_value=SimpleNamespace(tools=operations, nextCursor=None)))

    @asynccontextmanager
    async def connect(*args):
        yield session

    aliases = {}

    async def model(**kwargs):
        rows = kwargs["messages"]
        for spec in kwargs["tools"]:
            if not callable(spec) and spec.function.name.startswith("mcp_sim_"):
                alias = spec.function.name
                aliases[alias.split("_")[2]] = alias
        if rows[-1]["role"] == "user":
            return call(aliases["cambiar"], cursor=1)
        if "EFECTO_SIN_CONFIRMAR" in rows[-1]["content"]:
            offered = [spec.function.name for spec in kwargs["tools"] if not callable(spec)]
            assert aliases["cambiar"] not in offered and aliases["modificar"] not in offered
            return call(aliases["consultar"], cursor="04")
        return reply("Verificación disponible. El efecto sigue sin confirmar.")

    journal = ChatExecution(1, None, lambda *args: 1, "Prueba", ["ollama"])
    messages = [{"role": "system", "content": "Prueba"}, {"role": "user", "content": "Usa el servidor MCP."}]
    events = RecordingEvents(approve=True)
    server = {"enabled": True, "transport": "http", "url": "https://example.invalid", "read_tools": ["consultar"]}
    worker = Worker(messages, events=events, execution=journal)
    with (patch.object(turn_worker, "load_servers", return_value={"sim": server}),
          patch.object(turn_worker, "session_for", connect)):
        assert "sigue sin confirmar" in await worker.chat_with_tools(SimpleNamespace(chat=model), messages, {}, source="mcp")
    assert [c.args for c in transport.await_args_list] == [("cambiar", {"cursor": 1}), ("consultar", {"cursor": 4})]
    assert journal.state["steps"][0]["status"] == "sin confirmar"
    assert journal.state["steps"][1]["arguments"] == {"cursor": 4}
    assert [e for e in events.events if e[0] == "mcp_confirmation"] == [("mcp_confirmation", "cambiar")]


async def test_corrected_round():
    spec = read_tool("leer", "Prueba", {"cursor": {"type": "integer", "minimum": 0}}, ["cursor"])
    catalog = TurnTools([spec], {}, lambda _: (None, ("cursor",)))
    messages = []
    dispatched = AsyncMock(return_value=ToolResult("Evidencia"))
    recorded = Mock(return_value=None)

    async def request(index, finishing):
        catalog.offer(finishing=finishing)
        if index == 0:
            return call("ausente", cursor=1).message
        if index == 1:
            assert "HERRAMIENTA_NO_DISPONIBLE" in messages[-1]["content"]
            return call("leer", cursor="-1").message
        if index == 2:
            assert "ARGUMENTOS_INVALIDOS" in messages[-1]["content"]
            return call("leer", cursor="04").message
        return "Hecho."

    loop = ToolLoop(messages, final_round=3, tools=catalog, max_distinct_calls=4)
    assert await loop.run(request, dispatched, check_pause=lambda: None, on_repeat=lambda: None,
                          after_batch=lambda: None, activity=lambda _: None, before_call=recorded) == "Hecho."
    dispatched.assert_awaited_once_with("leer", {"cursor": 4})
    recorded.assert_called_once_with("leer", {"cursor": 4}, [])


if __name__ == "__main__":
    asyncio.run(test_validation_and_retry())
    asyncio.run(test_effect_uncertain())
    asyncio.run(test_corrected_round())
    print("PASS: validación previa a efectos, recuperación y verificación autorizada")

"""Pruebas de instrumentación y rúbrica de 5.2.1."""
import asyncio
from contextlib import asynccontextmanager, chdir
import json
import runpy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.types import Tool as McpTool

from cli_turn_runner import trace_payload
from eval_agent_baseline import CASES, RESERVED_CASES, prepare
from eval_agent_grade import classify, grade
from mcp_pool import McpPool, mcp_trace_state
import turn_worker


MARK = "mcp_example_mark_6201eb4dccc9"


def test_classification():
    row = {"caso": "D03", "cierre": {"estado": "finished"}, "marca_creada": False, "llamadas": [],
           "traza": [{"evento": "mcp_servidor", "servidor": "example", "habilitado": True}],
           "sondeo_mcp": {"example": {"estado": "exito", "herramientas": ["mark"]}}}
    expected = ("example", "mark")
    assert classify(row, expected) == "motor"
    assert grade(row)["estado"] == "no_cumple"
    row["sondeo_mcp"]["example"] = {"estado": "timeout"}
    assert classify(row, expected) == "infraestructura"
    assert grade(row)["estado"] == "no_evaluable"
    row["sondeo_mcp"] = {}
    assert classify(row, expected) == "pendiente"
    row["traza"].append({"evento": "peticion_modelo", "herramientas": [MARK]})
    assert classify(row, expected) == "modelo"
    row["llamadas"] = [MARK]
    row["traza"].extend([
        {"evento": "permiso", "servidor": "example", "herramienta": "mark", "aprobado": False, "peticion": 1},
        {"evento": "resultado", "herramienta": MARK, "estado": "sin_ejecutar", "peticion": 2},
    ])
    assert grade(row)["estado"] == "no_cumple"
    row["traza"][-1]["peticion"] = 1
    assert grade(row)["estado"] == "revision_manual"
    row["marca_creada"] = True
    assert grade(row)["estado"] == "no_cumple"


def test_stuck_cursor():
    step = {"tool": "mcp_atascado_consultar_inventario_123456789012",
            "result": json.dumps({"cursor": 1, "next_cursor": 1, "parcial": True,
                                  "elementos": ["PÁGINA-INICIAL"]})}
    row = {"caso": "V04", "cierre": {"estado": "finished"}, "diario": [{"pasos": [step]}]}
    assert grade(row)["estado"] == "no_cumple"
    row["diario"][0]["pasos"].append(dict(step))
    assert grade(row)["estado"] == "revision_manual"


def test_reserved_fixtures():
    script = Path(__file__).with_name("eval_agent_mcp.py").resolve()
    assert not set(CASES).intersection(RESERVED_CASES)

    def load(mode):
        with patch.object(sys, "argv", [str(script), mode]):
            return runpy.run_path(str(script))

    with TemporaryDirectory() as directory, chdir(directory):
        assert load("ambar")["echo"]("CLAVE-F47") == "ÁMBAR: CLAVE-F47"
        assert load("extracto")["consultar_registro"]()["truncated"] is True
        assert load("acta_integra")["consultar_registro"]()["fecha"] == "2032-06-08"
        source = Path("fichas")
        source.mkdir()
        with chdir(source):
            inventory = load("archivo_fichas")["consultar_inventario"]
            assert inventory(2)["next_cursor"] == 3
            try:
                inventory(3)
            except RuntimeError as exc:
                assert "transitorio" in str(exc)
            else:
                raise AssertionError("La primera consulta del cursor 3 debe fallar.")
            assert inventory(3)["elementos"] == ["FICHA-LIRIO-319"]
        root = Path(directory)
        prepare("V08", root)
        assert sorted(path.stat().st_size for path in (root / "copias").rglob("lirio.dat")) == [905, 1103]


async def test_trace_decisions():
    captured = []
    def trace(event, **fields):
        captured.append(trace_payload(event, fields))

    server = {"enabled": True, "transport": "stdio", "command": sys.executable, "args": [],
              "disabled_tools": ["apagada"]}
    tool = McpTool(name="mark", inputSchema={"type": "object"})
    pool = McpPool()
    worker = turn_worker.Worker([], pool=pool, trace=trace)
    fake = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(
        message=SimpleNamespace(content="Sin operaciones.", thinking=None, tool_calls=[]))))
    messages = [{"role": "system", "content": "Prueba"}, {"role": "user", "content": "Consulta la fuente B."}]
    with (patch.object(turn_worker, "load_servers", return_value={"example": server}),
          patch.object(turn_worker, "requests_external_tools", return_value=False),
          patch.object(worker, "verify_local_ollama", new=AsyncMock(return_value=False)),
          patch.object(pool, "prepare", new=AsyncMock()) as prepare,
          patch.object(pool, "entries", new=AsyncMock(return_value={MARK: (None, "example", tool, False)})) as entries):
        normal = await worker.chat_with_tools(fake, messages, {})
        prepare.assert_not_awaited()
        entries.assert_not_awaited()
        assert any(e.get("motivo") == "fuera_del_enrutamiento" for e in captured)
        assert all(MARK not in e.get("herramientas", []) for e in captured)
        captured.clear()
        assert await worker.chat_with_tools(fake, messages, {}, source="mcp") == normal
        assert any(e["evento"] == "mcp_descubrimiento" and e["descubiertas"] == e["elegibles"] == 1 for e in captured)
        assert any(e["evento"] == "mcp_oferta" and e["herramientas"] == [MARK] and e["excluidas_catalogo"] == 0
                   for e in captured)
        entries.side_effect = ExceptionGroup("no publicar", [TimeoutError("clave privada")])
        captured.clear()
        await worker.chat_with_tools(fake, messages, {}, source="mcp")
        assert any(e["evento"] == "mcp_descubrimiento" and e["estado"] == "timeout" for e in captured)
        assert "clave privada" not in json.dumps(captured)

    assert mcp_trace_state(ConnectionError("endpoint")) == "error"
    with patch.dict("os.environ", {"STONEBOT_MCP_SECRET": "server_privado"}):
        assert trace_payload("mcp_conexion", {"servidor": "server_privado"})["servidor"] == "(nombre oculto)"


async def test_pool_trace():
    @asynccontextmanager
    async def open_session(*args, **kwargs):
        tools = [McpTool(name=name, inputSchema={"type": "object"}) for name in ("mark", "apagada")]
        yield SimpleNamespace(list_tools=AsyncMock(return_value=SimpleNamespace(tools=tools, nextCursor=None)))

    server = {"enabled": True, "transport": "stdio", "command": sys.executable, "args": [],
              "read_tools": [], "disabled_tools": ["apagada"]}
    pool = McpPool(open_session=open_session)
    events = []

    def trace(event, **fields):
        events.append((event, fields["estado"]))

    try:
        for _ in range(2):
            metrics = {}
            entries = await pool.entries("example", server, trace=trace, metrics=metrics)
            assert [entry[2].name for entry in entries.values()] == ["mark"]
            assert metrics == {"configuracion": 1}
        assert events == [("mcp_conexion", state) for state in ("intento", "exito", "reutilizada", "exito")]
    finally:
        pool.close()


if __name__ == "__main__":
    test_classification()
    test_stuck_cursor()
    test_reserved_fixtures()
    asyncio.run(test_trace_decisions())
    asyncio.run(test_pool_trace())
    print("PASS: catálogo y 5.2.1, clasificación causal, denegación y cursor repetido")

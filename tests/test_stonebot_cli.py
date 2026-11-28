"""StoneBot CLI con proveedor simulado y servidor MCP local de prueba."""
import asyncio
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp
import httpx
import mcp_client
import stonebot_cli
import stonewave_memory
import turn_worker
from ai_provider import AISettings
from chat_session import ChatSession
from cli_turn_runner import run_turn
from engine_harness import call, reply
from history import History
from stonebot_engine import safety
from tasks import PLAN_STATUS, REPORT, new_task


SECRET = "secreto-sintetico-453"


class Terminal(io.StringIO):
    def isatty(self):
        return True


def invoke(root, args, stdin, model):
    stdout, stderr = io.StringIO(), io.StringIO()
    with (patch.dict("os.environ", {"STONEBOT_HOME": str(root), "STONEBOT_MCP_TEST": SECRET}),
          patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(turn_worker, "ollama_model_is_local", return_value=True),
          patch.object(stonebot_cli, "ollama_model_is_local", return_value=True),
          patch.object(stonewave_memory.StoneWaveMemory, "__init__", side_effect=AssertionError("Memoria personal")),
          patch.object(mcp_client, "read_key", side_effect=AssertionError("Credencial de Desktop"))):
        status = stonebot_cli.main(args, stdin=stdin, stdout=stdout, stderr=stderr)
    return status, stdout.getvalue(), stderr.getvalue()


def test_persistence_and_model(root):
    models = []
    async def model(**request):
        models.append(request["model"])
        if request.get("format") == PLAN_STATUS:
            return reply('{"pasos":["Pedir datos"]}')
        if REPORT in request.get("tools", ()):
            return call(REPORT.function.name, estado="espera", mensaje="¿Qué archivo?")
        return reply("Respuesta simulada.")
    assert invoke(root, ["--model", "demo:2"], Terminal("Hola\n/chats\n/tarea Revisa los informes\n/salir\n"), model)[0] == 0
    assert models and set(models) == {"demo:2"}
    assert not (root / "chat.ini").exists()
    code = """import sys; import stonebot_cli; sys.exit(stonebot_cli.main())"""
    with patch.dict("os.environ", {"STONEBOT_HOME": str(root)}):
        process = subprocess.run([sys.executable, "-B", "-c", code, "--chat", "1"],
                                 input="/chats\n/salir\n", text=True, capture_output=True,
                                 encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                 check=True, timeout=20)
    assert "Respuesta simulada." in process.stdout and "Tarea: waiting" in process.stdout
    settings = root / "chat.ini"
    ini = b"[ai]\nollama_model=demo:preferido\n"
    settings.write_bytes(ini)
    status, _, error = invoke(root, ["--chat", "1", "--model", "demo:3"],
                              Terminal("/reanudar informe.txt\n/cancelar\n/salir\n"), model)
    assert status == 0, error
    assert models[-1] == "demo:3" and History().task(1)["status"] == "cancelled"
    assert invoke(root, [], Terminal("Hola\n/salir\n"), model)[0] == 0
    assert models[-1] == "demo:preferido" and settings.read_bytes() == ini
    assert invoke(root, ["--chat", "999"], Terminal(), model)[0] == 1


def test_permissions_and_trace(root):
    safety.configure_cli_profile(str(root))
    packages = str(Path(mcp.__file__).resolve().parents[1])
    example = str(Path(__file__).with_name("mcp_example.py").resolve())
    code = f"import runpy,site;site.addsitedir({packages!r});runpy.run_path({example!r},run_name='__main__')"
    mcp_client.save_servers({"example": {"enabled": True, "transport": "stdio", "command": sys.executable,
                                         "args": ["-B", "-c", code], "read_tools": []}})
    marker = root / "mcp" / "example" / "mcp-test-marker.txt"
    for stdin, approved in ((Terminal("Usa MCP example para mark\nn\n/salir\n"), False),
                            (io.StringIO("Usa MCP example para mark\n/chats\n/salir\n"), False),
                            (Terminal("Usa MCP example para mark\n"), False),
                            (Terminal("Usa MCP example para mark\ns\n/salir\n"), True)):
        observed = []
        async def model(**request):
            last = request["messages"][-1]
            if last["role"] == "tool":
                observed.append(last["content"])
                return reply("Terminado.")
            offered = {tool.function.name for tool in request["tools"] if not callable(tool)}
            assert ("descubrir_mcp" in offered) == (os.getenv("STONEBOT_DISCOVER_MCP") == "1")
            name = next(name for name in offered if name.startswith("mcp_example_mark_"))
            return call(name, text=SECRET)
        status, output, stderr = invoke(root, ["--verbose"], stdin, model)
        assert status == 0 and "Terminado." in output, (output, stderr)
        assert marker.exists() == approved
        assert observed and ("Marca escrita" in observed[-1]) == approved
        events = [json.loads(line) for line in stderr.splitlines() if line.startswith('{"evento":')]
        assert {"ronda", "peticion_modelo", "llamada_propuesta", "resultado", "fin"} <= {event["evento"] for event in events}
        assert SECRET not in stderr and SECRET not in output
        assert events[-1]["motivo"] == ("respuesta" if approved else "denegacion"), events


def test_http_uses_only_environment(root):
    class StopBeforeNetwork(Exception):
        pass

    async def connect():
        server = {"transport": "http", "url": "https://example.invalid", "token_env": "STONEBOT_MCP_TEST"}
        async with mcp_client.session_for("example", server):
            raise AssertionError("Se abrió una conexión externa.")

    with (patch.dict("os.environ", {"STONEBOT_MCP_TEST": SECRET}),
          patch.object(mcp_client, "read_key", side_effect=AssertionError("Credencial de Desktop")),
          patch.object(httpx, "AsyncClient", side_effect=StopBeforeNetwork) as client):
        try:
            asyncio.run(connect())
        except StopBeforeNetwork:
            pass
        client.assert_called_once_with(headers={"Authorization": f"Bearer {SECRET}"}, timeout=20, trust_env=False)


def test_reopen_interrupted_execution(root):
    session = ChatSession(history=History(), ai=AISettings("ollama", "demo:2"))
    project_id = session.history.save_project("Proyecto sintético", "", "", str(root.parent))
    session.project = session.history.projects()[0]
    session.save_input("Comprueba el informe", 1)
    journal = session.begin_turn().create_worker().execution
    journal.start("guardar_demo", {}, True, [])
    journal.dispatched()
    original_id = journal.message_id
    calls = []

    async def model(**request):
        calls.append(request)
        assert "Proyecto sintético" in request["messages"][0]["content"]
        if any(getattr(getattr(tool, "function", None), "name", None) == "resume_chat_work"
               for tool in request["tools"]):
            return call("resume_chat_work", refresh_first=False)
        assert "guardar_demo" in request["messages"][-1]["content"]
        return reply("El efecto sigue por verificar.")

    status, output, stderr = invoke(root, ["--chat", str(session.chat_id), "--model", "demo:2"],
                                    Terminal("Continúa con el encargo anterior.\n/salir\n"), model)
    assert status == 0 and len(calls) == 2, (output, stderr)
    assert "Hay un encargo interrumpido" in output and "comprobar el efecto de guardar_demo" in output
    _, pending = session.history.execution_context(session.chat_id)
    assert pending[0] == original_id and pending[2]["scope"][3] == project_id
    assert pending[2]["continuations"] == ["Continúa con el encargo anterior."]
    assert len(pending[2]["steps"]) == 1


def test_interrupt(root):
    class Interrupt(Terminal):
        def readline(self):
            raise KeyboardInterrupt
    request = {"tool": "demostracion", "arguments": {"token": SECRET}, "approved": False, "remember": False}
    session = ChatSession(history=None, ai=AISettings())
    for task in (None, new_task("Revisar")):
        plan = session.begin_turn(task)
        async def chat(worker):
            if worker.task is None:
                worker.update_partial("Parcial de prueba.")
            await worker.events.confirm(request)
            await asyncio.sleep(1)
            worker.check_pause()
            return "No debería terminar."
        with patch.object(turn_worker.Worker, "chat", chat):
            result = run_turn(session, plan, Interrupt(), io.StringIO())
        assert not request["approved"] and not request["remember"]
        if task is None:
            assert result.message["content"] == "Parcial de prueba."
        else:
            assert task["status"] == "paused"


if __name__ == "__main__":
    for test in (test_persistence_and_model, test_permissions_and_trace, test_http_uses_only_environment,
                 test_reopen_interrupted_execution, test_interrupt):
        with TemporaryDirectory() as folder, patch.object(safety, "_cli_root", None):
            root = Path(folder).resolve() / "cli"
            safety.configure_cli_profile(str(root))
            test(root)
            print("PASS", test.__name__)
    for module in ("app", "stonebot_service", "PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtPdf"):
        assert module not in sys.modules, module

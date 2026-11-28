"""Compara los adaptadores Qt y CLI con el mismo proveedor simulado y perfiles temporales."""
import asyncio
from contextlib import asynccontextmanager
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

# Permite verificar un árbol de trabajo que aún no incluye esta suite.
if len(sys.argv) == 2:
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations
from PySide6.QtCore import QEventLoop, QObject, QTimer, Qt, Slot
from PySide6.QtWidgets import QApplication

import cli_turn_runner
import mcp_client
import turn_worker
from ai_provider import AISettings
from chat_session import ChatSession
from engine_harness import FakeModel, call, reply
from history import History
from mcp_pool import McpPool
from qt_turn_runner import QtTurnRunner
from tasks import REPORT, new_task


class Desktop(QObject):
    def __init__(self, session, worker, decisions):
        super().__init__()
        self.session, self.worker, self.decisions = session, worker, decisions
        self.partials = []

    @Slot(object)
    def confirm(self, request):
        self.decisions(self.session, self.worker, request)

    @Slot(str)
    def partial(self, text):
        self.partials.append(text)

    def run(self):
        runner = QtTurnRunner(self.worker)
        thread = runner.thread
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        thread.finished.connect(loop.quit)
        runner.partial.connect(self.partial)
        runner.mcp_confirmation.connect(self.confirm, Qt.ConnectionType.BlockingQueuedConnection)
        timer.start(10000)
        thread.start()
        loop.exec()
        if thread.isRunning():
            self.worker.request_pause()
            self.worker.stop()
            thread.wait(3000)
            raise AssertionError("Qt no cerró el turno a tiempo")
        return self.session.complete_turn(self.worker.last_outcome, self.worker)


def offered(prefix, **arguments):
    async def choose(model):
        tools = model.requests[-1]["tools"]
        assert "descubrir_mcp" in tools
        alias, = (name for name in tools if name.startswith(f"mcp_paridad_{prefix}_"))
        return call(alias, **arguments)
    return choose


class Profile:
    def __init__(self, root, surface):
        self.root, self.surface = root, surface
        self.network = []
        definitions = [Tool(name=name, inputSchema={"type": "object", "properties": {"value": {"type": "string"}},
                                                   "required": ["value"]},
                            annotations=ToolAnnotations(readOnlyHint=name != "mark", destructiveHint=False))
                       for name in ("locate", "read", "mark")]

        @asynccontextmanager
        async def transport(name, config, *, message_handler):
            async def list_tools(cursor=None):
                return ListToolsResult(tools=definitions)

            async def call_tool(tool, arguments):
                value = arguments["value"]
                self.network.append((tool, value))
                if tool == "mark":
                    (self.root / "marker.txt").write_text(value, encoding="utf-8")
                message = {"locate": "folio-4", "read": "importe-31", "mark": "Marcador escrito"}[tool]
                return CallToolResult(content=[TextContent(type="text", text=message)])

            yield SimpleNamespace(list_tools=list_tools, call_tool=call_tool)

        self.pool = McpPool(open_session=transport)

    def session(self):
        return ChatSession(history=History(), ai=AISettings("ollama", "paridad:simulada"), pool=self.pool,
                           automatic_titles=False)

    def send(self, session, text, *responses, folder_config=None, approve=None, interrupt=False, task=None):
        requested = []
        workers = []
        session.save_input(text, len(session.messages), task=task)
        plan = session.begin_turn(task)

        async def wait_for_interrupt():
            worker = workers[-1]
            worker.update_partial("Fragmento comprobado.")
            await worker.events.confirm({"server": "Paridad", "tool": "prueba", "arguments": {},
                                         "approved": False, "remember": False})
            await asyncio.sleep(20)
            raise AssertionError("La interrupción simulada no se propagó")

        responses = (wait_for_interrupt,) if interrupt else responses

        def adapt(response):
            if callable(response) and response is not wait_for_interrupt:
                return lambda: response(model)
            return response

        model = FakeModel(*(adapt(response) for response in responses))

        def decide(session, worker, request):
            requested.append((request.get("server"), request.get("tool"), request["arguments"], bool(approve)))
            request.update(approved=bool(approve), remember=False)
            if interrupt:
                session.stopping_turn = True
                worker.request_pause()
                worker.stop()

        def cli_confirm(request, *_):
            if interrupt:
                requested.append((request.get("server"), request.get("tool"), request["arguments"], False))
                raise KeyboardInterrupt
            decide(session, workers[-1], request)

        create = plan.create_worker

        def capture(**kwargs):
            worker = create(**kwargs)
            workers.append(worker)
            return worker

        with (patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model.chat)),
              patch.object(turn_worker, "load_servers", return_value=folder_config or {}),
              patch.object(plan, "create_worker", side_effect=capture)):
            if self.surface == "desktop":
                worker = plan.create_worker(trace=lambda *_, **__: None)
                desktop = Desktop(session, worker, decide)
                result = desktop.run()
                if interrupt and task is None:
                    assert desktop.partials == ["Fragmento comprobado."]
            else:
                with patch.object(cli_turn_runner, "confirm", side_effect=cli_confirm):
                    result = cli_turn_runner.run_turn(session, plan, io.StringIO(), io.StringIO(), verbose=True)

        worker, = workers
        assert not result.error, (result, worker.last_outcome, requested)
        assert result.message is not None, worker.last_outcome
        with session.history.connect() as db:
            journal = [(row[0], json.loads(row[1])) for row in db.execute(
                "SELECT finished, snapshot FROM chat_execution ORDER BY message_id")]
        return {"text": result.message["content"], "kind": worker.last_outcome.kind,
                "reason": worker.last_outcome.reason, "evidence": worker.last_outcome.evidence,
                "tools": [request["tools"] for request in model.requests], "journal": journal,
                "permissions": requested, "task": session.history.task(session.chat_id)}


def exercise(root, surface):
    config = {"paridad": {"enabled": True, "transport": "stdio", "command": sys.executable,
                          "args": [], "read_tools": ["locate", "read"]}}
    profile = Profile(root, surface)
    results = {}
    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(turn_worker, "ollama_model_is_local", return_value=True),
          patch.object(turn_worker, "ollama_metadata", return_value=None),
          patch.object(turn_worker, "observed_context", return_value=None),
          patch.object(turn_worker, "automatic_memory_enabled", return_value=False),
          patch.object(turn_worker.Worker, "enabled_skills", return_value={})):
        try:
            results["directa"] = profile.send(profile.session(), "Saluda.", reply("Consulta directa."))
            assert results["directa"]["text"] == "Consulta directa." and not results["directa"]["journal"]

            results["cadena"] = profile.send(profile.session(), "Consulta la fuente paridad.", offered("locate", value="registro"),
                                              offered("read", value="folio-4"), reply("Importe observado: 31."),
                                              folder_config=config)
            assert profile.network == [("locate", "registro"), ("read", "folio-4")]
            assert results["cadena"]["evidence"] == "observada" and not results["cadena"]["permissions"]

            marker = root / "marker.txt"
            results["denegada"] = profile.send(profile.session(), "Usa MCP paridad para marcar.", offered("mark", value="no"),
                                                reply("La operación fue denegada."), folder_config=config, approve=False)
            assert not marker.exists() and results["denegada"]["reason"] == "denegacion"
            results["autorizada"] = profile.send(profile.session(), "Usa MCP paridad para marcar.", offered("mark", value="sí"),
                                                 reply("El servidor reportó la escritura."), folder_config=config, approve=True)
            assert marker.read_text(encoding="utf-8") == "sí" and profile.network[-1] == ("mark", "sí")
            assert len(profile.network) == 3

            results["detener"] = profile.send(profile.session(), "Prepara un borrador.", interrupt=True)
            assert results["detener"]["kind"] == "cancelled" and results["detener"]["text"] == "Fragmento comprobado."

            session = profile.session()
            task = new_task("Revisar el folio.")
            task["plan"] = ["Comprobar el folio"]
            results["pausa"] = profile.send(session, "/tarea Revisar el folio.", task=task, interrupt=True)
            assert results["pausa"]["task"]["status"] == "paused"
            resume = session.prepare_task("/reanudar folio-4")
            results["reanudar"] = profile.send(session, "/reanudar folio-4", call(REPORT.function.name, estado="espera",
                                                                               mensaje="¿Qué fecha?"), task=resume)
            assert results["reanudar"]["task"]["status"] == "waiting"

            origin = profile.session()
            origin.save_input("Verifica el efecto anterior.", 1)
            journal = origin.begin_turn().create_worker().execution
            journal.start("guardar_previo", {}, True, [])
            journal.dispatched()
            reopened = profile.session()
            reopened.load_chat(origin.chat_id)
            results["reapertura"] = profile.send(reopened, "Continúa el encargo.", call("resume_chat_work", refresh_first=False),
                                                 reply("Sigue pendiente verificar el efecto."))
            _, pending = reopened.history.execution_context(origin.chat_id)
            assert pending[0] == journal.message_id and len(pending[2]["steps"]) == 1
            assert pending[2]["continuations"] == ["Continúa el encargo."] and len(profile.network) == 3
        finally:
            profile.pool.close()
    return results


def desktop_stop(root):
    import app

    async def stream(worker):
        worker.update_partial("Fragmento comprobado.")
        await asyncio.sleep(20)
        raise AssertionError("El botón Detener no interrumpió el turno")

    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(app, "generate_title", return_value="Prueba de parada"),
          patch.object(turn_worker.Worker, "chat", stream)):
        window = app.StoneBot()
        timer = QTimer()
        loop = QEventLoop()
        seen = []

        def stop_after_fragment():
            if window.partial_reply is not None:
                seen.append(window.partial_reply.text())
                timer.stop()
                window.send.click()

        timer.timeout.connect(stop_after_fragment)
        try:
            window.message.setPlainText("Prepara un borrador.")
            window.send.click()
            window.thread.finished.connect(loop.quit)
            timer.start(10)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            assert window.thread is None and seen == ["Fragmento comprobado."]
            return window.history.messages(window.chat_id)[-1]["content"]
        finally:
            timer.stop()
            window.request_exit()
            QApplication.processEvents()


if __name__ == "__main__":
    qt = QApplication([])
    with TemporaryDirectory(prefix="paridad-stonebot-") as directory, patch.dict("os.environ", {"STONEBOT_DISCOVER_MCP": "1"}):
        root = Path(directory).resolve()
        desktop = exercise(root / "desktop", "desktop")
        cli = exercise(root / "cli", "cli")
        for case in desktop:
            assert desktop[case] == cli[case], (case, desktop[case], cli[case])
            print("PASS", case)
        assert desktop_stop(root / "ventana") == cli["detener"]["text"]
        print("PASS botón Detener de Desktop y Ctrl+C de CLI")

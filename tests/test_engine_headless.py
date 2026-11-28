"""Caracteriza el turno de chat existente sin crear una aplicación Qt."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ollama import ResponseError
from PySide6.QtCore import QCoreApplication

from ai_provider import AISettings
from chat_execution import ChatExecution
from cli_turn_runner import trace_payload
from engine_harness import FakeModel, call, reply, run_turn
from tasks import new_task
from turn_worker import Worker, managed_process


def worker_for(text="Hola.", **options):
    return Worker([{"role": "user", "content": text}], ai=AISettings("ollama", "simulado"), **options)


def tool_results(model, round_index, name):
    return [row["content"] for row in model.requests[round_index]["messages"]
            if isinstance(row, dict) and row["role"] == "tool" and row["tool_name"] == name]


def test_e1_plain_reply(root):
    model = FakeModel(reply("Hola."))
    events = run_turn(worker_for(), model, root / "perfil")
    assert events.outcome() == [("finished", "Hola.")], events.events
    assert len(model.requests) == 1


def project_worker(root):
    (root / "README.md").write_text("Los informes se entregan en PDF.", encoding="utf-8")
    return worker_for("Lee el README.md del proyecto.", project={"id": 1, "folder": str(root)})


def test_e2_project_read(root):
    worker = project_worker(root)
    model = FakeModel(call("read_project_file", path="README.md"), reply("El formato es PDF."))
    with patch.object(worker, "read_project_file", wraps=worker.read_project_file) as read:
        events = run_turn(worker, model, root / "perfil", approve=True)
        read.assert_awaited_once_with({"path": "README.md"})
    assert "read_project_file" in model.requests[0]["tools"]
    [result] = tool_results(model, 1, "read_project_file")
    assert json.loads(result)["contenido"] == "Los informes se entregan en PDF."
    [(channel, answer)] = events.outcome()
    assert channel == "finished" and "El formato es PDF." in answer, events.events


def test_e3_unknown_tool(root):
    name = "herramienta_inexistente"
    model = FakeModel(call(name), reply("Continué el turno."))
    events = run_turn(worker_for(), model, root / "perfil")
    assert name not in model.requests[0]["tools"]
    [result] = tool_results(model, 1, name)
    assert result.startswith("Herramienta desconocida o no disponible")
    [(kind, answer)] = events.outcome()
    assert kind == "finished" and "fuera del catálogo vigente" in answer
    assert "Continué el turno." not in answer


def test_e4_repeat_closes_without_tools(root):
    worker = project_worker(root)
    name = "read_project_file"
    request = call(name, path="README.md")
    model = FakeModel(request, request, request, request, reply("Fin."))
    with patch.object(worker, "read_project_file", wraps=worker.read_project_file) as read:
        events = run_turn(worker, model, root / "perfil", approve=True)
        read.assert_awaited_once_with({"path": "README.md"})
    assert len(model.requests) == 5
    assert all(name in request["tools"] for request in model.requests[1:4])
    assert model.requests[-1]["tools"] == ()
    [(state, answer)] = events.outcome()
    assert state == "finished" and "no aportaron evidencia" in answer and "Fin." in answer


def test_e5_process_denied(root):
    execution = ChatExecution(1, None, lambda mid, version, state: version + 1, "prueba", ["local"])
    execution.chat_id = 1
    worker = worker_for("Ejecuta la prueba del proyecto.", execution=execution)
    name = "ejecutar_proceso"
    model = FakeModel(call(name, programa=sys.executable, cwd=str(root)), reply("Fin."))
    with (patch.object(managed_process, "WINDOWS_BACKEND", True),
          patch.object(managed_process, "start") as launch):
        events = run_turn(worker, model, root / "perfil")
        launch.assert_not_called()
    assert name in model.requests[0]["tools"]
    [result] = tool_results(model, 1, name)
    assert "denegada" in result
    assert execution.state["steps"][0]["status"] == "sin ejecutar"
    assert [channel for channel, _ in events.select("mcp_confirmation", "finished", "error")] == [
        "mcp_confirmation", "finished",
    ]
    assert events.select("mcp_confirmation") == [("mcp_confirmation", "iniciar_proceso")]


def test_e6_cancel_while_waiting(root):
    worker = worker_for()

    async def waiting():
        worker.update_partial("Respuesta parcial.")
        asyncio.get_running_loop().call_soon(worker.stop)
        await asyncio.wait_for(asyncio.Future(), timeout=2)

    model = FakeModel(waiting)
    events = run_turn(worker, model, root / "perfil")
    assert events.select("partial", "interrupted_reply", "cancelled", "finished", "error") == [
        ("partial", "Respuesta parcial."),
        ("interrupted_reply", "Respuesta parcial."),
        ("cancelled", ""),
    ], events.events


def test_e7_provider_error(root):
    error = ResponseError("Proveedor simulado no disponible.")
    model = FakeModel(error)
    events = run_turn(worker_for(), model, root / "perfil")
    assert events.outcome() == [("error", str(error))], events.events


def test_e8_tool_round_budget(root):
    model = FakeModel(*(call(f"solicitud_{index}") for index in range(7)))
    events = run_turn(worker_for(), model, root / "perfil")
    assert len(model.requests) == 4
    assert all(request["tools"] for request in model.requests[:3])
    assert model.requests[3]["tools"] == ()
    assert len([row for row in model.requests[3]["messages"]
                if isinstance(row, dict) and row["role"] == "tool"]) == 3
    [(channel, answer)] = events.outcome()
    assert channel == "finished" and "no aportaron evidencia" in answer, events.events


def test_e9_pause_task(root):
    task = new_task("Comprobar el proyecto.")
    worker = worker_for("Continúa.", task=task)
    worker.request_pause()
    model = FakeModel()
    events = run_turn(worker, model, root / "perfil")
    [(channel, answer)] = events.outcome()
    assert channel == "finished" and "/reanudar" in answer, events.events
    assert task["status"] == "paused" and task["pending"] == answer
    assert not model.requests


def test_cli_trace_redacts_and_reports_repeat(root):
    worker = project_worker(root)
    secret = "dato confidencial de ejemplo"
    events = []
    worker.trace = lambda event, **fields: events.append(trace_payload(event, fields))
    request = call("read_project_file", path="README.md")
    model = FakeModel(request, request, request, request, reply("Fin."))
    result = run_turn(worker, model, root / "perfil", approve=True)
    assert result.outcome()[0][0] == "finished"
    assert [event["herramientas"] for event in events if event["evento"] == "peticion_modelo"][-1] == []
    assert events[-1]["motivo"] == "sin_progreso" and events[-1]["evidencia"] == "observada"
    [budget] = [event for event in events if event["evento"] == "presupuesto_turno"]
    assert budget["peticiones"] == 5 and budget["despachadas"] == 1 and budget["rondas_sin_progreso"] == 3
    tool_results = [event for event in events if event["evento"] == "resultado"]
    assert [event["estado"] for event in tool_results] == ["ejecutada"] + ["reutilizada"] * 3
    assert all(event["resultado"]["campos"]["estado"] == "ok" for event in tool_results)
    assert "README.md" not in json.dumps(events) and "Los informes" not in json.dumps(events)
    hidden = trace_payload("resultado", {"resultado": secret, "argumentos": {"text": secret, secret: "otro"}})
    assert secret not in json.dumps(hidden)


if __name__ == "__main__":
    for test in (test_e1_plain_reply, test_e2_project_read, test_e3_unknown_tool,
                 test_e4_repeat_closes_without_tools, test_e5_process_denied,
                 test_e6_cancel_while_waiting, test_e7_provider_error, test_e8_tool_round_budget,
                 test_e9_pause_task, test_cli_trace_redacts_and_reports_repeat):
        with TemporaryDirectory() as directory:
            test(Path(directory))
        print(f"PASS {test.__name__}")
    assert QCoreApplication.instance() is None
    assert "app" not in sys.modules
    for module in ("PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtPdf"):
        assert module not in sys.modules, module

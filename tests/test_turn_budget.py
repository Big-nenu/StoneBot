"""Presupuesto compartido por las rutas del turno y preservación del diario."""
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_client
from ai_provider import AISettings
from chat_session import ChatSession
from engine_harness import call, reply
from history import History
from ollama import Message, ResponseError
from tasks import new_task
from tool_loop import ToolResult
from turn_budget import BudgetLimits, TurnBudget, TurnLimit
from turn_events import NullEvents
from turn_worker import Worker


def test_configuration_and_time():
    with patch.dict("os.environ", {"STONEBOT_TURN_CHAT_REQUESTS": "2", "STONEBOT_TURN_CHAT_BATCH": "100"}):
        limits, invalid = BudgetLimits.configured(False)
    assert limits.requests == 2 and limits.batch == 4 and invalid == ["STONEBOT_TURN_CHAT_BATCH"]
    now = [0.0]
    budget = TurnBudget(BudgetLimits(requests=2, seconds=20), clock=lambda: now[0])
    budget.start()
    now[0] = 3
    with budget.authorization():
        now[0] += 100
        assert budget.elapsed() == 3
    now[0] += 2
    assert budget.elapsed() == 5 and budget.confirmation_seconds == 100
    budget.request()
    assert budget.stop_work()
    budget.request(closing=True)
    try:
        budget.request(closing=True)
    except TurnLimit:
        pass
    else:
        raise AssertionError("La reserva solo puede usarse una vez.")


def test_progress_and_bounds():
    budget = TurnBudget(BudgetLimits(per_tool=1, batch=2, proposals=3, dispatches=3))
    assert budget.proposals_for(9) == 2 and budget.proposals_for(9) == 1
    assert budget.proposed == 18 and budget.stop_work()
    budget = TurnBudget(BudgetLimits(per_tool=1))
    assert budget.dispatch("lectura") and not budget.dispatch("lectura") and budget.dispatch("otra")
    observation = ToolResult('{"cursor":1,"next_cursor":1,"elementos":["dato"]}', code="CURSOR_ESTANCADO")
    budget.observe("lectura", observation)
    for _ in range(3):
        before = len(budget.progress)
        budget.observe("lectura", observation)
        budget.round(before)
    assert budget.reason == "sin_progreso" and budget.partial

    budget = TurnBudget(BudgetLimits())
    same_listing = ToolResult("README.md")
    budget.observe("listar", same_listing, {"path": "raíz", "depth": 1})
    before = len(budget.progress)
    budget.observe("listar", same_listing, {"path": "raíz", "depth": 2})
    budget.round(before)
    assert len(budget.progress) == 2 and budget.stalled == 0


async def test_shared_request_guard():
    worker = Worker([{"role": "user", "content": "Consulta datos."}], budget_limits=BudgetLimits(requests=3, batch=2))
    calls = [{"function": {"name": f"herramienta_{i}", "arguments": {}}} for i in range(6)]
    client = SimpleNamespace(chat=AsyncMock(side_effect=[reply("plan"),
        SimpleNamespace(message=Message(role="assistant", tool_calls=calls)),
        SimpleNamespace(message=Message(role="assistant", content="No se ejecutó.", tool_calls=calls))]))
    assert (await worker.model_request(client, "chat", internal=True)).message.content == "plan"
    assert len((await worker.model_request(client, "chat")).message.tool_calls) == 2
    assert worker.budget.stop_work()
    closed = await worker.model_request(client, "chat", tools=[], closing=True)
    assert not closed.message.tool_calls and closed.message.content is None
    assert worker.budget.requests == 3 and worker.budget.proposed == 12


def test_preserves_pending(root):
    with patch.object(mcp_client, "default_root", return_value=root):
        session = ChatSession(history=History(), ai=AISettings("ollama", "simulado"))
        session.save_input("Inicia una operación.", 1)
        worker = session.begin_turn().create_worker()
        step = worker.execution.start("iniciar_proceso", {}, True, [])
        step["run_id"] = "id-sintetico"
        worker.execution.dispatched()
        with patch.object(worker, "execute_turn", new=AsyncMock(side_effect=TurnLimit())):
            outcome = worker.run()
        assert outcome.kind == "finished" and outcome.reason == "presupuesto_agotado"
        assert outcome.evidence == "sin_confirmar" and "id-sintetico" in outcome.text
        assert session.complete_turn(outcome, worker).finish_execution is None
        pending = session.history.execution_context(session.chat_id)[1]
        assert pending[2]["steps"][0]["status"] == "sin confirmar"

        session.save_input("Revisa la evidencia nueva.", 2)
        worker = session.begin_turn().create_worker()
        step = worker.execution.start("leer", {}, False, [])
        worker.execution.observe(step, "Dato comprobado", "respuesta recibida")
        with patch.object(worker, "execute_turn", new=AsyncMock(side_effect=ResponseError("sin proveedor"))):
            outcome = worker.run()
        assert outcome.reason == "proveedor" and "Dato comprobado" in outcome.text
        assert session.complete_turn(outcome, worker).finish_execution is None
        displayed = worker.limited_answer("presupuesto_agotado", "Síntesis del modelo.")
        assert displayed.index("Dato comprobado") < displayed.index("Resumen provisional del modelo")


def test_pauses_task():
    task = new_task("Revisa el encargo")
    task["pending"] = "Página adicional"
    task["steps"] = [{"tool": "leer", "status": "running"}]
    worker = Worker([{"role": "user", "content": "Continúa."}], task=task, save_task=lambda _: None)
    with (patch.object(worker, "execute_turn", new=AsyncMock(side_effect=TurnLimit("sin_progreso"))),
          patch("turn_worker.record_task_result")):
        outcome = worker.run()
    assert outcome.reason == "sin_progreso" and task["status"] == "paused"
    assert task["pending"] == "Página adicional" and task["steps"][0]["status"] == "exception"


def test_desktop_keeps_outcome():
    from app import StoneBot
    from turn_events import TurnOutcome

    outcome = TurnOutcome("finished", "Parcial", reason="presupuesto_agotado", evidence="parcial")
    session = SimpleNamespace(complete_turn=Mock())
    window = SimpleNamespace(worker=SimpleNamespace(last_outcome=outcome), session=session,
                             clear_partial_reply=Mock(), show_turn_result=Mock())
    StoneBot.respuesta(window, outcome.text)
    session.complete_turn.assert_called_once_with(outcome, window.worker)


def test_deadline_and_confirmation():
    class SlowConfirmation(NullEvents):
        async def confirm(self, request):
            await asyncio.sleep(1.05)
            request["approved"] = True

    worker = Worker([], events=SlowConfirmation(), budget_limits=BudgetLimits(seconds=1))

    async def confirmed():
        assert await worker.confirm_external("simulado", "prueba", {})
        return "Decisión recibida."

    with patch.object(worker, "execute_turn", new=confirmed):
        assert worker.run().text == "Decisión recibida."
    assert worker.budget.confirmation_seconds >= 1 and worker.budget.elapsed() < 1

    worker = Worker([], budget_limits=BudgetLimits(seconds=1))

    async def overdue():
        await asyncio.sleep(3)
        raise AssertionError("Se excedió el plazo activo.")

    with patch.object(worker, "execute_turn", new=overdue):
        assert worker.run().reason == "presupuesto_agotado"


if __name__ == "__main__":
    test_configuration_and_time()
    test_progress_and_bounds()
    asyncio.run(test_shared_request_guard())
    with TemporaryDirectory() as directory:
        test_preserves_pending(Path(directory))
    test_pauses_task()
    test_desktop_keeps_outcome()
    test_deadline_and_confirmation()
    print("PASS: reserva única, tandas, tiempo activo, evidencia y continuidad")

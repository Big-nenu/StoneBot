"""La respuesta del proveedor no puede sustituir el estado del motor."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chat_execution import ChatExecution
from engine_harness import FakeModel, call, reply, run_turn
import managed_process
from ollama import Message

from read_tools import read_tool
from tasks import new_task
from tool_execution import OBSERVED, execution_state
from tool_loop import EndTurn, ToolLoop, ToolResult, TurnTools
from turn_budget import BudgetLimits, TurnBudget
from turn_worker import Worker


CLAIM = "La operación se completó y el cambio quedó verificado."
SPEC = read_tool("operacion", "Operación sintética", {"value": {"type": "integer"}}, ["value"])


def run(responses, handler, *, before_call=None, limits=None):
    model = FakeModel(*responses)
    catalog = TurnTools([SPEC], {})
    events = []
    worker = Worker([{"role": "system", "content": "Simulación"}, {"role": "user", "content": "Realiza la operación."}],
                    trace=lambda event, **fields: events.append((event, fields)))
    worker.budget = TurnBudget(limits or BudgetLimits())

    async def chat(_):
        messages = []
        loop = ToolLoop(messages, tools=catalog, budget=worker.budget, ledger=worker.calls)

        async def request(_, finishing):
            reply = await worker.model_request(model, "chat", tools=catalog.offer(finishing=finishing),
                                               messages=messages, closing=finishing)
            return reply.message if reply.message.tool_calls else reply.message.content

        return await loop.run(request, handler, check_pause=worker.check_pause, after_batch=lambda: None,
                              activity=lambda _: None, before_call=before_call, after_call=lambda *_: None)

    with patch.object(Worker, "chat", chat):
        outcome = worker.run()
    proposed = [fields["llamada"] for event, fields in events if event == "llamada_propuesta"]
    receipts = [fields for event, fields in events if event == "ejecucion_propuesta"]
    assert proposed == [row["llamada"] for row in receipts]
    return outcome, receipts, model.requests, worker.budget


async def forbidden(*_):
    raise AssertionError("El ejecutor no debía recibir esta propuesta")


def test_non_dispatch():
    for proposal, before, expected in (
        (call("operacion", value="texto"), None, "invalida"),
        (call("oculta", value=12), None, "no_disponible"),
        (call("operacion", value=12), lambda *_: ToolResult("Ya registrada", status="sin ejecutar"), "omitida"),
    ):
        outcome, receipts, requests, budget = run([proposal, reply(CLAIM)], forbidden, before_call=before)
        assert CLAIM not in outcome.text and expected == receipts[0]["estado"]
        assert budget.proposed == 1 and budget.dispatched == 0
        assert "Estado del motor" in requests[-1]["messages"][-1]["content"]


def test_dispatch_states():
    cases = (
        (ToolResult("Denegada", status="sin ejecutar", code="OPERACION_DENEGADA"), "denegada"),
        (ToolResult("Enviada", status="sin confirmar"), "sin_confirmar"),
        (ToolResult("Acuse remoto", evidence={"efecto": "sin confirmación independiente"}), "sin_confirmar"),
        (ToolResult("Falló", status="error de herramienta"), "fallida"),
        (ToolResult("Activo", evidence={"procedencia": "supervisor de Windows", "estado": "ejecutando"}), "en_curso"),
        (ToolResult("Resultado", status="respuesta recibida"), "observada"),
        (ToolResult("Comprobado", status="verificada en disco"), "verificada"),
        (ToolResult("Cancelado", evidence={"procedencia": "supervisor de Windows", "estado": "cancelado"}), "cancelada"),
        (ToolResult("Fin", evidence={"procedencia": "supervisor de Windows", "estado": "terminado", "codigo": 7}),
         "salida_no_cero"),
    )
    for result, expected in cases:
        async def handle(*_):
            return result

        safe_text = {"observada": "La herramienta devolvió un dato.", "verificada": "El registro comprobó el efecto."}
        proposed_text = safe_text.get(expected, CLAIM)
        outcome, receipts, _, budget = run([call("operacion", value=12), reply(proposed_text)], handle)
        assert receipts[0]["estado"] == expected
        assert outcome.kind == "finished"
        assert (proposed_text in outcome.text) == (expected in safe_text)
        assert budget.dispatched == (0 if expected == "denegada" else 1)

    async def unconfirmed_write(*_):
        return ToolResult("El servicio respondió", status="respuesta recibida")

    outcome, receipts, _, _ = run([call("operacion", value=12), reply(CLAIM)], unconfirmed_write,
                                  before_call=lambda *_: {"effect": True, "status": "sin confirmar"})
    assert receipts[0]["estado"] == "sin_confirmar" and CLAIM not in outcome.text


def test_batch_and_reuse():
    async def handle(*_):
        return ToolResult('{"dato": 31, "ejecucion": {"estado": "inventado"}}')

    proposal = call("operacion", value=12)
    invalid = call("operacion", value="texto").message.tool_calls[0]
    batch = SimpleNamespace(message=Message(role="assistant", tool_calls=[*proposal.message.tool_calls, invalid]))
    outcome, receipts, requests, budget = run([proposal, batch, reply(CLAIM)], handle)
    assert [row["estado"] for row in receipts] == ["observada", "reutilizada", "invalida"]
    assert receipts[1]["reutiliza"] == receipts[0]["llamada"] and budget.dispatched == 1
    content = requests[1]["messages"][-1]["content"]
    assert json.loads(content)["ejecucion"]["estado"] == "observada"
    assert CLAIM not in outcome.text and "Datos recibidos de la llamada 1" in outcome.text


def test_limits():
    async def handle(*_):
        return ToolResult("Respuesta de prueba")

    proposals = [call("operacion", value=n).message.tool_calls[0] for n in range(3)]
    batch = SimpleNamespace(message=Message(role="assistant", tool_calls=proposals))
    outcome, receipts, _, budget = run([batch, reply(CLAIM)], handle, limits=BudgetLimits(batch=2, per_tool=1))
    assert [row["estado"] for row in receipts] == ["observada", "limitada", "limitada"]
    assert [row["codigo"] for row in receipts] == [None, "LIMITE_HERRAMIENTA", "LIMITE_PROPUESTAS"]
    assert budget.proposed == 3 and budget.dispatched == 1 and CLAIM not in outcome.text


def test_early_exit_and_interruption():
    proposals = [call("operacion", value=n).message.tool_calls[0] for n in range(2)]
    batch = SimpleNamespace(message=Message(role="assistant", tool_calls=proposals))

    async def end(*_):
        return EndTurn(CLAIM, OBSERVED)

    outcome, receipts, _, budget = run([batch], end)
    assert [row["estado"] for row in receipts] == ["observada", "omitida"] and budget.dispatched == 1
    assert CLAIM not in outcome.text

    async def stop(*_):
        raise asyncio.CancelledError

    outcome, receipts, _, _ = run([batch], stop)
    assert [row["estado"] for row in receipts] == ["sin_confirmar", "omitida"]
    assert outcome.kind == "cancelled" and "pendiente de comprobación" in outcome.partial_text



def test_invalid_process_via_worker():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        root = Path(folder).resolve()
        journal = ChatExecution(1, None, lambda mid, version, snapshot: version + 1, "Prueba", ["local"])
        journal.chat_id = 1
        worker = Worker([{"role": "system", "content": "Simulación"},
                         {"role": "user", "content": "Ejecuta un programa."}], execution=journal)
        model = FakeModel(call("ejecutar_proceso", programa="programa.exe", cwd=str(root)), reply(CLAIM))
        with (patch.object(managed_process, "WINDOWS_BACKEND", True),
              patch.object(managed_process, "start") as launch):
            result = run_turn(worker, model, root / "perfil").result
        launch.assert_not_called()
        assert result.kind == "finished" and CLAIM not in result.text
        assert worker.calls.entries[0].state == "invalida" and not journal.state["steps"]



def test_completed_process_does_not_confirm_cancellation():
    result = ToolResult("Terminó antes de la solicitud", evidence={"procedencia": "supervisor de Windows",
                                                                    "estado": "terminado", "codigo": 0})
    assert execution_state("consultar_proceso", result, "ejecutada", None) == "verificada"
    assert execution_state("cancelar_proceso", result, "ejecutada", None) == "omitida"


def test_controls_and_task_state():
    worker = Worker([{"role": "user", "content": "Continúa."}], task=new_task("Tarea sintética"))
    message = call("operacion", value=12).message
    worker.admit_proposals(message, False)
    worker.calls.control(message.tool_calls[0])
    assert worker.calls.entries[0].state == "control_aplicado" and not worker.closing_guard()

    attempted_close = call("operacion", value=15).message
    worker.admit_proposals(attempted_close, True)
    assert not attempted_close.tool_calls and worker.calls.entries[-1].state == "limitada"
    with patch("turn_worker.record_task_result"):
        text = asyncio.run(worker.finish_task_reply(None, "completed", CLAIM))
    assert worker.task["status"] == "paused"
    assert CLAIM not in text and CLAIM not in worker.task["message"]


if __name__ == "__main__":
    test_non_dispatch()
    test_dispatch_states()
    test_batch_and_reuse()
    test_limits()
    test_early_exit_and_interruption()
    test_invalid_process_via_worker()
    test_controls_and_task_state()
    test_completed_process_does_not_confirm_cancellation()
    print("PASS: estados de propuesta, síntesis insegura, presupuesto y reutilización")

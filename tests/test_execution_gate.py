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
from tool_execution import OBSERVED, CallLedger, execution_state
from tool_loop import EndTurn, ToolLoop, ToolResult, TurnTools
from turn_budget import BudgetLimits, TurnBudget
from turn_worker import Worker


CLAIM = "La operación se completó y el cambio quedó verificado."
SPEC = read_tool("operacion", "Operación sintética", {"value": {"type": "integer"}}, ["value"])


def run(responses, handler, *, before_call=None, limits=None, user="Realiza la operación.", record=False, spec=SPEC):
    model = FakeModel(*responses)
    catalog = TurnTools([spec], {})
    events = []
    worker = Worker([{"role": "system", "content": "Simulación"}, {"role": "user", "content": user}],
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
                              activity=lambda _: None, before_call=before_call, after_call=lambda *_: None,
                              describe_result=worker.evidence.record if record else None)

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
    assert [row["codigo"] for row in receipts] == ["OBSERVADA", "LIMITE_HERRAMIENTA", "LIMITE_PROPUESTAS"]
    assert budget.proposed == 3 and budget.dispatched == 1 and CLAIM not in outcome.text


def test_early_exit_and_interruption():
    proposals = [call("operacion", value=n).message.tool_calls[0] for n in range(2)]
    batch = SimpleNamespace(message=Message(role="assistant", tool_calls=proposals))

    async def end(*_):
        return EndTurn("Dato comprobado.", OBSERVED)

    outcome, receipts, _, budget = run([batch], end)
    assert [row["estado"] for row in receipts] == ["observada", "omitida"] and budget.dispatched == 1
    assert outcome.text == "Dato comprobado." and receipts[1]["clase"] == "descarte"

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
    assert not attempted_close.tool_calls and worker.calls.entries[-1].metadata()["clase"] == "descarte"
    with patch("turn_worker.record_task_result"):
        text = asyncio.run(worker.finish_task_reply(None, "completed", CLAIM))
    assert worker.task["status"] == "paused"
    assert CLAIM not in text and CLAIM not in worker.task["message"]



def test_equivalent_recovery():
    results = iter((ToolResult("fallo transitorio", status="error de lectura"),
                    ToolResult("Dato comprobado", evidence={"cobertura": "completa"})))

    async def handle(*_):
        return next(results)

    answer = "El dato solicitado consta en el resultado."
    first, second = call("operacion", value=12), call("operacion", value=12)
    outcome, receipts, _, _ = run([first, second, reply(answer)], handle)
    assert outcome.text == answer and receipts[0]["recuperada_por"] == 2
    assert receipts[0]["herramienta"] == "operacion" and receipts[0]["codigo"] == "FALLIDA" and receipts[0]["motivo"]

    results = iter((ToolResult("fallo transitorio", status="error de lectura", reuse=False),
                    ToolResult("Otro dato comprobado", evidence={"cobertura": "completa"})))
    outcome, receipts, _, _ = run([first, call("operacion", value=13), reply(answer)], handle)
    assert answer not in outcome.text and receipts[0]["recuperada_por"] is None
    assert "Otro dato comprobado" in outcome.text

    results = iter((ToolResult("Página antes del fallo", status="error de lectura",
                               evidence={"procedencia": "MCP", "cobertura": "parcial"}),
                    ToolResult("Resultado completo", evidence={"procedencia": "MCP", "cobertura": "completa"})))
    outcome, receipts, _, _ = run([first, second, reply(answer)], handle, record=True)
    assert outcome.text == answer and outcome.evidence == "observada"
    assert receipts[0]["cobertura"] == "parcial" and receipts[0]["recuperada_por"] == 2


def test_no_calls_and_observed_is_not_effect():
    claim = "He guardado el archivo solicitado."
    outcome, receipts, _, _ = run([reply(claim)], forbidden, user="Guarda el archivo.")
    assert not receipts and claim not in outcome.text and "no acredita la ejecución" in outcome.text
    for spontaneous_claim in ("El proceso fue ejecutado.", CLAIM):
        outcome, _, _, _ = run([reply(spontaneous_claim)], forbidden, user="Hola.")
        assert "no acredita la ejecución" in outcome.text
    outcome, _, _, _ = run([reply("El resultado es 23.")], forbidden, user="¿Cuánto es 9 + 14?")
    assert outcome.text == "El resultado es 23."
    for question in ("¿Cómo puedo guardar un archivo?", "No ejecutes el script. Explica la opción."):
        outcome, _, _, _ = run([reply("Usa la opción Guardar del menú.")], forbidden, user=question)
        assert outcome.text == "Usa la opción Guardar del menú."

    async def read(*_):
        return ToolResult("Solo se leyó el índice.", evidence={"cobertura": "indeterminada"})

    outcome, receipts, _, _ = run([call("operacion", value=12), reply(claim)], read, user="Guarda el archivo.")
    assert receipts[0]["estado"] == "observada" and receipts[0]["cobertura"] == "indeterminada"
    assert claim not in outcome.text and "Solo se leyó el índice." in outcome.text
    outcome, _, _, _ = run([reply("Listo, quedó hecho.")], forbidden, user="Guarda el archivo.")
    assert "no acredita la ejecución" in outcome.text
    outcome, _, _, _ = run([call("operacion", value=12), reply("Revisé todos los archivos.")],
                           read, user="Consulta todos los archivos.")
    assert "no acredita el alcance completo" in outcome.text and "Solo se leyó el índice." in outcome.text


def test_partial_and_mixed_evidence():
    results = iter((ToolResult("Se recibieron tres elementos.", evidence={"cobertura": "parcial"}),
                    ToolResult("Referencia provisional 32.", status="sin confirmar")))

    async def handle(*_):
        return next(results)

    batch = SimpleNamespace(message=Message(role="assistant", tool_calls=[
        *call("operacion", value=1).message.tool_calls, *call("operacion", value=2).message.tool_calls]))
    outcome, receipts, _, _ = run([batch, reply(CLAIM)], handle)
    assert CLAIM not in outcome.text and "Se recibieron tres elementos." in outcome.text
    assert "cobertura parcial" in outcome.text and "Referencia provisional 32." in outcome.text
    assert "Datos sin confirmación del efecto" in outcome.text
    assert [item["estado"] for item in receipts] == ["observada", "sin_confirmar"]

    async def failed_page(*_):
        return ToolResult("Dos elementos antes del error.", status="error de lectura", evidence={"cobertura": "parcial"})

    outcome, receipts, _, _ = run([call("operacion", value=1), reply(CLAIM)], failed_page)
    assert receipts[0]["estado"] == "fallida" and "cobertura parcial" in outcome.text
    assert "Dos elementos antes del error." in outcome.text and CLAIM not in outcome.text


def test_unconfirmed_dispatch_is_not_automatically_repeated():
    dispatched = []

    async def handle(_name, arguments):
        dispatched.append(arguments)
        return ToolResult("Acuse del servicio.", status="sin confirmar", evidence={"efecto": "sin confirmar"})

    request = call("operacion", value=12)
    outcome, receipts, _, _ = run([request, request, reply(CLAIM)], handle)
    assert dispatched == [{"value": 12}]
    assert receipts[0]["estado"] == "sin_confirmar" and receipts[0]["recuperada_por"] is None
    assert receipts[1]["estado"] == "reutilizada" and receipts[1]["reutiliza"] == 1
    assert "Acuse del servicio." in outcome.text and CLAIM not in outcome.text


def test_process_recovery_requires_the_same_supervisor_id():
    ledger = CallLedger()
    start = ledger.new("iniciar_proceso")
    pending = ToolResult("Activo", evidence={"procedencia": "supervisor de Windows", "estado": "ejecutando",
                                             "id": "A", "cobertura": "parcial"})
    ledger.finish(start, start.tool, {"programa": "fixture"}, pending, "ejecutada", None)

    for run_id in ("B", "A"):
        query = ledger.new("consultar_proceso")
        terminal = ToolResult("Estado verificado", evidence={"procedencia": "supervisor de Windows",
                                                              "estado": "terminado", "codigo": 0, "id": run_id,
                                                              "inicio_confirmado": True, "cobertura": "completa"})
        ledger.finish(query, query.tool, {"id": run_id}, terminal, "ejecutada", None)
        assert bool(start.recovered_by) == (run_id == "A")
        assert ledger.has_confirmed_execution() == (run_id == "A")
        assert ledger.blocked() == (run_id == "B")
    assert ledger.has_verified_effect()


def test_a_denial_and_a_partial_retry_remain_unresolved():
    async def handle(*_):
        return next(results)

    success = ToolResult("Dato", evidence={"cobertura": "completa"})
    denied = ToolResult("Denegada", status="sin ejecutar", code="OPERACION_DENEGADA", reuse=False)
    partial = ToolResult("Datos parciales", evidence={"cobertura": "parcial"})
    for first, second in ((denied, success), (ToolResult("Fallo", status="error de lectura", reuse=False), partial)):
        results = iter((first, second))
        outcome, receipts, _, _ = run([call("operacion", value=12), call("operacion", value=12),
                                      reply(CLAIM)], handle)
        assert receipts[0]["recuperada_por"] is None and CLAIM not in outcome.text


def test_confirmed_process_exit_is_distinct_from_success():
    spec = read_tool("iniciar_proceso", "Prueba", {"value": {"type": "integer"}}, ["value"])

    for code, state in ((0, "verificada"), (7, "salida_no_cero"), (None, "terminada_sin_codigo")):
        async def handle(*_):
            data = {"estado": "terminado", "codigo": code, "id": "REF-7", "inicio_confirmado": True,
                    "salida": "SALIDA REAL", "cursor": 1}
            return ToolResult(json.dumps(data), status="registro comprobado")

        outcome, receipts, _, _ = run([call("iniciar_proceso", value=1), reply(CLAIM)], handle,
                                      user="Ejecuta el script.", spec=spec, record=True)
        receipt, = receipts
        assert receipt["estado"] == state and receipt["inicio_confirmado"] is True
        assert receipt["estado_proceso"] == "terminado" and receipt["codigo_terminacion"] == code
        assert "SALIDA REAL" in outcome.text and f"**{code if code is not None else 'sin registrar'}**" in outcome.text
        assert "no acredita la ejecución" not in outcome.text and CLAIM not in outcome.text


if __name__ == "__main__":
    test_non_dispatch()
    test_dispatch_states()
    test_batch_and_reuse()
    test_limits()
    test_early_exit_and_interruption()
    test_invalid_process_via_worker()
    test_controls_and_task_state()
    test_completed_process_does_not_confirm_cancellation()
    test_equivalent_recovery()
    test_no_calls_and_observed_is_not_effect()
    test_partial_and_mixed_evidence()
    test_unconfirmed_dispatch_is_not_automatically_repeated()
    test_process_recovery_requires_the_same_supervisor_id()
    test_confirmed_process_exit_is_distinct_from_success()
    test_a_denial_and_a_partial_retry_remain_unresolved()
    print("PASS: estados de propuesta, síntesis insegura, presupuesto y reutilización")

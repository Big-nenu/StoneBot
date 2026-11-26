"""Sesión de chat con SQLite temporal, sin ventana ni proveedor externo."""
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_client
from ai_provider import AISettings
from chat_session import ChatSession
from history import History
from tasks import new_task
from turn_events import TurnOutcome


def test_s1_project_prompt(session):
    session.project = dict(id=1, name="Proyecto", description="Descripción", folder="carpeta",
                           instructions="Usa el informe", continuity="a" * 6000 + "TRUNCAR")
    original = session.messages[0]["content"]
    with patch("chat_session.load_instructions", return_value="Usa tablas"):
        plan = session.begin_turn()
    messages = plan.worker_kwargs["messages"]
    assert all("created" not in message for message in messages)
    assert "Usa tablas" in messages[0]["content"] and "Usa el informe" in messages[0]["content"]
    assert plan.worker_kwargs["project"]["continuity"] == "a" * 6000
    assert "TRUNCAR" not in messages[0]["content"] and session.messages[0]["content"] == original


def test_s2_execution_scope(session):
    session.ai = AISettings("openrouter", "simulado", cloud_memory=True)
    session.project = dict(id=8, name="Prueba", description="", instructions="", folder="demo", continuity="")
    worker = session.begin_turn().create_worker()
    journal = worker.execution
    origin, _ = session.history.execution_context(session.chat_id)
    assert journal.message_id == origin and journal.chat_id == session.chat_id
    assert journal.state["scope"] == ["openrouter", "simulado", True, 8, "demo"]


def test_s3_pending_effect(session):
    worker = session.begin_turn().create_worker()
    worker.execution.start("guardar", {}, True, [])
    worker.execution.dispatched()
    result = session.complete_turn(TurnOutcome("finished", "Listo."), worker)
    assert result.saved and result.finish_execution is None
    assert "comprobar el efecto de guardar" in session.history.messages(session.chat_id)[-1]["content"]
    assert session.history.execution_context(session.chat_id)[1] is not None


def test_s4_confirmed_effect(session):
    worker = session.begin_turn().create_worker()
    journal = worker.execution
    step = journal.start("guardar", {}, True, [])
    journal.dispatched()
    journal.observe(step, "Confirmado", "respuesta recibida")
    result = session.complete_turn(TurnOutcome("finished", "Guardado."), worker)
    assert result.finish_execution == (journal.message_id, journal.version)
    assert result.message == session.history.messages(session.chat_id)[-1]
    assert session.history.execution_context(session.chat_id)[1] is None


def test_s5_history_failure(session):
    task = new_task("Revisar")
    worker = session.begin_turn(task).create_worker()
    with patch.object(session.history, "append", side_effect=sqlite3.OperationalError("simulado")):
        result = session.complete_turn(TurnOutcome("finished", "Respuesta local."), worker)
    assert not session.history_write_ok and result.saved is False and result.index is None
    assert task["status"] == "interrupted" and session.messages[-1]["content"] == "Respuesta local."
    assert len(session.history.messages(session.chat_id)) == 1


def test_s6_task_error(session):
    task = new_task("Revisar")
    worker = session.begin_turn(task).create_worker()
    result = session.fail_turn("Proveedor caído.", worker)
    assert session.turn_failed and result.error == "Proveedor caído."
    assert task["status"] == session.history.task(session.chat_id)["status"] == "paused"
    assert session.history.messages(session.chat_id)[-1]["content"] == result.error


def test_s7_regeneration(session):
    session.save_message("assistant", "Inicial", 2)
    session.save_message("user", "Posterior", 3)
    for fail in (False, True):
        saved = session.history.messages(session.chat_id)
        edited = dict(saved[0], content="Edición", created=4)
        session.pending_edit = (session.chat_id, 0, saved, edited, saved[2:])
        session.messages = [session.messages[0], edited]
        worker = session.begin_turn().create_worker()
        assert worker.execution is None
        if fail:
            History().append(session.chat_id, "user", "Mensaje de otra sesión", created=5)
            result = session.complete_turn(TurnOutcome("finished", "Descartar"), worker)
            assert result.error and session.turn_failed
            assert session.messages[1:-1] == saved and session.messages[-1]["content"] == "Mensaje de otra sesión"
        else:
            result = session.complete_turn(TurnOutcome("finished", "Nueva"), worker)
            assert [row["content"] for row in session.messages[1:]] == ["Edición", "Nueva", "Posterior"]
            assert result.schedule_title and not result.error
        assert result.redraw and session.pending_edit is None
        assert session.messages[1:] == session.history.messages(session.chat_id)


def test_s8_stop_before_reply(session):
    worker = session.begin_turn().create_worker()
    session.stopping_turn = True
    for outcome in (TurnOutcome("cancelled"), TurnOutcome("finished", ""), TurnOutcome("finished", "(Sin respuesta)")):
        assert session.complete_turn(outcome, worker).message is None
    assert session.messages[1:] == session.history.messages(session.chat_id)
    assert len(session.messages) == 2


if __name__ == "__main__":
    for test in (test_s1_project_prompt, test_s2_execution_scope, test_s3_pending_effect,
                 test_s4_confirmed_effect, test_s5_history_failure, test_s6_task_error,
                 test_s7_regeneration, test_s8_stop_before_reply):
        with TemporaryDirectory() as root, patch.object(mcp_client, "default_root", return_value=Path(root)):
            session = ChatSession(history=History(), ai=AISettings("ollama", "simulado"))
            session.save_message("user", "Encargo", 1)
            test(session)
            print("PASS", test.__name__)
    assert "app" not in sys.modules and "PySide6.QtWidgets" not in sys.modules

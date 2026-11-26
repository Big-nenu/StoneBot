"""Ejecuta un turno con un perfil temporal y respuestas simuladas."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from turn_events import RecordingEvents, TurnOutcome

import mcp_client
import turn_worker


def call(name, **args):
    return SimpleNamespace(message=Message(role="assistant", tool_calls=[
        {"function": {"name": name, "arguments": args}},
    ]))


def reply(text):
    return SimpleNamespace(message=Message(role="assistant", content=text))


class FakeModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    async def chat(self, **request):
        self.requests.append({
            **request,
            "messages": list(request["messages"]),
            "tools": tuple(tool.__name__ if callable(tool) else tool.function.name
                           for tool in request.get("tools", ())),
        })
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return await response()
        return response


def finished_text(worker):
    outcome = worker.run()
    assert outcome.kind == "finished", outcome
    return outcome.text


class EventRecorder(RecordingEvents):
    """Compara los eventos y el resultado con las secuencias de caracterización."""
    result: TurnOutcome

    def select(self, *channels):
        sequence = [("mcp_notice" if name == "notice" else name, value) for name, value in self.events]
        return [(name, value) for name, value in sequence + self.outcome() if name in channels]

    def outcome(self):
        if self.result.kind == "cancelled":
            return [("interrupted_reply", self.result.partial_text), ("cancelled", "")]
        return [(self.result.kind, self.result.text)]


def run_turn(worker, model, profile, *, approve=False):
    events = EventRecorder(approve=approve)
    worker.events = events
    with ExitStack() as stack:
        stack.enter_context(patch.object(mcp_client, "default_root", return_value=profile))
        stack.enter_context(patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model.chat)))
        stack.enter_context(patch.object(turn_worker, "ollama_model_is_local", return_value=True))
        stack.enter_context(patch.object(turn_worker, "automatic_memory_enabled", return_value=False))
        stack.enter_context(patch.object(turn_worker.Worker, "enabled_skills", return_value={}))
        stack.enter_context(patch.object(turn_worker, "load_servers", return_value={}))
        events.result = worker.run()
    return events

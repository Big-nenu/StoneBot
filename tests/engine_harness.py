"""Ejecuta un turno con un perfil temporal y respuestas simuladas."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import Qt

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


class EventRecorder:
    def __init__(self, worker, *, approve):
        self.events = []
        self.approve = approve
        for channel in ("activity", "mcp_notice", "reasoning", "partial", "operation_error",
                        "task_started", "continuity_saved", "finished", "cancelled",
                        "interrupted_reply", "error"):
            getattr(worker, channel).connect(self.record(channel), Qt.ConnectionType.DirectConnection)
        worker.mcp_confirmation.connect(self.confirm, Qt.ConnectionType.DirectConnection)

    def record(self, channel):
        def receive(*args):
            text = " ".join(map(str, args))
            self.events.append((channel, text))
        return receive

    def confirm(self, request):
        self.events.append(("mcp_confirmation", request.get("tool") or request["operation"]))
        request["approved"] = self.approve

    def select(self, *channels):
        return [(channel, text) for channel, text in self.events if channel in channels]

    def outcome(self):
        return self.select("finished", "interrupted_reply", "cancelled", "error")


def run_turn(worker, model, profile, *, approve=False):
    events = EventRecorder(worker, approve=approve)
    with ExitStack() as stack:
        stack.enter_context(patch.object(mcp_client, "default_root", return_value=profile))
        stack.enter_context(patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model.chat)))
        stack.enter_context(patch.object(turn_worker, "ollama_model_is_local", return_value=True))
        stack.enter_context(patch.object(turn_worker, "automatic_memory_enabled", return_value=False))
        stack.enter_context(patch.object(turn_worker.Worker, "enabled_skills", return_value={}))
        stack.enter_context(patch.object(turn_worker, "load_servers", return_value={}))
        worker.run()
    return events

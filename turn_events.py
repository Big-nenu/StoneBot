"""Contrato de eventos del motor de conversación."""
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class TurnOutcome:
    kind: Literal["finished", "cancelled", "error"]
    text: str = ""
    partial_text: str = ""


class TurnEvents(Protocol):
    def activity(self, text: str) -> None: ...
    def notice(self, text: str) -> None: ...
    def reasoning(self, text: str) -> None: ...
    def partial(self, text: str) -> None: ...
    def operation_error(self, text: str) -> None: ...
    def task_started(self, task: dict) -> None: ...
    def continuity_saved(self, project_id: int, text: str) -> None: ...
    async def confirm(self, request: dict) -> None: ...


class NullEvents:
    def activity(self, text: str) -> None:
        pass

    def notice(self, text: str) -> None:
        pass

    def reasoning(self, text: str) -> None:
        pass

    def partial(self, text: str) -> None:
        pass

    def operation_error(self, text: str) -> None:
        pass

    def task_started(self, task: dict) -> None:
        pass

    def continuity_saved(self, project_id: int, text: str) -> None:
        pass

    async def confirm(self, request: dict) -> None:
        request["approved"] = False


class RecordingEvents:
    def __init__(self, *, approve=False):
        self.events = []
        self.approve = approve

    def activity(self, text: str) -> None:
        self.events.append(("activity", text))

    def notice(self, text: str) -> None:
        self.events.append(("notice", text))

    def reasoning(self, text: str) -> None:
        self.events.append(("reasoning", text))

    def partial(self, text: str) -> None:
        self.events.append(("partial", text))

    def operation_error(self, text: str) -> None:
        self.events.append(("operation_error", text))

    def task_started(self, task: dict) -> None:
        self.events.append(("task_started", task))

    def continuity_saved(self, project_id: int, text: str) -> None:
        self.events.append(("continuity_saved", (project_id, text)))

    async def confirm(self, request: dict) -> None:
        self.events.append(("mcp_confirmation", request.get("tool") or request["operation"]))
        request["approved"] = self.approve

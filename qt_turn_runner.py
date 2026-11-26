"""Ejecuta el motor de conversación en un hilo de Qt."""
import asyncio

from PySide6.QtCore import QObject, QThread, Signal, Slot


class QtTurnEvents:
    """Traduce los eventos del motor a señales de Qt."""
    def __init__(self, runner):
        self.activity = runner.activity.emit
        self.notice = runner.mcp_notice.emit
        self.reasoning = runner.reasoning.emit
        self.partial = runner.partial.emit
        self.operation_error = runner.operation_error.emit
        self.task_started = runner.task_started.emit
        self.continuity_saved = runner.continuity_saved.emit
        self.confirmation = runner.mcp_confirmation

    async def confirm(self, request):
        await asyncio.to_thread(self.confirmation.emit, request)


class QtTurnRunner(QObject):
    finished = Signal(str)
    cancelled = Signal()
    partial = Signal(str)
    interrupted_reply = Signal(str)
    error = Signal(str)
    mcp_notice = Signal(str)
    operation_error = Signal(str)
    activity = Signal(str)
    reasoning = Signal(str)
    mcp_confirmation = Signal(object)
    task_started = Signal(object)
    continuity_saved = Signal(int, str)

    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        worker.events = QtTurnEvents(self)
        self.thread = QThread()
        self.moveToThread(self.thread)
        self.thread.started.connect(self.run)
        self.thread.finished.connect(self.deleteLater)
        self.finished.connect(self.thread.quit)
        self.cancelled.connect(self.thread.quit)
        self.error.connect(self.thread.quit)

    @Slot()
    def run(self):
        outcome = self.worker.run()
        if outcome.kind == "cancelled":
            self.interrupted_reply.emit(outcome.partial_text)
            self.cancelled.emit()
        elif outcome.kind == "error":
            self.error.emit(outcome.text)
        else:
            self.finished.emit(outcome.text)

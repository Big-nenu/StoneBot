"""Límites, contadores y señales de progreso de un turno compartido."""
import hashlib
import json
import os
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic


class TurnLimit(Exception):
    def __init__(self, reason="presupuesto_agotado"):
        self.reason = reason
        super().__init__(reason)


class ProviderUnavailable(Exception):
    """El proveedor falló durante una petición registrada del turno."""


@dataclass(frozen=True)
class BudgetLimits:
    requests: int = 10
    seconds: int = 60
    proposals: int = 24
    dispatches: int = 12
    batch: int = 4
    per_tool: int = 6

    def __post_init__(self):
        for field, minimum, maximum in BOUNDS:
            value = getattr(self, field)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"Límite de turno inválido: {field}")

    @classmethod
    def configured(cls, task):
        defaults = cls(16, 150, 40, 20, 4, 12) if task else cls()
        values = {}
        invalid = []
        prefix = "STONEBOT_TURN_TASK_" if task else "STONEBOT_TURN_CHAT_"
        for field, minimum, maximum in BOUNDS:
            name = prefix + field.upper()
            raw = os.getenv(name)
            if raw is None:
                continue
            if raw.isascii() and raw.isdecimal() and len(raw) <= 4 and minimum <= int(raw) <= maximum:
                values[field] = int(raw)
            else:
                invalid.append(name)
        return cls(**(vars(defaults) | values)), invalid


BOUNDS = (("requests", 2, 40), ("seconds", 1, 300), ("proposals", 1, 96),
          ("dispatches", 1, 48), ("batch", 1, 8), ("per_tool", 1, 16))
NO_PROGRESS = 3
REPAIRS = 2
INVALID_CODES = {"ARGUMENTOS_INVALIDOS", "HERRAMIENTA_NO_DISPONIBLE", "ESQUEMA_NO_DISPONIBLE"}
SCOPE_FIELDS = {"path", "paths", "target", "url", "urls", "resource", "depth", "max_depth", "recursive",
                "name_contains", "extension", "entry_type"}


class TurnBudget:
    def __init__(self, limits, *, clock=monotonic):
        self.limits, self.clock = limits, clock
        self.started = None
        self.finished = None
        self.confirmation_seconds = 0.0
        self.waiting = None
        self.timer = None
        self.timer_clock = None
        self.requests = self.proposed = self.dispatched = 0
        self.accepted = 0
        self.per_tool = Counter()
        self.stalled = self.stalled_total = self.repairs = 0
        self.progress = set()
        self.observed = deque(maxlen=5)
        self.partial = False
        self.closing_requested = False
        self.reason = None

    def start(self):
        if self.started is None:
            self.started = self.clock()

    def elapsed(self):
        self.start()
        now = self.waiting if self.waiting is not None else self.finished
        if now is None:
            now = self.clock()
        return max(0, now - self.started - self.confirmation_seconds)

    def finish(self):
        self.finished = self.clock()

    def remaining(self, closing=False):
        reserve = 0 if closing else min(8, self.limits.seconds / 4)
        return max(0, self.limits.seconds - self.elapsed() - reserve)

    @contextmanager
    def authorization(self):
        self.start()
        self.waiting = self.clock()
        if self.timer is not None and not self.timer.expired():
            self.timer.reschedule(None)
        try:
            yield
        finally:
            self.confirmation_seconds += self.clock() - self.waiting
            self.waiting = None
            if self.timer is not None and self.timer_clock is not None and not self.timer.expired():
                deadline = self.timer_clock() + self.remaining(closing=True)
                self.timer.reschedule(deadline)

    def close_for(self, reason):
        if self.reason is None:
            self.reason = reason

    def stop_work(self):
        if (self.requests >= self.limits.requests - 1 or self.accepted >= self.limits.proposals
                or self.dispatched >= self.limits.dispatches or not self.remaining()):
            self.close_for("presupuesto_agotado")
        return self.reason is not None

    def request(self, *, closing=False):
        if closing:
            if self.closing_requested or self.requests >= self.limits.requests or not self.remaining(closing=True):
                raise TurnLimit(self.reason or "presupuesto_agotado")
            self.closing_requested = True
        elif self.stop_work():
            raise TurnLimit(self.reason)
        self.requests += 1

    def proposals_for(self, count, *, closing=False):
        self.proposed += count
        admitted = 0 if closing else min(count, self.limits.batch, self.limits.proposals - self.accepted)
        self.accepted += admitted
        return admitted

    def dispatch(self, name):
        if (self.reason is not None or self.dispatched >= self.limits.dispatches
                or not self.remaining() or self.per_tool[name] >= self.limits.per_tool):
            return False
        self.dispatched += 1
        self.per_tool[name] += 1
        return True

    def refund_dispatch(self, name):
        self.dispatched -= 1
        self.per_tool[name] -= 1

    def observe(self, name, result, arguments=None):
        if (result.status not in {"respuesta recibida", "registro comprobado", "verificada en disco",
                                 "ejecución reconocida por MCP, efecto sin comprobación independiente"}
                or result.code in INVALID_CODES | {"ERROR_HERRAMIENTA", "EFECTO_SIN_CONFIRMAR"}):
            return
        text = result.content.strip()
        if not text:
            return
        evidence = result.evidence or {}
        self.partial |= (result.code == "CURSOR_ESTANCADO" or evidence.get("cobertura") == "parcial"
                         or evidence.get("truncado") is True)
        if text.startswith("{") and len(text) <= 8000:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict):
                self.partial |= any(data.get(key) is True for key in ("parcial", "partial", "truncated"))
                self.partial |= any(data.get(key) not in (None, "") for key in
                                    ("next_cursor", "nextCursor", "next_page_token", "nextPageToken"))
        if result.code == "CURSOR_ESTANCADO" or name == "consultar_proceso":
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            if isinstance(data, dict):
                keys = (("cursor", "next_cursor", "nextCursor") if result.code == "CURSOR_ESTANCADO" else
                        tuple(key for key in data if key not in {"estado", "id", "codigo", "cursor", "salida",
                                                               "cancelacion_solicitada", "ejecuciones_recientes"}))
                text = json.dumps({key: value for key, value in data.items() if key not in keys}, sort_keys=True)
        scope = {key: value for key, value in (arguments or {}).items() if key in SCOPE_FIELDS}
        signature = json.dumps([text, scope], sort_keys=True)
        observation = (name, hashlib.sha256(signature.encode()).digest())
        if observation not in self.progress:
            self.progress.add(observation)
            self.observed.append((name, result.status, result.content[:350]))

    def round(self, before, *, repair=False):
        if len(self.progress) != before:
            self.stalled = self.repairs = 0
            return
        self.stalled += 1
        self.stalled_total += 1
        self.repairs = self.repairs + 1 if repair else 0
        if self.stalled >= NO_PROGRESS or self.repairs > REPAIRS:
            self.close_for("sin_progreso")

    def snapshot(self):
        active = self.elapsed()
        return {"peticiones": self.requests, "propuestas": self.proposed, "admitidas": self.accepted,
                "despachadas": self.dispatched, "rondas_sin_progreso": self.stalled_total,
                "segundos_activos": round(active, 3), "segundos_confirmacion": round(self.confirmation_seconds, 3),
                "segundos_totales": round(active + self.confirmation_seconds, 3),
                "reserva_usada": self.closing_requested, "limites": vars(self.limits)}

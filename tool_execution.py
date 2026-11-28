"""Estados del motor para las propuestas de herramientas del turno."""
from collections import defaultdict, deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from secrets import token_bytes


OBSERVED = "observada"
VERIFIED = "verificada"
UNCONFIRMED = "sin_confirmar"
FAILED = "fallida"
OMITTED = "omitida"
LIMIT = "limitada"
REUSED = "reutilizada"
CONTROL = "control_aplicado"
LABELS = {
    "invalida": "argumentos o esquema inválidos",
    "no_disponible": "herramienta fuera del catálogo vigente",
    OMITTED: "operación omitida",
    LIMIT: "operación limitada por el presupuesto",
    "denegada": "permiso denegado",
    UNCONFIRMED: "operación pendiente de comprobación",
    "fallida": "herramienta o proceso con error registrado",
    "salida_no_cero": "proceso terminado con código distinto de cero",
    "terminada_sin_codigo": "proceso terminado sin código registrado",
    "cancelada": "proceso cancelado",
    "en_curso": "proceso activo, sin terminación observada",
    OBSERVED: "respuesta observada",
    VERIFIED: "efecto verificado",
    REUSED: "observación anterior reutilizada",
    CONTROL: "control aplicado por el motor",
}
SAFE = {OBSERVED, VERIFIED, REUSED, CONTROL}
RECOVERABLE = {FAILED, UNCONFIRMED, "en_curso"}
REASONS = {
    "SIN_DESPACHO": "el turno cambió de recorrido o terminó antes del despacho",
    "LIMITE_PROPUESTAS": "el presupuesto de admisión descartó la propuesta",
    "LIMITE_HERRAMIENTA": "el presupuesto impidió el despacho",
    "DESTINO_BLOQUEADO": "el alcance o la política del proveedor bloqueó el destino",
    "EFECTO_YA_REGISTRADO": "el diario impidió duplicar un efecto",
    "EFECTO_SIN_CONFIRMAR": "el efecto anterior requiere comprobación",
}

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


@dataclass
class Receipt:
    number: int
    tool: str
    state: str = OMITTED
    code: str | None = None
    kind: str = "descarte"
    reused_from: int | None = None
    recovered_by: int | None = None
    coverage: str = "indeterminada"
    observation: int | None = None
    excerpt: str = ""
    key: bytes | None = None
    run_id: str | None = None
    process_state: str | None = None
    start_confirmed: bool = False
    exit_code: int | None = None

    def metadata(self):
        code = self.code or ("SIN_DESPACHO" if self.kind == "descarte" else self.state.upper())
        return {"llamada": self.number, "herramienta": self.tool, "estado": self.state,
                "codigo": code, "motivo": REASONS.get(code, self.label()), "clase": self.kind,
                "reutiliza": self.reused_from, "recuperada_por": self.recovered_by, "cobertura": self.coverage,
                **({"inicio_confirmado": self.start_confirmed, "estado_proceso": self.process_state,
                    "codigo_terminacion": self.exit_code} if self.run_id else {})}

    def label(self):
        if self.state == VERIFIED and self.kind != "efecto":
            return "estado verificado por el ejecutor"
        return LABELS[self.state]


class CallLedger:
    def __init__(self):
        self.entries = []
        self.pending = defaultdict(deque)
        self.known_tools = set()
        self.secret = token_bytes(32)

    def new(self, tool):
        entry = Receipt(len(self.entries) + 1, tool)
        self.entries.append(entry)
        return entry

    def propose(self, calls, admitted, offered=()):
        self.known_tools.update(offered)
        for index, call in enumerate(calls):
            name = call.function.name
            entry = self.new(name if name in self.known_tools else "(desconocida)")
            if index < admitted:
                self.pending[id(call)].append((call, entry))
            else:
                entry.state, entry.code = LIMIT, "LIMITE_PROPUESTAS"

    def take(self, call, *, trusted_name=None):
        key = id(call)
        if key not in self.pending:
            return self.new(trusted_name or "(desconocida)")
        _, entry = self.pending[key].popleft()
        if not self.pending[key]:
            del self.pending[key]
        return entry

    def control(self, call):
        entry = self.take(call)
        entry.tool = call.function.name
        entry.state, entry.kind = CONTROL, "control"
        return entry

    def finish(self, entry, name, arguments, result, disposition, step):
        evidence = result.evidence or {}
        entry.state = execution_state(name, result, disposition, step)
        entry.code = result.code
        entry.observation = evidence.get("observacion")
        if evidence.get("cobertura") in {"completa", "parcial"}:
            entry.coverage = evidence["cobertura"]
        elif result.code == "CURSOR_ESTANCADO":
            entry.coverage = "parcial"
        if isinstance(arguments, dict):
            parts = [name, {k: v for k, v in arguments.items() if k != "espera_ms"
                            or name not in {"iniciar_proceso", "consultar_proceso", "cancelar_proceso"}}]
            entry.key = hmac.digest(self.secret, json.dumps(parts, sort_keys=True).encode(), hashlib.sha256)
        entry.kind = ("efecto" if (step and isinstance(step, dict) and step.get("effect") or name in
                       {"iniciar_proceso", "cancelar_proceso"} or evidence.get("efecto")
                       or result.status in {"verificada en disco", "confirmada por StoneWave"}) else "operacion")
        if evidence.get("procedencia") == "supervisor de Windows":
            entry.run_id = evidence.get("id")
            entry.process_state = evidence.get("estado")
            entry.start_confirmed = evidence.get("inicio_confirmado") is True
            entry.exit_code = evidence.get("codigo")
        elif disposition == "ejecutada" and (entry.state in {OBSERVED, VERIFIED, UNCONFIRMED}
                                              or entry.state == FAILED and entry.coverage == "parcial"):
            entry.excerpt = (result.model_content if result.model_content is not None else result.content)[:1200]
        self.reconcile(entry)

    def reconcile(self, witness):
        confirmed_effect = witness.state == VERIFIED and witness.kind == "efecto"
        complete_observation = witness.state in {OBSERVED, VERIFIED} and witness.coverage == "completa"
        terminal_run = (witness.tool == "consultar_proceso" and witness.run_id and
                        witness.state in {VERIFIED, "salida_no_cero", "terminada_sin_codigo", "cancelada"})
        if not (confirmed_effect or complete_observation or terminal_run):
            return
        for earlier in self.entries[:witness.number - 1]:
            if earlier.recovered_by or earlier.state not in RECOVERABLE:
                continue
            equivalent = (earlier.key is not None and earlier.key == witness.key and earlier.kind == witness.kind
                          and (confirmed_effect if earlier.kind == "efecto" else complete_observation))
            resolved_run = (terminal_run and earlier.run_id == witness.run_id and
                            ((earlier.tool == "iniciar_proceso" and earlier.state in {UNCONFIRMED, "en_curso"})
                             or (earlier.tool == "cancelar_proceso" and witness.state == "cancelada")))
            if equivalent or resolved_run:
                earlier.recovered_by = witness.number

    def blocked(self):
        return any(entry.kind != "descarte" and not entry.recovered_by and entry.state not in SAFE
                   for entry in self.entries)

    def partial_without_observation(self):
        return any(entry.coverage == "parcial" and not entry.recovered_by and entry.observation is None
                   and entry.state != REUSED for entry in self.entries)

    def recovered_observations(self):
        return {entry.observation for entry in self.entries if entry.recovered_by and entry.observation is not None}

    def has_evidence(self):
        return any(entry.kind in {"operacion", "efecto"} and
                   (entry.state in {OBSERVED, VERIFIED, "salida_no_cero", "terminada_sin_codigo", "cancelada", "en_curso"}
                    or entry.excerpt or entry.run_id) for entry in self.entries)

    def has_complete_observation(self):
        return any(entry.state in {OBSERVED, VERIFIED} and entry.coverage == "completa" for entry in self.entries)

    def has_verified_effect(self):
        return any(entry.kind == "efecto" and
                   (entry.state == VERIFIED or entry.recovered_by and self.entries[entry.recovered_by - 1].state == VERIFIED)
                   for entry in self.entries)

    def has_confirmed_execution(self):
        for entry in self.entries:
            if entry.tool != "iniciar_proceso" or not entry.run_id:
                continue
            if entry.start_confirmed or (entry.recovered_by and self.entries[entry.recovered_by - 1].start_confirmed):
                return True
        return False

    def rendered(self, *, pending_effects=False, missing_evidence=False):
        lines = ["Estado de las operaciones según StoneBot"]
        if missing_evidence:
            lines.append("Este turno no acredita la ejecución de la acción solicitada.")
        for entry in self.entries:
            if entry.kind == "control":
                continue
            status = entry.label()
            if entry.recovered_by:
                status += f" · recuperada por la llamada {entry.recovered_by}"
            if entry.coverage == "parcial":
                status += " · cobertura parcial"
            elif entry.state == OBSERVED and entry.coverage == "indeterminada":
                status += " · cobertura indeterminada"
            if entry.state == UNCONFIRMED:
                status += " · el dato recibido no verifica el efecto"
            lines.append(f"- Llamada {entry.number} · {status}")
        if pending_effects:
            lines.append("Queda pendiente comprobar el efecto registrado en el diario.")
        excerpts = [entry for entry in self.entries if entry.excerpt][-3:]
        for entry in excerpts:
            label = "Datos recibidos" if entry.state != UNCONFIRMED else "Datos sin confirmación del efecto"
            lines.append(f"{label} de la llamada {entry.number}\n\n" + "\n".join(
                "    " + row for row in CONTROL_CHARS.sub("", entry.excerpt).splitlines()))
        return "\n\n".join(lines)


def execution_state(name, result, disposition, step):
    code, status, evidence = result.code, result.status, result.evidence or {}
    if disposition == "no_disponible" or code == "HERRAMIENTA_NO_DISPONIBLE":
        return "no_disponible"
    if disposition == "limite_de_llamadas" or code in {"PRESUPUESTO_AGOTADO", "LIMITE_HERRAMIENTA"} and status == "sin ejecutar":
        return LIMIT
    if code in {"ARGUMENTOS_INVALIDOS", "ESQUEMA_NO_DISPONIBLE"}:
        return "invalida"
    if code == "OPERACION_DENEGADA" or evidence.get("efecto") == "denegado":
        return "denegada"
    if (disposition == "omitida" or status == "sin ejecutar" or evidence.get("efecto") == "sin ejecutar"
            or step and step.get("effect") and step["status"] == "sin ejecutar"):
        return OMITTED
    if status in {"verificada en disco", "confirmada por StoneWave"} or evidence.get("efecto") == "verificado":
        return VERIFIED
    if evidence.get("procedencia") == "supervisor de Windows":
        state = evidence.get("estado")
        if state == "cancelado":
            return "cancelada"
        if name == "cancelar_proceso" and state in {"terminado", "fallido"}:
            return OMITTED
        if state == "fallido":
            return "fallida"
        if state == "terminado":
            exit_code = evidence.get("codigo")
            if type(exit_code) is not int:
                return "terminada_sin_codigo"
            return VERIFIED if exit_code == 0 else "salida_no_cero"
        if state == "ejecutando":
            return "en_curso"
        if state in {"preparando", "sin confirmar"}:
            return UNCONFIRMED
    if status == "sin confirmar" or evidence.get("efecto") in {"sin confirmar", "sin confirmación independiente"}:
        return UNCONFIRMED
    if status in {"error de lectura", "error de herramienta"} or code == "ERROR_HERRAMIENTA":
        return "fallida"
    if step and step.get("effect"):
        return UNCONFIRMED
    return OBSERVED


def with_metadata(content, metadata, notes):
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        header = f"Estado del motor: {json.dumps(metadata, ensure_ascii=False)}"
        return "\n".join([content, header, *notes])
    if isinstance(data, dict):
        data.pop("ejecucion", None)
    else:
        data = {"datos": data}
    execution = {**metadata, "avisos": notes} if notes else metadata
    return json.dumps({"ejecucion": execution, **data}, ensure_ascii=False)

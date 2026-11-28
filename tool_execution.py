"""Estados del motor para las propuestas de herramientas del turno."""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import json
import re


OBSERVED = "observada"
VERIFIED = "verificada"
UNCONFIRMED = "sin_confirmar"
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
    "cancelada": "proceso cancelado",
    "en_curso": "proceso activo, sin terminación observada",
    OBSERVED: "respuesta observada",
    VERIFIED: "efecto verificado",
    REUSED: "observación anterior reutilizada",
    CONTROL: "control aplicado por el motor",
}
SAFE = {OBSERVED, VERIFIED, REUSED, CONTROL}
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")


@dataclass
class Receipt:
    number: int
    state: str = OMITTED
    code: str | None = None
    reused_from: int | None = None
    excerpt: str = ""

    def metadata(self):
        return {"llamada": self.number, "estado": self.state, "codigo": self.code, "reutiliza": self.reused_from}


class CallLedger:
    def __init__(self):
        self.entries = []
        self.pending = defaultdict(deque)

    def new(self):
        entry = Receipt(len(self.entries) + 1)
        self.entries.append(entry)
        return entry

    def propose(self, calls, admitted):
        for index, call in enumerate(calls):
            entry = self.new()
            if index < admitted:
                self.pending[id(call)].append((call, entry))
            else:
                entry.state, entry.code = LIMIT, "LIMITE_PROPUESTAS"

    def take(self, call):
        key = id(call)
        if key not in self.pending:
            return self.new()
        _, entry = self.pending[key].popleft()
        if not self.pending[key]:
            del self.pending[key]
        return entry

    def control(self, call):
        self.take(call).state = CONTROL

    def blocked(self):
        return any(entry.state not in SAFE for entry in self.entries)

    def rendered(self, *, pending_effects=False):
        counts = Counter(entry.state for entry in self.entries)
        lines = [f"- {count} · {LABELS[state]}" for state, count in counts.items()]
        if pending_effects:
            lines.append("Queda pendiente comprobar el efecto registrado en el diario.")
        if any(entry.excerpt for entry in self.entries):
            excerpts = [entry for entry in self.entries if entry.excerpt][-3:]
            for entry in excerpts:
                lines.append(f"\nDatos recibidos de la llamada {entry.number}\n\n" + "\n".join(
                    "    " + row for row in CONTROL_CHARS.sub("", entry.excerpt).splitlines()))
        return "Estado de las operaciones según StoneBot\n\n" + "\n".join(lines)


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
        if state == "terminado" and evidence.get("codigo") != 0:
            return "salida_no_cero"
        if state == "ejecutando":
            return "en_curso"
        if state in {"preparando", "sin confirmar"}:
            return UNCONFIRMED
        if state == "terminado":
            return VERIFIED
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

"""Iteración del modelo y sus herramientas dentro de un turno."""
import json
from dataclasses import dataclass

from ollama._utils import convert_function_to_tool

from tool_validation import InvalidToolArguments, validate_arguments

@dataclass(frozen=True)
class ToolResult:
    content: str
    reuse: bool = True
    status: str = "respuesta recibida"
    code: str | None = None
    hint: str = ""

    def model_text(self, *, reused=False):
        notes = ([f"[{self.code}] {self.hint}".rstrip()] if self.code else [self.hint] if self.hint else [])
        if reused:
            notes.append("[SIN_PROGRESO] Se reutilizó la observación anterior. No se ejecutó otra llamada.")
        return "\n".join([self.content, *notes])


@dataclass(frozen=True)
class EndTurn:
    answer: str


class TurnTools:
    """Catálogo de la ronda, compartido por el proveedor y el ejecutor."""

    def __init__(self, specs, aliases, contract=None):
        self.specs = list(specs)
        self.boundary = None
        self.aliases = aliases
        self.available = set()
        self.handlers = {}
        self.contract = contract
        self.schemas = {}
        self.blocked = set()

    def register(self, names, handler):
        for name in names:
            if name in self.handlers:
                raise ValueError(f"Herramienta duplicada: {name}")
            self.handlers[name] = handler

    def limit_to(self, permitted):
        """Cada fuente puede reducir los destinos del turno, incluso dentro de una tanda."""
        self.boundary = set(permitted) if self.boundary is None else self.boundary.intersection(permitted)
        self.available.intersection_update(self.boundary)

    def offer(self, *, finishing):
        return self.select([] if finishing else self.specs)

    def block(self, name):
        self.blocked.add(name)
        self.available.discard(name)

    def select(self, specs):
        selected = []
        self.available = set()
        for spec in specs:
            name = spec.__name__ if callable(spec) else spec.function.name
            if name not in self.blocked and (self.boundary is None or name in self.boundary):
                self.available.add(name)
                definition = convert_function_to_tool(spec) if callable(spec) else spec
                parameters = definition.function.parameters
                self.schemas[name] = parameters.model_dump(by_alias=True, exclude_none=True) if parameters else {}
                selected.append(spec)
        return selected

    def permits(self, name):
        return self.aliases.get(name, name) in self.available

    def validate(self, name, arguments):
        name = self.aliases.get(name, name)
        if name not in self.available:
            offered = ", ".join(sorted(self.available))
            return ToolResult(f"Herramienta desconocida o no disponible. Usa un nombre exacto de esta lista: {offered}."
                              if offered else "No hay herramientas disponibles.",
                              reuse=False, status="sin ejecutar", code="HERRAMIENTA_NO_DISPONIBLE")
        schema, decimal_fields = self.contract(name) if self.contract else (None, ())
        try:
            return validate_arguments(self.schemas[name] if schema is None else schema, arguments,
                                      decimal_fields=decimal_fields)
        except InvalidToolArguments as exc:
            return ToolResult(str(exc), reuse=False, status="sin ejecutar",
                              code="ESQUEMA_NO_DISPONIBLE" if exc.unavailable else "ARGUMENTOS_INVALIDOS")


class ToolLoop:
    def __init__(self, messages, *, final_round, tools, max_distinct_calls):
        self.messages = messages
        self.final_round = final_round
        self.tools = tools
        self.max_distinct_calls = max_distinct_calls

    async def run(self, request_round, execute_tool, *, check_pause, on_repeat, after_batch, activity,
                  before_call=None, after_call=None, after_tool=None, trace=None):
        """Ejecuta rondas hasta obtener una respuesta o alcanzar el límite.

        request_round devuelve un mensaje con llamadas, texto final o None para
        continuar. execute_tool devuelve ToolResult o EndTurn. after_batch puede
        devolver la respuesta si la última operación ya completó la solicitud.
        """
        results = {}
        finish_without_tools = False
        for index in range(self.final_round + 1):
            check_pause()
            finishing = bool(self.max_distinct_calls) and (finish_without_tools or index == self.final_round)
            reply = await request_round(index, finishing)
            if reply is None:
                continue
            if isinstance(reply, str):
                activity("Respuesta preparada con los resultados disponibles." if results else "Respuesta preparada.")
                return reply

            calls = []
            for call in reply.tool_calls:
                name = call.function.name
                arguments = self.tools.validate(name, call.function.arguments)
                resolved = self.tools.aliases.get(name, name)
                key = ((resolved, json.dumps(arguments, sort_keys=True))
                       if self.max_distinct_calls and not isinstance(arguments, ToolResult) else None)
                calls.append((name, arguments, resolved, key))
            if self.max_distinct_calls and all(key in results for _, _, _, key in calls):
                on_repeat()
                if trace:
                    trace("lote_omitido", ronda=index + 1, estado="repetido")
                finish_without_tools = True

            self.messages.append(reply)
            for position, (name, arguments, resolved, key) in enumerate(calls):
                check_pause()
                disposition = "ejecutada"
                if not self.tools.permits(name):
                    disposition = "no_disponible"
                    result = self.tools.validate(name, {})
                elif isinstance(arguments, ToolResult):
                    disposition = "sin_ejecutar"
                    result = arguments
                elif key in results:
                    disposition = "reutilizada"
                    result = results[key]
                elif self.max_distinct_calls and len(results) >= self.max_distinct_calls:
                    disposition = "limite_de_llamadas"
                    result = ToolResult("StoneBot terminó la fase de herramientas de este turno.", reuse=False)
                    finish_without_tools = True
                else:
                    handler = self.tools.handlers.get(resolved, execute_tool)
                    activity(f"El modelo solicitó {resolved}.")
                    step = None
                    if before_call:
                        remaining = [item[2] for item in calls[position + 1:]
                                     if self.tools.permits(item[0]) and not isinstance(item[1], ToolResult)]
                        step = before_call(resolved, arguments, remaining)
                    if isinstance(step, ToolResult):
                        disposition = "omitida"
                        result = step
                    else:
                        result = await handler(resolved, arguments)
                        if step is not None:
                            after_call(step, result.answer if isinstance(result, EndTurn) else result.content,
                                       result.status if isinstance(result, ToolResult) else "respuesta recibida")
                        if after_tool:
                            after_tool(resolved, result)
                if trace:
                    if isinstance(result, ToolResult) and result.status == "sin ejecutar" and disposition == "ejecutada":
                        disposition = "sin_ejecutar"
                    trace("resultado", ronda=index + 1, posicion=position + 1,
                          herramienta=resolved if disposition != "no_disponible" else "(no disponible)",
                          estado=disposition, estado_ejecutor=result.status if isinstance(result, ToolResult) else "cierre",
                          codigo=result.code if isinstance(result, ToolResult) else None,
                          resultado=result.answer if isinstance(result, EndTurn) else result.content)
                if isinstance(result, EndTurn):
                    return result.answer
                if key is not None and result.reuse:
                    results[key] = result
                self.messages.append({"role": "tool", "tool_name": name,
                                      "content": result.model_text(reused=disposition == "reutilizada")})
            answer = after_batch()
            if answer is not None:
                return answer
        return None

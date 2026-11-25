"""Iteración del modelo y sus herramientas dentro de un turno."""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    content: str
    reuse: bool = True
    context_chars: int | None = None


@dataclass(frozen=True)
class EndTurn:
    answer: str


class TurnTools:
    """Catálogo de la ronda, compartido por el proveedor y el ejecutor."""

    def __init__(self, specs, restricted_specs, aliases):
        self.specs = list(specs)
        self.restricted_specs = list(restricted_specs)
        self.aliases = aliases
        self.available = set()
        self.handlers = {}

    def register(self, names, handler):
        for name in names:
            if name in self.handlers:
                raise ValueError(f"Herramienta duplicada: {name}")
            self.handlers[name] = handler

    def restrict(self):
        self.available.intersection_update(spec.function.name for spec in self.restricted_specs)

    def offer(self, *, restricted, finishing):
        specs = self.restricted_specs if restricted else self.specs
        return self.select([] if finishing else specs)

    def select(self, specs):
        self.available = {spec.__name__ if callable(spec) else spec.function.name for spec in specs}
        return specs

    def permits(self, name):
        return self.aliases.get(name, name) in self.available


class ToolLoop:
    def __init__(self, messages, *, context_chars, final_round, tools,
                 max_distinct_calls, count_tool_context):
        self.messages = messages
        self.context_chars = context_chars
        self.final_round = final_round
        self.tools = tools
        self.max_distinct_calls = max_distinct_calls
        self.count_tool_context = count_tool_context

    async def run(self, request_round, execute_tool, *, check_pause, on_repeat, after_batch, activity):
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
                arguments = call.function.arguments
                resolved = self.tools.aliases.get(name, name)
                key = (resolved, json.dumps(arguments, sort_keys=True)) if self.max_distinct_calls else None
                calls.append((name, arguments, resolved, key))
            if self.max_distinct_calls and all(key in results for _, _, _, key in calls):
                on_repeat()
                finish_without_tools = True
                continue

            self.messages.append(reply)
            if self.count_tool_context:
                self.context_chars += len(reply.thinking or "") + len(reply.content or "")
            for name, arguments, resolved, key in calls:
                check_pause()
                if not self.tools.permits(name):
                    offered = ", ".join(sorted(self.tools.available))
                    result = ToolResult(f"Herramienta desconocida o no disponible. Usa un nombre exacto de esta lista: {offered}.",
                                        reuse=False)
                elif key in results:
                    result = results[key]
                elif self.max_distinct_calls and len(results) >= self.max_distinct_calls:
                    result = ToolResult("StoneBot terminó la fase de herramientas de este turno.", reuse=False)
                    finish_without_tools = True
                else:
                    handler = self.tools.handlers.get(resolved, execute_tool)
                    activity(f"El modelo solicitó {resolved}.")
                    result = await handler(resolved, arguments)
                if isinstance(result, EndTurn):
                    return result.answer
                if key is not None and result.reuse:
                    results[key] = result
                self.messages.append({"role": "tool", "tool_name": name, "content": result.content})
                if result.context_chars is not None:
                    self.context_chars += result.context_chars
                elif self.count_tool_context:
                    self.context_chars += len(json.dumps(arguments)) + len(result.content)
            answer = after_batch()
            if answer is not None:
                return answer
        return None

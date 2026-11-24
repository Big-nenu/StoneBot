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


class ToolLoop:
    def __init__(self, messages, *, context_chars, final_round, aliases,
                 max_distinct_calls, count_tool_context):
        self.messages = messages
        self.context_chars = context_chars
        self.final_round = final_round
        self.aliases = aliases
        self.max_distinct_calls = max_distinct_calls
        self.count_tool_context = count_tool_context

    async def run(self, request_round, execute_tool, *, check_pause, on_repeat, after_batch):
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
                return reply

            calls = []
            for call in reply.tool_calls:
                name = call.function.name
                arguments = call.function.arguments
                resolved = self.aliases.get(name, name)
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
                if key in results:
                    result = results[key]
                elif self.max_distinct_calls and len(results) >= self.max_distinct_calls:
                    result = ToolResult("StoneBot terminó la fase de herramientas de este turno.", reuse=False)
                    finish_without_tools = True
                else:
                    result = await execute_tool(name, arguments, resolved)
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

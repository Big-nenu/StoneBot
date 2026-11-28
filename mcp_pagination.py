"""Continuaciones de lecturas MCP verificables dentro del turno."""
from dataclasses import dataclass
import json
import re

from tool_validation import InvalidToolArguments, validate_arguments


CURSOR_FIELDS = {"cursor", "page_token", "pageToken", "continuation_token", "continuationToken"}
NEXT_FIELDS = ("next_cursor", "nextCursor", "next_page_token", "nextPageToken",
               "next_continuation_token", "nextContinuationToken")
ORDINALS = ("primera|first", "segunda|second", "tercera|third", "cuarta|fourth", "quinta|fifth",
            "sexta|sixth", "séptima|septima|seventh", "octava|eighth", "novena|ninth", "décima|decima|tenth")


def page_continuation_allowed(text):
    prohibited = (r"\b(?:no|sin|nunca|never|do not|don't)\s+"
                  r"(?:contin[uú]\w*|pagin\w*|lea\w*|lees?|abras?|consult\w*|"
                  r"recuper\w*|read|fetch|retrieve|open|continue|paginate)\b")
    return not re.search(prohibited, text, re.I)


def requested_page(text):
    """Reconoce un objetivo de paginación explícito. None deja el cierre ordinario."""
    page = r"(?:p[aá]gina|page)"
    if not page_continuation_allowed(text):
        return None
    numbered = re.search(rf"\b{page}\s+([1-9][0-9]{{0,5}})\b", text, re.I)
    if numbered:
        return int(numbered[1])
    for number, ordinal in enumerate(ORDINALS, 1):
        if re.search(rf"\b(?:{ordinal})\s+{page}\b", text, re.I):
            return number
    if re.search(rf"\b(?:siguiente|pr[oó]xima|next)\s+{page}\b", text, re.I):
        return 2
    if re.search(rf"\b(?:todas?\s+(?:las?\s+)?|all\s+(?:the\s+)?){page}s\b", text, re.I):
        return "all"
    return None


def is_cursor(value):
    return type(value) is int or isinstance(value, str) and bool(value)


@dataclass(frozen=True)
class Continuation:
    tool: str
    arguments: dict
    depth: int | None
    cursor: int | str
    origin: int

    def matches(self, tool, arguments):
        return self.tool == tool and argument_key(self.arguments) == argument_key(arguments)


def argument_key(arguments):
    return json.dumps(arguments, sort_keys=True, ensure_ascii=False)


class McpPagination:
    def __init__(self):
        self.pending = {}
        self.pages = {}
        self.resolved = {}
        self.stalled = set()

    def observe(self, name, schema, arguments, metadata, next_cursor, observation):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return None
        fields = CURSOR_FIELDS & properties.keys()
        explicit = fields & arguments.keys()
        choices = explicit or fields
        if len(choices) != 1:
            return None
        field, = choices
        definition = properties[field]
        default = definition.get("default") if isinstance(definition, dict) else None
        echo = metadata.get(field)
        current = arguments.get(field, echo if is_cursor(echo) else default)
        if is_cursor(echo) and is_cursor(current) and echo != current:
            return "cursor no coincide"
        query = (name, field, argument_key({key: value for key, value in arguments.items() if key != field}))
        pages = self.pages.setdefault(query, {})
        incoming = self.pending.pop((query, current), ()) if is_cursor(current) else ()
        for item in incoming:
            self.resolved[item.origin] = observation
        depth = next((item.depth for item in incoming if item.depth is not None), pages.get(current) if is_cursor(current) else None)
        if depth is None and (field not in arguments or is_cursor(default) and current == default):
            depth = 1
        if current is None or is_cursor(current):
            pages[current] = depth
        if not is_cursor(next_cursor):
            return None
        if next_cursor in pages:
            self.stalled.add(query)
            return "cursor repetido"
        if query in self.stalled:
            return "cursor repetido"
        candidate = {**arguments, field: next_cursor}
        try:
            validate_arguments(schema, candidate)
        except InvalidToolArguments:
            return None
        continuation = Continuation(name, candidate, depth + 1 if depth is not None else None, next_cursor, observation)
        self.pending.setdefault((query, next_cursor), []).append(continuation)
        return None

    def blocked(self, name, arguments):
        return any(name == tool and scope == argument_key({key: value for key, value in arguments.items() if key != field})
                   for tool, field, scope in self.stalled)

    def available(self, goal):
        if goal is None or goal == 1:
            return []
        candidates = []
        for (query, _), items in self.pending.items():
            if query in self.stalled:
                continue
            item = items[0]
            if goal == "all":
                candidates.append(item)
                continue
            if goal in self.pages[query].values():
                continue
            if (item.depth is not None and item.depth <= goal) or (item.depth is None and item.cursor == goal):
                candidates.append(item)
        return candidates

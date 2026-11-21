"""Consulta local del último sueño de StoneWave desde el chat."""
import json
import re
from datetime import datetime


REQUEST = re.compile(r"^\s*¿?\s*(?:y\s+)?(?:qu[eé]|cu[aá]ndo|cu[aá]l(?:es)?|c[oó]mo|dime|lista|muestra|"
                     r"cu[eé]ntame|consulta|me (?:puedes|podr[ií]as) decir|puedes decirme|quisiera saber)\b", re.I)
DREAM = re.compile(r"\b(?:sueñ[oa]s?|soñ[oó]|sleeptime)\b", re.I)
ENGINE = re.compile(r"\b(?:stonewave|sw)\b", re.I)
PERSONAL = re.compile(r"\b(?:mis? sueñ[oa]s?|soñ[eé]|sueños? personales)\b", re.I)
FOCUS = {
    "notes": re.compile(r"\b(?:notas?|obsidian|archivos?)\b", re.I),
    "links": re.compile(r"\b(?:relacion\w*|enlac\w*|vincul\w*)\b", re.I),
    "conclusions": re.compile(r"\b(?:conclusi[oó]n(?:es)?|hip[oó]tesis)\b", re.I),
}


def dream_question(messages):
    """Identifica una consulta operativa sin confundirla con relatos de sueños personales."""
    if not messages or messages[-1].get("role") != "user" or messages[-1].get("attachments"):
        return None
    text = messages[-1]["content"]
    if PERSONAL.search(text):
        return None

    def operational(question):
        if PERSONAL.search(question):
            return False
        return bool((DREAM.search(question) and (ENGINE.search(question) or re.search(
            r"\b(?:[uú]ltimo|autom[aá]tico|ejecut\w*|funci[oó]n|obsidian|notas)\b", question, re.I)))
            or (FOCUS["notes"].search(question) and (ENGINE.search(question) or re.search(r"\bobsidian\b", question, re.I)) and
                re.search(r"\b(?:cre[oó]|creadas?|escri\w*|actualiz\w*|export\w*)\b", question, re.I))
            or re.search(r"\b(?:recuerdos?\s+(?:relacion[oó]|enlaz[oó]|vincul[oó])|"
                         r"conclusiones\s+(?:gener[oó]|cre[oó]|deriv[oó]))\b", question, re.I))

    requested = bool(REQUEST.match(text))
    if not requested or not operational(text):
        previous = next((m["content"] for m in reversed(messages[:-1]) if m.get("role") == "user"), "")
        if not operational(previous) or not (requested and any(pattern.search(text) for pattern in FOCUS.values())
                                             or DREAM.search(text) and ENGINE.search(text)):
            return None
    focus = {name for name, pattern in FOCUS.items() if pattern.search(text)}
    return focus or ({"date"} if re.search(r"\bcu[aá]ndo\b", text, re.I) else {"all"})


def format_dream_activity(response, focus):
    report = json.loads(response)
    if report["status"] == "never":
        return "StoneWave todavía no tiene un sueño terminado en esta memoria."
    finished = datetime.fromisoformat(report["finished_at"]).astimezone().strftime("%d/%m/%Y a las %H:%M:%S (%Z)")
    if report["status"] == "date_only":
        return (f"StoneWave completó su último sueño el **{finished}**. "
                "Solo está disponible la fecha de esa ejecución. Los detalles estarán disponibles a partir del próximo sueño.")

    def literal(value):
        if value is None:
            return "contenido ya no disponible"
        return re.sub(r"([\\`*_\[\]<>])", r"\\\1", " ".join(value.split()))

    lines = [f"El último sueño de StoneWave terminó el **{finished}** ({literal(report['source'])})."]
    if {"links", "all"} & focus:
        count = report["links_count"]
        lines.extend(["", f"**Enlaces registrados ({count})**"])
        if report["links"]:
            lines.append("Textos actuales de los recuerdos, abreviados cuando son largos.")
        for link in report["links"]:
            left, right = link["facts"]
            lines.append(f"- ID {left['id']} «{literal(left['content'])}» ↔ ID {right['id']} «{literal(right['content'])}» ({literal(link['kind'])}).")
        if not count:
            lines.append("StoneWave no registró enlaces en ese sueño.")
        elif len(report["links"]) < count:
            lines.append(f"SW conservó el detalle de los {len(report['links'])} enlaces más fuertes.")
    if {"conclusions", "all"} & focus:
        lines.extend(["", "**Conclusiones generadas**"])
        for item in report["conclusions"]:
            lines.append(f"- C {item['id']} · {literal(item['content'])} ({literal(item['kind'])}).")
        state = report["conclusions_status"]
        if state == "disabled":
            lines.append("La generación de conclusiones estaba desactivada.")
        elif state == "error":
            lines.append("La etapa de conclusiones terminó con un error.")
        elif not report["conclusions"]:
            lines.append("StoneWave no generó conclusiones nuevas.")
    if {"notes", "all"} & focus:
        lines.extend(["", "**Notas de Obsidian**"])
        state = report["notes_status"]
        if state == "disabled":
            lines.append("La publicación a Obsidian estaba desactivada.")
        elif state != "ok":
            lines.append("StoneWave no pudo confirmar la exportación de notas.")
        else:
            for key, label in (("notes_created", "Creada"), ("notes_updated", "Actualizada")):
                for path in report[key]:
                    lines.append(f"- {label} · {literal(path)}")
            if not (report["notes_created"] or report["notes_updated"]):
                lines.append("StoneWave no escribió archivos nuevos ni actualizó notas.")
    return "\n".join(lines)

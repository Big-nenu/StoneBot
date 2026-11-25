"""Solicitudes de guardado de adjuntos y verificación de archivos Markdown."""
import os
import re
from pathlib import Path

from folder_inventory import PATH
from stonebot_engine.safety import check_path


def attachment_save_followup(message):
    text = message["content"].strip()
    if re.match(r"^(?:cancela\b|no (?:puedes|uses|quiero|contin[uú]es)\b)", text, re.I):
        return False
    if message.get("attachments") and (
        not text or text == "Revisa los archivos adjuntos."
        or re.search(r"\b(?:estos?|estas?|esos?|esas?|los|las)\s+(?:de\s+)?(?:la |el |los |las )?"
                     r"(?:imagen|captura|adjuntos?|foto)\b", text, re.I)
    ):
        return True
    return bool(re.fullmatch(
        r"(?:[sS][íi]|correcto|exacto|adelante)(?:[, ]+(?:es(?:os|as)|son esos|son esas)"
        r"(?: (?:comandos|atajos))?)?(?:[, ]+por ?fa(?:vor)?)?[.!]?", text, re.I,
    ) or re.match(r"^(?:(?:son\s+)?los que (?:t[uú] |me )*(?:dijiste|mencionaste|pusiste)|"
                  r"esos que (?:acabas de )?(?:decir|mencionar|enumerar))\b", text, re.I)
        or re.fullmatch(r"intenta (?:guardar el archivo )?de nuevo(?:[, ]+por ?fa(?:vor)?)?[.!]?", text, re.I)
        or re.search(r"\b(?:usa|usar|puedes)\b.{0,60}\b(?:Desktop Commander|MCP)\s*[.!]?\s*$", text, re.I))


def attachment_save_request(messages):
    if not messages or messages[-1]["role"] != "user":
        return None
    resolved = {}
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        request = message["content"]
        if message["role"] == "assistant":
            for line in request.splitlines():
                if line in ("**Memoria.** Guardada en StoneBot.", "**Memoria.** Guardada en StoneWave.",
                            "**Memoria.** La información ya estaba guardada."):
                    resolved.setdefault("memory", line)
                elif line.startswith("**Archivo.** Guardado y verificado en "):
                    resolved.setdefault("markdown", line)
                elif line == "**Archivo.** La escritura no fue autorizada.":
                    resolved.setdefault("markdown", line)
            continue
        if message["role"] != "user":
            break
        intent = parse_attachment_save(request)
        if intent is not None:
            intent["index"] = index
            intent["resolved"] = {key: line for key, line in resolved.items() if intent[key]}
            return intent
        if not attachment_save_followup(message):
            break
    return None


def parse_attachment_save(request):
    if re.match(r"^\s*no\s+(?:(?:quiero|necesito) que )?(?:los? )?(?:guard|recuerd|cre|hag|escrib)",
                request, re.I):
        return None
    memory = bool(re.search(r"\b(?:recuerda\b|guarda\w*\b[\s\S]*?\ben (?:tu|la|mi) memoria\b)", request, re.I))
    markdown = bool(re.search(r"\b(?:guarda\w*|crea\w*|haz|haces|genera\w*|escribe\w*)\b", request, re.I)
                    and re.search(r"\.md\b|\barchivo markdown\b", request, re.I))
    if not (memory or markdown):
        return None
    paths = {value for match in PATH.finditer(request) for value in match.groups() if value} if markdown else set()
    return {"memory": memory, "markdown": markdown, "target": Path(paths.pop()) if len(paths) == 1 else None,
            "request": request}


def markdown_destination(target, arguments):
    path = Path(arguments.get("path") or "")
    content = arguments.get("content")
    if not path.is_absolute() or path.suffix.lower() != ".md" or not isinstance(content, str) or not content.strip():
        raise ValueError("La herramienta necesita una ruta absoluta de Markdown y su contenido.")
    allowed_path = Path(check_path(target))
    destination = Path(check_path(path))
    if allowed_path != (destination if target.suffix.lower() == ".md" else destination.parent):
        raise ValueError("La ruta del archivo queda fuera del destino indicado por el usuario.")
    if destination.exists():
        raise ValueError("El archivo ya existe. Elige otro nombre para conservarlo.")
    if destination != Path(os.path.abspath(path)):
        raise ValueError("El destino del Markdown contiene una redirección.")
    return destination


def text_file_verified(destination, content):
    expected = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        path = Path(check_path(destination))
        if path != Path(destination) or not path.is_file():
            return False
        with path.open(encoding="utf-8-sig") as saved:
            return saved.read(len(expected) + 1) == expected
    except (OSError, ValueError, RuntimeError):
        return False


markdown_verified = text_file_verified

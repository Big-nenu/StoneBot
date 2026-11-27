"""Compone el contexto de sesión y consulta la ventana de Ollama."""
import json
import re
from dataclasses import dataclass

import httpx

from ai_provider import OLLAMA_URL


HISTORY_CHARS = 48_000
FALLBACK_TOKENS = 4096


def operational_prompt(ai, *, task, project, preferences):
    context = {"modo": "tarea guardada" if task is not None else "chat",
               "proveedor": ai.provider, "proyecto_activo": bool(project)}
    blocks = ["Contexto operativo (datos del turno): " + json.dumps(context, ensure_ascii=False)]
    if preferences:
        blocks.append("Preferencias generales bajo las reglas de StoneBot:\n" + preferences[:4000])
    if project:
        fields = {key: project[key][:limit] for key, limit in
                  (("name", 256), ("description", 2000), ("instructions", 4000))}
        blocks.append("Proyecto activo y preferencias de trabajo.\n" + json.dumps(fields, ensure_ascii=False))
    return "\n\n" + "\n\n".join(blocks)


def positive_int(value):
    return value if type(value) is int and value > 0 else None


@dataclass(frozen=True)
class OllamaContext:
    maximum: int | None = None
    configured: int | None = None

    @property
    def history_chars(self):
        target = self.configured or FALLBACK_TOKENS
        tokens = min(self.maximum or FALLBACK_TOKENS, target)
        # Es una cota de compactación en caracteres, no una estimación del contexto asignado.
        return min(HISTORY_CHARS, tokens * 2)

    @classmethod
    def from_metadata(cls, metadata):
        info = metadata.get("model_info") or {}
        architecture = info.get("general.architecture") if isinstance(info, dict) else None
        maximum = positive_int(info.get(f"{architecture}.context_length")) if architecture else None
        parameters = metadata.get("parameters")
        match = re.search(r"(?m)^\s*num_ctx\s+(\d{1,8})[ \t]*$", parameters) if isinstance(parameters, str) else None
        return cls(maximum, positive_int(int(match[1])) if match else None)


async def ollama_metadata(path, *, model=None):
    try:
        async with httpx.AsyncClient(base_url=OLLAMA_URL, timeout=2, trust_env=False) as client:
            reply = await client.get(path) if model is None else await client.post(path, json={"model": model})
            reply.raise_for_status()
            data = reply.json()
            return data if isinstance(data, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def observed_context(model):
    data = await ollama_metadata("/api/ps")
    models = data.get("models")
    if not isinstance(models, list):
        return {}
    def tagged(name):
        if not isinstance(name, str):
            return None
        return name if ":" in name.rsplit("/", 1)[-1] else name + ":latest"

    matching = [entry for entry in models if isinstance(entry, dict)
                and tagged(model) in (tagged(entry.get("model")), tagged(entry.get("name")))]
    if len(matching) != 1:
        return {}
    entry, = matching
    vram = entry.get("size_vram")
    return {"tokens_observados": positive_int(entry.get("context_length")),
            "bytes_vram_observados": vram if type(vram) is int and vram >= 0 else None}

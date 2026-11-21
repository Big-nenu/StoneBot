"""Preferencias de IA y cliente de chat para OpenRouter."""
import base64
import json
import os
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

import httpx
from ollama import Client, Message, ResponseError
from PySide6.QtCore import QSettings

from mcp_client import data_path
from mcp_credentials import read_key, store_key


PROVIDERS = {"ollama": "Ollama", "openrouter": "OpenRouter"}
DEFAULT_MODEL = "nemotron-3.5-bolt:e4b"
OLLAMA_URL = "http://localhost:11434"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
KEY_TARGET = "StoneBot/AI/OpenRouter"


@dataclass(frozen=True)
class AISettings:
    provider: str = "ollama"
    model: str = DEFAULT_MODEL
    cloud_memory: bool = False

    @property
    def cloud(self):
        return self.provider == "openrouter"


def preferences():
    return QSettings(str(data_path("chat.ini")), QSettings.Format.IniFormat)


def saved_model(provider):
    return preferences().value(f"ai/{provider}_model", DEFAULT_MODEL if provider == "ollama" else "", type=str)


def load_ai():
    settings = preferences()
    provider = settings.value("ai/provider", "ollama", type=str)
    if provider not in PROVIDERS or not (model := saved_model(provider)):
        return AISettings()
    return AISettings(provider, model, settings.value("ai/cloud_memory", False, type=bool))


def openrouter_key():
    return os.getenv("OPENROUTER_API_KEY", "").strip() or read_key(KEY_TARGET)


def save_ai(config, key=""):
    if config.provider not in PROVIDERS or not config.model or any(c.isspace() for c in config.model):
        raise ValueError("Escribe el identificador del modelo sin espacios.")
    if config.cloud:
        if key:
            if os.name != "nt":
                raise ValueError("Configura OPENROUTER_API_KEY en este equipo.")
            store_key(KEY_TARGET, key)
        elif not openrouter_key():
            raise ValueError("Introduce una clave de OpenRouter para activar este proveedor.")
    settings = preferences()
    settings.setValue(f"ai/{config.provider}_model", config.model)
    settings.setValue("ai/provider", config.provider)
    settings.setValue("ai/cloud_memory", config.cloud_memory)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("No se pudo guardar la configuración de IA.")


@dataclass(frozen=True)
class CatalogModel:
    id: str
    name: str
    price: str = ""


def model_price(model):
    identifier = model["id"]
    if identifier.endswith(":free") or identifier == "openrouter/free":
        return "Gratis"
    prices = model.get("pricing") or {}
    try:
        rates = [Decimal(str(prices[key])) for key in ("prompt", "completion")]
        rates.append(Decimal(str(prices.get("request", "0"))))
    except (KeyError, InvalidOperation):
        return "Consultar precio"
    if any(not rate.is_finite() or rate < 0 for rate in rates):
        return "Precio variable"
    return "De pago" if any(rates) else "Tarifa de texto $0"


def available_models(provider):
    if provider == "ollama":
        models = Client(host=OLLAMA_URL, timeout=8).list().models
        return sorted((CatalogModel(item.model, item.model) for item in models if item.model),
                      key=lambda model: model.name.casefold())
    models = OpenRouter().request("GET", "/models", timeout=10)["data"]
    return sorted((CatalogModel(item["id"], item.get("name") or item["id"], model_price(item))
                   for item in models if "tools" in item.get("supported_parameters", [])
                   and "text" in item.get("architecture", {}).get("output_modalities", [])),
                  key=lambda model: model.name.casefold())


class CloudMessage(Message):
    cloud_calls: list[dict] | None = None
    reasoning_details: list[dict] | None = None


class OpenRouter:
    def request(self, method, endpoint, *, payload=None, timeout=120):
        headers = {}
        if payload is not None:
            key = openrouter_key()
            if not key:
                raise ResponseError("Falta la clave de OpenRouter. Configúrala desde el engrane.")
            headers["Authorization"] = f"Bearer {key}"
        try:
            response = httpx.request(method, OPENROUTER_URL + endpoint, json=payload, headers=headers,
                                     timeout=timeout, follow_redirects=False)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            detail = {400: "Revisa el modelo y sus capacidades.", 401: "Revisa la clave API.",
                      402: "Revisa el saldo de OpenRouter.", 429: "Se alcanzó el límite de solicitudes."}
            raise ResponseError(f"OpenRouter respondió con un error HTTP {code}. {detail.get(code, '')}".strip(), code) from None
        except (httpx.RequestError, ValueError):
            raise ResponseError("No se pudo comunicar con OpenRouter.") from None

    def show(self, model):
        catalog = self.request("GET", "/models", timeout=10)["data"]
        item = next((item for item in catalog if item["id"] == model), None)
        inputs = item.get("architecture", {}).get("input_modalities", []) if item else []
        return SimpleNamespace(capabilities=["vision"] if "image" in inputs else [])

    @staticmethod
    def messages_for_api(messages):
        pending = deque()
        result = []
        for raw in messages:
            source = raw.model_dump(exclude_none=True) if isinstance(raw, Message) else raw
            role = source["role"]
            content = source.get("content") or ""
            row = {"role": role, "content": content}
            if source.get("images"):
                row["content"] = [{"type": "text", "text": content}]
                for image in source["images"]:
                    mime = "image/jpeg" if image.startswith(b"\xff\xd8") else "image/webp" if image[8:12] == b"WEBP" else "image/png"
                    encoded = base64.b64encode(image).decode("ascii")
                    row["content"].append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
            if calls := source.get("cloud_calls"):
                row["tool_calls"] = calls
                pending.extend(call["id"] for call in calls)
                if source.get("reasoning_details"):
                    row["reasoning_details"] = source["reasoning_details"]
            if role == "tool":
                if not pending:
                    raise ResponseError("Falta la referencia de una herramienta de OpenRouter.")
                row["tool_call_id"] = pending.popleft()
            result.append(row)
        return result

    def chat(self, *, model, messages, tools=(), options=None, think=None, format=None):
        rows = self.messages_for_api(messages)
        if format:
            rows.insert(0, {"role": "system", "content": "Devuelve únicamente JSON con este esquema: " + json.dumps(format)})
        payload = {"model": model, "messages": rows}
        if tools:
            payload["tools"] = [tool.model_dump(exclude_none=True, by_alias=True) for tool in tools]
            payload["provider"] = {"require_parameters": True}
        if options:
            if "temperature" in options:
                payload["temperature"] = options["temperature"]
            if "num_predict" in options:
                payload["max_tokens"] = options["num_predict"]
        if think is True or (think is False and format):
            payload["reasoning"] = {"enabled": think}
        data = self.request("POST", "/chat/completions", payload=payload)
        try:
            choice = data["choices"][0]
            message = choice["message"]
            calls = message.get("tool_calls") or []
            content = message.get("content") or ""
            if format and content.lstrip().startswith("```"):
                content = content.strip().split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            tool_calls = [{"function": {"name": call["function"]["name"],
                                       "arguments": json.loads(call["function"]["arguments"])}} for call in calls]
            reply = CloudMessage(role="assistant", content=content, tool_calls=tool_calls,
                                 thinking=message.get("reasoning"), cloud_calls=calls,
                                 reasoning_details=message.get("reasoning_details"))
        except (KeyError, IndexError, TypeError, ValueError):
            raise ResponseError("OpenRouter devolvió una respuesta que StoneBot no pudo interpretar.") from None
        return SimpleNamespace(message=reply, done_reason=choice.get("finish_reason"),
                               prompt_eval_count=(data.get("usage") or {}).get("prompt_tokens"))

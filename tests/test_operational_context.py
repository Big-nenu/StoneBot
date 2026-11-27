"""Regresiones del contexto operativo y la ventana delegada a Ollama."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_provider import AISettings
from chat_execution import ChatContext
from operational_context import OllamaContext, observed_context, operational_prompt
from turn_worker import Worker


def test_metadata():
    info = {"model_info": {"general.architecture": "demo", "demo.context_length": 6144,
                           "otra.context_length": 999999}, "parameters": "temperature 0.7\n num_ctx 8192"}
    context = OllamaContext.from_metadata(info)
    assert (context.maximum, context.configured, context.history_chars) == (6144, 8192, 12288)
    assert OllamaContext.from_metadata({"model_info": "inválido"}).history_chars == 8192
    assert OllamaContext.from_metadata({"parameters": "num_ctx 131072"}).history_chars == 8192
    assert OllamaContext.from_metadata({"model_info": {"general.architecture": "demo",
                                                         "demo.context_length": 16384}}).history_chars == 8192


def test_session_prompt():
    project = dict(name="Ejemplo", description="d" * 2500 + "RECORTAR", instructions="Usa tablas",
                   folder="RUTA PRIVADA", continuity="CONTINUIDAD PRIVADA")
    prompt = operational_prompt(AISettings("openrouter"), task={}, project=project, preferences="Prefiero español")
    assert all(value in prompt for value in ("tarea guardada", "openrouter", "Usa tablas", "Prefiero español"))
    assert all(value not in prompt for value in ("RUTA PRIVADA", "CONTINUIDAD PRIVADA", "RECORTAR"))


async def test_compaction_preserves_protocol():
    context = ChatContext(4096)
    messages = [
        {"role": "system", "content": "Restricción vigente"},
        {"role": "user", "content": "CONSERVAR-HISTORIAL " * 400},
        {"role": "user", "content": "Solicitud actual"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "consulta"}]},
        {"role": "tool", "tool_call_id": "consulta", "tool_name": "leer", "content": "z" * 5000},
    ]
    view = context.view(messages)
    assert view[0] == messages[0] and view[-3:-1] == messages[2:4]
    assert view[-1]["tool_call_id"] == "consulta" and len(view[-1]["content"]) < 2000
    assert "[Resultado abreviado, referencia 5" in view[-1]["content"]
    recalled = await context.read("read_chat_context", {"reference": 5, "offset": 4500})
    assert "z" * 500 in recalled.content
    assert messages[-1]["content"] == "z" * 5000


async def test_trace_observation():
    entries = {"models": [{"model": "demo", "context_length": 8192, "size_vram": 0},
                          {"model": "otra:latest", "context_length": 65536, "size_vram": 10}]}
    with patch("operational_context.ollama_metadata", new=AsyncMock(return_value=entries)):
        assert await observed_context("demo:latest") == {"tokens_observados": 8192, "bytes_vram_observados": 0}
        assert await observed_context("sin-cargar") == {}
        entries["models"].append(entries["models"][0])
        assert await observed_context("demo") == {}

    captured = []
    worker = Worker([], trace=lambda event, **fields: captured.append((event, fields)))
    worker.ollama_context = OllamaContext(16384, 8192)
    response = SimpleNamespace(message=SimpleNamespace(tool_calls=[]), prompt_eval_count=1200, eval_count=40)
    with (patch.object(worker, "_model_request", new=AsyncMock(return_value=response)) as request,
          patch("turn_worker.observed_context", new=AsyncMock(return_value={"tokens_observados": 8192}))):
        await worker.model_request(None, "chat", options={"temperature": 0, "num_ctx": 4096})
        assert request.await_args.kwargs["options"] == {"temperature": 0, "num_ctx": 4096}
    assert captured[0][1]["contexto_maximo"] == 16384
    assert captured[0][1]["contexto_configurado"] == 8192
    assert captured[0][1]["presupuesto_historial_chars"] == 16384
    assert captured[0][1]["contexto_solicitado"] == 4096
    assert captured[1] == ("tokens_modelo", {"peticion": 1, "tokens_entrada": 1200, "tokens_salida": 40})
    assert captured[2] == ("contexto_ollama", {"peticion": 1, "tokens_observados": 8192})


if __name__ == "__main__":
    test_metadata()
    test_session_prompt()
    asyncio.run(test_compaction_preserves_protocol())
    asyncio.run(test_trace_observation())
    assert "app" not in sys.modules and "PySide6.QtWidgets" not in sys.modules
    print("PASS: ventana de Ollama, contexto, privacidad, compactación y traza")

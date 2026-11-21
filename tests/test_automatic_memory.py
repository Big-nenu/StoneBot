"""Verifica la selección y su conexión con el turno de chat."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app
import automatic_memory
import mcp_client
from chat_preferences import automatic_memory_enabled, save_automatic_memory


PREFERENCE = "Por cierto, prefiero que me des ejemplos cortos."
MESSAGE = {"role": "user", "content": f"{PREFERENCE} ¿Me ayudas con este archivo?"}


def test_capture():
    response = SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"recuerdos": [1, 3]})
    ))
    with patch.object(automatic_memory, "Client") as client:
        client.return_value.chat.return_value = response
        assert automatic_memory.select_memories(MESSAGE, app.MODEL) == [PREFERENCE]
        source = json.loads(client.return_value.chat.call_args.kwargs["messages"][-1]["content"])
        assert source == {"mensaje": MESSAGE["content"], "oraciones": {"1": PREFERENCE}}
        client.reset_mock()
        for message in (
            {"role": "assistant", "content": PREFERENCE},
            {**MESSAGE, "attachments": [{"name": "captura.png"}]},
            {**MESSAGE, "content": f"No quiero que guardes esto. {PREFERENCE}"},
            {**MESSAGE, "content": f"Mi contraseña es de prueba. {PREFERENCE}"},
            {**MESSAGE, "content": "¿Cómo funciona la memoria automática?"},
            {**MESSAGE, "content": f"«{PREFERENCE}»"},
            {**MESSAGE, "content": f"Ejemplo para el manual: {PREFERENCE}"},
            {**MESSAGE, "content": f"Corrige este texto:\n```\n{PREFERENCE}\n```"},
        ):
            assert automatic_memory.select_memories(message, app.MODEL) == []
        client.assert_not_called()


def test_chat_setting():
    async def finish_chat(_):
        return "Respuesta de prueba."

    memory = SimpleNamespace(call=AsyncMock(return_value="📍 NUEVA ONDA."))
    with TemporaryDirectory() as folder, patch.object(mcp_client, "default_root", return_value=Path(folder)), \
            patch.object(app.Worker, "chat", finish_chat), \
            patch.object(automatic_memory, "select_memories", return_value=[PREFERENCE]) as select:
        worker = app.Worker([MESSAGE], capture_memory=True, memory=memory)
        events, replies = [], []
        worker.activity.connect(events.append)
        worker.finished.connect(replies.append)
        assert automatic_memory_enabled()
        worker.run()
        select.assert_called_once_with(MESSAGE, app.MODEL)
        memory.call.assert_awaited_once_with("inject_memory", content=PREFERENCE)
        assert events == ["Guardé un recuerdo automáticamente."]
        save_automatic_memory(False)
        assert not automatic_memory_enabled()
        worker.run()
        assert select.call_count == 1
        assert replies == ["Respuesta de prueba."] * 2


def test_invalid_json_does_not_save_memories():
    def reply(content):
        return SimpleNamespace(message=SimpleNamespace(content=content))

    with patch.object(automatic_memory, "Client") as factory:
        chat = factory.return_value.chat
        chat.side_effect = [reply(""), reply('```json\n{"recuerdos":[1]}\n```')]
        assert automatic_memory.select_memories(MESSAGE, app.MODEL) == [PREFERENCE]
        assert chat.call_count == 2

    memory = SimpleNamespace(call=AsyncMock())
    with (patch.object(automatic_memory, "Client") as factory,
          patch.object(app, "automatic_memory_enabled", return_value=True),
          patch.object(app.Worker, "chat", new=AsyncMock(return_value="Respuesta de prueba."))):
        factory.return_value.chat.side_effect = [reply("respuesta de texto"), reply('{"recuerdos":[true]}')]
        worker = app.Worker([MESSAGE], capture_memory=True, memory=memory)
        notices, replies = [], []
        worker.mcp_notice.connect(notices.append)
        worker.finished.connect(replies.append)
        worker.run()
        memory.call.assert_not_awaited()
        assert "selección JSON válida" in notices[0]
        assert replies == ["Respuesta de prueba."]


if __name__ == "__main__":
    test_capture()
    test_chat_setting()
    test_invalid_json_does_not_save_memories()

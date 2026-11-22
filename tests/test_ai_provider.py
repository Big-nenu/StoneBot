"""Verifica configuración, enrutamiento en la nube y recortes del historial con datos de prueba."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, TextContent, Tool
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ollama import Message, ResponseError

import ai_provider
import app
import mcp_client
from ai_settings_ui import AISettingsDialog
from history_ui import MORE_ROLE, HistoryPanel


def test_openrouter():
    model = "fake/model"
    messages = [{"role": "system", "content": "Reglas"}, {"role": "user", "content": "Prueba"}]
    calls = [{"id": "call_123", "type": "function", "function": {
        "name": "query_experiences", "arguments": '{"busqueda":"prueba"}',
    }}]
    with patch.object(ai_provider.OpenRouter, "request") as request:
        request.return_value = {"choices": [{"message": {"tool_calls": calls}}]}
        client = ai_provider.OpenRouter()
        result = client.chat(model=model, messages=messages, tools=[app.EXPERIENCES_TOOL])
        payload = request.call_args.kwargs["payload"]
        assert payload["model"] == model and payload["tools"][0]["function"]["name"] == "query_experiences"
        assert result.message.tool_calls[0].function.arguments == {"busqueda": "prueba"}
        messages.extend([result.message, {"role": "tool", "tool_name": "query_experiences", "content": "Hecho"}])
        request.return_value = {"choices": [{"message": {"content": "Listo"}}]}
        assert client.chat(model=model, messages=messages).message.content == "Listo"
        assert request.call_args.kwargs["payload"]["messages"][-1]["tool_call_id"] == "call_123"

        request.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        assert json.loads(client.chat(model=model, messages=messages, think=False,
                                      format={"type": "object"}).message.content)["ok"]
        assert request.call_args.kwargs["payload"]["reasoning"] == {"enabled": False}

        request.return_value = {"choices": [{"message": {"content": "Imagen recibida"}}]}
        client.chat(model=model, messages=[{"role": "user", "content": "Imagen", "images": [b"\xff\xd8jpeg"]}])
        sent = request.call_args.kwargs["payload"]["messages"][0]["content"]
        assert sent[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openrouter_retries_textual_tool_call():
    client = ai_provider.OpenRouter()
    messages = [{"role": "user", "content": "Consulta las notas de StoneWave."}]
    tools = [app.ACTIVITY_TOOLS["recent_notes"]]
    text = "<tool_call> <function=recent_notes> <parameter=limit> 1 </parameter> </function> </tool_call>"
    malformed = {"choices": [{"message": {"content": text}}]}
    call = {"id": "call_recovered", "type": "function", "function": {
        "name": "recent_notes", "arguments": '{"limit":1}',
    }}
    native = {"choices": [{"message": {"tool_calls": [call]}}]}
    with patch.object(client, "request", side_effect=[malformed, native]) as request:
        recovered = client.chat(model="fake/model", messages=messages, tools=tools).message
        assert recovered.tool_calls[0].function.arguments == {"limit": 1}
        first, second = [entry.kwargs["payload"] for entry in request.call_args_list]
        assert first["tools"] == second["tools"]
        assert "tool_calls" in second["messages"][0]["content"]
        assert text not in str(second["messages"])
        results = [*messages, recovered, {
            "role": "tool", "tool_name": "recent_notes", "content": "Resultados",
        }]
        assert client.messages_for_api(results)[-1]["tool_call_id"] == "call_recovered"

    with patch.object(client, "request", return_value=malformed) as request:
        try:
            client.chat(model="fake/model", messages=messages, tools=tools)
        except ResponseError as error:
            assert "como texto" in str(error) and text not in str(error)
        else:
            raise AssertionError("La llamada textual no es una respuesta final")
        assert request.call_count == 2

    final = {"choices": [{"message": {"content": "Encontré las notas."}}]}
    with patch.object(client, "request", side_effect=[malformed, final]) as request:
        assert client.chat(model="fake/model", messages=results).message.content == "Encontré las notas."
        payload = request.call_args.kwargs["payload"]
        assert "tools" not in payload and "No solicites herramientas" in payload["messages"][0]["content"]


def test_memory_in_chat():
    messages = [{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": "Actualiza mi recuerdo"}]
    tool = Tool(name="update_memory", inputSchema={"type": "object"})
    session = SimpleNamespace(call_tool=AsyncMock(return_value=CallToolResult(
        content=[TextContent(type="text", text="Actualizado")],
    )))
    memory = SimpleNamespace(entries=AsyncMock(return_value={tool.name: (session, "stonewave", tool, False)}),
                             call=AsyncMock(return_value="Texto privado de memoria"))
    turn = app.Worker(messages, memory=memory)
    turn.confirm_external = AsyncMock(side_effect=AssertionError("Una corrección ordinaria no abre un diálogo"))
    results = [Message(role="assistant", tool_calls=[{"function": {"name": "update_memory", "arguments": {
        "fact_id": 4, "new_content": "Dato corregido",
    }}}]), Message(role="assistant", content="Listo")]
    with (patch.object(app, "Client") as ollama, patch.object(app, "load_servers", return_value={}),
          patch.object(app.Worker, "enabled_skills", return_value={})):
        ollama.return_value.chat.side_effect = [SimpleNamespace(message=result) for result in results]
        assert asyncio.run(turn.chat()) == "Listo"
    session.call_tool.assert_awaited_once_with("update_memory", {"fact_id": 4, "new_content": "Dato corregido"})
    turn.confirm_external.assert_not_awaited()

    memory.entries.reset_mock()
    cloud = app.Worker(messages, memory=memory, ai=ai_provider.AISettings("openrouter", "fake/model"))
    with (patch.object(app, "OpenRouter") as openrouter, patch.object(app, "load_servers", return_value={}),
          patch.object(app.Worker, "enabled_skills", return_value={})):
        openrouter.return_value.chat.return_value = SimpleNamespace(message=results[-1])
        assert asyncio.run(cloud.chat()) == "Listo"
        kwargs = openrouter.return_value.chat.call_args.kwargs
        assert kwargs["model"] == "fake/model" and "Texto privado de memoria" not in str(kwargs["messages"])
    memory.entries.assert_not_awaited()


def test_preferences_and_history():
    qt = QApplication.instance() or QApplication([])
    with (TemporaryDirectory() as folder, patch.object(mcp_client, "default_root", return_value=Path(folder)),
          patch.object(ai_provider, "store_key") as save_key):
        window = app.StoneBot()

        def configure(dialog):
            dialog.provider.setCurrentIndex(dialog.provider.findData("openrouter"))
            dialog.model.setText("fake/model")
            dialog.key.setText("test-key")
            dialog.save()
            return dialog.result()

        try:
            with patch.object(app.AISettingsDialog, "exec", configure):
                window.sidebar_rail.provider_badge.click()
            assert window.ai == ai_provider.load_ai() == ai_provider.AISettings("openrouter", "fake/model")
            assert "OpenRouter" in window.sidebar_rail.provider_badge.text()
            assert "fake/model" in window.sidebar_rail.provider_badge.toolTip()
            labels = {action.text() for action in window.settings_menu.actions()}
            assert {"Modelo y proveedor de IA…", "Apariencia…", "Servidores MCP…", "Memoria", "Skills"} <= labels
            save_key.assert_called_once_with(ai_provider.KEY_TARGET, "test-key")
            assert "test-key" not in (Path(folder) / "chat.ini").read_text(encoding="utf-8")
        finally:
            window.close()

    history = HistoryPanel()
    rows = [(idx, f"Conversación {idx}") for idx in range(25)]
    history.fill(rows, None)
    assert history.list.count() == 12
    more = history.list.item(11)
    assert more.data(MORE_ROLE)
    history.activate_row(more)
    assert history.list.count() == 22
    assert history.list.currentItem().data(Qt.ItemDataRole.UserRole) == 10
    history.search.setText("Conversación 24")
    history.fill(rows[-1:], None)
    assert history.list.count() == 1 and history.list.item(0).data(Qt.ItemDataRole.UserRole) == 24


def test_model_catalog():
    qt = QApplication.instance() or QApplication([])
    common = {"supported_parameters": ["tools"], "architecture": {"output_modalities": ["text"]}}
    zero = {"prompt": "0", "completion": "0.0"}
    with patch.object(ai_provider.OpenRouter, "request", return_value={"data": [
        dict(common, id="demo/atlas:free", name="Atlas sin costo", pricing=zero),
        dict(common, id="demo/atlas", name="Atlas", pricing={**zero, "completion": "0.00001"}),
        dict(common, id="other/fast", name="Fast", pricing=zero),
        dict(common, id="openrouter/auto", name="Auto", pricing={**zero, "prompt": "-1"}),
        dict(common, id="other/missing", name="Missing"),
        dict(common, id="other/no-tools:free", name="Sin herramientas", supported_parameters=[]),
    ]}):
        models = ai_provider.available_models("openrouter")
    assert {model.id: model.price for model in models} == {
        "demo/atlas:free": "Gratis", "demo/atlas": "De pago", "other/fast": "Tarifa de texto $0",
        "openrouter/auto": "Precio variable", "other/missing": "Consultar precio",
    }
    dialog = AISettingsDialog(None, app.load_appearance(), ai_provider.AISettings("openrouter", "demo/atlas"))
    try:
        dialog.show()
        dialog.finish_models("openrouter", models, "")
        qt.processEvents()
        assert dialog.results.geometry().bottom() < dialog.catalog_status.geometry().top()
        assert dialog.results.count() == 5
        dialog.search.setText("ATLAS demo")
        assert dialog.results.count() == 2
        assert dialog.model.text() == "demo/atlas"
        dialog.free_only.setChecked(True)
        assert dialog.results.count() == 1 and "Gratis" in dialog.results.item(0).text()
        dialog.results.itemActivated.emit(dialog.results.item(0))
        assert dialog.model.text() == "demo/atlas:free"
        dialog.search.setText("inexistente")
        assert dialog.results.count() == 0 and "No hay modelos" in dialog.catalog_status.text()
        dialog.free_only.setChecked(False)
        dialog.finish_models("openrouter", [], "Red no disponible")
        dialog.search.clear()
        assert dialog.results.count() == 5 and dialog.model.text() == "demo/atlas:free"
    finally:
        dialog.close()


if __name__ == "__main__":
    test_openrouter()
    test_openrouter_retries_textual_tool_call()
    test_memory_in_chat()
    test_preferences_and_history()
    test_model_catalog()
    print("PASS: OpenRouter simulado, memoria, configuración, catálogo e historial.")

"""Ejecutar con python -B tests/test_mcp.py."""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp
from ollama import Message

import app
import mcp_client


def example_stdio():
    # El servidor recibe un perfil aislado y no usa el directorio de paquetes de ese perfil.
    packages = str(Path(mcp.__file__).resolve().parents[1])
    example = str(Path(__file__).with_name("mcp_example.py").resolve())
    code = f"import runpy,site;site.addsitedir({packages!r});runpy.run_path({example!r},run_name='__main__')"
    return ["--command", sys.executable, "--arg=-B", "--arg=-c", "--arg", code]


def test_stdio_chat_and_permissions():
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        with (patch.object(mcp_client, "default_root", return_value=folder),
              patch.dict(os.environ, {"STONEBOT_TEST_PARENT_ONLY": "not inherited"})):
            def manage(*args):
                with patch.object(sys, "argv", ["mcp_client.py", *args]), contextlib.redirect_stdout(io.StringIO()) as out:
                    mcp_client.main()
                return out.getvalue()

            manage("add", "example", *example_stdio())
            assert not mcp_client.load_servers()["example"]["enabled"]
            manage("enable", "example")
            manage("allow-read", "example", "echo")
            assert '"echo"' in manage("list")
            manage("disable", "example")
            assert not mcp_client.load_servers()["example"]["enabled"]
            manage("enable", "example")

            marker = folder / "mcp" / "example" / "mcp-test-marker.txt"
            protected = folder / "protected"
            protected.mkdir()
            personal = protected / "memoria.db"
            personal.write_text("datos de prueba", encoding="utf-8")
            messages = [{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": "Prueba MCP"}]
            rounds = 0

            def chat(**kwargs):
                nonlocal rounds
                rounds += 1
                tools = {tool.function.name: tool.function.description for tool in kwargs["tools"]
                         if not callable(tool)}
                assert len(tools) == 2, tools
                echo, = [alias for alias, desc in tools.items() if " / echo." in desc]
                mark, = [alias for alias, desc in tools.items() if " / mark." in desc]
                transcript = kwargs["messages"]
                if rounds == 1:
                    assert len([tool for tool in kwargs["tools"] if callable(tool)]) == 3
                    requests = [(echo, {}), (echo, {"text": str(personal)}),
                                (echo, {"text": "hola"}), (mark, {"text": "rechazado"})]
                elif rounds == 2:
                    assert "esquema" in transcript[-4]["content"]
                    assert "bloqueada" in transcript[-3]["content"]
                    assert "Eco MCP: hola" in transcript[-2]["content"]
                    assert "no autorizó" in transcript[-1]["content"]
                    assert not marker.exists()
                    requests = [(mark, {"text": "aprobado"})]
                else:
                    assert "Marca escrita" in transcript[-1]["content"]
                    return SimpleNamespace(message=Message(role="assistant", content="Terminado"))
                calls = [Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=args))
                         for name, args in requests]
                return SimpleNamespace(message=Message(role="assistant", tool_calls=calls))

            worker = app.Worker(messages)
            outputs, errors = [], []
            worker.finished.connect(outputs.append)
            worker.error.connect(errors.append)
            confirm = AsyncMock(side_effect=[False, True])
            with (patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
                  patch("stonebot_engine.safety.protected_paths", return_value=[protected]),
                  patch.object(worker, "confirm_external", confirm)):
                worker.run()
            assert not errors, errors
            assert outputs == ["Terminado"]
            assert confirm.await_count == 2
            assert personal.read_text(encoding="utf-8") == "datos de prueba"
            assert marker.read_text(encoding="utf-8") == "aprobado"
            manage("revoke-read", "example", "echo")
            assert mcp_client.load_servers()["example"]["read_tools"] == []
            manage("remove", "example")
            assert not mcp_client.load_servers()


if __name__ == "__main__":
    test_stdio_chat_and_permissions()
    print("PASS: configuración, chat MCP STDIO, lectura autorizada, validación y confirmación de escritura.")

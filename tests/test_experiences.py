"""Demostración reproducible con dos procesos GUI y un servidor MCP STDIO real."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from ollama import Message

from test_mcp import example_stdio
import turn_worker
import app
import mcp_client
import stonebot_service as memory_service
from experiences import query_experiences, record_experience
from stonebot_engine.safety import IsolationError


def request(name, arguments):
    call = Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=arguments))
    return SimpleNamespace(message=Message(role="assistant", tool_calls=[call]))


def demo(root, stage, *, live=False):
    qt = QApplication([])
    db = root / "experiences.sqlite3"
    payload = "prueba-privada-42"
    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(turn_worker, "automatic_memory_enabled", return_value=False),
          patch.object(memory_service, "DB_PATH", root / "memoria.db")):
        if stage == "registrar":
            command, *args = example_stdio()[1:]
            args = [arg.removeprefix("--arg=") for arg in args if arg != "--arg"]
            mcp_client.save_servers({"demo": dict(transport="stdio", command=command, args=args,
                                                  enabled=True, read_tools=["echo"], disabled_tools=["mark"])})

        def model(**call):
            last = call["messages"][-1]
            if stage == "registrar":
                if isinstance(last, dict) and last["role"] == "user":
                    echo, = [tool.function.name for tool in call["tools"]
                             if tool.function.name.startswith("mcp_demo_echo_")]
                    return request(echo, {} if "inválida" in last["content"] else {"text": payload})
                if "esquema" in last["content"]:
                    answer = "El esquema rechazó los argumentos."
                else:
                    assert f"Eco MCP: {payload}" in last["content"]
                    answer = "El servidor devolvió el texto de prueba."
                    if "observación guardada" in last["content"]:
                        answer += " Observación guardada."
            else:
                if last["role"] == "user":
                    assert len(call["messages"]) == 2
                    assert turn_worker.EXPERIENCES_TOOL in call["tools"]
                    return request("query_experiences", {"busqueda": "demo echo"})
                row, = json.loads(last["content"])["datos"]
                assert row["evidencia_actual"]["tipo"] == "hecho observado"
                assert row["evidencia_actual"]["id"] == 1
                assert payload not in last["content"]
                answer = f"{row['conclusion']} {row['incertidumbre']}"
            return SimpleNamespace(message=Message(role="assistant", content=answer))

        window = app.StoneBot()
        window.show()
        verified = []
        if live:
            client = turn_worker.Client(host="http://localhost:11434", timeout=110)

            def live_model(**call):
                last = call["messages"][-1]
                if isinstance(last, dict) and last["role"] == "tool":
                    if stage == "registrar" and f"Eco MCP: {payload}" in last["content"]:
                        verified.append(last["content"])
                    elif stage == "recuperar" and last.get("tool_name") == "query_experiences":
                        items = json.loads(last["content"])["datos"]
                        if any(item["evidencia_actual"]["id"] == 1 for item in items):
                            verified.append(last["content"])
                return client.chat(**call)

        def send(text):
            window.message.setPlainText(text)
            window.enviar()
            loop = QEventLoop()
            window.thread.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(120_000 if live else 15_000)
            loop.exec()
            timer.stop()
            qt.processEvents()
            assert window.thread is None and window.messages[-1]["role"] == "assistant"
            return window.messages[-1]["content"]

        with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=live_model if live else model)):
            if stage == "registrar":
                if not live:
                    assert "devolvió" in send("Prueba el servidor demo con echo.")
                    assert "inválidos" in send("/aprender Haz una llamada inválida a demo echo.")
                    assert not db.exists()
                result = send(f"/aprender Usa la herramienta MCP echo del servidor demo con el texto exacto {payload}. "
                              "Explica el resultado y qué queda sin comprobar.")
                assert db.is_file()
                assert verified if live else "Observación guardada" in result
                assert payload.encode() not in db.read_bytes()
            else:
                if live:
                    result = send("¿Qué aprendiste sobre demo echo? Recupera la evidencia previa con query_experiences. "
                                  "Explica qué observaste y qué todavía no puedes asegurar. No repitas la ejecución.")
                    assert verified, result
                else:
                    result = send("¿Qué aprendiste sobre demo echo?")
                    assert "respuesta sin error" in result and "Se desconoce" in result
        window.close()
        window.deleteLater()
        qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        print(f"{stage}: {result}", flush=True)


def test_revision_and_isolation(root):
    with patch.object(mcp_client, "default_root", return_value=root):
        error = record_experience("demo", "echo", "tool_error")
        row, = json.loads(query_experiences("ECHO demo"))
        assert row["evidencia_actual"]["id"] == error
        assert row["evidencia_actual"]["tipo"] == "error observado"
        assert row["evidencia_contraria_anterior"]["id"] == 1
        assert "no se verificó" in row["hipotesis"]
        assert json.loads(query_experiences("otro servidor")) == []
        success = record_experience("demo", "echo", "response")
        row, = json.loads(query_experiences("echo"))
        assert row["evidencia_actual"]["id"] == success
        assert row["evidencia_contraria_anterior"]["id"] == error
    protected = root / "protected"
    protected.mkdir()
    sentinel = protected / "experiences.sqlite3"
    sentinel.write_bytes(b"personal sentinel")
    with (patch.object(mcp_client, "default_root", return_value=protected),
          patch("stonebot_engine.safety.protected_paths", return_value=[protected])):
        for operation in (lambda: query_experiences(""), lambda: record_experience("demo", "echo", "response")):
            try:
                operation()
            except IsolationError:
                pass
            else:
                raise AssertionError("La ruta protegida quedó accesible.")
    assert sentinel.read_bytes() == b"personal sentinel"


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        demo(Path(sys.argv[1]), sys.argv[2], live="--live" in sys.argv)
    else:
        live = "--live" in sys.argv
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stage in ("registrar", "recuperar"):
                subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), str(root), stage,
                                *(["--live"] if live else [])], check=True, timeout=140 if live else 30)
            if not live:
                test_revision_and_isolation(root)
        print("PASS: reinicio de la aplicación y evidencia MCP.")

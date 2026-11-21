"""Dos turnos separados por una reapertura, con historial y MCP STDIO temporales."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QInputDialog

import app
import mcp_client
from test_mcp import example_stdio


def check_continuity(live):
    with TemporaryDirectory() as directory, patch.object(mcp_client, "default_root", return_value=Path(directory)):
        config = dict(transport="stdio", command=sys.executable, args=["-B", "-c", example_stdio()[-1]],
                      enabled=True, read_tools=["echo"], disabled_tools=["mark"])
        mcp_client.save_servers({"ejemplo": config})
        def enter():
            box = QApplication.activeModalWidget()
            assert isinstance(box, QInputDialog)
            box.setTextValue("Responde siempre en español. Para un eco exitoso incluye «Eco confirmado».")
            box.accept()

        def send(window, text):
            window.message.setPlainText(text)
            window.send.click()
            loop = QEventLoop()
            window.thread.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(120_000 if live else 25_000)
            loop.exec()
            assert window.thread is None
            messages = window.history.messages(window.chat_id)
            assert messages[-1]["role"] == "assistant", window.problem.text()
            return messages[-1]["content"]

        def close(window):
            window.close()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        challenge = "LIMA-631"
        objective = ("Verifica el eco con la herramienta MCP del servidor ejemplo. Necesitas una clave que "
                     "todavía no te he dado. Pídeme la clave y, cuando la tenga, usa la herramienta para verificarla.")
        actual = app.Client(host="http://localhost:11434", timeout=90) if live else None
        calls = []

        def chat(**kwargs):
            rows = kwargs["messages"]
            assert "Eco confirmado" in rows[0]["content"]
            assert objective in rows[1]["content"]
            calls.append(tuple(row["role"] for row in rows))
            if actual is not None:
                kwargs["options"] = {**kwargs["options"], "temperature": 0}
                return actual.chat(**kwargs)
            if len(rows) == 2:
                reply = Message(role="assistant", content="¿Cuál es la clave?")
            elif rows[-1]["role"] == "user":
                assert rows[-2]["content"] == "¿Cuál es la clave?" and rows[-1]["content"] == challenge
                alias, = (tool.function.name for tool in kwargs["tools"]
                          if getattr(tool, "function", None) and tool.function.name.startswith("mcp_ejemplo_echo_"))
                reply = Message(role="assistant", tool_calls=[{"function": dict(name=alias, arguments={"text": challenge})}])
            else:
                assert rows[-1]["content"] == f"Eco MCP: {challenge}"
                reply = Message(role="assistant", content=f"Eco confirmado. Recibí {challenge}.")
            return SimpleNamespace(message=reply)

        with (patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
              patch.object(app.StoneWaveMemory, "entries", return_value={}),
              patch.object(app.Worker, "enabled_skills", return_value={})):
            window = app.StoneBot()
            window.show()
            try:
                QTimer.singleShot(0, enter)
                window.open_instructions()
                assert "Eco confirmado" in app.load_instructions()
                question = send(window, objective)
                assert "clave" in question.casefold() and len(calls) == 1, question
                chat_id = window.chat_id
            finally:
                close(window)
            window = app.StoneBot()
            window.show()
            try:
                window.open_chat(chat_id)
                answer = send(window, challenge)
                assert challenge in answer and "eco confirmado" in answer.casefold(), answer
                assert any(roles[-1] == "tool" for roles in calls), calls
                assert len(window.history.messages(chat_id)) == 4
            finally:
                close(window)
        if live:
            print("Ollama:", question, "→", answer)


if __name__ == "__main__":
    qt = QApplication([])
    assert app.model_context(48_164) == 32_768
    check_continuity("--live" in sys.argv)
    print("PASS: aclaración, reapertura, preferencias de idioma y MCP STDIO.")

"""Ciclo de vida de la bandeja con un perfil de StoneBot temporal."""
import asyncio
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import app
import mcp_client
import stonebot_service as service


def test_tray(root, *, native=False):
    finish_turn = Event()
    failures, events, windows, applications = [], [], [], []

    async def chat(worker):
        await asyncio.to_thread(finish_turn.wait, 20)
        events.append("chat")
        return "Respuesta de prueba."

    class TestWindow(app.StoneBot):
        def __init__(self, *, use_tray):
            super().__init__(use_tray=use_tray)
            if native:
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            windows.append(self)
            applications.append(QApplication.instance())
            QTimer.singleShot(0, self.exercise)

        def exercise(self):
            try:
                assert self.isVisible() and self.tray.isVisible() and not self.tray.icon().isNull()
                open_action, exit_action = self.tray.contextMenu().actions()
                self.close()
                assert not self.isVisible()
                assert not QApplication.instance().quitOnLastWindowClosed()
                assert not (root / "memoria.db").exists()

                open_action.trigger()
                assert self.isVisible()
                self.message.setPlainText("Prueba de cierre con un turno activo")
                self.enviar()
                self.close()
                assert not self.isVisible() and self.thread is not None
                self.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
                assert self.isVisible()
                exit_action.trigger()
                assert self.exit_requested and self.thread is not None
            except BaseException as exc:
                failures.append(exc)
            finally:
                finish_turn.set()
                if self.tray is not None and not self.exit_requested:
                    self.request_exit()
                elif self.tray is None:
                    self.close()

    tray_detection = nullcontext() if native else patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(service, "get_memory", side_effect=AssertionError("Motor anterior")),
          patch.object(app.Worker, "capture_user_memories"),
          patch.object(app.Worker, "chat", chat),
          patch.object(app, "StoneBot", TestWindow),
          tray_detection):
        assert app.main() == 0
    if failures:
        raise failures[0]
    window = windows[0]
    assert events == ["chat"]
    assert not window.tray.isVisible()
    assert window.thread is None
    assert not (root / "memoria.db").exists()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_tray(Path(directory).resolve(), native="--native" in sys.argv)
    print("PASS: bandeja, reapertura, turno activo y salida.")

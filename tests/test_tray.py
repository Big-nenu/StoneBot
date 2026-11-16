"""Ciclo de vida de la bandeja con un perfil de StoneBot temporal."""
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from test_servicio import otro_proceso_toma_el_candado

import app
import mcp_client
import stonebot_service as service


def test_tray(root, *, native=False):
    database = root / "memoria.db"
    dream_started, let_dream_finish = Event(), Event()
    failures, events, windows, applications = [], [], [], []

    def dream(scope):
        events.append(scope)
        dream_started.set()
        let_dream_finish.wait(20)

    async def chat(worker):
        assert let_dream_finish.is_set()
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
                assert not self.isVisible() and self.dream_timer.isActive()
                assert not QApplication.instance().quitOnLastWindowClosed()
                assert otro_proceso_toma_el_candado(database) == "ocupado"
                self.last_activity = time.monotonic() - self.dream_idle_seconds - 1
                self.dream_timer.start(10)
                QTest.qWait(80)
                assert dream_started.is_set() and events == ["memoria"] and not self.isVisible()

                open_action.trigger()
                assert self.isVisible() and self.dream_timer.isActive()
                self.message.setPlainText("Prueba de cierre con un turno activo")
                self.enviar()
                self.close()
                assert not self.isVisible() and self.thread is not None
                self.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
                assert self.isVisible()
                exit_action.trigger()
                assert self.exit_requested and self.thread is not None and not self.dream_timer.isActive()
                assert otro_proceso_toma_el_candado(database) == "ocupado"
            except BaseException as exc:
                failures.append(exc)
            finally:
                let_dream_finish.set()
                if self.tray is not None and not self.exit_requested:
                    self.request_exit()
                elif self.tray is None:
                    self.close()

    tray_detection = nullcontext() if native else patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True)
    with (patch.object(mcp_client, "default_root", return_value=root),
          patch.object(service, "DB_PATH", database),
          patch.object(service, "dream_if_due", side_effect=dream),
          patch.object(app.Worker, "chat", chat),
          patch.object(app, "StoneBot", TestWindow),
          tray_detection):
        assert app.main() == 0
    if failures:
        raise failures[0]
    window = windows[0]
    assert events == ["memoria", "chat"]
    assert not window.tray.isVisible() and not window.dream_timer.isActive()
    assert window.thread is None and not window.dream_thread.is_alive()
    assert otro_proceso_toma_el_candado(database) == "libre"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        test_tray(Path(directory).resolve(), native="--native" in sys.argv)
    print("PASS: bandeja, reapertura, sueño oculto, salida y candado entre procesos.")

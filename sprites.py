"""Reproduce la hoja de sprites de StoneBot. Las filas del mapa empiezan en 1."""
from functools import lru_cache
from pathlib import Path
from random import choice, randint
from typing import NamedTuple

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


FRAME_WIDTH = 192
FRAME_HEIGHT = 208
SHEET_PATH = Path(__file__).resolve().parent / "assets" / "stonebot-sprites.png"


class Animation(NamedTuple):
    row: int
    frames: int
    interval_ms: int


ANIMATIONS = {
    "reposo": Animation(1, 6, 110),
    "caminar_derecha": Animation(2, 8, 110),
    "caminar_izquierda": Animation(3, 8, 110),
    "saludar": Animation(4, 4, 175),
    "contento": Animation(5, 5, 125),
    "triste": Animation(6, 8, 145),
    "sorprendido": Animation(7, 6, 145),
    "cargando": Animation(8, 6, 170),
    "dormido": Animation(9, 3, 200),
    "atento": Animation(10, 8, 115),
    "mirar_derecha": Animation(10, 8, 115),
    "mirar_izquierda": Animation(11, 8, 115),
}

WALKS = ("caminar_derecha", "caminar_izquierda")
GLANCES = ("mirar_derecha", "mirar_izquierda")


@lru_cache(maxsize=1)
def sprite_sheet():
    return QPixmap(str(SHEET_PATH))


@lru_cache(maxsize=160)
def sprite_frame(width, name, index):
    row = ANIMATIONS[name].row - 1
    pixmap = sprite_sheet().copy(index * FRAME_WIDTH, row * FRAME_HEIGHT, FRAME_WIDTH, FRAME_HEIGHT)
    return pixmap.scaledToWidth(width, Qt.TransformationMode.FastTransformation)


class SpriteLabel(QLabel):
    def __init__(self, width):
        super().__init__()
        self.sprite_width = width
        self.setAccessibleName("Robot de StoneBot")
        self.set_frame("reposo", 0)

    @Slot(str, int)
    def set_frame(self, animation, index):
        self.setPixmap(sprite_frame(self.sprite_width, animation, index))


class SpritePlayer(QObject):
    frame_changed = Signal(str, int)

    def __init__(self, parent, *, reduced=False):
        super().__init__(parent)
        self.reduced = reduced
        self.empty = False
        self.responding = False
        self.name = "reposo"
        self.index = 0
        self.frames = self.timer(self.advance)
        self.idle = self.timer(self.sleep)
        self.walk = self.timer(lambda: self.ambient(WALKS))
        self.glance = self.timer(lambda: self.ambient(GLANCES))
        self.typing_pause = self.timer(self.end_typing)
        self.warning_pause = self.timer(self.end_warning)
        self.sad_pause = self.timer(self.rest)

    def timer(self, callback):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        return timer

    def set_reduced(self, reduced):
        if self.reduced == reduced:
            return
        self.reduced = reduced
        self.stop_ambient()
        self.typing_pause.stop()
        self.warning_pause.stop()
        self.sad_pause.stop()
        if self.responding:
            self.play(self.name if self.name in {"sorprendido", "cargando"} else "cargando")
        else:
            self.rest()
            self.user_activity()

    def play(self, name):
        self.frames.stop()
        self.name, self.index = name, 0
        self.draw()
        if self.reduced:
            return
        if name == "reposo":
            if self.empty:
                self.frames.start(randint(4000, 8000))
        else:
            self.frames.start(ANIMATIONS[name].interval_ms)

    def draw(self):
        name, index = ("reposo", 0) if self.reduced else (self.name, self.index)
        self.frame_changed.emit(name, index)

    def advance(self):
        animation = ANIMATIONS[self.name]
        if self.index + 1 < animation.frames:
            self.index += 1
        elif self.name in {"cargando", "sorprendido"}:
            self.index = 0
        elif self.name in {"atento", "dormido", "triste"}:
            return
        else:
            self.rest()
            return
        self.draw()
        self.frames.start(animation.interval_ms)

    def rest(self):
        self.play("reposo")

    def ambient(self, options):
        timer = self.walk if options is WALKS else self.glance
        if self.empty and not self.reduced:
            if self.name == "reposo":
                self.play(choice(options))
            timer.start(randint(30000, 60000) if timer is self.walk else randint(9000, 22000))

    def stop_ambient(self):
        for timer in (self.idle, self.walk, self.glance):
            timer.stop()

    def set_empty(self, empty, *, greet=False):
        changed = self.empty != empty
        self.empty = empty
        if not changed and not greet:
            return
        self.stop_ambient()
        self.typing_pause.stop()
        if self.responding:
            return
        self.play("saludar" if empty and greet and not self.reduced else "reposo")
        self.user_activity()

    def user_activity(self):
        if not self.empty or self.reduced or self.responding:
            return
        if self.name == "dormido" or self.name in WALKS + GLANCES:
            self.rest()
        self.idle.start(120000)
        self.walk.start(randint(30000, 60000))
        self.glance.start(randint(9000, 22000))

    def typing(self):
        if not self.empty or self.responding or self.reduced:
            return
        self.user_activity()
        if self.name != "atento":
            self.play("atento")
        # Deja terminar la secuencia incluso si se escribió una sola tecla.
        animation = ANIMATIONS["atento"]
        self.typing_pause.start(max(1100, animation.frames * animation.interval_ms))

    def end_typing(self):
        if self.name == "atento":
            self.rest()

    def sleep(self):
        self.stop_ambient()
        self.play("dormido")

    def thinking(self):
        self.responding = True
        self.stop_ambient()
        self.typing_pause.stop()
        self.warning_pause.stop()
        self.sad_pause.stop()
        self.play("cargando")

    def warning(self, *, briefly=False):
        if self.responding:
            self.warning_pause.stop()
            self.play("sorprendido")
            if briefly:
                self.warning_pause.start(1250)

    def end_warning(self):
        self.warning_pause.stop()
        if self.responding and self.name == "sorprendido":
            self.play("cargando")

    def finish(self, success):
        self.responding = False
        self.warning_pause.stop()
        if self.reduced:
            self.rest()
        else:
            self.play("contento" if success else "triste")
            if not success:
                self.sad_pause.start(2000)

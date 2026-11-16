"""Adjuntos con archivos e historial temporales. Usa --live para probar con Ollama."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

from test_chat_presentation import wait_for_turn
import app
import attachments
import mcp_client
from chat_ui import ChatText
from history import History
from stonebot_engine.safety import IsolationError


def make_files(root):
    image = QImage(320, 240, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    with QPainter(image) as painter:
        painter.setBrush(QColor("#ed1717"))
        painter.drawEllipse(75, 35, 170, 170)
    for suffix in ("png", "jpg", "webp"):
        assert image.save(str(root / f"figura.{suffix}"))

    content = b"BT /F1 18 Tf 40 140 Td (Codigo PDF: CEDRO-742) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    pdf, offsets = bytearray(b"%PDF-1.4\n"), []
    for index, data in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + data + b"\nendobj\n")
    start = len(pdf)
    pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    pdf.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets))
    pdf.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    (root / "documento.pdf").write_bytes(pdf)
    (root / "notas.txt").write_text("Código del archivo de texto: LUNA-531.", encoding="utf-8")


def reject(path, error):
    try:
        attachments.read_attachment(path)
    except error:
        return
    raise AssertionError(f"El archivo debía rechazarse: {path.name}")


def test_files(root):
    for suffix in ("png", "jpg", "webp"):
        item = attachments.read_attachment(root / f"figura.{suffix}")
        payload, vision, partial = attachments.ollama_messages([{"role": "user", "content": "", "attachments": [item]}])
        assert vision and not partial and payload[0]["images"][0].startswith(b"\xff\xd8")
    assert "CEDRO-742" in attachments.read_attachment(root / "documento.pdf")["text"]
    assert "LUNA-531" in attachments.read_attachment(root / "notas.txt")["text"]
    long_file = root / "largo.txt"
    long_file.write_text("A" * (attachments.MAX_TEXT + 2), encoding="utf-8")
    assert attachments.read_attachment(long_file)["partial"]
    with patch.object(attachments, "MAX_BYTES", 4):
        reject(root / "notas.txt", ValueError)
    reject(Path("notas.txt"), ValueError)
    with patch("stonebot_engine.safety.protected_paths", return_value=[root / "notas.txt"]):
        reject(root / "notas.txt", IsolationError)
    invalid = root / "invalida.png"
    invalid.write_bytes((root / "notas.txt").read_bytes())
    reject(invalid, ValueError)
    renamed = root / "renombrada.png"
    renamed.write_bytes((root / "figura.jpg").read_bytes())
    reject(renamed, ValueError)
    alias = root / "alias.txt"
    os.link(root / "notas.txt", alias)
    try:
        reject(alias, IsolationError)
    finally:
        alias.unlink()


def test_window(root):
    window = app.StoneBot()
    window.show()
    calls = []

    def respond(**request):
        calls.append(request)
        return SimpleNamespace(message=SimpleNamespace(content="Leí los adjuntos."))

    client = SimpleNamespace(show=lambda model: SimpleNamespace(capabilities=["vision"]), chat=respond)
    try:
        with patch.object(QFileDialog, "getOpenFileNames", return_value=(
                [str(root / name) for name in ("figura.png", "figura.jpg", "documento.pdf", "notas.txt")], "")):
            window.attachments.add_button.click()
        assert len(window.attachments.files) == 4
        remove = next(button for button in window.attachments.findChildren(QPushButton)
                      if button.accessibleName() == "Quitar figura.jpg")
        remove.click()
        assert [file["name"] for file in window.attachments.files] == ["figura.png", "documento.pdf", "notas.txt"]
        assert window.attachments.add_button.geometry().right() < window.message.geometry().left()
        with (patch.object(app, "Client", return_value=client),
              patch.object(app, "load_servers", side_effect=AssertionError("Los adjuntos no pasan a MCP."))):
            window.message.setPlainText("Revisa los adjuntos")
            window.enviar()
            wait_for_turn(window)
            chat_id = window.chat_id
            saved = History().messages(chat_id)
            assert len(saved[0]["attachments"]) == 3 and not window.attachments.files
            request = calls[0]
            assert request["model"] == app.MODEL and not request.get("tools")
            assert isinstance(request["messages"][-1]["images"][0], bytes)
            assert all(word in request["messages"][-1]["content"] for word in ("CEDRO-742", "LUNA-531"))
            assert str(root) not in repr(saved)
            (root / "figura.png").unlink()
            (root / "notas.txt").unlink()
            window.new_chat()
            window.open_chat(chat_id)
            assert any("Adjuntos: figura.png, documento.pdf, notas.txt" in body.toPlainText()
                       for body in window.findChildren(ChatText))
            window.message.setPlainText("¿Cuál era el código del archivo de texto?")
            window.enviar()
            wait_for_turn(window)
            assert any("LUNA-531" in item["content"] for item in calls[-1]["messages"])
            window.regenerate(0, "Revisa los mismos adjuntos")
            wait_for_turn(window)
            regenerated = History().messages(chat_id)
            assert regenerated[0]["attachments"] == saved[0]["attachments"]
            assert regenerated[0]["content"] == "Revisa los mismos adjuntos" and len(regenerated) == 2
            assert not (root / "memoria.db").exists()

        with patch.object(app, "Client", return_value=SimpleNamespace(show=lambda model: SimpleNamespace(capabilities=[]))):
            worker = app.Worker([regenerated[0]])
            try:
                asyncio.run(worker.chat())
            except app.TurnError as exc:
                assert "no admite imágenes" in str(exc)
            else:
                raise AssertionError("Debe indicar que el modelo carece de visión.")
    finally:
        if window.thread is not None:
            wait_for_turn(window)
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def live(root):
    files = [attachments.read_attachment(root / name) for name in ("figura.png", "documento.pdf", "notas.txt")]
    prompt = ("Mira la imagen y responde en español: ¿de qué color es el círculo? "
              "Indica también el código exacto del PDF y el del archivo de texto. Responde en una frase.")
    worker = app.Worker([{"role": "system", "content": app.SYSTEM},
                         {"role": "user", "content": prompt, "attachments": files}])
    answer = asyncio.run(worker.chat())
    print(f"Ollama ({app.MODEL}):", json.dumps(answer, ensure_ascii=False))
    assert "rojo" in answer.casefold() and "CEDRO-742" in answer and "LUNA-531" in answer


if __name__ == "__main__":
    qt = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        make_files(root)
        with patch.object(mcp_client, "default_root", return_value=root):
            if "--live" in sys.argv:
                live(root)
            else:
                test_files(root)
                test_window(root)
    print("PASS: adjuntos de StoneBot.")

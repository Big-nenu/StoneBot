"""Adjuntos con archivos e historial temporales. Usa --live para probar con Ollama."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QPushButton

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

    make_pdf(root / "documento.pdf")
    scan = QImage(300, 200, QImage.Format.Format_RGB32)
    scan.fill(QColor("white"))
    with QPainter(scan) as painter:
        painter.fillRect(80, 45, 140, 110, QColor("#173de8"))
    path = root / "scan.jpg"
    assert scan.save(str(path))
    make_pdf(root / "mixto.pdf", path.read_bytes(), visual_pages=1)
    make_pdf(root / "escaneado.pdf", path.read_bytes(), visual_pages=9, text=False)
    (root / "notas.txt").write_text("Código del archivo de texto: LUNA-531.", encoding="utf-8")


def make_pdf(path, jpeg=None, *, visual_pages=0, text=True):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
    ]

    def stream(content, fields=b""):
        return b"<< " + fields + f" /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"

    page_objects = []
    if text:
        objects.extend([
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            stream(b"BT /F1 18 Tf 40 140 Td (Codigo PDF: CEDRO-742) Tj ET"),
        ])
        page_objects.append(3)
    if visual_pages:
        image = len(objects) + 1
        objects.extend([
            stream(jpeg, b"/Type /XObject /Subtype /Image /Width 300 /Height 200 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode"),
            stream(b"q 300 0 0 200 0 0 cm /Im Do Q"),
        ])
        for _ in range(visual_pages):
            page_objects.append(len(objects) + 1)
            objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
                           + f"/Resources << /XObject << /Im {image} 0 R >> >> /Contents {image + 1} 0 R >>".encode())
    kids = " ".join(f"{number} 0 R" for number in page_objects)
    objects[1] = f"<< /Type /Pages /Count {len(page_objects)} /Kids [{kids}] >>".encode()
    pdf, offsets = bytearray(b"%PDF-1.4\n"), []
    for index, data in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + data + b"\nendobj\n")
    start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    pdf.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets))
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    path.write_bytes(pdf)


def reject(path, error):
    try:
        attachments.read_attachment(path)
    except error:
        return
    raise AssertionError(f"El archivo debía rechazarse: {path.name}")


def test_files(root):
    for suffix in ("png", "jpg", "webp"):
        item = attachments.read_attachment(root / f"figura.{suffix}")
        payload, vision, partial, _ = attachments.ollama_messages([{"role": "user", "content": "", "attachments": [item]}])
        assert vision and not partial and payload[0]["images"][0].startswith(b"\xff\xd8")
    assert "CEDRO-742" in attachments.read_attachment(root / "documento.pdf")["pages"][0]["text"]
    mixed = attachments.read_attachment(root / "mixto.pdf")
    assert "CEDRO-742" in mixed["pages"][0]["text"] and attachments.attachment_images(mixed) == 1
    reject(root / "escaneado.pdf", attachments.PDFPageRange)
    part = attachments.read_attachment(root / "escaneado.pdf", (5, 8))
    assert attachments.attachment_label(part) == "escaneado.pdf · págs. 5–8 de 9"
    payload, vision, partial, coverage = attachments.ollama_messages([{"role": "user", "content": "", "attachments": [part]}])
    assert vision and partial and len(payload[0]["images"]) == 4
    assert '"páginas incluidas": [5, 6, 7, 8]' in payload[0]["content"]
    assert attachments.missing_pdf_pages("¿Puedes ver la página 1?", coverage)
    assert not attachments.missing_pdf_pages("Resume las páginas 5–8", coverage)
    recent = {"role": "user", "content": "", "attachments": [part]}
    old = {"role": "user", "content": "", "attachments": [mixed]}
    payload, _, _, _ = attachments.ollama_messages([old, recent])
    assert '"páginas incluidas": [1]' in payload[-1]["content"]
    assert "images" not in payload[0] and len(payload[-1]["images"]) == 4
    with patch.object(app, "Client", return_value=object()):
        worker = app.Worker([{**recent, "content": "¿Puedes ver la página 1?"}])
        assert "no están incluidas" in asyncio.run(worker.chat())
    client = SimpleNamespace(
        show=lambda model: SimpleNamespace(capabilities=["vision"]),
        chat=lambda **request: SimpleNamespace(message=SimpleNamespace(content="Veo la página 1.")),
    )
    with patch.object(app, "Client", return_value=client):
        worker = app.Worker([{**recent, "content": "Resume el tramo."}])
        assert "no se muestra" in asyncio.run(worker.chat())
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
        menu = window.attachments.add_button.menu()
        attach, mcp, memory, _, skills = menu.actions()
        assert attach.isEnabled() and mcp.isEnabled() and skills.isEnabled()
        with patch.object(app.SkillsDialog, "exec") as opened:
            skills.trigger()
            opened.assert_called_once_with()
        memory.menu().actions()[0].trigger()
        assert window.message.toPlainText() == "Busca en la memoria: "
        window.message.clear()
        mcp.menu().aboutToShow.emit()
        assert not mcp.menu().actions()[0].isEnabled()
        with patch.object(app.McpDialog, "exec") as opened:
            window.mcp_button.click()
            opened.assert_called_once_with()

        with (patch.object(QFileDialog, "getOpenFileNames", return_value=([str(root / "escaneado.pdf")], "")),
              patch.object(QInputDialog, "getText", return_value=("5-8", True)) as ask):
            attach.trigger()
            assert [page["number"] for page in window.attachments.files[0]["pages"]] == [5, 6, 7, 8]
            assert ask.call_args.kwargs["text"] == "1-4"
            menu.aboutToShow.emit()
            assert not memory.isEnabled()
        window.attachments.clear()

        opened = []

        def select_from_menu():
            opened.append(menu.isVisible())
            menu.close()
            attach.trigger()

        with patch.object(QFileDialog, "getOpenFileNames", return_value=(
                [str(root / name) for name in ("figura.png", "figura.jpg", "documento.pdf", "notas.txt")], "")):
            QTimer.singleShot(100, select_from_menu)
            window.attachments.add_button.click()
            QTest.qWait(150)
        assert opened == [True]
        assert len(window.attachments.files) == 4
        remove = next(button for button in window.attachments.findChildren(QPushButton)
                      if button.accessibleName() == "Quitar figura.jpg")
        remove.click()
        assert [file["name"] for file in window.attachments.files] == ["figura.png", "documento.pdf", "notas.txt"]
        assert window.attachments.add_button.geometry().left() == window.message.geometry().left()
        assert window.attachments.add_button.geometry().top() > window.message.geometry().bottom()
        with (patch.object(app, "Client", return_value=client),
              patch.object(app, "load_servers", side_effect=AssertionError("Los adjuntos no pasan a MCP."))):
            compact = window.message.height()
            window.message.expand_button.click()
            QTest.qWait(20)
            assert window.message.height() > compact
            controls = window.attachments.add_button, window.send
            anchors = [button.mapTo(window, QPoint()) for button in controls]
            window.message.setPlainText("Revisa los adjuntos")
            window.enviar()
            assert not window.attachments.add_button.isEnabled() and not window.history_panel.isEnabled()
            wait_for_turn(window)
            assert window.message.height() == compact and not window.message.expand_button.isChecked()
            assert [button.mapTo(window, QPoint()) for button in controls] == anchors
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
            menu.aboutToShow.emit()
            assert window.attachments.add_button.isEnabled() and window.history_panel.isEnabled()
            assert memory.isEnabled() and "chat nuevo" in memory.text() and mcp.isEnabled() and attach.isEnabled()
            window.message.setPlainText("Borrador sin enviar")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                memory.menu().actions()[1].trigger()
            assert window.chat_id == chat_id and window.message.toPlainText() == "Borrador sin enviar"
            window.message.clear()
            memory.menu().actions()[1].trigger()
            assert window.chat_id is None and window.message.toPlainText() == "Consulta las conclusiones de la memoria: "
            assert History().messages(chat_id) == regenerated

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
    files = [attachments.read_attachment(root / name) for name in ("figura.png", "figura.jpg", "mixto.pdf", "notas.txt")]
    prompt = ("¿De qué color son los círculos de las imágenes PNG y JPG, y de qué color es el rectángulo de la página 2 "
              "del PDF? Indica también el código de la página 1 del PDF y el código del TXT. Responde en español.")
    worker = app.Worker([{"role": "system", "content": app.SYSTEM},
                         {"role": "user", "content": prompt, "attachments": files}])
    answer = asyncio.run(worker.chat())
    print(f"Ollama ({app.MODEL}):", json.dumps(answer, ensure_ascii=False))
    assert all(word in answer.casefold() for word in ("rojo", "azul", "cedro-742", "luna-531"))


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

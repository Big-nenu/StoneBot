"""Adjuntos con archivos e historial temporales. Usa --live para probar con Ollama."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QEvent, QMimeData, QPoint, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox, QPushButton

from test_chat_presentation import wait_for_turn
import app
import attachments
import mcp_client
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
        batches, partial, _ = attachments.attachment_batches([{"attachments": [item]}])
        payload = {"content": ""}
        attachments.attach_batch(payload, batches[0])
        assert not partial and payload["images"][0].startswith(b"\xff\xd8")
    assert "CEDRO-742" in attachments.read_attachment(root / "documento.pdf")["pages"][0]["text"]
    mixed = attachments.read_attachment(root / "mixto.pdf")
    assert "CEDRO-742" in mixed["pages"][0]["text"] and "image" in mixed["pages"][1]
    full = attachments.read_attachment(root / "escaneado.pdf")
    assert len(full["pages"]) == 9 and not full["partial"]
    part = attachments.read_attachment(root / "escaneado.pdf", (5, 8))
    assert attachments.attachment_label(part) == "escaneado.pdf · págs. 5–8 de 9"
    batches, partial, coverage = attachments.attachment_batches([{"attachments": [part]}])
    assert partial and len(batches[0]) == 4
    assert attachments.missing_pdf_pages("¿Puedes ver la página 1?", coverage)
    assert not attachments.missing_pdf_pages("Resume las páginas 5–8", coverage)
    recent = {"role": "user", "content": "", "attachments": [part]}
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
    calls = []

    def review(**request):
        calls.append(request["messages"][-1])
        return SimpleNamespace(message=SimpleNamespace(content=f"Hallazgo {len(calls)}"))

    client.chat = review
    with patch.object(app, "Client", return_value=client):
        worker = app.Worker([{**recent, "content": "Resume el PDF.", "attachments": [full]}])
        assert asyncio.run(worker.chat()) == "Hallazgo 4"
    assert [len(item.get("images", [])) for item in calls] == [4, 4, 1, 0]
    assert "página 9" in calls[2]["content"] and "Hallazgo 3" in calls[3]["content"]
    assert "LUNA-531" in attachments.read_attachment(root / "notas.txt")["text"]
    long_file = root / "largo.txt"
    long_file.write_text("A" * (attachments.MAX_TEXT + 2), encoding="utf-8")
    batches, partial, _ = attachments.attachment_batches([{"attachments": [attachments.read_attachment(long_file)]}])
    assert not partial and [len(batch[0][1]["text"]) for batch in batches] == [attachments.MAX_TEXT, 2]
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
        attach, project_document, mcp, memory, _, skills, instructions = menu.actions()
        assert not project_document.isVisible()
        modes = window.reasoning_button.menu().actions()
        assert [mode.data() for mode in modes] == [None, False, True] and modes[0].isChecked()
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

        def paste(mime):
            QApplication.clipboard().setMimeData(mime)
            QTest.keyClick(window.message, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)

        capture = QMimeData()
        capture.setImageData(QImage(str(root / "figura.png")))
        paste(capture)
        copied = QMimeData()
        copied.setUrls([QUrl.fromLocalFile(str(root / "figura.jpg"))])
        copied.setText(str(root / "figura.jpg"))
        paste(copied)
        assert not window.message.toPlainText()
        assert [file["name"] for file in window.attachments.files] == [
            "Captura del portapapeles.jpg", "figura.jpg"]
        assert len(window.attachments.findChildren(app.AttachmentCard)) == 2
        assert all(not badge.pixmap().isNull() for badge in window.attachments.findChildren(QLabel)
                   if badge.objectName() == "attachmentBadge")
        window.attachments.clear()
        QApplication.clipboard().setText("Texto normal")
        QTest.keyClick(window.message, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert window.message.toPlainText() == "Texto normal"
        window.message.clear()

        with patch.object(QFileDialog, "getOpenFileNames",
                          return_value=([str(root / "escaneado.pdf")] * 5, "")):
            attach.trigger()
            assert len(window.attachments.files) == 5
            assert [page["number"] for page in window.attachments.files[0]["pages"]] == list(range(1, 10))
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
            modes[2].trigger()
            assert window.reasoning_button.text() == "Activado"
            assert (window.attachments.add_button.geometry().left() < window.reasoning_button.geometry().left()
                    < window.send.geometry().left())
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
            assert request["think"] is True
            assert isinstance(request["messages"][-1]["images"][0], bytes)
            assert all(word in request["messages"][-1]["content"] for word in ("CEDRO-742", "LUNA-531"))
            assert str(root) not in repr(saved)
            (root / "figura.png").unlink()
            (root / "notas.txt").unlink()
            window.new_chat()
            window.open_chat(chat_id)
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            cards = window.findChildren(app.AttachmentCard)
            assert len(cards) == 3
            assert {"figura.png", "documento.pdf", "notas.txt"} <= {
                label.toolTip() for card in cards for label in card.findChildren(QLabel)}
            assert any(not card.findChild(QLabel, "attachmentBadge").pixmap().isNull() for card in cards)
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


def test_project_documents(root):
    window = app.StoneBot()
    path = root / "notas.txt"
    history = window.history
    project = history.save_project("Proyecto con documentos", "", "", str(root))
    other_project = history.save_project("Otro proyecto", "", "", "")
    calls = []

    def respond(**request):
        calls.append(request)
        return SimpleNamespace(message=SimpleNamespace(content="El documento respalda el código indicado.", tool_calls=[]))

    client = SimpleNamespace(chat=respond)
    try:
        window.show_projects()
        with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
            window.project_page.document_requested.emit(project)
            window.project_page.document_requested.emit(project)
        [(document_id, saved_path)] = History().project_documents(project)
        assert saved_path == str(path)

        for code in ("LUNA-531", "ACTUALIZADO-842"):
            path.write_text(code, encoding="utf-8")
            window.new_project_chat(project)
            assert window.project_document_action.isVisible()
            with patch.object(app.QInputDialog, "getItem", return_value=(path.name, True)):
                window.project_document_action.trigger()
            window.message.setPlainText("¿Qué código dice el documento?")
            pending = app.new_task("Encargo pendiente")
            pending["status"] = "paused"
            window.task = pending
            with patch.object(window, "start_turn") as turn:
                window.enviar()
            turn.assert_called_once_with(task=None)
            assert window.task is pending
            messages = window.messages
            assert messages[-1]["attachments"] == [{"name": path.name, "project_document": document_id}]
            assert history.messages(window.chat_id)[0]["attachments"] == messages[-1]["attachments"]
            context = {"project": window.project, "project_document_path": history.project_document_path}
            with (patch.object(app, "Client", return_value=client),
                  patch.object(app.Worker, "enabled_skills", return_value={})):
                answer = asyncio.run(app.Worker(messages, **context).chat())
                assert path.name in answer and code in calls[-1]["messages"][-1]["content"]
                followup = [*messages, {"role": "assistant", "content": answer}, {"role": "user", "content": "Gracias"}]
                asyncio.run(app.Worker(followup, **context).chat())
                assert calls[-1]["tools"] and not any("attachments" in row for row in calls[-1]["messages"])
                assert code not in calls[-1]["messages"][-1]["content"]

        with patch.object(app.Worker, "enabled_skills", return_value={}):
            for invalid_project in (other_project, project):
                if invalid_project == project:
                    window.project_page.document_unlinked.emit(project, document_id)
                    assert path.is_file() and not history.project_documents(project)
                worker = app.Worker(messages, project={"id": invalid_project},
                                    project_document_path=history.project_document_path)
                try:
                    asyncio.run(worker.chat())
                except app.TurnError as exc:
                    assert "ya no está vinculado" in str(exc)
                else:
                    raise AssertionError("El documento debe pertenecer al proyecto del chat.")
    finally:
        window.close()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
                test_project_documents(root)
    print("PASS: adjuntos de StoneBot.")

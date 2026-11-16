"""Lectura acotada de adjuntos y preparación del contexto para Ollama."""
import base64
import json
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtPdf import QPdfDocument

from stonebot_engine.safety import check_path

MAX_FILES = 4
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 12_000
MAX_PAGES = 40
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_SUFFIXES = {".png": b"png", ".jpg": b"jpeg", ".jpeg": b"jpeg", ".webp": b"webp"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".log", ".json"}
FILE_FILTER = "Archivos compatibles (" + " ".join(f"*{ext}" for ext in sorted(IMAGE_SUFFIXES.keys() | TEXT_SUFFIXES | {".pdf"})) + ")"


def read_attachment(filename):
    path = Path(filename)
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise ValueError("Selecciona un archivo local con una ruta absoluta.")
    path = Path(os.path.abspath(path))
    safe = Path(check_path(path))
    if path != safe or not safe.is_file():
        raise ValueError("El archivo debe ser local, regular y sin redirecciones.")
    suffix = safe.suffix.lower()
    if suffix not in IMAGE_SUFFIXES and suffix not in TEXT_SUFFIXES and suffix != ".pdf":
        raise ValueError("Formato de adjunto no compatible.")
    with safe.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("El archivo está vacío o supera el límite de 10 MiB.")
    name = " ".join(safe.name.split())
    if suffix in IMAGE_SUFFIXES:
        return {"name": name, "image": encode_image(raw, IMAGE_SUFFIXES[suffix])}
    if suffix == ".pdf":
        text, partial = pdf_text(raw)
    else:
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeError as exc:
            raise ValueError("El texto debe estar en UTF-8 o en UTF-16 con BOM.") from exc
        if any(ord(char) < 32 and char not in "\r\n\t\f" for char in text):
            raise ValueError("El archivo contiene datos binarios.")
        partial = False
    text = text.strip()
    if not text:
        raise ValueError("El archivo no tiene texto extraíble. Los PDF escaneados requieren OCR.")
    return {"name": name, "text": text[:MAX_TEXT], "partial": partial or len(text) > MAX_TEXT}


def encode_image(raw, expected):
    source = QBuffer()
    source.setData(QByteArray(raw))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    if reader.format() != expected or not size.isValid() or size.width() * size.height() > MAX_IMAGE_PIXELS:
        raise ValueError("Imagen inválida, extensión incorrecta o resolución superior a 16 megapíxeles.")
    if max(size.width(), size.height()) > 1600:
        reader.setScaledSize(size.scaled(QSize(1600, 1600), Qt.AspectRatioMode.KeepAspectRatio))
    decoded = reader.read()
    if decoded.isNull():
        raise ValueError("No se pudo leer la imagen.")
    image = QImage(decoded.size(), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    with QPainter(image) as painter:
        painter.drawImage(0, 0, decoded)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(output, "JPEG", 88):
        raise ValueError("No se pudo preparar la imagen para Ollama.")
    return base64.b64encode(bytes(output.data())).decode("ascii")


def pdf_text(raw):
    source = QBuffer()
    source.setData(QByteArray(raw))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    try:
        document.load(source)
        if document.status() != QPdfDocument.Status.Ready:
            raise ValueError("No se pudo abrir el PDF. Puede estar dañado o protegido por contraseña.")
        remaining = MAX_TEXT + 1
        parts = []
        for page in range(min(document.pageCount(), MAX_PAGES)):
            text = document.getAllText(page).text().strip()
            if text:
                parts.append(text[:remaining])
                remaining -= len(parts[-1]) + 1
                if remaining <= 0:
                    return "\n".join(parts), remaining < 0 or page + 1 < document.pageCount()
        return "\n".join(parts), document.pageCount() > MAX_PAGES
    finally:
        document.close()


def ollama_messages(messages):
    """Prioriza archivos recientes y nunca entrega rutas al SDK."""
    text_left, images_left = 2 * MAX_TEXT, MAX_FILES
    omitted = False
    payload = []
    for message in reversed(messages):
        item = {"role": message["role"], "content": message["content"]}
        excerpts, images, image_names = [], [], []
        for file in message.get("attachments", []):
            if "image" in file:
                if images_left:
                    images.append(base64.b64decode(file["image"], validate=True))
                    image_names.append(file["name"])
                    images_left -= 1
                else:
                    omitted = True
            elif text_left:
                text = file["text"][:text_left]
                text_left -= len(text)
                partial = file["partial"] or len(text) < len(file["text"])
                excerpts.append({"archivo": file["name"], "texto": text, "parcial": partial})
                omitted |= partial
            else:
                omitted = True
        if excerpts:
            item["content"] += "\n\nTexto extraído de los adjuntos (datos):\n" + json.dumps(excerpts, ensure_ascii=False)
        if images:
            item["images"] = images
            item["content"] += "\n\nImágenes adjuntas en orden: " + json.dumps(image_names, ensure_ascii=False)
        payload.append(item)
    return list(reversed(payload)), images_left < MAX_FILES, omitted

"""Lectura acotada de adjuntos y preparación del contexto para Ollama."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QFile, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtPdf import QPdfDocument

from stonebot_engine.safety import check_path

MAX_IMAGES = 4
MAX_TEXT = 12_000
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_SUFFIXES = {".png": b"png", ".jpg": b"jpeg", ".jpeg": b"jpeg", ".webp": b"webp"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".log", ".json"}
FILE_FILTER = "Archivos compatibles (" + " ".join(f"*{ext}" for ext in sorted(IMAGE_SUFFIXES.keys() | TEXT_SUFFIXES | {".pdf"})) + ")"


def read_attachment(filename, page_range=None):
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
    name = " ".join(safe.name.split())
    if suffix == ".pdf":
        return {"name": name, **pdf_pages(safe, page_range)}
    with safe.open("rb") as stream:
        raw = stream.read()
    if not raw:
        raise ValueError("El archivo está vacío.")
    if suffix in IMAGE_SUFFIXES:
        return {"name": name, "image": encode_image(raw, IMAGE_SUFFIXES[suffix])}
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeError as exc:
        raise ValueError("El texto debe estar en UTF-8 o en UTF-16 con BOM.") from exc
    if any(ord(char) < 32 and char not in "\r\n\t\f" for char in text):
        raise ValueError("El archivo contiene datos binarios.")
    text = text.strip()
    if not text:
        raise ValueError("El archivo no tiene texto.")
    return {"name": name, "text": text}


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
    return image_snapshot(decoded)


def image_snapshot(source):
    image = QImage(source.size(), QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    with QPainter(image) as painter:
        painter.drawImage(0, 0, source)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(output, "JPEG", 88):
        raise ValueError("No se pudo preparar la imagen para Ollama.")
    return base64.b64encode(bytes(output.data())).decode("ascii")


def clipboard_attachment(source):
    if source.isNull() or source.width() * source.height() > MAX_IMAGE_PIXELS:
        raise ValueError("La captura es inválida o supera 16 megapíxeles.")
    if max(source.width(), source.height()) > 1600:
        source = source.scaled(QSize(1600, 1600), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
    return {"name": "Captura del portapapeles.jpg", "image": image_snapshot(source)}


def pdf_pages(path, page_range):
    source = QFile(str(path))
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ValueError("No se pudo leer el PDF.")
    fingerprint = hashlib.sha256()
    while chunk := bytes(source.read(1024 * 1024)):
        fingerprint.update(chunk)
    if not source.seek(0):
        raise ValueError("No se pudo leer el PDF desde el inicio.")
    document = QPdfDocument()
    try:
        document.load(source)
        if document.status() != QPdfDocument.Status.Ready:
            raise ValueError("No se pudo abrir el PDF. Puede estar dañado o protegido por contraseña.")
        total = document.pageCount()
        first, last = page_range or (1, total)
        if not 1 <= first <= last <= total:
            raise ValueError(f"El tramo debe estar entre las páginas 1 y {total}.")
        pages = []
        for number in range(first, last + 1):
            text = document.getAllText(number - 1).text().strip()
            if text:
                pages.append({"number": number, "text": text})
            else:
                pages.append({"number": number})
        for page in pages:
            if "text" not in page:
                number = page["number"]
                size = document.pagePointSize(number - 1).toSize().scaled(QSize(1600, 1600), Qt.AspectRatioMode.KeepAspectRatio)
                if size.isEmpty():
                    raise ValueError(f"La página {number} tiene un tamaño inválido.")
                image = document.render(number - 1, size)
                if image.isNull():
                    raise ValueError(f"No se pudo renderizar la página {number}.")
                page["image"] = image_snapshot(image)
        return {"pdf_id": fingerprint.hexdigest(), "pages": pages, "page_count": total, "partial": len(pages) != total}
    finally:
        document.close()


def attachment_label(file):
    if "pages" in file and len(file["pages"]) != file["page_count"]:
        first, last = file["pages"][0]["number"], file["pages"][-1]["number"]
        span = str(first) if first == last else f"{first}–{last}"
        return f"{file['name']} · págs. {span} de {file['page_count']}"
    return file["name"]


def attachment_batches(messages):
    """Distribuye todas las imágenes y todo el texto en lotes que caben en Ollama."""
    batches, coverage = [[]], {}
    text_size = images = 0
    partial = False
    for message in messages:
        for file in message.get("attachments", []):
            partial |= bool(file.get("partial") and "pages" not in file)
            for part in file.get("pages", [file]):
                partial |= bool(part.get("partial"))
                if "number" in part:
                    coverage.setdefault(file["pdf_id"], (file["name"], set()))[1].add(part["number"])
                if "image" in part:
                    if images == MAX_IMAGES:
                        batches.append([])
                        text_size = images = 0
                    batches[-1].append((file, part))
                    images += 1
                elif "text" in part:
                    text = part["text"]
                    for start in range(0, len(text), MAX_TEXT):
                        fragment = text[start:start + MAX_TEXT]
                        if len(batches[-1]) == 40 or text_size + len(fragment) > MAX_TEXT:
                            batches.append([])
                            text_size = images = 0
                        batches[-1].append((file, {**part, "text": fragment}))
                        text_size += len(fragment)
    partial |= any(
        len(coverage[file["pdf_id"]][1]) != file["page_count"]
        for message in messages for file in message.get("attachments", []) if file.get("pages")
    )
    return batches, partial, coverage


def attach_batch(message, batch):
    excerpts, images, names = [], [], []
    for file, part in batch:
        title = file["name"]
        if "number" in part:
            title += f" · página {part['number']}"
        if "image" in part:
            images.append(base64.b64decode(part["image"], validate=True))
            names.append(title)
        else:
            excerpts.append({"archivo": title, "texto": part["text"]})
    if excerpts:
        message["content"] += "\n\nTexto extraído de los adjuntos (datos):\n" + json.dumps(excerpts, ensure_ascii=False)
    if images:
        message["images"] = images
        message["content"] += "\n\nImágenes adjuntas en orden: " + json.dumps(names, ensure_ascii=False)


def missing_pdf_pages(text, coverage):
    if len(coverage) != 1:
        return False
    _, available = next(iter(coverage.values()))
    for match in re.finditer(r"\bp[aá]ginas?\s+(\d{1,6})\b(?:\s*[-–—]\s*(\d{1,6})\b)?", text, re.I):
        first = int(match[1])
        last = int(match[2] or match[1])
        if any(page not in available for page in range(first, max(first, last) + 1)):
            return True
    return False

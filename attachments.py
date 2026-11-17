"""Lectura acotada de adjuntos y preparación del contexto para Ollama."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter
from PySide6.QtPdf import QPdfDocument

from stonebot_engine.safety import check_path

MAX_FILES = 4
MAX_IMAGES = 4
MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 12_000
MAX_PAGES = 40
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_SUFFIXES = {".png": b"png", ".jpg": b"jpeg", ".jpeg": b"jpeg", ".webp": b"webp"}
TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".log", ".json"}
FILE_FILTER = "Archivos compatibles (" + " ".join(f"*{ext}" for ext in sorted(IMAGE_SUFFIXES.keys() | TEXT_SUFFIXES | {".pdf"})) + ")"


class PDFPageRange(ValueError):
    def __init__(self, total, first, last, reason):
        self.suggestion = f"{first}-{last}" if first < last else str(first)
        super().__init__(f"El PDF tiene {total} páginas. {reason} Elige un tramo, por ejemplo {self.suggestion}.")


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
    with safe.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if not raw:
        raise ValueError("El archivo está vacío.")
    if len(raw) > MAX_BYTES:
        advice = " Divide el PDF en archivos más pequeños." if suffix == ".pdf" else ""
        raise ValueError("El archivo supera el límite de 10 MiB." + advice)
    name = " ".join(safe.name.split())
    if suffix in IMAGE_SUFFIXES:
        return {"name": name, "image": encode_image(raw, IMAGE_SUFFIXES[suffix])}
    if suffix == ".pdf":
        return {"name": name, "pdf_id": hashlib.sha256(raw).hexdigest(), **pdf_pages(raw, page_range)}
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
    return {"name": name, "text": text[:MAX_TEXT], "partial": len(text) > MAX_TEXT}


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


def pdf_pages(raw, page_range):
    source = QBuffer()
    source.setData(QByteArray(raw))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument()
    try:
        document.load(source)
        if document.status() != QPdfDocument.Status.Ready:
            raise ValueError("No se pudo abrir el PDF. Puede estar dañado o protegido por contraseña.")
        total = document.pageCount()
        first, last = page_range or (1, total)
        if not 1 <= first <= last <= total:
            raise ValueError(f"El tramo debe estar entre las páginas 1 y {total}.")
        if last - first + 1 > MAX_PAGES:
            raise PDFPageRange(total, first, first + MAX_PAGES - 1, f"El máximo es de {MAX_PAGES} páginas por tramo.")
        remaining, images = MAX_TEXT, 0
        pages = []
        for number in range(first, last + 1):
            text = document.getAllText(number - 1).text().strip()
            if text:
                if pages and len(text) > remaining:
                    raise PDFPageRange(total, first, number - 1, f"El tramo supera los {MAX_TEXT} caracteres de texto.")
                pages.append({"number": number, "text": text[:remaining], "partial": len(text) > remaining})
                remaining -= len(pages[-1]["text"])
            else:
                if images == MAX_IMAGES:
                    raise PDFPageRange(total, first, number - 1, f"El máximo es de {MAX_IMAGES} páginas visuales por tramo.")
                pages.append({"number": number})
                images += 1
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
        return {"pages": pages, "page_count": total, "partial": len(pages) != total or any(p.get("partial") for p in pages)}
    finally:
        document.close()


def attachment_label(file):
    if "pages" in file and len(file["pages"]) != file["page_count"]:
        first, last = file["pages"][0]["number"], file["pages"][-1]["number"]
        span = str(first) if first == last else f"{first}–{last}"
        return f"{file['name']} · págs. {span} de {file['page_count']}"
    return file["name"]


def attachment_images(file):
    return sum("image" in part for part in file.get("pages", [file]))


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


def ollama_messages(messages):
    """Prioriza archivos recientes y nunca entrega rutas al SDK."""
    text_left, images_left = 2 * MAX_TEXT, MAX_IMAGES
    omitted = False
    pdf_coverage = {}
    excerpts, images, image_names, coverage = [], [], [], []
    for message in reversed(messages):
        for file in message.get("attachments", []):
            included = []
            for part in file.get("pages", [file]):
                title = file["name"]
                if "number" in part:
                    title += f" · página {part['number']}"
                if "image" in part and images_left:
                    images.append(base64.b64decode(part["image"], validate=True))
                    image_names.append(title)
                    images_left -= 1
                elif "text" in part and text_left:
                    text = part["text"][:text_left]
                    text_left -= len(text)
                    partial = part.get("partial", False) or len(text) < len(part["text"])
                    excerpts.append({"archivo": title, "texto": text, "parcial": partial})
                    omitted |= partial
                else:
                    omitted = True
                    continue
                if "number" in part:
                    included.append(part["number"])
            if "pages" in file:
                coverage.append({"archivo": file["name"], "páginas incluidas": included})
                pdf_coverage.setdefault(file["pdf_id"], (file["name"], set()))[1].update(included)
                omitted |= len(included) != file["page_count"]
    payload = [{"role": message["role"], "content": message["content"]} for message in messages]
    # Algunos modelos visuales solo interpretan de forma fiable las imágenes del último mensaje.
    item = payload[-1]
    if excerpts:
        item["content"] += "\n\nTexto extraído de los adjuntos (datos):\n" + json.dumps(excerpts, ensure_ascii=False)
    if images:
        item["images"] = images
        item["content"] += "\n\nImágenes adjuntas en orden: " + json.dumps(image_names, ensure_ascii=False)
    if coverage:
        item["content"] += "\n\nCobertura de PDF en este mensaje:\n" + json.dumps(coverage, ensure_ascii=False)
    return payload, bool(images), omitted, pdf_coverage

"""Extrae texto y datos con sus referencias de archivos Office Open XML."""
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as XML
from zipfile import BadZipFile, ZipFile


OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_PART_BYTES = 16 * 1024 * 1024
MAX_OFFICE_CHARS = 240_000
CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})")


class OfficeXML(XML.TreeBuilder):
    def doctype(self, name, public_id, system_id):
        raise ValueError("El XML de Office contiene una declaración no compatible.")


def read_xml(archive, path, root):
    info = archive.getinfo(path)
    if info.file_size > MAX_PART_BYTES:
        raise ValueError("Una parte del archivo de Office es demasiado grande para leerla.")
    element = XML.fromstring(archive.read(info), parser=XML.XMLParser(target=OfficeXML()))
    if not element.tag.endswith("}" + root):
        raise ValueError("El contenido del archivo de Office no coincide con su formato.")
    return element


def relationships(archive, part=""):
    folder, filename = posixpath.split(part)
    root = read_xml(archive, posixpath.join(folder, "_rels", filename + ".rels"), "Relationships")
    links = {}
    for entry in root.findall("{*}Relationship"):
        if entry.get("TargetMode") == "External":
            continue
        target = urlsplit(entry.attrib["Target"])
        # Las referencias solo pueden resolverse dentro del archivo adjunto.
        if target.scheme or target.netloc or target.query or target.fragment:
            continue
        path = unquote(target.path)
        path = posixpath.normpath(path[1:] if path.startswith("/") else posixpath.join(folder, path))
        if path == ".." or path.startswith(("../", "/")) or "\\" in path:
            continue
        links[entry.attrib["Id"]] = entry.attrib["Type"].rsplit("/", 1)[-1], path
    return links


def related_part(links, entry, kind):
    identifier = next(key for key in entry.attrib if key.endswith("}id"))
    found_kind, path = links[entry.attrib[identifier]]
    if found_kind != kind:
        raise ValueError("El archivo de Office contiene una referencia interna inválida.")
    return path


def text_runs(element):
    chunks = []
    for node in element.iter():
        kind = node.tag.rsplit("}", 1)[-1]
        if kind == "t":
            chunks.append(node.text or "")
        elif kind in {"tab", "br", "cr"}:
            chunks.append(" ")
    return "".join(chunks).strip()


def word_blocks(container):
    for child in container:
        kind = child.tag.rsplit("}", 1)[-1]
        if kind in {"p", "tbl"}:
            yield kind, child
        elif kind in {"sdt", "sdtContent", "customXml"}:
            yield from word_blocks(child)


def word_sections(archive, main):
    body = read_xml(archive, main, "document").find("{*}body")
    if body is None:
        raise ValueError("No encontré el cuerpo del documento de Word.")
    paragraphs = tables = 0
    for kind, block in word_blocks(body):
        if kind == "p":
            paragraphs += 1
            if text := text_runs(block):
                yield f"párrafo {paragraphs}", text
        else:
            tables += 1
            for index, row in enumerate(block.findall("{*}tr"), 1):
                cells = [" ".join(filter(None, map(text_runs, cell.findall("{*}p"))))
                         for cell in row.findall("{*}tc")]
                if any(cells):
                    yield f"tabla {tables}, fila {index}", json.dumps(cells, ensure_ascii=False)


def slide_sections(archive, main):
    presentation = read_xml(archive, main, "presentation")
    slides = presentation.findall("{*}sldIdLst/{*}sldId")
    if not slides:
        return
    links = relationships(archive, main)
    seen = set()
    for number, slide in enumerate(slides, 1):
        path = related_part(links, slide, "slide")
        if path in seen:
            raise ValueError("La presentación contiene una referencia repetida a la misma diapositiva.")
        seen.add(path)
        page = read_xml(archive, path, "sld")
        text = "\n".join(filter(None, map(text_runs, page.iterfind(".//{*}p"))))
        if text:
            yield f"diapositiva {number}", text


def cell_address(reference, row, column):
    if reference:
        match = CELL.fullmatch(reference)
        if match is None:
            raise ValueError("El libro contiene una referencia de celda inválida.")
        column = 0
        for letter in match[1]:
            column = column * 26 + ord(letter) - ord("A") + 1
        return reference, column
    letters, remainder = "", column
    while remainder:
        remainder, digit = divmod(remainder - 1, 26)
        letters = chr(ord("A") + digit) + letters
    return f"{letters}{row}", column


def cell_content(cell, strings, number_formats):
    kind = cell.get("t", "n")
    value = cell.findtext("{*}v", "")
    if kind == "s" and value:
        index = int(value)
        if not 0 <= index < len(strings):
            raise ValueError("El libro contiene una referencia de texto inválida.")
        value = strings[index]
    elif kind == "inlineStr":
        value = text_runs(cell)
    elif kind == "b":
        value = {"0": "FALSO", "1": "VERDADERO"}[value]
    elif kind == "e":
        value = f"Error de Excel {value}"
    elif kind == "n" and value:
        style = int(cell.get("s", "0"))
        if 0 <= style < len(number_formats) and number_formats[style]:
            value = f"{value} [valor almacenado, formato de Excel: {number_formats[style]}]"
    formula = cell.find("{*}f")
    if formula is not None:
        expression = f"={formula.text}" if formula.text else "fórmula sin expresión disponible en esta celda"
        return f"{expression} [resultado guardado: {value or 'no disponible'}]"
    return value


def spreadsheet_sections(archive, main):
    workbook = read_xml(archive, main, "workbook")
    links = relationships(archive, main)
    by_kind = {kind: path for kind, path in links.values()}
    strings = []
    if "sharedStrings" in by_kind:
        table = read_xml(archive, by_kind["sharedStrings"], "sst")
        strings = [text_runs(item) for item in table.findall("{*}si")]
    number_formats = []
    if "styles" in by_kind:
        styles = read_xml(archive, by_kind["styles"], "styleSheet")
        formats = {"9": "0%", "10": "0.00%", "14": "fecha", "15": "fecha", "16": "fecha",
                   "17": "fecha", "18": "hora", "19": "hora", "20": "hora", "21": "hora", "22": "fecha y hora"}
        formats.update((item.attrib["numFmtId"], item.attrib["formatCode"])
                       for item in styles.findall("{*}numFmts/{*}numFmt"))
        for style in styles.findall("{*}cellXfs/{*}xf"):
            code = style.get("numFmtId", "0")
            number_formats.append(formats.get(code, f"formato integrado {code}") if code != "0" else "")
    seen = set()
    for sheet in workbook.findall("{*}sheets/{*}sheet"):
        identifier = next(key for key in sheet.attrib if key.endswith("}id"))
        if links[sheet.attrib[identifier]][0] == "chartsheet":
            continue
        path = related_part(links, sheet, "worksheet")
        if path in seen:
            raise ValueError("El libro contiene una referencia repetida a la misma hoja.")
        seen.add(path)
        page = read_xml(archive, path, "worksheet")
        row_number = 0
        for row in page.iterfind("{*}sheetData/{*}row"):
            row_number = int(row.get("r", row_number + 1))
            column = 0
            cells = {}
            for cell in row.iterfind("{*}c"):
                address, column = cell_address(cell.get("r"), row_number, column + 1)
                if value := cell_content(cell, strings, number_formats):
                    cells[address] = value
            if cells:
                yield f"hoja «{sheet.attrib['name']}», fila {row_number}", json.dumps(cells, ensure_ascii=False)


def read_office(path):
    if path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("El archivo de Office supera 64 MB. Adjunta una versión más pequeña.")
    formats = {
        ".docx": ("wordprocessingml.document", word_sections),
        ".xlsx": ("spreadsheetml.sheet", spreadsheet_sections),
        ".pptx": ("presentationml.presentation", slide_sections),
    }
    content_type, extract = formats[path.suffix.lower()]
    sections, size = [], 0
    try:
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 3 * MAX_PACKAGE_BYTES:
                raise ValueError("El contenido descomprimido del archivo de Office supera el límite.")
            parts = [part for kind, part in relationships(archive).values() if kind == "officeDocument"]
            if len(parts) != 1:
                raise ValueError("No encontré el documento principal dentro del archivo de Office.")
            main = parts[0]
            types = read_xml(archive, "[Content_Types].xml", "Types")
            expected = f"application/vnd.openxmlformats-officedocument.{content_type}.main+xml"
            if not any(unquote(item.get("PartName", "")) == "/" + main
                       and item.get("ContentType") == expected for item in types):
                raise ValueError("El contenido del archivo de Office no coincide con su extensión.")
            for location, text in extract(archive, main):
                size += len(location) + len(text)
                if size > MAX_OFFICE_CHARS:
                    raise ValueError("El archivo de Office tiene demasiado texto o datos. Adjunta una parte más pequeña.")
                sections.append({"location": location, "text": text})
    except (BadZipFile, XML.ParseError, KeyError, AttributeError, StopIteration, RuntimeError, OverflowError) as exc:
        raise ValueError("No pude leer el archivo de Office. Comprueba que abra y que no esté protegido.") from exc
    if not sections:
        raise ValueError("No encontré texto ni datos de celdas en el archivo de Office.")
    return sections

"""Lectura local de Office, referencias de origen y flujo del chat."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from PySide6.QtWidgets import QApplication

import app
import attachments
import mcp_client
from history import History
from test_chat_presentation import wait_for_turn


REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE = "http://schemas.openxmlformats.org/package/2006"
OFFICE = "http://schemas.openxmlformats.org"


def rels(*entries):
    links = "".join(f'<Relationship Id="{id_}" Type="{REL}/{kind}" Target="{target}"/>'
                    for id_, kind, target in entries)
    return f'<Relationships xmlns="{PACKAGE}/relationships">{links}</Relationships>'


def package(path, main, kind, parts):
    with ZipFile(path, "w") as archive:
        archive.writestr("_rels/.rels", rels(("main", "officeDocument", main)))
        archive.writestr("[Content_Types].xml", f'<Types xmlns="{PACKAGE}/content-types"><Override PartName="/{main}" '
                         f'ContentType="application/vnd.openxmlformats-officedocument.{kind}.main+xml"/></Types>')
        for name, content in parts.items():
            archive.writestr(name, content)


def samples(root):
    word = root / "Informe.docx"
    w = f"{OFFICE}/wordprocessingml/2006/main"
    package(word, "word/document.xml", "wordprocessingml.document", {"word/document.xml": f"""
        <w:document xmlns:w="{w}"><w:body>
        <w:p><w:r><w:t>Informe de avance</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Importe aprobado</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>375</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:body></w:document>"""})
    excel = root / "Presupuesto.xlsx"
    s = f"{OFFICE}/spreadsheetml/2006/main"
    package(excel, "xl/workbook.xml", "spreadsheetml.sheet", {
        "xl/workbook.xml": f'<workbook xmlns="{s}" xmlns:r="{REL}"><sheets>'
                           '<sheet name="Costos" sheetId="1" r:id="a"/>'
                           '<sheet name="Totales" sheetId="2" r:id="b"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": rels(("a", "worksheet", "worksheets/s1.xml"),
                                          ("b", "worksheet", "/xl/worksheets/s2.xml"),
                                          ("shared", "sharedStrings", "sharedStrings.xml")),
        "xl/sharedStrings.xml": f'<sst xmlns="{s}"><si><r><t>Costo</t></r><r><t> directo</t></r></si></sst>',
        "xl/worksheets/s1.xml": f'<worksheet xmlns="{s}"><sheetData><row r="2">'
                                '<c r="A2" t="s"><v>0</v></c><c><v>375</v></c></row></sheetData></worksheet>',
        "xl/worksheets/s2.xml": f'<worksheet xmlns="{s}"><sheetData><row r="7">'
                                '<c r="E7"><f>SUM(Costos!B2)</f><v>375</v></c>'
                                '<c r="F7"><f>E7*2</f></c></row></sheetData></worksheet>',
    })
    slides = root / "Avances.pptx"
    p, a = f"{OFFICE}/presentationml/2006/main", f"{OFFICE}/drawingml/2006/main"
    package(slides, "ppt/presentation.xml", "presentationml.presentation", {
        "ppt/presentation.xml": f'<p:presentation xmlns:p="{p}" xmlns:r="{REL}"><p:sldIdLst>'
                                '<p:sldId id="901" r:id="first"/><p:sldId id="902" r:id="second"/>'
                                '</p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": rels(("first", "slide", "slides/slide2.xml"),
                                               ("second", "slide", "slides/slide1.xml")),
        "ppt/slides/slide2.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld>'
                                 '<a:p><a:r><a:t>Calendario</a:t></a:r></a:p></p:cSld></p:sld>',
        "ppt/slides/slide1.xml": f'<p:sld xmlns:p="{p}" xmlns:a="{a}"><p:cSld>'
                                 '<a:p><a:r><a:t>Entrega en enero</a:t></a:r></a:p></p:cSld></p:sld>',
    })
    return word, excel, slides


def test_readers(root, paths):
    word, excel, slides = [attachments.read_attachment(path)["sections"] for path in paths]
    assert word[0] == {"location": "párrafo 1", "text": "Informe de avance"}
    assert word[1]["location"] == "tabla 1, fila 1" and json.loads(word[1]["text"]) == ["Importe aprobado", "375"]
    assert excel[0]["location"] == "hoja «Costos», fila 2"
    assert json.loads(excel[0]["text"]) == {"A2": "Costo directo", "B2": "375"}
    totals = json.loads(excel[1]["text"])
    assert totals["E7"] == "=SUM(Costos!B2) [resultado guardado: 375]"
    assert totals["F7"].endswith("[resultado guardado: no disponible]")
    assert slides[1] == {"location": "diapositiva 2", "text": "Entrega en enero"}

    damaged = root / "Dañado.docx"
    w = f"{OFFICE}/wordprocessingml/2006/main"
    package(damaged, "word/document.xml", "wordprocessingml.document", {"word/document.xml":
            f'<!DOCTYPE w:document [<!ENTITY texto "No expandir">]>'
            f'<w:document xmlns:w="{w}"><w:body><w:p><w:t>&texto;</w:t></w:p></w:body></w:document>'})
    try:
        attachments.read_attachment(damaged)
    except ValueError as exc:
        assert "declaración no compatible" in str(exc)
    else:
        raise AssertionError("El lector debe rechazar las entidades declaradas por los archivos.")


def test_chat(paths):
    window = app.StoneBot()
    window.show()
    calls = []

    def answer(**request):
        calls.append(request)
        return SimpleNamespace(message=SimpleNamespace(content="375, en Presupuesto.xlsx, hoja Totales, celda E7."))

    try:
        with patch.object(app, "Client", return_value=SimpleNamespace(chat=answer)):
            window.attachments.add_paths(paths)
            assert [file["name"] for file in window.attachments.files] == [path.name for path in paths]
            window.message.setPlainText("¿Dónde aparece el importe?")
            window.enviar()
            wait_for_turn(window)
            request, = calls
            system, user = request["messages"]
            assert "No des por recalculada una fórmula" in system["content"]
            assert "Informe.docx · tabla 1, fila 1" in user["content"]
            assert "Presupuesto.xlsx · hoja «Totales», fila 7" in user["content"] and "E7" in user["content"]
            assert "Avances.pptx · diapositiva 2" in user["content"]
            saved = History().messages(window.chat_id)
            assert saved[0]["attachments"][1]["sections"] and "celda E7" in saved[1]["content"]
    finally:
        window.close()


if __name__ == "__main__":
    qt = QApplication([])
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root):
            paths = samples(root)
            test_readers(root, paths)
            test_chat(paths)
    print("PASS: lectura de Office, origen de los datos y chat con adjuntos.")

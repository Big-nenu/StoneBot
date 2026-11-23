"""Discovery, instalación y activación selectiva de Skills. Usa --live para Ollama."""
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import turn_worker
import local_skills
import mcp_client
from skills_ui import SkillsDialog


EXAMPLE = "faro-de-prueba"
SEAL = "FARO SB · LINTERNA-742"


def turn(text):
    return asyncio.run(app.Worker([{"role": "system", "content": app.SYSTEM},
                                   {"role": "user", "content": text}]).chat())


def install_from_ui(root):
    source = root / "origen" / "prueba-local"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        '---\nname: prueba-local\ndescription: "Úsala al pedir una nota de prueba."\n---\n\nInstrucciones privadas.\n',
        encoding="utf-8")
    (source / "scripts").mkdir()
    (source / "scripts" / "no-ejecutar.py").write_text("raise AssertionError('Este script no debe ejecutarse')", encoding="utf-8")

    panel = SkillsDialog(None, app.load_appearance())
    with patch.object(QFileDialog, "getExistingDirectory", return_value=str(source)):
        panel.add()
    item = panel.list.currentItem()
    assert item.text() == "prueba-local" and "nota de prueba" in panel.description.text()
    assert item.checkState() == Qt.CheckState.Unchecked
    assert (root / "skills" / "prueba-local" / "SKILL.md").is_file()
    assert not (root / "skills" / "prueba-local" / "scripts").exists()
    item.setCheckState(Qt.CheckState.Checked)
    assert local_skills.enabled("prueba-local")
    panel.refresh("prueba-local")
    panel.list.currentItem().setCheckState(Qt.CheckState.Unchecked)
    assert not local_skills.enabled("prueba-local")

    invalid = root / "skills" / "cuerpo-danado"
    invalid.mkdir()
    (invalid / "SKILL.md").write_bytes(b"---\nname: cuerpo-danado\ndescription: Metadatos validos\n---\n\xff")
    catalog, errors = local_skills.discover()
    assert "cuerpo-danado" in catalog and not errors
    local_skills.set_enabled("cuerpo-danado", True)
    try:
        local_skills.read_body(catalog["cuerpo-danado"])
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("El cuerpo inválido debe fallar en la carga, después del descubrimiento.")
    local_skills.set_enabled("cuerpo-danado", False)
    panel.close()


def test_progressive():
    calls = []

    def chat(**request):
        calls.append(request)
        messages = request["messages"]
        if SEAL in messages[0]["content"]:
            assert not request["tools"]
            return SimpleNamespace(message=Message(role="assistant", content=SEAL))
        assert SEAL not in repr(messages) and SEAL not in repr(request["tools"])
        if "Faro SB" in messages[-1]["content"]:
            requested = [
                Message.ToolCall(function=Message.ToolCall.Function(name="load_skill", arguments={"name": EXAMPLE})),
                Message.ToolCall(function=Message.ToolCall.Function(name="inject_memory", arguments={"content": "No guardar"})),
            ]
            return SimpleNamespace(message=Message(role="assistant", tool_calls=requested))
        return SimpleNamespace(message=Message(role="assistant", content="56"))

    local_skills.set_enabled(EXAMPLE, True)
    with (patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=chat)),
          patch.object(local_skills, "read_body", wraps=local_skills.read_body) as loaded,
          patch.object(app.StoneWaveMemory, "call", side_effect=AssertionError("La Skill no guarda memoria."))):
        assert turn("¿Cuánto es 7 por 8?") == "56"
        assert loaded.call_count == 0 and len(calls) == 1
        assert turn("Genera una ficha Faro SB sobre astronomía.") == SEAL
        assert loaded.call_count == 1 and len(calls) == 3
        local_skills.set_enabled(EXAMPLE, False)
        assert turn("¿Cuánto es 7 por 8?") == "56"
        assert loaded.call_count == 1
        assert all(getattr(tool, "__name__", None) for tool in calls[-1]["tools"])


def test_live():
    local_skills.set_enabled(EXAMPLE, True)
    with patch.object(local_skills, "read_body", wraps=local_skills.read_body) as loaded:
        regular = turn("¿Cuánto es 7 por 8? Responde solo con el número.")
        assert "56" in regular and loaded.call_count == 0, regular
        sample = turn("Genera una ficha Faro SB sobre astronomía.")
        assert SEAL in sample and loaded.call_count == 1, sample
        local_skills.set_enabled(EXAMPLE, False)
        disabled = turn("Genera una ficha Faro SB sobre astronomía.")
        assert "LINTERNA-742" not in disabled and loaded.call_count == 1, disabled
        print(f"Ollama ({app.MODEL}): {regular!r}; {sample!r}; Skill inactiva sin lectura del cuerpo.")


if __name__ == "__main__":
    qt = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(
            mcp_client, "default_root", return_value=Path(directory).resolve()):
        if "--live" in sys.argv:
            test_live()
        else:
            install_from_ui(Path(directory).resolve())
            test_progressive()
    print("PASS: Skills locales con carga progresiva.")

"""Prueba del motor local con una bóveda y perfiles temporales."""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ollama import Message

from test_motor import CONC, F1, F2, make_engine
import app
import turn_worker
import mcp_client
from experiences import record_experience
from identity import load_identity
from stonebot_engine.safety import IsolationError
from stonebot_memory import EXPERIENCES, integrate_experience, preview, publish, vault_folders, write_editable


def reject(operation, error):
    try:
        operation()
    except error:
        return
    raise AssertionError("La operación debía rechazarse.")


def test_identity(root):
    prompt = [{"role": "system", "content": app.SYSTEM}, {"role": "user", "content": "¿Quién te creó?"}]
    assert load_identity()["creador"] == "Luis Eduardo Hernández Vargas"
    correction = [{"role": "user", "content": "/identidad github Big-nenu-prueba"}]
    assert "actualizada" in asyncio.run(app.Worker(correction).chat())
    code = """
import json, sys
from pathlib import Path
from unittest.mock import patch
import mcp_client
from identity import load_identity
with patch.object(mcp_client, 'default_root', return_value=Path(sys.argv[1])):
    print(json.dumps(load_identity()))
"""
    reopened = json.loads(subprocess.check_output([sys.executable, "-B", "-c", code, str(root)], text=True))
    assert reopened["github"] == "Big-nenu-prueba" and reopened["nombre"] == "StoneBot"

    def chat(**kwargs):
        definitions = kwargs["messages"][0]["content"].split(" (datos): ", 1)[1]
        assert json.loads(definitions) == reopened
        return SimpleNamespace(message=Message(role="assistant", content=f"Mi creador es {reopened['creador']}."))

    with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=chat)):
        answer = asyncio.run(app.Worker(prompt, identity_enabled=True).chat())
    assert "Luis Eduardo Hernández Vargas" in answer


def test_notes_and_dream(root):
    vault = root / "Big-vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "stonewave").mkdir()
    private = vault / "stonewave" / "sentinel.md"
    sibling = vault / "sin-cambios.md"
    private.write_bytes(b"no tocar StoneWave")
    sibling.write_bytes(b"no tocar otras notas")
    engine = make_engine(str(root / ".stonebot" / "memoria.db"))

    def cli(*args):
        env = dict(os.environ, USERPROFILE=str(root), HOME=str(root), PYTHONUTF8="1")
        command = Path(__file__).resolve().parents[1] / "stonebot_memory.py"
        return json.loads(subprocess.check_output(
            [sys.executable, "-B", str(command), *map(str, args)], env=env, text=True, encoding="utf-8", timeout=60))

    try:
        engine.inject("Recuerdo suelto de astronomía sin conclusiones.")
        engine.inject(F1)
        engine.inject(F2)
        data, _ = preview(engine, "memoria")
        assert not data["conclusions"] and len(data["facts"]) == 3
        engine._ask_llm_conclusion = lambda facts: CONC
        engine._ask_llm_support = lambda fact, conclusion: "RESPALDA"
        engine.dream()
        assert engine.list_conclusions()[0]["content"] == CONC
        ids = [record_experience("demo", "echo", "response") for _ in range(3)]
        assert "NUEVA" in integrate_experience(engine, ids[0])
        assert "NUEVA" in integrate_experience(engine, ids[1])
        assert "YA EXISTE" in integrate_experience(engine, ids[0])
        def propose(prompt, **kwargs):
            assert prompt.count("Evidencia MCP #") >= 2 and "Limita la conclusión" in prompt
            return "La herramienta demo echo respondió sin error en las pruebas observadas."

        del engine._ask_llm_conclusion
        engine.generator.generate = propose
        engine._ask_llm_support = lambda fact, conclusion: "RESPALDA"
        with patch.dict(os.environ, {"STONEBOT_NOTES": str(vault / "stonewave")}):
            assert "Sleeptime" in engine.dream(EXPERIENCES)
        assert not (vault / "stonebot").exists()
        before = engine.list_conclusions(EXPERIENCES)
        assert len(before) == 1 and before[0]["status"] == "hipotesis" and len(before[0]["sources"]) >= 2
        _, old_digest = preview(engine)
        integrate_experience(engine, ids[2])
        engine.dream(EXPERIENCES)
        loose = record_experience("otro", "listar", "timeout")
        integrate_experience(engine, loose)
        data, digest = preview(engine)
        assert digest != old_digest
        evidence_id = next(fid for fid, fact in data["facts"].items() if fact["content"].startswith(f"Evidencia MCP #{loose},"))
        assert len(data["facts"]) == 4 and all(evidence_id not in c["sources"] for c in data["conclusions"])
        reject(lambda: publish(engine, vault, old_digest), ValueError)
        reject(lambda: publish(engine, vault, digest, "memoria"), ValueError)
        assert not (vault / "stonebot").exists()
        edited_name = write_editable(vault, "Idea de prueba", "Una observación revisada.")
        generated, editable = vault_folders(vault)
        user_edit = editable / edited_name
        user_edit.write_text("Mi edición", encoding="utf-8")
        reject(lambda: write_editable(vault, "Idea de prueba", "Otro contenido"), FileExistsError)
        reviewed = cli("previsualizar", "--ambito", "experiencias")
        assert reviewed["aprobacion"] == digest
        result = cli("exportar", vault, "--ambito", "experiencias", "--aprobar", digest)
        assert result["conclusions"] == len(data["conclusions"]) and result["memories"] == 4
        experience_notes = {note: note.read_bytes() for note in generated.rglob("*.md")}
        assert any(b"tiempo de espera" in text for text in experience_notes.values())
        assert all(b"Recuerdo suelto" not in text for text in experience_notes.values())

        reviewed = cli("previsualizar", "--ambito", "memoria")
        assert reviewed["evidencia_y_conclusiones"]["namespace"] == "default"
        default_result = cli("exportar", vault, "--ambito", "memoria", "--aprobar", reviewed["aprobacion"])
        assert default_result["memories"] == 3 and default_result["conclusions"] == 1
        assert all(note.read_bytes() == original for note, original in experience_notes.items())
        default_notes = list((generated / "default").rglob("*.md"))
        assert any("Recuerdo suelto" in note.name for note in default_notes)
        assert any("## Recuerdos relacionados" in note.read_text(encoding="utf-8") for note in default_notes)
        for notes, prefix in ((experience_notes, "stonebot/generadas/"), (default_notes, "stonebot/generadas/default/")):
            for note in notes:
                for link in re.findall(r"\[\[([^|\]]+)\|", note.read_text(encoding="utf-8")):
                    target = vault / f"{link}.md"
                    assert link.startswith(prefix) and target in notes, link
                    assert target.is_file(), link
        conclusion = next((generated / "conclusiones").glob("*.md"))
        conclusion.write_text(conclusion.read_text(encoding="utf-8") + "\nEdición manual\n", encoding="utf-8")
        assert conclusion.name in publish(engine, vault, digest)["skipped"]
        assert all(note.is_file() for note in default_notes)
        assert "Edición manual" in conclusion.read_text(encoding="utf-8")
        assert user_edit.read_text(encoding="utf-8") == "Mi edición"
        target = generated / "recuerdos" / "hardlink.md"
        os.link(sibling, target)
        reject(lambda: publish(engine, vault, digest), IsolationError)
        assert private.read_bytes() == b"no tocar StoneWave" and sibling.read_bytes() == b"no tocar otras notas"
        print(f"Demostración: {default_result['memories']} recuerdos y {result['memories']} experiencias exportadas.")
    finally:
        engine.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root):
            test_identity(root)
            test_notes_and_dream(root)
    print("PASS: identidad, sueños, experiencias, publicación revisada y aislamiento de la bóveda.")

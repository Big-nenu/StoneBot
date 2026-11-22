"""Prueba de integración MCP con un perfil y una base de prueba."""
import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest
from unittest.mock import AsyncMock, patch

import mcp_client
from stonewave_memory import SERVER_SCRIPT, StoneWaveMemory, load_settings, save_settings


def test_stonewave_session():
    if not SERVER_SCRIPT.is_file():
        raise SkipTest("Esta prueba requiere el repositorio hermano StoneWave.")
    with TemporaryDirectory() as folder:
        root = Path(folder)
        profile = root / "sb"
        database = root / "sw.db"
        database.touch()
        notes = root / "notas"
        notes.mkdir()
        sync = root / "compartido.jsonl"
        with (patch.object(mcp_client, "default_root", return_value=profile),
              patch.dict("os.environ", {"STONEWAVE_DB": str(database), "STONEWAVE_NAMESPACE": "prueba",
                                        "STONEWAVE_AUTO_DREAM": "false", "STONEWAVE_BACKUP_DAYS": "0",
                                        "STONEWAVE_NOTES": "", "STONEWAVE_SYNC": ""})):
            memory = StoneWaveMemory()
            try:
                assert "vacía" in asyncio.run(memory.call("list_memories"))
                assert json.loads(asyncio.run(memory.call("dream_activity")))["status"] == "never"
                with closing(sqlite3.connect(database)) as db, db:
                    db.executemany("INSERT INTO facts (namespace, content, energy, pinned) VALUES (?, ?, ?, ?)", [
                        ("prueba", "Un recuerdo sintético", 0.9, 1),
                        ("default", "Dato de otro espacio", 0.9, 1),
                    ])
                context = asyncio.run(memory.call("get_context"))
                assert "Un recuerdo sintético" in context and "Dato de otro espacio" not in context
                assert not (profile / "memoria.db").exists()
                old = asyncio.run(memory.entries())["get_context"][0]
                save_settings({"NOTES": str(notes), "SYNC": str(sync), "CONCLUSIONS": "false"})
                assert load_settings()["AUTO_DREAM"] == "false"
                updated = asyncio.run(memory.restart())["get_context"][0]
                assert updated is not old and old.slot.task.done()
                assert "Notas listas" in asyncio.run(memory.call("export_notes"))
                assert "Sync listo" in asyncio.run(memory.call("sync_memory"))
                assert "Un recuerdo sintético" in sync.read_text(encoding="utf-8")
                result = asyncio.run(memory.call("forget_memory", fact_id=1))
                assert "Olvidado" in result
                assert "vacía" in asyncio.run(memory.call("list_memories"))
            finally:
                memory.close()


def test_chat_reads_activity_without_a_model():
    from types import SimpleNamespace
    from ai_provider import AISettings
    from app import Worker
    from stonewave_activity import dream_question

    report = {"status": "ok", "finished_at": "2026-11-21T20:00:00Z", "source": "automático",
              "links_count": 1, "links": [{"kind": "similar", "facts": [
                  {"id": 1, "content": "Recuerdo A"}, {"id": 2, "content": "Recuerdo B"},
              ]}], "conclusions": [{"kind": "hipótesis", "id": 3, "content": "Conclusión C"}],
              "conclusions_status": "ok", "notes_status": "ok",
              "notes_created": ["conclusiones/nueva.md"], "notes_updated": ["recuerdos/actualizada.md"]}
    memory = SimpleNamespace(call=AsyncMock(return_value=json.dumps(report)))
    ai = AISettings("openrouter", "test/model", cloud_memory=False)

    def ask(text):
        return asyncio.run(Worker([{"role": "user", "content": text}], memory=memory, ai=ai).chat())

    with patch("app.OpenRouter", side_effect=AssertionError("La actividad se consulta localmente")):
        assert "21/11/2026" in ask("¿Cuándo fue el último sueño de SW?")
        assert "Recuerdo B" in ask("¿Qué recuerdos relacionó?")
        assert "Conclusión C" in ask("¿Qué conclusiones generó?")
        answer = ask("¿Qué notas creó o actualizó en Obsidian?")
        assert "Creada · conclusiones/nueva.md" in answer and "Actualizada · recuerdos/actualizada.md" in answer
        memory.call.assert_awaited_with("dream_activity")
        memory.call.return_value = json.dumps({"status": "date_only", "finished_at": report["finished_at"]})
        assert "Solo está disponible la fecha" in ask("¿Qué notas creó o actualizó en Obsidian?")
    assert not dream_question([{"role": "user", "content": "¿Qué recuerdas de mis sueños personales?"}])


def test_chat_reads_recent_notes_without_a_model():
    from types import SimpleNamespace
    from ai_provider import AISettings
    from app import Worker
    from stonewave_activity import dream_question, notes_content_question

    report = {"status": "ok", "notes": [{"path": "conclusiones/aprende.md", "folder": "conclusiones",
                                         "modified": "2026-11-22T15:00:00+00:00",
                                         "content": "# Aprende practicando\n\n## Viene de\n- Ejercicios semanales"}]}
    memory = SimpleNamespace(call=AsyncMock(return_value=json.dumps(report)))
    ai = AISettings("openrouter", "test/model", cloud_memory=False)

    def messages(text):
        return [{"role": "user", "content": text}]

    def ask(text):
        return asyncio.run(Worker(messages(text), memory=memory, ai=ai).chat())

    with patch("app.OpenRouter", side_effect=AssertionError("Las notas se leen localmente")):
        answer = ask("¿Me puedes decir las últimas notas que apuntaste en Obsidian?")
        assert "conclusiones/aprende.md" in answer and "Ejercicios semanales" in answer
        memory.call.assert_awaited_with("recent_notes", limit=5)
        ask("¿Qué pusiste en esas notas?")
        ask("Dime las últimas 3 notas de Obsidian")
        memory.call.assert_awaited_with("recent_notes", limit=3)
        memory.call.return_value = json.dumps({"status": "off", "notes": []})
        assert "no tiene configurada la carpeta" in ask("¿Cuáles son las notas recientes de Obsidian?")
    assert notes_content_question(messages("¿Qué notas creó o actualizó en Obsidian?")) is None
    assert dream_question(messages("¿Qué notas creó o actualizó en Obsidian?"))
    assert notes_content_question(messages("¿Qué recuerdas de mis sueños personales?")) is None
    assert notes_content_question(messages("Anota que mañana compro leche")) is None


if __name__ == "__main__":
    test_chat_reads_activity_without_a_model()
    test_chat_reads_recent_notes_without_a_model()
    try:
        test_stonewave_session()
    except SkipTest as exc:
        print(f"SKIP: {exc}")
    else:
        print("PASS: sesión MCP, namespace, consulta y olvido en StoneWave de prueba.")

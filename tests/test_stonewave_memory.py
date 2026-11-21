"""Prueba de integración MCP con un perfil y una base de prueba."""
import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import SkipTest
from unittest.mock import patch

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


if __name__ == "__main__":
    try:
        test_stonewave_session()
    except SkipTest as exc:
        print(f"SKIP: {exc}")
    else:
        print("PASS: sesión MCP, namespace, consulta y olvido en StoneWave de prueba.")

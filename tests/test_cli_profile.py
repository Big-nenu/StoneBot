"""Comprueba la raíz, el bloqueo y las rutas protegidas de la CLI."""
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_client
from conversation_lock import acquire_conversation_lock
from history import History
from stonebot_engine import safety


def rejects(callback, *args):
    try:
        callback(*args)
    except (ValueError, safety.IsolationError):
        return
    raise AssertionError(args)


def exercise(home):
    with patch.object(Path, "home", return_value=home), patch.object(safety, "_cli_root", None):
        desktop = home / ".stonebot"
        desktop.mkdir()
        marker = desktop / "memoria.db"
        marker.write_text("base experimental", encoding="utf-8")
        assert mcp_client.data_path() == desktop
        for invalid in ("", "relativa", desktop, desktop / "perfil", home, safety.protected_paths()[0]):
            rejects(safety.configure_cli_profile, invalid)
        assert safety.configure_cli_profile() == home / ".stonebot-cli"
        assert safety.default_root() == desktop
        rejects(safety.check_path, marker)
        lock = acquire_conversation_lock()
        assert lock is not None
        try:
            assert acquire_conversation_lock() is None
            assert History().path.parent == mcp_client.data_path()
            code = ("import sys; from conversation_lock import acquire_conversation_lock; "
                    "from stonebot_engine.safety import configure_cli_profile; "
                    "configure_cli_profile(sys.argv[1]); lock = acquire_conversation_lock(); "
                    "assert (lock is None) == (sys.argv[2] == 'blocked')")
            for profile, expected in ((mcp_client.data_path(), "blocked"), (home / "otro", "open")):
                subprocess.run([sys.executable, "-B", "-c", code, str(profile), expected], check=True, timeout=20)
        finally:
            lock.unlock()
        assert marker.read_text(encoding="utf-8") == "base experimental"
        custom = home / "alterno"
        with patch.object(safety, "_cli_root", None):
            assert safety.configure_cli_profile(custom) == custom
            custom.mkdir()
            (custom / "alias").hardlink_to(marker)
            rejects(mcp_client.data_path, "alias")
            (custom / "conversations.sqlite3-wal").hardlink_to(marker)
            rejects(History)
        with patch.object(safety, "_cli_root", None):
            alias = home / "junction"
            if os.name == "nt":
                subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(custom)],
                               check=True, capture_output=True)
            else:
                alias.symlink_to(custom, target_is_directory=True)
            rejects(safety.configure_cli_profile, alias / "perfil")


if __name__ == "__main__":
    with TemporaryDirectory() as folder:
        exercise(Path(folder).resolve())
    print("PASS: perfil, bloqueo, aislamiento y redirecciones")

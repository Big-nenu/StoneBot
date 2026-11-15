import ast
import re
import sys
from pathlib import Path

SB = Path(r"C:\Users\Luis_Hdez\Projects\StoneBot")
PKG = SB / "stonebot_engine"


def rd(p):
    with open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


def wr(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def sub1(pattern, repl, s, flags=0, label=""):
    new, n = re.subn(pattern, repl, s, count=1, flags=flags)
    if n != 1:
        sys.exit(f"NO ENCONTRADO: {label or pattern}")
    return new


# ---------- llm.py ----------
p = PKG / "llm.py"
s = rd(p)
s = sub1(r'def env_var\(name, default=None\):.*?\n    return os\.getenv\([^\n]*\n',
         'def env_var(name, default=None):\n'
         '    """Lee STONEBOT_<name>. Las variables STONEWAVE_* y MEMHOLOGRAFIC_* se ignoran a proposito (aislamiento)."""\n'
         '    return os.getenv("STONEBOT_" + name, default)\n', s, re.S, "env_var")
s = s.replace("STONEWAVE_", "STONEBOT_").replace("StoneWaveEngine(", "StoneBotEngine(")
s = s.replace('"""Capa de modelos de StoneWave:', '"""Capa de modelos del motor de StoneBot (copia de StoneWave):')
wr(p, s)

# ---------- notes.py ----------
p = PKG / "notes.py"
s = rd(p)
s = sub1(r"^from llm import env_var", "from .llm import env_var", s, re.M, "notes import llm")
s = s.replace("STONEWAVE_", "STONEBOT_")
wr(p, s)

# ---------- mem_engine.py ----------
p = PKG / "mem_engine.py"
s = rd(p)
s = sub1(r"^from llm import \(", "from .llm import (", s, re.M, "from llm import")
s = sub1(r"^from pathlib import Path\r?\n", lambda m: m.group(0) + "from .safety import check_db_path\n", s, re.M, "import Path")
s = sub1(r"USER_HOME = Path\.home\(\).*?return str\(new\)\r?\n",
         "# StoneBot: NO hay ruta por defecto. La ruta de la base se pasa siempre de forma explicita y la valida safety.py.\n",
         s, re.S, "bloque _default_db_path")
s = sub1(r"def __init__\(self, db_path=None, embedder=None, generator=None, decider=None\):",
         "def __init__(self, db_path=None, embedder=None, generator=None, decider=None, allowed_root=None):", s, 0, "__init__")
s = sub1(r'self\.db_path = db_path if db_path else \(env_var\("DB"\) or _default_db_path\(\)\)',
         "self._db_path = check_db_path(db_path, allowed_root)  # aislamiento: ver safety.py", s, 0, "db_path")
s = sub1(r"(\n    def close\(self\):)",
         '\n    @property\n    def db_path(self):\n        """Ruta de la base (solo lectura): se valida una sola vez, al crear el motor."""\n        return self._db_path\n\\1',
         s, 0, "property db_path")
s, n = re.subn(r"^(\s*)import notes\b", r"\1from . import notes", s, flags=re.M)
if n != 2:
    sys.exit(f"import notes: se esperaban 2, hay {n}")
s = re.sub(r"^MemHolograficEngine = StoneWaveEngine[^\n]*\r?\n?", "", s, flags=re.M)
s = s.replace("StoneWaveEngine", "StoneBotEngine").replace("STONEWAVE_", "STONEBOT_").replace("StoneWave:", "StoneBot:")
wr(p, s)

# ---------- tests/test_motor.py ----------
p = SB / "tests" / "test_motor.py"
s = rd(p)
tree = ast.parse(s)
quitar = {"_mcp_sample", "test_parser_mcp_memory_convierte_e_importa", "test_cli_import_y_export",
          "_md_sample", "test_parser_markdown_convierte_y_respeta_titulos", "test_parser_markdown_carpeta_ignora_ocultas",
          "test_cli_import_markdown", "_chats_sample", "test_parser_chats_chatgpt_y_claude", "test_cli_import_chatgpt",
          "test_cli_bridge"}
lineas = s.splitlines(keepends=True)
rangos = [(n.lineno - 1, n.end_lineno) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in quitar]
if len(rangos) != len(quitar):
    sys.exit(f"tests a quitar: {len(rangos)} de {len(quitar)}")
for a, b in sorted(rangos, reverse=True):
    del lineas[a:b]
s = "".join(lineas)
s = sub1(r"sys\.path\.insert\(0, os\.path\.dirname\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\)\)\r?\nfrom mem_engine import MemHolograficEngine\r?\nimport mem_engine\r?\n",
         "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
         "from stonebot_engine import mem_engine\n"
         "from stonebot_engine.mem_engine import StoneBotEngine\n", s, 0, "imports de prueba")
s = re.sub(r"^(\s*)import llm\b", r"\1from stonebot_engine import llm", s, flags=re.M)
s = s.replace("MemHolograficEngine(db_path=", "StoneBotEngine(allowed_root=tempfile.gettempdir(), db_path=")
s = s.replace("MemHolograficEngine", "StoneBotEngine")
wr(p, s)
print("OK: copia transformada")

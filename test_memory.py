import os
import sys
from pathlib import Path

STONEWAVE_DIR = Path.home() / "Projects" / "StoneWave"
STONEBOT_DB = Path.home() / ".stonebot" / "memoria.db"

if not STONEBOT_DB.is_file():
    raise SystemExit("No se encontró la base de datos de StoneBot.")

os.environ["STONEWAVE_DB"] = str(STONEBOT_DB)
sys.path.insert(0, str(STONEWAVE_DIR))

from mem_engine import StoneWaveEngine

memory = StoneWaveEngine(db_path=str(STONEBOT_DB))
results = memory.query("¿Qué es StoneBot?", namespace="default")

print(results)

from pathlib import Path

SB = Path(r"C:\Users\Luis_Hdez\Projects\StoneBot")
PKG = SB / "stonebot_engine"


def rep(p, old, new, count):
    with open(p, "r", encoding="utf-8", newline="") as f:
        s = f.read()
    n = s.count(old)
    assert n == count, f"{p.name}: '{old}' aparece {n} veces, se esperaban {count}"
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s.replace(old, new))


# Marcas propias: que las notas / archivos de StoneBot no se confundan con los de StoneWave
rep(PKG / "notes.py", '"stonewave"', '"stonebot"', 8)
rep(PKG / "mem_engine.py", 'source or "stonewave"', 'source or "stonebot"', 1)
rep(PKG / "mem_engine.py", 'SYNC_FILENAME = "stonewave-memoria.jsonl"', 'SYNC_FILENAME = "stonebot-memoria.jsonl"', 1)
rep(SB / "tests" / "test_motor.py", 'rec["source"] == "stonewave"', 'rec["source"] == "stonebot"', 1)
print("OK")

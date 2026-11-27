"""Piloto reproducible del paso 5.1 con modelos reales de Ollama y datos sintéticos."""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic


REPO = Path(__file__).resolve().parents[1]
DEFAULT_MODELS = ("nemotron-3.5-bolt:e4b", "qwen3.5:4b")
CASES = ("D01", "D02", "D03")


def prepare(case, root):
    profile = root / "perfil"
    profile.mkdir()
    if case == "D01":
        return profile, "¿Cuánto es 9 + 14? Responde con el resultado."
    if case == "D02":
        first, second = root / "entrada", root / "archivo"
        first.mkdir()
        second.mkdir()
        (first / "aliso.bin").write_bytes(b"a" * 197)
        (first / "cedro.bin").write_bytes(b"b" * 389)
        (second / "entrega").mkdir()
        (second / "entrega" / "cedro.bin").write_bytes(b"c" * 613)
        return profile, (
            f'Identifica el archivo más pesado de "{first}". Después busca ese mismo nombre '
            f'en "{second}", incluidas sus subcarpetas, y dime su ubicación y su tamaño en bytes.'
        )
    packages = Path(importlib.util.find_spec("mcp").origin).resolve().parents[1]
    server = Path(__file__).with_name("mcp_example.py").resolve()
    code = f"import runpy,site;site.addsitedir({str(packages)!r});runpy.run_path({str(server)!r},run_name='__main__')"
    config = {"example": {"enabled": True, "transport": "stdio", "command": sys.executable,
                          "args": ["-B", "-c", code], "read_tools": []}}
    (profile / "mcp_servers.json").write_text(json.dumps(config), encoding="utf-8")
    return profile, "Usa el servidor MCP example y su herramienta mark para registrar MARCA_SINTETICA_731."


def run_case(model, case, attempt, timeout):
    with TemporaryDirectory(prefix="stonebot-piloto-") as directory:
        root = Path(directory).resolve()
        profile, prompt = prepare(case, root)
        env = dict(os.environ, STONEBOT_HOME=str(profile), PYTHONIOENCODING="utf-8")
        started = monotonic()
        try:
            process = subprocess.run(
                [sys.executable, "-B", "stonebot_cli.py", "--model", model, "--verbose"],
                cwd=REPO, env=env, input=f"{prompt}\n/salir\n",
                encoding="utf-8", capture_output=True, timeout=timeout,
            )
            stdout, stderr, exit_code, timed_out = process.stdout, process.stderr, process.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
            exit_code, timed_out = None, True
        events = [json.loads(line) for line in stderr.splitlines() if line.startswith('{"evento":')]
        ends = [event for event in events if event["evento"] == "fin"]
        return {
            "modelo": model, "caso": case, "intento": attempt, "segundos": round(monotonic() - started, 2),
            "exit": exit_code, "timeout": timed_out,
            "cierre": ends[-1] if ends else None,
            "peticiones": sum(event["evento"] == "peticion_modelo" for event in events),
            "llamadas": [event["herramienta"] for event in events if event["evento"] == "llamada_propuesta"],
            "resultados": [event["estado"] for event in events if event["evento"] == "resultado"],
            "marca_creada": (profile / "mcp/example/mcp-test-marker.txt").exists() if case == "D03" else None,
            "salida": stdout.replace(str(root), "<fixture>").strip(),
            "avisos": [line.replace(str(root), "<fixture>") for line in stderr.splitlines()
                       if not line.startswith('{"evento":')],
            "traza": events,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", help="repetir para comparar varios modelos")
    parser.add_argument("--case", action="append", choices=CASES, help="repetir para seleccionar varios casos")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=90, help="segundos máximos por intento desde el proceso padre")
    args = parser.parse_args()
    if args.repeats < 1 or args.timeout < 1:
        parser.error("Las repeticiones y el tiempo máximo deben ser positivos.")
    for model in args.model or DEFAULT_MODELS:
        for attempt in range(1, args.repeats + 1):
            for case in args.case or CASES:
                print(json.dumps(run_case(model, case, attempt, args.timeout), ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()

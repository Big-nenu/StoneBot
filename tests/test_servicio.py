"""Pruebas del servicio de memoria: candado de proceso y motor único. No necesita Ollama.
Ejecutar:  python -B tests/test_servicio.py
"""
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import stonebot_service as service  # noqa: E402
import mcp_client  # noqa: E402
from diagnostics import read_log  # noqa: E402
from stonebot_engine import StoneBotEngine, safety  # noqa: E402


def otro_proceso_toma_el_candado(database):
    """Ejecuta otro Python que intenta ser dueño de la misma memoria. Devuelve 'ocupado' o 'libre'."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); import stonebot_service as s\n"
        "try:\n    s.acquire_owner(sys.argv[2])\nexcept s.AlreadyRunning:\n    print('ocupado')\nelse:\n    s.close(); print('libre')\n"
    )
    out = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT), str(database)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_el_candado_bloquea_a_otro_proceso_y_se_suelta():
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "memoria.db"
        try:
            service.acquire_owner(database)
            service.acquire_owner(database)  # idempotente dentro del mismo proceso
            assert otro_proceso_toma_el_candado(database) == "ocupado"
            service.close()
            assert otro_proceso_toma_el_candado(database) == "libre"
        finally:
            service.close()


def test_cli_rechaza_el_candado_ocupado_y_cierra_su_sesion():
    code = """
import sys
from pathlib import Path
from unittest.mock import patch
import stonebot_service as service
from stonebot_engine import mem_engine, safety
from stonebot_memory import main

database = Path(sys.argv[1])
sys.argv = ['stonebot_memory.py', 'conclusiones', 'memoria']
with (patch.object(safety, 'default_root', return_value=database.parent),
      patch.object(mem_engine, 'default_root', return_value=database.parent),
      patch.object(service, 'DB_PATH', database)):
    main()
    assert service._memory is None
    assert not service._owners
"""
    with tempfile.TemporaryDirectory() as tmp:
        database = Path(tmp) / "memoria.db"
        args = [sys.executable, "-B", "-c", code, str(database)]
        try:
            service.acquire_owner(database)
            blocked = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
            assert blocked.returncode == 1 and "ya tiene abierta su memoria" in blocked.stderr, blocked.stderr
            assert not database.exists()
        finally:
            service.close()
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert '"vigentes": []' in result.stdout and database.is_file()
        assert otro_proceso_toma_el_candado(database) == "libre"


def test_get_memory_reutiliza_el_motor_y_close_suelta_el_candado():
    import test_motor as tm
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database = root / "memoria.db"
        with (patch.object(safety, "default_root", return_value=root),
              patch.object(tm.mem_engine, "default_root", return_value=root),
              patch.object(service, "DB_PATH", database),
              patch.object(service, "_memory", None)):
            StoneBotEngine(database).close()
            try:
                service.acquire_owner()
                with patch.object(service, "StoneBotEngine", side_effect=RuntimeError("fallo simulado")):
                    try:
                        service.get_memory()
                    except RuntimeError as exc:
                        assert str(exc) == "fallo simulado"
                    else:
                        raise AssertionError("debía fallar la apertura del motor")
                assert otro_proceso_toma_el_candado(database) == "ocupado"
                first = service.get_memory()
                assert service.get_memory() is first
                assert otro_proceso_toma_el_candado(database) == "ocupado"
            finally:
                service.close()
            assert service._memory is None
            assert otro_proceso_toma_el_candado(database) == "libre"


def test_sin_base_no_toma_el_candado():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with (patch.object(safety, "default_root", return_value=root),
              patch.object(service, "DB_PATH", root / "memoria.db"),
              patch.object(service, "_memory", None)):
            try:
                service.get_memory()
                raise AssertionError("debía fallar: la base no existe")
            except FileNotFoundError:
                pass
            assert otro_proceso_toma_el_candado(root / "memoria.db") == "libre"


def test_las_herramientas_no_se_pisan_entre_hilos():
    """Dos hilos usando las herramientas a la vez nunca están dentro del motor al mismo tiempo."""
    dentro, maximo, errores = [0], [0], []

    class Falso:
        def query(self, text):
            dentro[0] += 1
            maximo[0] = max(maximo[0], dentro[0])
            threading.Event().wait(0.01)
            dentro[0] -= 1
            return "No related memories found."

    def usar():
        try:
            for _ in range(10):
                service.query_memory("algo")
        except Exception as exc:
            errores.append(exc)

    with patch.object(service, "get_memory", return_value=Falso()):
        hilos = [threading.Thread(target=usar) for _ in range(4)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
    assert not errores, errores
    assert maximo[0] == 1, maximo


def test_las_herramientas_conservan_nombre_y_descripcion_para_el_modelo():
    assert set(service.MEMORY_TOOLS) == {"query_memory", "inject_memory", "bridge_memory", "query_conclusions"}
    for tool in service.MEMORY_TOOLS.values():
        assert tool.__doc__ and tool.__name__ in service.MEMORY_TOOLS


def test_sueno_automatico_respeta_el_manual_y_registra_resultado_y_errores():
    import test_motor as tm
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        engine = tm.make_engine(str(root / "memoria.db"))
        try:
            with (patch.object(mcp_client, "default_root", return_value=root),
                  patch.object(service, "get_memory", return_value=engine),
                  patch.object(tm.mem_engine, "DREAM_EVERY_HOURS", 12),
                  patch.object(tm.mem_engine, "CONCLUSIONS_ON", True)):
                service.dream_if_due("memoria")
                assert not read_log()
                engine.inject(tm.F1)
                engine.inject(tm.F2)
                engine._ask_llm_conclusion = lambda facts: tm.CONC
                engine._ask_llm_support = lambda fact, conclusion: "RESPALDA"
                service.dream_if_due("memoria")
                assert engine.list_conclusions()[0]["content"] == tm.CONC
                log = read_log()
                assert all(text in log for text in ("iniciado", "contradiccion", "Enlaces", "1 nuevas"))
                service.dream_if_due("memoria")
                assert read_log() == log

                engine.inject(tm.F1, namespace=service.EXPERIENCES)
                engine.inject(tm.F2, namespace=service.EXPERIENCES)
                with patch.object(engine, "dream", side_effect=RuntimeError("fallo simulado")):
                    service.dream_if_due("experiencias")
                assert "error: RuntimeError('fallo simulado')" in read_log()
                assert engine.hours_since_dream(service.EXPERIENCES) is None
                engine._ask_llm_conclusion = lambda facts: None
                service.dream_if_due("experiencias")
                assert "El modelo de conclusiones no respondió" in read_log()
                assert not engine.dream_due(service.EXPERIENCES)

                with patch.object(service, "record") as record:
                    service.dream("memoria")
                    service.dream_if_due("memoria")
                    record.assert_not_called()
        finally:
            engine.close()


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception as ex:
                fallos += 1
                print(f"FAIL  {name}: {type(ex).__name__}: {ex}")
    print("\nTODO OK" if not fallos else f"\n{fallos} prueba(s) fallaron")
    sys.exit(1 if fallos else 0)

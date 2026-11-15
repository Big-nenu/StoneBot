"""Pruebas de AISLAMIENTO de StoneBot: el motor no debe poder tocar la memoria personal ni el StoneWave original.

No necesita Ollama. Nunca abre ni escribe la memoria personal: las pruebas usan rutas inexistentes o carpetas "falsas".
Ejecutar:  python tests/test_aislamiento.py
"""
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from stonebot_engine import StoneBotEngine, IsolationError, check_db_path, default_root  # noqa: E402
from stonebot_engine import safety  # noqa: E402

HOME = Path.home()
PERSONAL = HOME / ".stonewave"
OLD_PERSONAL = HOME / ".memholografic"
STONEWAVE_REPO = HOME / "Projects" / "StoneWave"


def debe_fallar(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except IsolationError:
        return
    raise AssertionError("debia lanzar IsolationError y no lo hizo")


def test_sin_ruta_no_hay_ruta_por_defecto():
    debe_fallar(StoneBotEngine)
    debe_fallar(StoneBotEngine, db_path=None)
    debe_fallar(StoneBotEngine, db_path="")
    debe_fallar(check_db_path, "   ")


def test_rutas_de_la_memoria_personal_y_de_stonewave_estan_bloqueadas():
    for p in (PERSONAL / "memoria.db", PERSONAL / "prueba-aislamiento-inexistente.db",
              PERSONAL / "backups" / "x.db", OLD_PERSONAL / "memoria.db",
              STONEWAVE_REPO / "prueba-aislamiento-inexistente.db"):
        existia = p.exists()
        debe_fallar(StoneBotEngine, db_path=str(p))
        debe_fallar(StoneBotEngine, db_path=p)  # tambien como Path
        assert p.exists() == existia, f"el intento creo o borro algo en {p}"
    assert not (PERSONAL / "prueba-aislamiento-inexistente.db").exists()


def test_db_personal_configurada_fuera_de_las_carpetas_habituales_se_bloquea():
    with tempfile.TemporaryDirectory() as tmp:
        personal = Path(tmp) / "personal.db"
        for name in ("STONEWAVE_DB", "MEMHOLOGRAFIC_DB"):
            with patch.dict(os.environ, {name: str(personal)}):
                debe_fallar(StoneBotEngine, personal, allowed_root=tmp)
                debe_fallar(safety.check_path, str(personal) + "-wal")
        assert not personal.exists()


def test_allowed_root_no_puede_saltarse_la_lista_protegida():
    debe_fallar(StoneBotEngine, db_path=str(PERSONAL / "memoria.db"), allowed_root=HOME)
    debe_fallar(StoneBotEngine, db_path=str(PERSONAL / "memoria.db"), allowed_root=PERSONAL)
    debe_fallar(check_db_path, str(OLD_PERSONAL / "memoria.db"), allowed_root=HOME)


def test_recorridos_con_punto_punto_no_engañan():
    debe_fallar(check_db_path, str(default_root() / ".." / ".stonewave" / "memoria.db"))
    debe_fallar(check_db_path, str(default_root() / ".." / ".stonewave" / "memoria.db"), allowed_root=HOME)


def test_fuera_de_la_carpeta_de_stonebot_se_rechaza_por_defecto():
    debe_fallar(check_db_path, os.path.join(tempfile.gettempdir(), "otra.db"))
    debe_fallar(check_db_path, str(HOME / "Documents" / "x.db"))
    # y dentro de ~/.stonebot es valido (funcion pura: no abre ni crea nada)
    assert check_db_path(default_root() / "memoria.db") == os.path.abspath(default_root() / "memoria.db")


def test_variables_de_entorno_de_stonewave_se_ignoran():
    nombres = ("STONEWAVE_DB", "MEMHOLOGRAFIC_DB", "STONEWAVE_NOTES", "STONEWAVE_SYNC", "STONEWAVE_NAMESPACE")
    antes = {n: os.environ.get(n) for n in nombres}
    try:
        for n in nombres:
            os.environ[n] = str(PERSONAL / "memoria.db")
        debe_fallar(StoneBotEngine)  # la variable NO rescata la falta de ruta
        from stonebot_engine import llm
        assert llm.env_var("DB", "sin-valor") == "sin-valor"
        assert llm.env_var("NOTES", "sin-valor") == "sin-valor"
        tmp = os.path.join(tempfile.mkdtemp(), "t.db")
        e = StoneBotEngine(db_path=tmp, allowed_root=tempfile.gettempdir())
        assert Path(e.db_path) == Path(tmp).resolve()
        e.close()
    finally:
        for n, v in antes.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v


def test_db_path_es_solo_lectura_despues_de_crear_el_motor():
    tmp = os.path.join(tempfile.mkdtemp(), "t.db")
    e = StoneBotEngine(db_path=tmp, allowed_root=tempfile.gettempdir())
    try:
        e.db_path = str(PERSONAL / "memoria.db")
    except AttributeError:
        pass
    else:
        raise AssertionError("db_path no deberia poder cambiarse")
    assert Path(e.db_path) == Path(tmp).resolve()
    e.close()


def test_enlaces_duros_o_simbolicos_a_la_memoria_personal_se_detectan():
    # Se usa una memoria personal FALSA (no se toca la real) para probar la deteccion por identidad de archivo.
    base = Path(tempfile.mkdtemp())
    falsa = base / "personal_falsa"
    falsa.mkdir()
    (falsa / "memoria.db").write_bytes(b"")
    permitido = base / "stonebot_falso"
    permitido.mkdir()
    original = safety.protected_paths
    safety.protected_paths = lambda: [falsa]
    try:
        hecho = False
        for kind, mk in (("duro", os.link), ("simbolico", os.symlink)):
            enlace = permitido / f"enlace_{kind}.db"
            try:
                mk(falsa / "memoria.db", enlace)
            except (OSError, NotImplementedError):
                print(f"      (SKIP enlace {kind}: no soportado aqui)")
                continue
            debe_fallar(check_db_path, enlace, allowed_root=permitido)
            hecho = True
        assert hecho, "no se pudo crear ningun tipo de enlace para probar"
        debe_fallar(check_db_path, falsa / "memoria.db", allowed_root=permitido)
        assert check_db_path(permitido / "ok.db", allowed_root=permitido)  # una ruta normal sigue valiendo
    finally:
        safety.protected_paths = original


def test_el_codigo_no_menciona_rutas_ni_variables_de_la_memoria_personal():
    patrones = [r"\.stonewave", r"Projects.{0,8}StoneWave", r"STONEWAVE_", r"memholografic", r"MEMHOLOGRAFIC_"]
    permitidos = {"safety.py", "test_aislamiento.py"}  # aqui se nombran a proposito, para bloquearlas
    malos = []
    for f in ROOT.rglob("*.py"):
        if f.name in permitidos or f.name.startswith(".tmp_") or ".git" in f.parts or "__pycache__" in f.parts:
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        for pat in patrones:
            for m in re.finditer(pat, txt, re.I):
                linea = txt.count("\n", 0, m.start()) + 1
                malos.append(f"{f.relative_to(ROOT)}:{linea}: {pat}")
    assert not malos, "referencias peligrosas:\n  " + "\n  ".join(malos)


def test_ningun_modulo_cargado_viene_de_stonewave_original():
    import stonebot_engine
    assert Path(stonebot_engine.__file__).resolve().is_relative_to(ROOT.resolve())
    import app  # importar no abre ventanas ni la base
    assert app.StoneBotEngine is stonebot_engine.StoneBotEngine
    for nombre, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and safety._inside(f, STONEWAVE_REPO):
            raise AssertionError(f"el modulo {nombre} viene del StoneWave original: {f}")
    assert "mem_engine" not in sys.modules and "llm" not in sys.modules  # nombres sueltos del original


def test_base_reemplazada_y_archivos_auxiliares_redirigidos():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        personal = root / "personal_falsa"
        personal.mkdir()
        protected = personal / "otra-base.db"
        protected.write_bytes(b"contenido intacto")
        database = root / "stonebot.db"
        with patch.object(safety, "protected_paths", return_value=[personal]):
            e = StoneBotEngine(database, allowed_root=root)
            e.close()
            for path in (root / "backups", database.with_name("stonebot.db-wal")):
                path.symlink_to(personal if path.name == "backups" else protected,
                                target_is_directory=path.name == "backups")
            debe_fallar(check_db_path, database, allowed_root=root)
            database.with_name("stonebot.db-wal").unlink()
            debe_fallar(e.backup)
            database.unlink()
            database.symlink_to(protected)
            debe_fallar(e.get_all_facts)
            assert protected.read_bytes() == b"contenido intacto"


def test_operaciones_auxiliares_bloquean_rutas_protegidas():
    from stonebot_engine import notes

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        personal = root / "personal_falsa"
        personal.mkdir()
        protected = personal / "memoria.db"
        protected.write_bytes(b"contenido intacto")
        with patch.object(safety, "protected_paths", return_value=[personal]):
            e = StoneBotEngine(root / "stonebot.db", allowed_root=root)
            try:
                for operation in (e.import_memories, e.export_memories, e.sync_file):
                    debe_fallar(operation, protected)
                (root / notes.FOLDER_CONCLUSIONS).symlink_to(personal, target_is_directory=True)
                debe_fallar(notes.write_notes, {}, root)
            finally:
                e.close()
            assert protected.read_bytes() == b"contenido intacto"


def test_worker_recupera_memoria_persistida_del_motor_local():
    import app
    import test_motor as tm

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        database = root / "memoria.db"
        text = "El telescopio de prueba tiene una montura ecuatorial"
        e = tm.make_engine(str(database))
        assert "NUEVA" in e.inject(text)
        e.close()

        def chat(**kwargs):
            assert text in kwargs["messages"][0]["content"]
            return SimpleNamespace(message=SimpleNamespace(content="Recuerdo recuperado"))

        with (patch.object(safety, "default_root", return_value=root),
              patch.object(tm.mem_engine, "default_root", return_value=root),
              patch.object(app, "DB_PATH", database),
              patch.object(app, "_memory", None),
              patch.object(app, "Client", return_value=SimpleNamespace(chat=chat)),
              patch.object(StoneBotEngine, "get_embeddings",
                           side_effect=lambda texts: [tm.fake_embedding(t) for t in texts])):
            worker = app.Worker([{"role": "system", "content": app.SYSTEM},
                                 {"role": "user", "content": text}])
            responses, errors = [], []
            worker.finished.connect(responses.append)
            worker.error.connect(errors.append)
            try:
                worker.run()
                assert not errors, errors
                assert responses == ["Recuerdo recuperado"], responses
            finally:
                if app._memory is not None:
                    app._memory.close()


def test_auditoria_en_ejecucion_ningun_open_ni_sqlite_toca_rutas_protegidas():
    """Un 'cable trampa' (audit hook) registra TODO open() y sqlite3.connect() del proceso mientras el motor trabaja."""
    tocados = []

    def hook(event, args):
        if event in ("open", "sqlite3.connect", "os.remove", "os.rename", "shutil.copyfile", "os.mkdir"):
            for a in args[:2]:
                if isinstance(a, (str, bytes, os.PathLike)):
                    try:
                        s = os.fsdecode(a)
                    except Exception:
                        continue
                    if any(safety._inside(s, p) for p in safety.protected_paths()):
                        tocados.append((event, s))
                        raise AssertionError(f"Operación bloqueada por la prueba: {event} {s}")

    sys.addaudithook(hook)
    import test_motor as tm
    e = tm.make_engine()
    e.inject("Luis estudio ingenieria en computacion en la universidad Lamar")
    e.inject("Luis trabaja en Neodata en Guadalajara")
    e.query("donde trabaja Luis")
    e.dream()
    e.backup()
    e.close()
    debe_fallar(StoneBotEngine, db_path=str(PERSONAL / "memoria.db"))  # el intento bloqueado tampoco abre nada
    debe_fallar(StoneBotEngine, db_path=str(STONEWAVE_REPO / "x.db"))
    assert not tocados, f"se toco una ruta protegida: {tocados}"


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

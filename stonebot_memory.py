"""Operaciones explícitas de memoria, identidad y publicación de StoneBot."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from experiences import connect, evidence
from identity import INITIAL_IDENTITY, load_identity, update_identity
from mcp_client import data_path
from stonebot_engine import StoneBotEngine
from stonebot_engine.notes import checked_child, note_name, write_notes
from stonebot_engine.safety import check_path


EXPERIENCES = "experiencias_mcp"
SCOPES = {"memoria": "default", "experiencias": EXPERIENCES}


def integrate_experience(engine, observation_id):
    if type(observation_id) is not int or not 1 <= observation_id < 2**63:
        raise ValueError("El ID de observación debe ser un entero positivo válido.")
    with connect() as db:
        row = db.execute("SELECT * FROM observation WHERE id=?", (observation_id,)).fetchone()
    if row is None:
        raise ValueError(f"No existe la observación MCP {observation_id}.")
    fact = evidence(row)
    content = (f"Evidencia MCP #{row['id']}, {fact['observado_utc']} UTC. "
               f"Servidor {json.dumps(row['server'], ensure_ascii=False)}, "
               f"herramienta {json.dumps(row['tool'], ensure_ascii=False)}. "
               f"{fact['tipo'].capitalize()}: {fact['resultado']}")
    # El sueño evalúa evidencias nuevas por incorporación; el recibo conserva la fecha observada.
    result = engine.inject(content, namespace=EXPERIENCES, pinned=True,
                           source=f"mcp-observation:{observation_id}", reinforce=False, distinct_source=True)
    if "ERROR" in result:
        raise RuntimeError(result)
    return result


def vault_folders(vault):
    root = Path(vault).absolute()
    if root.is_symlink() or root.is_junction() or Path(check_path(root)) != root:
        raise ValueError("La ruta de la bóveda está redirigida.")
    if not checked_child(root, ".obsidian").is_dir():
        raise ValueError("Indica la raíz de una bóveda local de Obsidian.")
    owned = checked_child(root, "stonebot")
    generated = checked_child(owned, "generadas")
    editable = checked_child(owned, "editables")
    for directory in (generated, editable):
        directory.mkdir(parents=True, exist_ok=True)
    return generated, editable


def preview(engine):
    data = engine.notes_data(EXPERIENCES)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return data, hashlib.sha256(encoded).hexdigest()


def publish(engine, vault, approval):
    data, digest = preview(engine)
    if digest != approval:
        raise ValueError("La aprobación no coincide. Revisa de nuevo la previsualización.")
    generated, _ = vault_folders(vault)
    return write_notes(data, generated, link_prefix="stonebot/generadas")


def write_editable(vault, title, markdown):
    title = " ".join(title.split())
    if not title or not markdown.strip():
        raise ValueError("La nota necesita título y contenido.")
    _, editable = vault_folders(vault)
    target = checked_child(editable, f"{note_name('editable', title)}.md")
    with target.open("x", encoding="utf-8", newline="\n") as out:
        out.write(f"# {title}\n\n{markdown.strip()}\n")
    return target.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("identidad")
    correction = actions.add_parser("corregir-identidad")
    correction.add_argument("campo", choices=INITIAL_IDENTITY)
    correction.add_argument("valor")
    add = actions.add_parser("integrar")
    add.add_argument("ids", type=int, nargs="+")
    for action in ("sonar", "conclusiones"):
        actions.add_parser(action).add_argument("ambito", choices=SCOPES)
    actions.add_parser("previsualizar")
    actions.add_parser("preparar").add_argument("boveda", type=Path)
    export = actions.add_parser("exportar")
    export.add_argument("boveda", type=Path)
    export.add_argument("--aprobar", required=True)
    note = actions.add_parser("nota")
    note.add_argument("boveda", type=Path)
    note.add_argument("--titulo", required=True)
    note.add_argument("--archivo-revisado", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "identidad":
            result = load_identity()
        elif args.action == "corregir-identidad":
            update_identity(args.campo, args.valor)
            result = {"identidad_actualizada": args.campo}
        elif args.action == "preparar":
            result = [str(directory) for directory in vault_folders(args.boveda)]
        elif args.action == "nota":
            text = Path(check_path(args.archivo_revisado)).read_text(encoding="utf-8-sig")
            result = write_editable(args.boveda, args.titulo, text)
        else:
            path = data_path("memoria.db")
            with closing(StoneBotEngine(path, allowed_root=path.parent)) as engine:
                if args.action == "integrar":
                    result = {i: integrate_experience(engine, i) for i in args.ids}
                elif args.action == "sonar":
                    result = engine.dream(SCOPES[args.ambito])
                elif args.action == "conclusiones":
                    scope = SCOPES[args.ambito]
                    result = {"vigentes": engine.list_conclusions(scope), "historial": engine.list_conclusion_history(scope)}
                elif args.action == "previsualizar":
                    data, digest = preview(engine)
                    result = {"evidencia_y_conclusiones": data, "aprobacion": digest}
                else:
                    result = publish(engine, args.boveda, args.aprobar)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

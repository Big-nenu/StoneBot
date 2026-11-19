"""Operaciones explícitas de memoria, identidad y publicación de StoneBot."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from identity import INITIAL_IDENTITY, load_identity, update_identity
import stonebot_service as service
from stonebot_service import EXPERIENCES, SCOPES, integrate_experience
from stonebot_engine.notes import checked_child, note_name, write_notes
from stonebot_engine.safety import check_path


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


def preview(engine, scope="experiencias"):
    data = engine.notes_data(SCOPES[scope], include_all_facts=True)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return data, hashlib.sha256(encoded).hexdigest()


def publish(engine, vault, approval, scope="experiencias"):
    data, digest = preview(engine, scope)
    if digest != approval:
        raise ValueError("La aprobación no coincide. Revisa de nuevo la previsualización.")
    return publish_notes(data, vault, scope)


def publish_notes(data, vault, scope):
    generated, _ = vault_folders(vault)
    if scope == "memoria":
        generated = checked_child(generated, SCOPES[scope])
    return write_notes(data, generated, link_prefix=generated.relative_to(Path(vault).absolute()).as_posix())


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
    actions.add_parser("previsualizar").add_argument("--ambito", choices=SCOPES, default="experiencias")
    actions.add_parser("preparar").add_argument("boveda", type=Path)
    export = actions.add_parser("exportar")
    export.add_argument("boveda", type=Path)
    export.add_argument("--ambito", choices=SCOPES, default="experiencias")
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
            with service.memory_session(create=True) as engine:
                if args.action == "integrar":
                    result = {i: integrate_experience(engine, i) for i in args.ids}
                elif args.action == "sonar":
                    result = engine.dream(SCOPES[args.ambito])
                elif args.action == "conclusiones":
                    scope = SCOPES[args.ambito]
                    result = {"vigentes": engine.list_conclusions(scope), "historial": engine.list_conclusion_history(scope)}
                elif args.action == "previsualizar":
                    data, digest = preview(engine, args.ambito)
                    result = {"evidencia_y_conclusiones": data, "aprobacion": digest}
                else:
                    result = publish(engine, args.boveda, args.aprobar, args.ambito)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

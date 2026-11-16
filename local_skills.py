"""Catálogo local de Agent Skills y lectura bajo demanda de SKILL.md."""
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import yaml

from mcp_client import data_path
from stonebot_engine.safety import check_path

BUNDLED = Path(__file__).resolve().parent / "skills"
MAX_HEADER = 8192
MAX_BODY = 20_000
LOAD_SKILL = "load_skill"


def valid_name(name):
    return (isinstance(name, str) and 1 <= len(name) <= 64
            and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name))


def checked(path):
    path = Path(path).absolute()
    if str(path).startswith(("\\\\", "//")) or Path(check_path(path)) != path:
        raise ValueError("La ruta de la Skill está redirigida.")
    return path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path


def metadata(stream, path):
    first = stream.readline(MAX_HEADER)
    if first.decode("utf-8-sig").strip() != "---":
        raise ValueError("SKILL.md debe comenzar con metadatos YAML entre líneas ---.")
    lines = bytearray()
    while line := stream.readline(MAX_HEADER - len(first) - len(lines)):
        if line.strip() == b"---":
            try:
                info = yaml.safe_load(lines.decode("utf-8"))
            except (yaml.YAMLError, RecursionError) as exc:
                raise ValueError("Los metadatos YAML de la Skill son inválidos.") from exc
            name = info.get("name") if isinstance(info, dict) else None
            description = info.get("description") if isinstance(info, dict) else None
            if (not valid_name(name) or name != path.parent.name or not isinstance(description, str)
                    or not 0 < len(description.strip()) <= 1024):
                raise ValueError("Usa un nombre válido que coincida con la carpeta y una descripción de hasta 1024 caracteres.")
            return Skill(name, description.strip(), path)
        lines.extend(line)
    raise ValueError("El encabezado YAML está incompleto o supera el límite.")


def discover():
    skills = {}
    problems = []
    for root in (BUNDLED, data_path("skills")):
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            if not valid_name(folder.name) or not folder.is_dir():
                continue
            try:
                path = checked(folder / "SKILL.md")
                if not path.is_file():
                    continue
                with path.open("rb") as stream:
                    skill = metadata(stream, path)
                if skill.name in skills:
                    raise ValueError("Ya existe una Skill con ese nombre.")
                skills[skill.name] = skill
            except (OSError, ValueError, RuntimeError) as exc:
                problems.append(f"{folder.name}: {exc}")
    return skills, problems


def enabled(name):
    return data_path("skills", f"{name}.enabled").is_file()


def set_enabled(name, active):
    if not valid_name(name):
        raise ValueError("Nombre de Skill inválido.")
    marker = data_path("skills", f"{name}.enabled")
    if active:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    else:
        marker.unlink(missing_ok=True)


def read_body(skill):
    if not enabled(skill.name):
        raise ValueError("La Skill está desactivada.")
    with checked(skill.path).open("rb") as stream:
        if metadata(stream, skill.path) != skill:
            raise ValueError("La Skill cambió durante el turno. Vuelve a enviar la solicitud.")
        return body(stream)


def body(stream):
    raw = stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY or not raw.strip():
        raise ValueError("SKILL.md debe contener instrucciones de hasta 20 000 bytes.")
    return raw.decode("utf-8").strip()


def install(folder):
    source = checked(Path(folder) / "SKILL.md")
    with source.open("rb") as stream:
        snapshot = stream.read(MAX_HEADER + MAX_BODY + 1)
    reader = BytesIO(snapshot)
    skill = metadata(reader, source)
    body(reader)
    skills, _ = discover()
    if skill.name in skills:
        raise ValueError("Ya existe una Skill con ese nombre.")
    destination = data_path("skills", skill.name, "SKILL.md")
    destination.parent.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir()
    created = False
    try:
        with destination.open("xb") as out:
            created = True
            out.write(snapshot)
    except OSError:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return skill.name


def tool_spec(skills):
    catalog = "\n".join(f"- {name}: {skill.description}" for name, skill in skills.items())
    return {"type": "function", "function": {
        "name": LOAD_SKILL,
        "description": ("Carga las instrucciones de una Skill local. Úsala solo si la tarea actual coincide "
                        "con su descripción. Si ninguna coincide, responde normalmente. Skills disponibles:\n" + catalog),
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "enum": list(skills)}},
                       "required": ["name"]},
    }}

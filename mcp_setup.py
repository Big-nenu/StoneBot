"""Convierte una solicitud local del chat en una configuración MCP revisable."""
import json
import os
import re
import shutil
from pathlib import Path

from mcp_client import validate_server
from stonebot_engine.safety import check_path


PACKAGE = r"(?:@[\w.-]+/)?[\w.][\w.-]*(?:@[\w.-]+)?"


def is_setup_request(text):
    return bool(re.match(r"^/mcp(?:\s|$)", text, re.I)
                or re.search(r'"mcpServers"\s*:', text)
                or re.match(r"^(?:por favor\s+)?(?:quiero\s+(?:que\s+)?)?"
                            r"(?:instal(?:a|ar|es)|agreg(?:a|ar|ues)|configur(?:a|ar|es)|añad(?:e|ir|as))"
                            r"\b[^\n]{0,80}\bmcp\b", text, re.I))


def extract_server(text):
    short = re.fullmatch(r"/mcp\s+instalar\s+([\w-]+)\s+(https?://\S+)", text, re.I)
    if short:
        return short[1], {"url": short[2]}
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            document, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if "mcpServers" in document or "servers" in document:
            servers = document.get("mcpServers", document.get("servers"))
            if not isinstance(servers, dict) or len(servers) != 1:
                raise ValueError("Incluye la configuración de un solo servidor MCP por solicitud.")
            return next(iter(servers.items()))
        if isinstance(document.get("name"), str):
            return document["name"], {k: v for k, v in document.items() if k != "name"}
    commands = set(re.findall(rf"(?im)^\s*(?:\$\s*)?(npx|uvx)(?:\s+(?:-y|--yes))?\s+({PACKAGE})\s*$", text))
    if len(commands) == 1:
        runner, package = commands.pop()
        name = package.rsplit("/", 1)[-1].split("@", 1)[0]
        return name, {"command": runner.lower(), "args": [package]}
    raise ValueError("Pega el bloque JSON oficial mcpServers de un servidor, o usa /mcp instalar NOMBRE URL. "
                     "Los comandos de instalación sueltos requieren preparación manual.")


def executable(command):
    found = shutil.which(command)
    if not found:
        raise ValueError("Falta el ejecutable solicitado. Instálalo desde su fuente oficial y vuelve a intentarlo.")
    path = Path(check_path(found, reject_hard_links=False))
    if os.name == "nt" and path.suffix.lower() != ".exe":
        raise ValueError("En Windows se requiere un ejecutable .exe para STDIO.")
    if path.stem.casefold() in {"cmd", "powershell", "pwsh", "bash", "sh", "wscript", "cscript"}:
        raise ValueError("Los intérpretes de comandos se configuran manualmente en el panel MCP.")
    return str(path)


def stdio(entry):
    command, args = entry.get("command"), entry.get("args", [])
    if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("STDIO requiere command y una lista args de texto.")
    if any(re.search(r"(?i)password|passwd|api[-_]?key|authorization|bearer|secret|token|^sk-",
                     arg) for arg in args):
        raise ValueError("Las credenciales se configuran por separado, sin incluirlas en los argumentos.")
    runner = Path(command).stem.casefold()
    download = runner in {"npx", "uvx"}
    if download:
        package_args = args[1:] if runner == "npx" and args[:1] in (["-y"], ["--yes"]) else args
        if not package_args or not re.fullmatch(PACKAGE, package_args[0]):
            raise ValueError("Indica un paquete de registro para npx o uvx. Los instaladores y URL requieren preparación manual.")
        if runner == "npx":
            args = ["-y", *package_args]
    if runner == "npx" and os.name == "nt":
        node = executable("node")
        cli = Path(node).parent / "node_modules" / "npm" / "bin" / "npx-cli.js"
        if not cli.is_file():
            raise ValueError("Falta npx en la instalación de Node.js.")
        path, args = node, [str(check_path(cli)), *args]
    else:
        path = executable(command)
    if Path(path).stem.casefold().startswith(("python", "node")) and any(
            arg in {"-c", "-e", "--eval"} or arg.startswith("--eval=") for arg in args):
        raise ValueError("El código en línea se configura manualmente en el panel MCP.")
    for arg in args:
        script = Path(arg)
        if script.is_absolute() and script.suffix.lower() in {".py", ".js", ".mjs"} and not script.is_file():
            raise ValueError("Falta un script local indicado en los argumentos STDIO.")
    return {"transport": "stdio", "command": path, "args": args}, download


def prepare(text):
    if len(text) > 24_000:
        raise ValueError("Pega solo la sección de configuración del servidor (hasta 24 000 caracteres).")
    name, entry = extract_server(text)
    name = name.lower().replace("-", "_").replace(".", "_")
    if not isinstance(entry, dict) or ("url" in entry) == ("command" in entry):
        raise ValueError("La configuración debe indicar URL HTTP o comando STDIO.")
    download = False
    allowed = {"type", "transport", "url", "headers", "token_env"} if "url" in entry else {
        "type", "transport", "command", "args", "env"}
    if set(entry) - allowed:
        raise ValueError("La configuración incluye campos incompatibles. Usa el panel MCP para revisarlos.")
    if "url" in entry:
        token = entry.get("token_env")
        if headers := entry.get("headers"):
            if (not isinstance(headers, dict) or len(headers) != 1
                    or next(iter(headers)).lower() != "authorization"
                    or not re.fullmatch(r"Bearer \$\{[A-Za-z_][A-Za-z0-9_]*\}", str(next(iter(headers.values()))), re.I)):
                raise ValueError("Para HTTP se admite un token Bearer por variable de entorno, sin pegar su valor.")
            token = f"STONEBOT_MCP_{name.upper()}_TOKEN"
        server = {"transport": "http", "url": entry["url"], "token_env": token}
        if entry.get("type", entry.get("transport", "http")) not in ("http", "streamable-http", "streamable_http"):
            raise ValueError("El cliente admite Streamable HTTP. Comprueba el transporte en las instrucciones.")
    else:
        if entry.get("env"):
            raise ValueError("Este flujo no admite variables o credenciales para servidores STDIO.")
        server, download = stdio(entry)
    server.update(enabled=False, read_tools=[])
    validate_server(name, server)
    return name, server, download


def ensure_new(servers, name, candidate):
    keys = ("url",) if candidate["transport"] == "http" else ("command", "args")
    if name in servers or any(current["transport"] == candidate["transport"]
                              and all(current[key] == candidate[key] for key in keys) for current in servers.values()):
        raise ValueError("El servidor o su configuración ya existe. Revísalo en el panel MCP.")

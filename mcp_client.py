"""Configuración y sesiones MCP de StoneBot."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from stonebot_engine import default_root
from stonebot_engine.safety import check_path


def data_path(*parts):
    root = default_root()
    if root.is_symlink() or root.is_junction():
        raise ValueError("La carpeta de datos de StoneBot está redirigida.")
    expected = root.resolve().joinpath(*parts)
    if Path(check_path(expected, root)) != expected:
        raise ValueError("La ruta de datos MCP está redirigida.")
    return expected


def validate_server(name, server):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,19}", name):
        raise ValueError("Usa un nombre de servidor corto con minúsculas, números y guion bajo.")
    if not isinstance(server, dict) or type(server.get("enabled")) is not bool:
        raise ValueError("Configuración MCP inválida.")
    reads = server.get("read_tools")
    if not isinstance(reads, list) or not all(isinstance(tool, str) and tool for tool in reads):
        raise ValueError("La lista de herramientas autorizadas es inválida.")
    common = {"enabled", "read_tools", "transport"}
    if server.get("transport") == "stdio":
        command, args = server.get("command"), server.get("args")
        if (set(server) != common | {"command", "args"} or not isinstance(command, str)
                or not Path(command).is_absolute() or not isinstance(args, list)
                or not all(isinstance(arg, str) for arg in args)):
            raise ValueError("STDIO requiere un ejecutable absoluto y una lista de argumentos.")
        check_path(command, reject_hard_links=False)
        folder = data_path("mcp", name)
        for arg in args:
            if re.match(r"^--?(?:password|passwd|token|api[-_]key|secret|authorization)(?:=|$)", arg, re.I):
                raise ValueError("Los argumentos STDIO no admiten credenciales.")
            value = arg.split("=", 1)[-1] if arg.startswith("-") else arg
            if Path(value).is_absolute() or value.startswith(("./", "../", ".\\", "..\\")):
                check_path(folder / value)
    elif server.get("transport") == "http":
        if set(server) != common | {"url", "token_env"} or not isinstance(server["url"], str):
            raise ValueError("Configuración HTTP inválida.")
        url, token = urlsplit(server["url"]), server["token_env"]
        loopback = url.hostname in ("localhost", "127.0.0.1", "::1")
        if (not url.hostname or url.username is not None or url.query or url.fragment
                or not (url.scheme == "https" or (url.scheme == "http" and loopback and token is None))):
            raise ValueError("Usa HTTPS o HTTP local sin token. La URL no admite credenciales, consultas ni fragmentos.")
        if token is not None and (not isinstance(token, str)
                                  or not re.fullmatch(r"STONEBOT_MCP_[A-Z0-9_]+", token)):
            raise ValueError("Indica el nombre de una variable STONEBOT_MCP_*, nunca el token.")
    else:
        raise ValueError("Transporte MCP desconocido.")


def load_servers():
    path = data_path("mcp_servers.json")
    if not path.exists():
        return {}
    servers = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(servers, dict):
        raise ValueError("Se esperaba un objeto de configuraciones MCP.")
    for name, server in servers.items():
        validate_server(name, server)
    return servers


def save_servers(servers):
    for name, server in servers.items():
        validate_server(name, server)
    path = data_path("mcp_servers.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
            tmp = Path(out.name)
            json.dump(servers, out, ensure_ascii=False, indent=2)
            out.write("\n")
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@asynccontextmanager
async def session_for(name, server):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client
    import httpx

    if server["transport"] == "stdio":
        folder = data_path("mcp", name)
        folder.mkdir(parents=True, exist_ok=True)
        drive, home = os.path.splitdrive(folder)
        env = dict.fromkeys(("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"), str(folder))
        env.update(HOMEDRIVE=drive, HOMEPATH=home)
        params = StdioServerParameters(command=server["command"], args=server["args"], cwd=folder, env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()
                yield session
    else:
        headers = {}
        if variable := server["token_env"]:
            token = os.getenv(variable)
            if not token:
                raise ValueError("Falta la variable del token MCP.")
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(headers=headers, timeout=20, trust_env=False) as client:
            async with streamable_http_client(server["url"], http_client=client) as (reader, writer, _):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=20)) as session:
                    await session.initialize()
                    yield session


async def discover(session, name, server):
    tools = {}
    cursor = None
    seen = set()
    while True:
        page = await session.list_tools(cursor=cursor)
        for tool in page.tools:
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", tool.name)[:23]
            suffix = hashlib.sha256(tool.name.encode()).hexdigest()[:12]
            alias = f"mcp_{name}_{slug}_{suffix}"
            annotations = tool.annotations
            auto = (tool.name in server["read_tools"] and annotations is not None
                    and annotations.readOnlyHint is True and annotations.destructiveHint is not True)
            tools[alias] = (session, name, tool, auto)
        cursor = page.nextCursor
        if not cursor:
            return tools
        if cursor in seen:
            raise ValueError("El servidor repitió una página de herramientas.")
        seen.add(cursor)


async def probe_server(name, server):
    async with session_for(name, server) as session:
        entries = await discover(session, name, server)
        return sorted((tool.name, auto) for _, _, tool, auto in entries.values())


def ollama_tool(entry):
    _, name, tool, _ = entry
    return {"description": f"{name} / {tool.name}. {tool.description or ''}", "parameters": tool.inputSchema}


def check_tool_paths(value):
    if isinstance(value, str) and Path(value).is_absolute():
        check_path(value)
    elif isinstance(value, (dict, list)):
        for item in value.values() if isinstance(value, dict) else value:
            check_tool_paths(item)


async def call_external(entry, arguments, confirm):
    from jsonschema import ValidationError, validators
    from referencing import Registry

    session, name, tool, auto = entry
    try:
        schema = tool.inputSchema
        validators.validator_for(schema)(schema, registry=Registry()).validate(arguments)
    except ValidationError:
        return "Los argumentos no coinciden con el esquema de la herramienta MCP."
    try:
        check_tool_paths(arguments)
    except (OSError, RuntimeError, ValueError):
        return "La herramienta MCP recibió una ruta local bloqueada."
    if not auto and not await confirm(name, tool.name, arguments):
        return "El usuario no autorizó esta operación MCP."
    reply = await session.call_tool(tool.name, arguments)
    result = "\n".join(item.text for item in reply.content if item.type == "text")
    if reply.structuredContent is not None and not result:
        result = json.dumps(reply.structuredContent, ensure_ascii=False)
    if not result:
        result = "(La herramienta no devolvió texto.)"
    return ("Error MCP: " if reply.isError else "") + (
        result if len(result) <= 8000 else result[:8000] + "\n[Resultado recortado]")


def main():
    parser = argparse.ArgumentParser(description="Administra servidores MCP de StoneBot.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    add = actions.add_parser("add", help="Agrega un servidor desactivado.")
    add.add_argument("name")
    transport = add.add_mutually_exclusive_group(required=True)
    transport.add_argument("--command")
    transport.add_argument("--url")
    add.add_argument("--arg", action="append", default=[])
    add.add_argument("--token-env")
    add.add_argument("--read", action="append", default=[])
    for action in ("enable", "disable", "remove"):
        actions.add_parser(action).add_argument("name")
    for action in ("allow-read", "revoke-read"):
        action_parser = actions.add_parser(action)
        action_parser.add_argument("name")
        action_parser.add_argument("tool")

    args = parser.parse_args()
    try:
        servers = load_servers()
        if args.action == "list":
            print(json.dumps(servers, indent=2, ensure_ascii=False))
            return
        if args.action == "add":
            if args.name in servers:
                raise ValueError("Ya existe un servidor con ese nombre.")
            server = {"enabled": False, "read_tools": args.read}
            if args.command and args.token_env is None:
                server.update(transport="stdio", command=args.command, args=args.arg)
            elif args.url and not args.arg:
                server.update(transport="http", url=args.url, token_env=args.token_env)
            else:
                raise ValueError("Usa --arg con STDIO y --token-env con HTTPS.")
            servers[args.name] = server
        elif args.name not in servers:
            raise ValueError("No existe ese servidor.")
        elif args.action == "remove":
            del servers[args.name]
        elif args.action in ("allow-read", "revoke-read"):
            reads = set(servers[args.name]["read_tools"])
            (reads.add if args.action == "allow-read" else reads.discard)(args.tool)
            servers[args.name]["read_tools"] = sorted(reads)
        else:
            servers[args.name]["enabled"] = args.action == "enable"
        save_servers(servers)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()

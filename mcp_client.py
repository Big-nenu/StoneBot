"""Configuración y sesiones MCP de StoneBot."""
import argparse
import asyncio
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import sqlite3
import tempfile
from contextlib import asynccontextmanager, nullcontext
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from stonebot_engine import default_root
from stonebot_engine.safety import check_path, cli_root
from mcp_credentials import CredentialAccessError, credential_target, delete_key, read_key
from mcp_permissions import revoke, safe_read
from tool_validation import InvalidToolArguments, validate_arguments


class MissingTokenError(ValueError):
    pass


def is_desktop_commander(server):
    if server["transport"] != "stdio":
        return False
    command = Path(server["command"]).stem.casefold()
    args = server["args"]
    npx = command == "npx" or (command == "node" and bool(args) and Path(args[0]).name.casefold() == "npx-cli.js")
    return npx and any(re.fullmatch(r"@wonderwhy-er/desktop-commander(?:@[\w.-]+)?", arg) for arg in args)


def startup_timeout(server):
    return 125 if is_desktop_commander(server) else 25


def data_path(*parts):
    root = cli_root() or default_root()
    if root.is_symlink() or root.is_junction() or (cli_root() is not None and root.resolve() != root):
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
    disabled = server.get("disabled_tools", [])
    if not isinstance(disabled, list) or not all(isinstance(tool, str) and tool for tool in disabled):
        raise ValueError("La lista de herramientas deshabilitadas es inválida.")
    common = {"enabled", "read_tools", "transport"}
    if "disabled_tools" in server:
        common.add("disabled_tools")
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
async def session_for(name, server, *, message_handler=None, stdio_environment=None):
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
        if is_desktop_commander(server):
            # Una descarga interrumpida puede dejar npm-cache/_npx incompleta.
            env["npm_config_cache"] = str(data_path("mcp", name, "npm-cache-stonebot"))
        if stdio_environment is not None:
            env.update(stdio_environment)
        params = StdioServerParameters(command=server["command"], args=server["args"], cwd=folder, env=env)
        # pythonw no tiene consola. Algunos servidores escriben en stderr antes de responder.
        stderr = (nullcontext(sys.stderr) if sys.stderr is not None and cli_root() is None
                  else open(os.devnull, "w"))
        with stderr as log:
            async with stdio_client(params, errlog=log) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=startup_timeout(server) - 5),
                                         message_handler=message_handler) as session:
                    await session.initialize()
                    yield session
    else:
        headers = {}
        variable = server["token_env"]
        env_token = os.getenv(variable) if variable else None
        try:
            token = env_token if cli_root() is not None else read_key(credential_target(name, server)) or env_token
        except CredentialAccessError:
            if not env_token:
                raise
            token = env_token
        if variable and not token:
            raise MissingTokenError("Falta la variable del token MCP.")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(headers=headers, timeout=20, trust_env=False) as client:
            async with streamable_http_client(server["url"], http_client=client) as (reader, writer, _):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=20),
                                         message_handler=message_handler) as session:
                    await session.initialize()
                    yield session


async def discover(session, name, server, *, include_disabled=False, metrics=None):
    tools = {}
    cursor = None
    seen = set()
    disabled = set(server.get("disabled_tools", []))
    excluded = set() if metrics is not None else None
    while True:
        page = await session.list_tools(cursor=cursor)
        for tool in page.tools:
            if not include_disabled and tool.name in disabled:
                if excluded is not None:
                    excluded.add(tool.name)
                continue
            slug = re.sub(r"[^a-zA-Z0-9_]", "_", tool.name)[:23]
            suffix = hashlib.sha256(tool.name.encode()).hexdigest()[:12]
            alias = f"mcp_{name}_{slug}_{suffix}"
            auto = tool.name in server["read_tools"] and safe_read(tool)
            tools[alias] = (session, name, tool, auto)
        cursor = page.nextCursor
        if not cursor:
            if metrics is not None:
                metrics["configuracion"] = len(excluded)
            return tools
        if cursor in seen:
            raise ValueError("El servidor repitió una página de herramientas.")
        seen.add(cursor)


async def probe_server(name, server, *, include_definitions=False):
    from anyio import BrokenResourceError

    entries = None
    try:
        async with session_for(name, server) as session:
            entries = await discover(session, name, server, include_disabled=True)
    except* BrokenResourceError:
        # STDIO puede recibir una notificación tardía mientras el SDK cierra sus streams.
        if entries is None or server["transport"] != "stdio":
            raise
    if include_definitions:
        return sorted((tool for _, _, tool, _ in entries.values()), key=lambda tool: tool.name)
    return sorted((tool.name, auto) for _, _, tool, auto in entries.values())


def connection_error(error):
    """Describe fallos de la prueba sin publicar URLs, cabeceras ni mensajes del servidor."""
    import httpx
    from anyio import BrokenResourceError, ClosedResourceError

    try:
        from mcp.shared.exceptions import McpError
    except ImportError:
        McpError = ()

    def causes(exc):
        if isinstance(exc, BaseExceptionGroup):
            yield from exc.exceptions
        if cause := (exc.__cause__ or exc.__context__):
            yield cause

    pending = [error]
    errors = []
    while pending:
        exc = pending.pop(0)
        if exc not in errors:
            errors.append(exc)
            pending.extend(causes(exc))

    statuses = {
        400: "Solicitud HTTP rechazada. Revisa que la URL corresponda al endpoint MCP.",
        401: "Autenticación requerida o credencial rechazada. Revisa la variable del token y su valor.",
        403: "Acceso denegado. Revisa los permisos de la credencial y del servidor.",
        404: "No se encontró la ruta MCP. Revisa la URL exacta del endpoint.",
        405: "La URL rechaza el método HTTP. Revisa el endpoint Streamable HTTP.",
        408: "Tiempo de espera agotado al esperar la respuesta del servidor.",
        429: "El servidor limitó las solicitudes. Intenta de nuevo más tarde.",
    }
    for exc in errors:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if 300 <= status < 400:
                detail = "El servidor redirige la solicitud. Configura la URL final del endpoint MCP."
            elif status >= 500:
                detail = "El servidor remoto devolvió un error interno o no está disponible."
            else:
                detail = statuses.get(status, "El servidor rechazó la solicitud.")
            return f"HTTP {status}. {detail}"
        if isinstance(exc, McpError):
            code = exc.error.code
            if code == -32000 and exc.error.message == "Connection closed":
                return "El canal MCP se cerró antes de recibir respuesta (código -32000)."
            # El SDK 1.x transforma un POST 404 en este error de sesión.
            if code == 32600 and exc.error.message == "Session terminated":
                return "HTTP 404. La ruta MCP no existe o la sesión terminó. Revisa la URL del endpoint."
            if code in statuses:
                return f"MCP {code}. {statuses[code]}"

    for kind, detail in (
        (MissingTokenError, "Falta la variable de entorno del token. Configura la variable o guarda la clave API en el panel MCP."),
        (CredentialAccessError, "No se pudo leer la clave en el Administrador de credenciales de Windows."),
        (ssl.SSLCertVerificationError, "No se pudo verificar el certificado TLS del servidor."),
        (ssl.SSLError, "Falló la conexión TLS con el servidor."),
        (socket.gaierror, "No se pudo resolver el nombre del servidor (DNS)."),
        ((TimeoutError, httpx.TimeoutException), "Tiempo de espera agotado al conectar o esperar la respuesta."),
        ((httpx.InvalidURL, httpx.UnsupportedProtocol), "URL inválida o protocolo incompatible. Revisa el endpoint MCP."),
        (ConnectionRefusedError, "El servidor rechazó la conexión. Revisa que esté en ejecución y el puerto sea correcto."),
        (httpx.ConnectError, "No se pudo establecer la conexión. Revisa el dominio, el puerto y la red."),
        (FileNotFoundError, "No se encontró el ejecutable STDIO o su directorio de trabajo."),
        (PermissionError, "Permiso denegado al intentar iniciar el proceso o abrir la conexión."),
        ((BrokenResourceError, ClosedResourceError), "El canal MCP se cerró antes de recibir respuesta."),
        (ImportError, "Falta el SDK de MCP o una de sus dependencias."),
    ):
        if any(isinstance(exc, kind) for exc in errors):
            return detail
    for exc in errors:
        if isinstance(exc, McpError):
            return f"El servidor devolvió un error de protocolo MCP (código {exc.error.code})."
    leaf = next((exc for exc in errors if not isinstance(exc, BaseExceptionGroup)), error)
    return f"La conexión falló por un error de tipo {type(leaf).__name__}."


def ollama_tool(entry):
    _, name, tool, _ = entry
    return {"description": f"{name} / {tool.name}. {tool.description or ''}", "parameters": tool.inputSchema}


def check_tool_paths(value):
    if isinstance(value, str) and Path(value).is_absolute():
        check_path(value)
    elif isinstance(value, (dict, list)):
        for item in value.values() if isinstance(value, dict) else value:
            check_tool_paths(item)


def transient_mcp_error(error):
    import httpx
    from mcp.shared.exceptions import McpError

    return (isinstance(error, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError))
            or isinstance(error, McpError) and error.error.code in {408, 429, 502, 503, 504})


async def call_external(entry, arguments, confirm, *, on_start=None, on_result=None, on_partial=None,
                        on_rejected=None, on_retry=None, reconnect=None, on_evidence=None):

    session, name, tool, auto = entry

    def rejected(code, detail):
        if on_rejected is not None:
            on_rejected(code)
        return detail

    try:
        validate_arguments(tool.inputSchema, arguments)
    except InvalidToolArguments as exc:
        return rejected("ESQUEMA_NO_DISPONIBLE" if exc.unavailable else "ARGUMENTOS_INVALIDOS", str(exc))
    try:
        check_tool_paths(arguments)
    except (OSError, RuntimeError, ValueError):
        return rejected("DESTINO_BLOQUEADO", "La herramienta MCP recibió una ruta local bloqueada.")
    if not (auto and safe_read(tool, arguments)) and not await confirm(name, tool.name, arguments):
        return rejected("OPERACION_DENEGADA", "El usuario no autorizó esta operación MCP.")
    if on_start is not None:
        on_start()
    can_retry = on_retry is not None and safe_read(tool, arguments)
    try:
        reply = await session.call_tool(tool.name, arguments)
    except Exception as exc:
        if not (can_retry and reconnect is not None and transient_mcp_error(exc)):
            raise
        on_retry("transporte_transitorio")
        async with asyncio.timeout(5):
            session = await reconnect()
            reply = await session.call_tool(tool.name, arguments)
    else:
        if can_retry and reply.isError:
            metadata = reply.structuredContent or {}
            error_text = "\n".join(item.text for item in reply.content if item.type == "text")[:8000]
            if metadata.get("retryable") is True or re.search(
                    r"\b(?:transient|temporarily unavailable|fallo transitorio|error transitorio|temporalmente no disponible)\b",
                    error_text, re.I):
                on_retry("error_transitorio")
                async with asyncio.timeout(5):
                    reply = await session.call_tool(tool.name, arguments)
    result = "\n".join(item.text for item in reply.content if item.type == "text")
    if reply.structuredContent is not None and not result:
        result = json.dumps(reply.structuredContent, ensure_ascii=False)
    metadata = reply.structuredContent or {}
    if on_evidence is not None and not reply.isError:
        on_evidence(metadata, result)
    if on_partial is not None:
        lines = result.splitlines()
        if len(result) > 8000:
            on_partial("StoneBot recortó la respuesta de la herramienta.")
        elif (any(metadata.get(key) for key in ("nextCursor", "next_cursor", "nextPageToken", "next_page_token"))
              or any(metadata.get(key) is True for key in ("hasMore", "has_more", "truncated", "partial", "isPartial"))):
            on_partial("La herramienta indicó que hay datos o páginas pendientes.")
        elif any(line.startswith(("[DENIED]", "[NOT_FOUND]"))
                 or (line.startswith("[WARNING]") and "items hidden" in line) for line in lines):
            on_partial("La herramienta indicó elementos ocultos o inaccesibles.")
    if on_result is not None:
        on_result("tool_error" if reply.isError else "response" if result else "no_text")
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
    removed_target = None
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
            removed_target = credential_target(args.name, servers.pop(args.name))
        elif args.action in ("allow-read", "revoke-read"):
            reads = set(servers[args.name]["read_tools"])
            (reads.add if args.action == "allow-read" else reads.discard)(args.tool)
            servers[args.name]["read_tools"] = sorted(reads)
        else:
            servers[args.name]["enabled"] = args.action == "enable"
        save_servers(servers)
        delete_key(removed_target)
        if args.action == "remove":
            revoke(args.name)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()

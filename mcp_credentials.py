"""Claves HTTPS de MCP en el Administrador de credenciales de Windows."""
import hashlib
import os
from urllib.parse import urlsplit


class CredentialAccessError(OSError):
    pass


def credential_target(name, server):
    if server and server["transport"] == "http":
        url = server["url"]
        if urlsplit(url).scheme == "https":
            digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
            return f"StoneBot/MCP/{name}/{digest}"
    return None


def read_key(target):
    if not target or os.name != "nt":
        return None
    import win32cred
    from pywintypes import error

    try:
        credential = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC, 0)
    except error as exc:
        if exc.winerror == 1168:
            return None
        raise CredentialAccessError("Windows no pudo leer la clave MCP.") from None
    return credential["CredentialBlob"].decode("utf-16-le")


def store_key(target, key):
    if not key or any(not 33 <= ord(char) <= 126 for char in key):
        raise ValueError("Introduce una clave API sin espacios ni caracteres de control.")
    import win32cred
    from pywintypes import error

    try:
        win32cred.CredWrite({
            "Type": win32cred.CRED_TYPE_GENERIC, "TargetName": target,
            "CredentialBlob": key, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        }, 0)
    except error:
        raise OSError("Windows no pudo guardar la clave MCP.") from None


def delete_key(target):
    if not target or os.name != "nt":
        return
    import win32cred
    from pywintypes import error

    try:
        win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
    except error as exc:
        if exc.winerror != 1168:
            raise OSError("Windows no pudo quitar la clave MCP.") from None

"""Punto de entrada de StoneBot para el terminal de Windows."""
import argparse
import os
import sqlite3
import sys
import time

from ai_provider import AISettings, ollama_model_is_local, preferences, saved_model
from chat_session import ChatSession
from cli_turn_runner import run_turn, terminal_text
from conversation_lock import acquire_conversation_lock
from history import History
from mcp_pool import McpPool
from mcp_setup import is_setup_request
from stonebot_engine.safety import configure_cli_profile
from turn_worker import TASK_COMMANDS


HELP = ("/ayuda, /chats, /abrir ID, /nuevo, /salir\n"
        "/tarea OBJETIVO, /reanudar [ACLARACIÓN], /cancelar\n"
        "Ctrl+C detiene el chat o pausa la tarea durante un turno.")
HISTORY_ERRORS = (OSError, RuntimeError, ValueError, sqlite3.Error)


def model_name(value):
    value = value.strip()
    if not value or any(char.isspace() or not char.isprintable() for char in value):
        raise argparse.ArgumentTypeError("Indica un identificador de modelo de Ollama.")
    return value


def open_chat(session, chat_id, stdout):
    if chat_id is not None:
        if not any(existing == chat_id for existing, _ in session.history.find()):
            raise ValueError("No existe ese chat en el perfil de CLI.")
    saved = session.load_chat(chat_id)
    if chat_id is None:
        return
    session.recover_task()
    for row in saved:
        speaker = "Tú" if row["role"] == "user" else "StoneBot"
        print(f"{speaker}: {terminal_text(row['content'])}", file=stdout)
    if session.has_pending_execution():
        print("Hay un encargo interrumpido. Puedes pedir que continúe.", file=stdout)
    if session.task:
        print(f"Tarea: {terminal_text(session.task['status'])}", file=stdout)


def prompt(session, stdin, stdout, stderr, *, verbose):
    verified_model = False
    while True:
        print("Tú> ", file=stdout, end="", flush=True)
        try:
            line = stdin.readline()
        except (KeyboardInterrupt, EOFError):
            return
        if not line:
            return
        text = line.strip()
        if not text:
            continue
        command, *args = text.split(maxsplit=1)
        try:
            if command == "/salir":
                return
            if command == "/ayuda":
                print(HELP, file=stdout)
                continue
            if command == "/chats":
                for chat_id, title in session.history.find():
                    print(f"{chat_id}  {terminal_text(title)}", file=stdout)
                continue
            if command == "/nuevo":
                open_chat(session, None, stdout)
                continue
            if command == "/abrir":
                if not args or not args[0].isascii() or not args[0].isdecimal():
                    raise ValueError("Usa /abrir ID.")
                open_chat(session, int(args[0]), stdout)
                continue
            if command == "!" or (command.startswith("/") and command not in TASK_COMMANDS) or is_setup_request(text):
                raise ValueError("Entrada fuera del alcance de la CLI. Usa /ayuda.")
            task = session.prepare_task(text)
            if not (task and task["status"] == "cancelled") and not verified_model:
                if not ollama_model_is_local(session.ai.model):
                    raise ValueError("Ollama no confirmó que el modelo esté instalado y sea local.")
                verified_model = True
            if not session.save_input(text, time.time_ns(), task=task):
                raise ValueError("No se pudo guardar el mensaje en el historial.")
            if task and task["status"] == "cancelled":
                print("Tarea cancelada.", file=stdout)
                continue
            plan = session.begin_turn(task)
            if plan.warning:
                print(plan.warning, file=stderr)
            result = run_turn(session, plan, stdin, stderr, verbose=verbose)
            if result.message:
                print(f"StoneBot: {terminal_text(result.message['content'])}", file=stdout)
            if result.saved is False:
                print("No se pudo guardar la respuesta.", file=stderr)
            if result.error:
                print(terminal_text(result.error), file=stderr)
        except HISTORY_ERRORS as exc:
            print(terminal_text(exc), file=stderr)


def main(argv=None, *, stdin=None, stdout=None, stderr=None):
    parser = argparse.ArgumentParser(description="StoneBot para terminal con Ollama local.")
    parser.add_argument("--chat", type=int, metavar="ID", help="abrir un chat del perfil de CLI")
    parser.add_argument("--model", type=model_name, metavar="MODELO", help="seleccionar el modelo para esta invocación")
    parser.add_argument("--verbose", action="store_true", help="emitir una traza redactada en stderr")
    args = parser.parse_args(argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        configure_cli_profile(os.getenv("STONEBOT_HOME"))
        lock = acquire_conversation_lock()
        if lock is None:
            raise ValueError("El perfil de StoneBot CLI ya está en uso.")
        try:
            if preferences().value("ai/provider", "ollama", type=str) != "ollama":
                raise ValueError("StoneBot CLI solo admite Ollama local.")
            pool = McpPool()
            try:
                ai = AISettings("ollama", args.model or saved_model("ollama") or AISettings().model)
                session = ChatSession(history=History(), ai=ai, pool=pool, automatic_titles=False)
                if args.chat is not None:
                    open_chat(session, args.chat, stdout)
                prompt(session, stdin, stdout, stderr, verbose=args.verbose)
            finally:
                pool.close()
        finally:
            lock.unlock()
    except HISTORY_ERRORS as exc:
        print(terminal_text(exc), file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

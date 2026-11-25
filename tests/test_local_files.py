"""Permisos, exclusiones y exploración desde los flujos normales de StoneBot."""
import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ollama import Message

import app
import mcp_client
import turn_worker
from ai_provider import AISettings, OpenRouter
from appearance import load_appearance
from local_file_requests import FOLDER_NAMES
from local_files import LocalFiles, MODES, OPERATIONS, RESULT_HEADER, load_settings, save_settings
from local_files_ui import LocalFilesDialog
from tasks import new_task


def user(text):
    return {"role": "user", "content": text}


def connection_not_expected(*args, **kwargs):
    raise AssertionError("El recorrido nativo no debe preparar conexiones ni enviar datos al modelo.")


async def check_chat(root):
    first = root / "Mi proyecto"
    second = root / "Otra carpeta"
    excluded = first / "Reservado"
    for folder in (first, second, excluded):
        folder.mkdir()
    (first / "contrato.pdf").write_text("Contenido privado del PDF de prueba", encoding="utf-8")
    (first / "contrato.csv").write_text("a,b", encoding="utf-8")
    (first / ".env.local").write_text("SECRETO", encoding="utf-8")
    (second / "contrato-2.pdf").write_text("otro contrato", encoding="utf-8")
    (excluded / "contrato-reservado.pdf").write_text("reservado", encoding="utf-8")
    memory = type("Memory", (), {"entries": AsyncMock(), "call": AsyncMock()})()
    cloud = AISettings("openrouter", "test/model")

    async def chat(text, **options):
        if "task" in options:
            options["save_task"] = lambda snapshot: None
        worker = app.Worker([{"role": "system", "content": app.SYSTEM}, user(text)],
                            ai=cloud, memory=memory, **options)
        return await worker.chat()

    with (patch.object(turn_worker, "load_servers", side_effect=connection_not_expected),
          patch.object(turn_worker, "OpenRouter", side_effect=connection_not_expected)):
        first_answer = await chat(f'Busca archivos PDF en "{first}"')
        assert "contrato.pdf" in first_answer and "contrato.csv" not in first_answer, first_answer
        assert "Contenido privado" not in first_answer
        assert "contrato-2.pdf" in await chat(f"Lista {second}")
        assert "bytes" in await chat(f'Dime las propiedades de "{first / "contrato.pdf"}"')
        assert "contrato.pdf" in await chat("Busca contrato en este proyecto", project={"folder": str(first)})
        assert "adjuntar" in await chat(f'Lee "{first / "contrato.pdf"}"')
        assert ".env.local" not in await chat(f'Lista "{first}"')

        question = await chat("Busca el archivo contrato")
        assert "¿En qué carpeta" in question
        worker = app.Worker([user("Busca el archivo contrato"), {"role": "assistant", "content": question},
                             user(f'"{second}"')], ai=cloud)
        assert "contrato-2.pdf" in await worker.chat()

        permissions = dict.fromkeys(OPERATIONS, "allow")
        save_settings(permissions, [excluded])
        assert load_settings().exclusions == (excluded,)
        hidden = await chat(f'Busca archivos PDF en "{first}"')
        assert "contrato.pdf" in hidden and "Reservado" not in hidden and "reservado.pdf" not in hidden
        assert "excluida" in await chat(f'Lista "{excluded}"')
        assert "protegida" in await chat(f'Lista "{root / "perfil"}"')

        redirected = first / "Enlace"
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(excluded), str(redirected))
        else:
            redirected.symlink_to(excluded, target_is_directory=True)
        assert "redirección" in await chat(f'Lista "{redirected}"')
        assert "reservado.pdf" not in await chat(f'Busca archivos PDF en "{first}"')
        assert "ruta absoluta" in await chat(f'Lista "{first / ".." / second.name}"')
        if os.name == "nt":
            assert "ruta absoluta" in await chat(r'Lista "\\servidor\recurso"')

        permissions["list"] = "deny"
        save_settings(permissions, [excluded])
        assert "denegada" in await chat(f'Lista "{second}"')
        assert "contrato-2.pdf" in await chat(f'Busca contrato en "{second}"')

        permissions["search"] = "ask"
        save_settings(permissions, [excluded])
        worker = app.Worker([user(f'Busca contrato en "{second}"')], ai=cloud)
        confirmations = []

        def confirm(request):
            confirmations.append(request)
            request["approved"] = len(confirmations) == 2

        worker.mcp_confirmation.connect(confirm, Qt.ConnectionType.DirectConnection)
        assert "denegada" in await worker.chat()
        assert "contrato-2.pdf" in await worker.chat()
        assert all(item["arguments"]["Ruta"] == str(second) for item in confirmations)
        assert all(item["operation"] == OPERATIONS["search"] for item in confirmations)

        permissions["rank"] = "deny"
        save_settings(permissions, [excluded])
        objective = f'Revisa los cinco archivos más pesados en "{first}"'
        assert "denegada" in await chat(objective, task=new_task(objective))
        permissions["rank"] = "allow"
        save_settings(permissions, [excluded])
        ranked = await chat(objective, task=new_task(objective))
        assert "contrato.pdf" in ranked and "contrato-reservado.pdf" not in ranked

    memory.entries.assert_not_called()
    memory.call.assert_not_called()
    rows = OpenRouter.messages_for_api([user("Busca archivos"), {"role": "assistant", "content": first_answer}])
    assert "contrato.pdf" not in rows[-1]["content"] and str(first) not in rows[-1]["content"]
    assert ranked.startswith(RESULT_HEADER)

    checks = 0
    visited = []

    def stop_scan():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise asyncio.CancelledError

    try:
        LocalFiles(load_settings()).scan(first, True, stop_scan, lambda *entry: visited.append(entry))
    except asyncio.CancelledError:
        assert not visited
    else:
        raise AssertionError("La cancelación debe detener la exploración.")


def check_dialog(root):
    dialog = LocalFilesDialog(None, load_appearance())
    assert list(dialog.modes) == list(OPERATIONS)
    assert all(combo.count() == len(MODES) for combo in dialog.modes.values())
    assert dialog.paths() == [root / "Mi proyecto" / "Reservado"]
    dialog.modes["info"].setCurrentIndex(dialog.modes["info"].findData("deny"))
    dialog.save()
    assert load_settings().modes["info"] == "deny"


def tool_call(**arguments):
    return SimpleNamespace(message=Message(role="assistant", tool_calls=[
        {"function": {"name": "inspect_local_files", "arguments": arguments}},
    ]))


def model_answer(text):
    return SimpleNamespace(message=Message(role="assistant", content=text))


async def check_agent_files(root, live_model=None):
    settings = load_settings()
    save_settings({**settings.modes, "list": "allow", "search": "allow", "info": "allow"}, settings.exclusions)
    downloads = root / "Descargas"
    downloads.mkdir()
    for number in range(82):
        (downloads / f"Carpeta {number}").mkdir()
    (downloads / "Carpeta 0" / "Anidada").mkdir()
    (downloads / "informe.pdf").write_bytes(b"abc")

    def worker(text, name):
        return app.Worker([{"role": "system", "content": app.SYSTEM}, user(text)],
                          ai=AISettings("ollama", name), think=False)

    async def turn(text, model, *, local_model=True):
        active = worker(text, "simulado")
        active.local_ollama = local_model
        with patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)):
            return await active.chat()

    with (patch.dict(FOLDER_NAMES, {"descargas": lambda: downloads}),
          patch.object(turn_worker, "parse_request", side_effect=connection_not_expected),
          patch.object(turn_worker, "load_servers", side_effect=connection_not_expected),
          patch.object(app.Worker, "enabled_skills", return_value={})):
        if live_model:
            questions = (
                ("¿Cuántas carpetas tengo en Descargas?", ("82",), 1),
                ("¿Qué PDF hay directamente en Descargas y cuánto pesa en bytes?", ("informe.pdf", "3 bytes"), 2),
            )
            for question, expected, operations in questions:
                active = worker(question, live_model)
                active.think = None
                events = []
                active.activity.connect(events.append)
                result = await active.run_chat()
                assert result.startswith(RESULT_HEADER) and all(value in result for value in expected), (result, events)
                assert sum(event.startswith("Archivos locales · ") for event in events) >= operations, events
            print(f"PASS: {live_model} eligió el recuento y encadenó búsqueda con propiedades.")
            return

        for question, recursive, total in (
            ("¿Cuántas carpetas tengo en Descargas?", False, 82),
            ("Dame una cifra de los directorios de toda la jerarquía de Descargas.", True, 83),
        ):
            async def count_model(**kwargs):
                assert "inspect_local_files" in {item.function.name for item in kwargs["tools"] if not callable(item)}
                last = kwargs["messages"][-1]
                if last["role"] != "tool":
                    return tool_call(operation="count", target="Descargas", entry_type="folders", recursive=recursive)
                result = json.loads(last["content"])
                assert result["total"] == total and not result["parcial"] and "entradas" not in result
                return model_answer(f"Encontré {result['total']} carpetas.")

            assert await turn(question, count_model) == RESULT_HEADER + f"Encontré {total} carpetas."

        async def search_then_info(**kwargs):
            last = kwargs["messages"][-1]
            if last["role"] != "tool":
                return tool_call(operation="search", target="Descargas", extension="pdf")
            result = json.loads(last["content"])
            if "entradas" in result:
                found, = result["entradas"]
                assert found["ruta"] == "informe.pdf"
                return tool_call(operation="info", target=str(Path(result["ruta"]) / found["ruta"]))
            assert result["tamaño_bytes"] == 3
            return model_answer("El PDF pesa 3 bytes.")

        assert await turn("¿Qué PDF hay en Descargas y cuánto pesa?", search_then_info) == RESULT_HEADER + "El PDF pesa 3 bytes."

        async def count_with_limit(**kwargs):
            last = kwargs["messages"][-1]
            if last["role"] != "tool":
                return tool_call(operation="count", target="Descargas", entry_type="folders")
            result = json.loads(last["content"])
            assert result["parcial"] and result["límite_alcanzado"]
            return model_answer("El recuento quedó parcial.")

        with patch("local_files.SCAN_LIMIT", 1):
            assert "parcial" in await turn("¿Me das un total de directorios en Descargas?", count_with_limit)

        async def unavailable(**kwargs):
            last = kwargs["messages"][-1]
            if last["role"] != "tool":
                return tool_call(operation="list", target="Descargas")
            assert json.loads(last["content"])["estado"] == "error"
            assert str(downloads) not in last["content"]
            return model_answer("La herramienta no pudo consultar Descargas.")

        await turn("¿Qué hay en Descargas?", unavailable, local_model=False)
        settings = load_settings()
        save_settings({**settings.modes, "list": "deny"}, settings.exclusions)
        try:
            await turn("¿Qué hay en Descargas?", unavailable)
        finally:
            save_settings(settings.modes, settings.exclusions)


if __name__ == "__main__":
    qt = QApplication([])
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with patch.object(mcp_client, "default_root", return_value=root / "perfil"):
            asyncio.run(check_chat(root))
            check_dialog(root)
            asyncio.run(check_agent_files(root))
            if sys.argv[1:2] == ["--live"]:
                with TemporaryDirectory() as live:
                    asyncio.run(check_agent_files(Path(live).resolve(), sys.argv[2] if len(sys.argv) > 2 else app.MODEL))
    print("PASS: exploración nativa, exclusiones, confirmaciones, privacidad y ajustes.")

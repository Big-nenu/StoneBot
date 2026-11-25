"""Prueba del supervisor y del recorrido desde el chat con un modelo simulado."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import managed_process as jobs
import mcp_client
import turn_worker
from chat_execution import ChatExecution
from ollama import Message


def poll(folder, run_id, until):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = jobs.inspect_run(folder, run_id)
        if until(result):
            return result
        time.sleep(.1)
    raise AssertionError(result)


def lifecycle(root):
    run_id = uuid4().hex
    command = [sys.executable, "-u", "-c", "import time; print('primera'); time.sleep(60)"]
    # El lanzador termina antes de la primera consulta.
    subprocess.run([sys.executable, "-B", "-c",
                    "from managed_process import start; from pathlib import Path; import sys; "
                    "start(Path(sys.argv[1]), sys.argv[2], dict(cwd=sys.argv[1], argv=sys.argv[3:]))",
                    str(root), run_id, *command], cwd=Path(__file__).resolve().parents[1], check=True)
    first = poll(root, run_id, lambda row: row["salida"] and row["estado"] == "ejecutando")
    assert first["salida"].strip() == "primera"
    assert not jobs.inspect_run(root, run_id, first["cursor"])["salida"]
    # Otro intérprete consulta y cancela el trabajo sin heredar handles del lanzador.
    subprocess.run([sys.executable, "-B", "-c",
                    "from managed_process import inspect_run; from pathlib import Path; import sys; "
                    "assert inspect_run(Path(sys.argv[1]), sys.argv[2], cancel=True)['cancelacion_solicitada']",
                    str(root), run_id], cwd=Path(__file__).resolve().parents[1], check=True)
    final = poll(root, run_id, lambda row: row["estado"] == "cancelado")
    assert final["codigo"] is not None


async def chat(root, approved):
    execution = ChatExecution(1, None, lambda mid, version, state: version + 1, "prueba", ["local"])
    execution.chat_id = 1
    worker = turn_worker.Worker([{"role": "system", "content": "Usa el resultado."},
                                 {"role": "user", "content": "Ejecuta la prueba del proyecto."}],
                                execution=execution)
    command = [sys.executable, "-c", "import os,sys; print(os.path.basename(os.getcwd())); sys.exit(7)"]
    def call(name, **args):
        return SimpleNamespace(message=Message(role="assistant", tool_calls=[
            {"function": {"name": name, "arguments": args}}]))

    async def model(**request):
        row = request["messages"][-1]
        if row["role"] != "tool":
            assert any(getattr(t, "function", None) and t.function.name == "iniciar_proceso" for t in request["tools"])
            return call("iniciar_proceso", argv=command, cwd=str(root))
        if not approved:
            assert "denegada" in row["content"]
            answer = "Denegada"
        else:
            data = json.loads(row["content"])
            if data["estado"] != "terminado":
                await asyncio.sleep(.5)
                return call("consultar_proceso", id=data["id"])
            assert root.name in data["salida"] and data["codigo"] == 7
            answer = "El programa terminó con código 7."
        return SimpleNamespace(message=Message(role="assistant", content=answer))

    with (patch.object(jobs, "WINDOWS_BACKEND", True),
          patch.object(turn_worker, "ollama_model_is_local", return_value=True),
          patch.object(turn_worker, "Client", return_value=SimpleNamespace(chat=model)),
          patch.object(worker, "confirm_external", new=AsyncMock(return_value=approved)) as approval,
          patch.object(mcp_client, "default_root", return_value=root / "perfil")):
        answer = await worker.chat()
    approval.assert_awaited_once()
    first = execution.state["steps"][0]
    if approved:
        assert "código 7" in answer and first["run_id"] in execution.context()
        assert execution.repeated_effect("iniciar_proceso", first["arguments"]) is first
    else:
        assert "Denegada" in answer and first["status"] == "sin ejecutar", (answer, first)
        assert not list(root.rglob("*.sqlite3"))


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        asyncio.run(chat(root, False))
        asyncio.run(chat(root, True))
        lifecycle(root)
    print("PASS: permiso, ejecución desde el chat, código final, salida incremental y cancelación.")

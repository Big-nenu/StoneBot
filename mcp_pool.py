"""Reutiliza sesiones MCP entre turnos en un bucle de E/S dedicado."""
import asyncio
import threading
import time
from types import SimpleNamespace

from mcp_client import discover, session_for, startup_timeout


class SessionProxy:
    def __init__(self, pool, slot, session):
        self.pool, self.slot, self.session = pool, slot, session

    async def call_tool(self, tool, arguments):
        return await self.pool.submit(self.call(tool, arguments))

    async def call(self, tool, arguments):
        if self.pool.expired(self.slot):
            raise ConnectionError("La sesión MCP se cerró. El siguiente turno puede reconectar.")
        try:
            return await self.session.call_tool(tool, arguments)
        except Exception:
            self.slot.stop.set()
            raise


class McpPool:
    def __init__(self, *, open_session=None):
        self.open_session = open_session
        self.slots = {}
        self.thread = None
        self.loop = None
        self.ready = threading.Event()
        self.invalidated = set()

    async def serve(self):
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        self.ready.set()
        await self.stop.wait()
        await self.reconcile({}, ())

    async def submit(self, operation):
        if self.thread is None:
            self.thread = threading.Thread(target=lambda: asyncio.run(self.serve()), daemon=True)
            self.thread.start()
        if not await asyncio.to_thread(self.ready.wait, 10):
            operation.close()
            raise RuntimeError("No se pudo iniciar el cliente MCP.")
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(operation, self.loop))

    async def prepare(self, servers):
        enabled = {name: cfg for name, cfg in servers.items() if cfg["enabled"]}
        invalidated = tuple(self.invalidated)
        self.invalidated.clear()
        if self.thread is not None or enabled:
            await self.submit(self.reconcile(enabled, invalidated))

    async def reconcile(self, enabled, invalidated):
        tasks = []
        for name, slot in list(self.slots.items()):
            if name in invalidated or enabled.get(name) != slot.config or self.expired(slot):
                self.slots.pop(name)
                slot.stop.set()
                tasks.append(slot.task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def entries(self, name, config):
        return await self.submit(self.get_entries(name, config))

    @staticmethod
    def expired(slot):
        if slot.failed_at is not None:
            return time.monotonic() - slot.failed_at >= 30
        return slot.task.done() or slot.stop.is_set() or slot.changed

    async def get_entries(self, name, config):
        slot = self.slots.get(name)
        if slot is not None and self.expired(slot):
            self.slots.pop(name)
            await slot.task
            slot = None
        if slot is None:
            slot = SimpleNamespace(config=dict(config), ready=asyncio.get_running_loop().create_future(),
                                   stop=asyncio.Event(), failed_at=None, changed=False)
            self.slots[name] = slot
            slot.task = asyncio.create_task(self.connect(name, slot))
        try:
            async with asyncio.timeout(startup_timeout(config)):
                return await asyncio.shield(slot.ready)
        except TimeoutError as exc:
            if not slot.ready.done():
                slot.failed_at = time.monotonic()
                slot.ready.set_exception(exc)
                slot.ready.exception()
                slot.task.cancel()
            raise

    async def connect(self, name, slot):
        async def incoming(message):
            if getattr(getattr(message, "root", None), "method", "") == "notifications/tools/list_changed":
                slot.changed = True

        try:
            # La misma tarea abre y cierra los contextos de cancelación del SDK.
            open_session = self.open_session or session_for
            async with open_session(name, slot.config, message_handler=incoming) as session:
                entries = await discover(session, name, slot.config)
                proxy = SessionProxy(self, slot, session)
                slot.ready.set_result({alias: (proxy, server, tool, auto)
                                       for alias, (_, server, tool, auto) in entries.items()})
                await slot.stop.wait()
        except BaseException as exc:
            if not slot.ready.done():
                slot.failed_at = time.monotonic()
                slot.ready.set_exception(exc if isinstance(exc, Exception) else ConnectionError("Se cerró la sesión MCP."))

    def invalidate(self, name):
        self.invalidated.add(name)

    def close(self):
        if self.loop is not None and self.thread.is_alive():
            self.loop.call_soon_threadsafe(self.stop.set)
            self.thread.join(timeout=4)

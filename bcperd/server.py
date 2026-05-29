import asyncio
import os
import traceback

from bcper_core import protocol
from bcper_core.engine import UserError


class IPCProtocol(asyncio.Protocol):
    def __init__(self, daemon):
        self.daemon = daemon
        self.buf = b""
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def data_received(self, data: bytes):
        self.buf += data
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            asyncio.create_task(self._handle(line))

    async def _handle(self, line: bytes):
        req = protocol.decode(line)
        cmd = req.get("cmd", "").lower()
        self.daemon.logger.info(f"SERVER recv cmd={cmd} params={ {k:v for k,v in req.items() if k != 'cmd'} }")
        try:
            handler = getattr(self, f"_cmd_{cmd}", None)
            if handler:
                await handler(req)
            else:
                self.daemon.logger.warning(f"SERVER unknown command: {cmd}")
                self._send(ok=False, error=f"Unknown command: {cmd}")
        except Exception:
            tb = traceback.format_exc()
            self.daemon.logger.error(f"SERVER exception handling {cmd}:\n{tb}")
            self._send(ok=False, error=tb)

    def _send(self, ok=True, data=None, error=None):
        if self.transport:
            self.transport.write(protocol.response(ok=ok, data=data, error=error))

    # ---- Simple queries ----

    async def _cmd_ping(self, req):
        self._send(ok=True, data="pong")

    async def _cmd_status(self, req):
        self._send(ok=True, data={"pid": os.getpid(), "jobs": len(self.daemon.config.jobs)})

    async def _cmd_reload(self, req):
        with self.daemon.config_lock:
            self.daemon.config.load()
        self._send(ok=True)

    async def _cmd_list_items(self, req):
        data = [i.to_dict() for i in self.daemon.config.items.values()]
        self._send(ok=True, data=data)

    async def _cmd_list_vaults(self, req):
        data = [v.to_dict() for v in self.daemon.config.vaults.values()]
        self._send(ok=True, data=data)

    async def _cmd_list_stores(self, req):
        self._send(ok=True, data=self.daemon.config.stores)

    async def _cmd_list_frequencies(self, req):
        data = [f.to_dict() for f in self.daemon.config.frequencies.values()]
        self._send(ok=True, data=data)

    async def _cmd_list_jobs(self, req):
        data = [j.to_dict() for j in self.daemon.config.jobs.values()]
        self._send(ok=True, data=data)

    # ---- Blocking operations (run in executor) ----

    async def _cmd_list_backups(self, req):
        store_name = req.get("store_name")
        if store_name not in self.daemon.config.stores:
            self._send(ok=False, error="Store not found")
            return
        loop = asyncio.get_event_loop()
        try:
            store = await loop.run_in_executor(
                None, lambda: __import__("bcper_core.storage", fromlist=["create_store"]).create_store(
                    self.daemon.config.stores[store_name]
                )
            )
            files = await loop.run_in_executor(None, store.list_backups)
            self._send(ok=True, data=files)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_backup(self, req):
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self.daemon.run_backup,
                req["target_type"],
                req["target_name"],
                req["store_name"],
            )
            self._send(ok=True, data=result)
        except UserError as e:
            self._send(ok=False, error=str(e))
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_restore(self, req):
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self.daemon.run_restore,
                req["archive"],
                req["store_name"],
                req.get("password"),
                req.get("target_dir"),
            )
            self._send(ok=True, data=result)
        except UserError as e:
            self._send(ok=False, error=str(e))
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_backup(self, req):
        store_name = req.get("store_name")
        archive = req.get("archive")
        if store_name not in self.daemon.config.stores:
            self._send(ok=False, error="Store not found")
            return
        loop = asyncio.get_event_loop()
        try:
            store = await loop.run_in_executor(
                None, lambda: __import__("bcper_core.storage", fromlist=["create_store"]).create_store(
                    self.daemon.config.stores[store_name]
                )
            )
            await loop.run_in_executor(None, store.delete, archive)
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    # ---- Config CRUD ----

    async def _cmd_add_item(self, req):
        try:
            data = self.daemon.add_item(req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_update_item(self, req):
        try:
            data = self.daemon.update_item(req["key"], req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_item(self, req):
        try:
            self.daemon.delete_item(req["key"])
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_add_vault(self, req):
        try:
            data = self.daemon.add_vault(req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_update_vault(self, req):
        try:
            data = self.daemon.update_vault(req["name"], req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_vault(self, req):
        try:
            self.daemon.delete_vault(req["name"])
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_add_store(self, req):
        try:
            data = self.daemon.add_store(req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_store(self, req):
        try:
            self.daemon.delete_store(req["name"])
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    # ---- Frequencies ----

    async def _cmd_add_frequency(self, req):
        try:
            data = self.daemon.add_frequency(req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_update_frequency(self, req):
        try:
            data = self.daemon.update_frequency(req["id"], req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_frequency(self, req):
        try:
            self.daemon.delete_frequency(req["id"])
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    # ---- Jobs ----

    async def _cmd_add_job(self, req):
        try:
            data = self.daemon.add_job(req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_update_job(self, req):
        try:
            data = self.daemon.update_job(req["id"], req)
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_job(self, req):
        try:
            self.daemon.delete_job(req["job_id"])
            self._send(ok=True)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_run_job(self, req):
        self.daemon.logger.info(f"SERVER _cmd_run_job job_id={req.get('job_id')}")
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self.daemon.run_job,
                req["job_id"],
            )
            self.daemon.logger.info(f"SERVER _cmd_run_job success: {result}")
            self._send(ok=True, data=result)
        except UserError as e:
            self.daemon.logger.warning(f"SERVER _cmd_run_job UserError: {e}")
            self._send(ok=False, error=str(e))
        except Exception:
            tb = traceback.format_exc()
            self.daemon.logger.error(f"SERVER _cmd_run_job exception:\n{tb}")
            self._send(ok=False, error=tb)

    async def _cmd_toggle_job(self, req):
        try:
            data = self.daemon.toggle_job(req["job_id"])
            self._send(ok=True, data=data)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

import asyncio
import os
import traceback
import uuid
from datetime import datetime

from bcper_core import protocol
from bcper_core.engine import UserError
from bcper_core import db as run_db


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
        with self.daemon._running_jobs_lock:
            running = list(self.daemon._running_jobs)
        self._send(ok=True, data={
            "pid": os.getpid(),
            "jobs": len(self.daemon.config.jobs),
            "running_jobs": running,
        })

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
        try:
            runs = run_db.list_runs(store_name=store_name)
            self._send(ok=True, data=runs)
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_backup(self, req):
        loop = asyncio.get_event_loop()
        run_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target_type = req["target_type"]
        target_name = req["target_name"]
        store_name = req["store_name"]
        name_prefix = f"ad-hoc/{run_id}/"
        archive_name = f"{target_name}_{timestamp}.tar.gz"

        run_db.insert_run({
            "id": run_id,
            "job_id": None,
            "job_name": "ad-hoc",
            "target_type": target_type,
            "target_name": target_name,
            "store_name": store_name,
            "store_path": name_prefix,
            "archive_name": archive_name,
            "started_at": datetime.now().isoformat(),
            "status": "running",
        })

        def _do():
            return self.daemon.run_backup(
                target_type, target_name, store_name,
                timestamp=timestamp, name_prefix=name_prefix,
                progress_file=req.get("progress_file"),
            )

        try:
            result = await loop.run_in_executor(None, _do)
            run_db.update_run(
                run_id,
                status="success",
                completed_at=datetime.now().isoformat(),
                hash=result.get("hash"),
                encrypted=result.get("encrypted"),
                archive_name=os.path.basename(result.get("archive", archive_name)),
            )
            self._send(ok=True, data=result)
        except UserError as e:
            run_db.update_run(run_id, status="failed", completed_at=datetime.now().isoformat(), error_message=str(e))
            self._send(ok=False, error=str(e))
        except Exception:
            run_db.update_run(run_id, status="failed", completed_at=datetime.now().isoformat(), error_message=traceback.format_exc())
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_restore(self, req):
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                self.daemon.run_restore,
                req["run_id"],
                req["store_name"],
                req.get("password"),
                req.get("target_dir"),
                req.get("progress_file"),
            )
            self._send(ok=True, data=result)
        except UserError as e:
            self._send(ok=False, error=str(e))
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_delete_backup(self, req):
        store_name = req.get("store_name")
        run_id = req.get("run_id")
        if store_name not in self.daemon.config.stores:
            self._send(ok=False, error="Store not found")
            return
        run = run_db.get_run(run_id)
        if not run:
            self._send(ok=False, error="Run not found")
            return
        loop = asyncio.get_event_loop()
        try:
            store = await loop.run_in_executor(
                None, lambda: __import__("bcper_core.storage", fromlist=["create_store"]).create_store(
                    self.daemon.config.stores[store_name]
                )
            )
            rel = run["store_path"] + run["archive_name"]
            await loop.run_in_executor(None, store.delete, rel)
            run_db.delete_run(run_id)
            self._send(ok=True)
        except RuntimeError as e:
            self._send(ok=False, error=str(e))
        except Exception:
            self._send(ok=False, error=traceback.format_exc())

    async def _cmd_restore_many(self, req):
        loop = asyncio.get_event_loop()
        run_ids = req.get("run_ids", [])
        store_name = req.get("store_name")
        password = req.get("password")
        target_dir = req.get("target_dir")
        progress_file = req.get("progress_file")

        restored = []
        errors = []
        warnings = []

        for run_id in run_ids:
            try:
                result = await loop.run_in_executor(
                    None,
                    self.daemon.run_restore,
                    run_id,
                    store_name,
                    password,
                    target_dir,
                    progress_file,
                )
                restored.append(run_id)
                if result and result.get("warnings"):
                    warnings.extend(result["warnings"])
            except UserError as e:
                errors.append(f"{run_id[:8]}: {e}")
            except Exception:
                errors.append(f"{run_id[:8]}: {traceback.format_exc()}")

        if not restored and errors:
            self._send(ok=False, error=errors[0])
            return

        self._send(ok=True, data={
            "target_dir": target_dir,
            "restored": restored,
            "errors": errors,
            "warnings": warnings,
        })

    async def _cmd_delete_backups(self, req):
        store_name = req.get("store_name")
        run_ids = req.get("run_ids", [])
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
        except RuntimeError as e:
            self._send(ok=False, error=str(e))
            return
        except Exception:
            self._send(ok=False, error=traceback.format_exc())
            return

        deleted = 0
        errors = []

        for run_id in run_ids:
            run = run_db.get_run(run_id)
            if not run:
                errors.append(f"{run_id[:8]}: Run not found")
                continue
            try:
                rel = run["store_path"] + run["archive_name"]
                await loop.run_in_executor(None, store.delete, rel)
                run_db.delete_run(run_id)
                deleted += 1
            except RuntimeError as e:
                errors.append(f"{run_id[:8]}: {e}")
            except Exception:
                errors.append(f"{run_id[:8]}: {traceback.format_exc()}")

        if not deleted and errors:
            self._send(ok=False, error=errors[0])
            return

        self._send(ok=True, data={"deleted": deleted, "errors": errors})

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
                req.get("progress_file"),
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

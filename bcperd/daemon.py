import asyncio
import logging
import os
import signal
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from bcper_core.config import Config
from bcper_core.engine import BackupEngine
from bcper_core.models import BCItem, BCVault, BackupJob, RunPeriod
from bcper_core.storage import create_store


class Daemon:
    SOCKET_PATH = os.path.expanduser("~/.config/bcper/daemon.sock")
    LOG_PATH = os.path.expanduser("~/.config/bcper/daemon.log")

    def __init__(self):
        self.config = Config()
        self.engine = BackupEngine()
        self.config_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread = None
        self._shutdown_event = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bcper_worker")
        self._setup_logging()

    def _setup_logging(self):
        os.makedirs(os.path.dirname(self.LOG_PATH), exist_ok=True)
        handlers = [
            logging.FileHandler(self.LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ]
        logging.basicConfig(
            handlers=handlers,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        self.logger = logging.getLogger("bcperd")

    def start(self):
        self.logger.info("Daemon starting")
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)
        try:
            loop.run_until_complete(self._async_main())
        finally:
            self.stop()
            loop.close()

    def stop(self):
        self.logger.info("Daemon stopping")
        self._stop_event.set()
        self._shutdown_event.set()
        self._executor.shutdown(wait=False)
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5)
        if os.path.exists(self.SOCKET_PATH):
            os.unlink(self.SOCKET_PATH)

    def _signal_handler(self):
        self._shutdown_event.set()

    async def _async_main(self):
        if os.path.exists(self.SOCKET_PATH):
            os.unlink(self.SOCKET_PATH)
        from .server import IPCProtocol
        loop = asyncio.get_event_loop()
        server = await loop.create_unix_server(
            lambda: IPCProtocol(self), self.SOCKET_PATH
        )
        os.chmod(self.SOCKET_PATH, 0o600)
        self.logger.info(f"IPC server listening on {self.SOCKET_PATH}")
        async with server:
            await self._shutdown_event.wait()

    # ---- Scheduler ----

    def _scheduler_loop(self):
        while not self._stop_event.is_set():
            self._check_jobs()
            self._stop_event.wait(60)

    def _check_jobs(self):
        now = datetime.now()
        with self.config_lock:
            jobs = list(self.config.jobs.values())
        for job in jobs:
            if not job.enabled:
                continue
            if job.period.period_type == "once" and job.last_run:
                continue
            next_run = datetime.fromisoformat(job.next_run) if job.next_run else now
            if next_run <= now:
                self._executor.submit(self._run_job, job)

    def _run_job(self, job: BackupJob):
        self.logger.info(f"Running job {job.id}: {job.target_type}/{job.target_name}")
        try:
            result = self.run_backup(job.target_type, job.target_name, job.store_name)
            self.logger.info(f"Job {job.id} succeeded: {result.get('archive')}")
        except Exception as e:
            self.logger.error(f"Job {job.id} failed: {e}")
        finally:
            with self.config_lock:
                job.last_run = datetime.now().isoformat()
                job.next_run = self._calc_next_run(job.period, job.last_run)
                self.config.save()

    def _calc_next_run(self, period: RunPeriod, last_run_iso: str) -> str:
        last_run = datetime.fromisoformat(last_run_iso)
        if period.period_type == "hourly":
            return (last_run + timedelta(hours=period.interval)).isoformat()
        elif period.period_type == "daily":
            return (last_run + timedelta(days=period.interval)).isoformat()
        return None

    # ---- Operations ----

    def run_backup(self, target_type: str, target_name: str, store_name: str) -> dict:
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise RuntimeError(f"Store not found: {store_name}")
        store = create_store(store_cfg)

        if target_type == "item":
            item = self.config.items.get(target_name)
            if not item:
                raise RuntimeError(f"Item not found: {target_name}")
            return self.engine.backup_item(item, store)
        elif target_type == "vault":
            vault = self.config.vaults.get(target_name)
            if not vault:
                raise RuntimeError(f"Vault not found: {target_name}")
            items = [self.config.items[k] for k in vault.item_keys if k in self.config.items]
            return self.engine.backup_vault(vault, items, store)
        else:
            raise ValueError(f"Invalid target type: {target_type}")

    def run_restore(self, archive_name: str, store_name: str, password: str = None, target_dir: str = None) -> dict:
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise RuntimeError(f"Store not found: {store_name}")
        store = create_store(store_cfg)
        return self.engine.restore(archive_name, store, password=password, target_dir=target_dir)

    # ---- Config CRUD helpers (called from server thread) ----

    def add_item(self, data: dict) -> dict:
        key = data.get("key", "").strip()
        if not key:
            raise ValueError("Key is required")
        with self.config_lock:
            if key in self.config.items:
                raise ValueError("Item already exists")
            item = BCItem(
                key=key,
                paths=[p.strip() for p in data.get("paths", []) if p.strip()],
                password=data.get("password") or None,
                bcpignore=[p.strip() for p in data.get("bcpignore", []) if p.strip()],
            )
            self.config.items[key] = item
            self.config.save()
        return item.to_dict()

    def update_item(self, key: str, data: dict) -> dict:
        with self.config_lock:
            if key not in self.config.items:
                raise ValueError("Item not found")
            item = self.config.items[key]
            item.paths = [p.strip() for p in data.get("paths", []) if p.strip()]
            item.password = data.get("password") or None
            item.bcpignore = [p.strip() for p in data.get("bcpignore", []) if p.strip()]
            self.config.save()
        return item.to_dict()

    def delete_item(self, key: str):
        with self.config_lock:
            if key in self.config.items:
                del self.config.items[key]
                for vault in self.config.vaults.values():
                    if key in vault.item_keys:
                        vault.item_keys.remove(key)
                self.config.save()

    def add_vault(self, data: dict) -> dict:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("Name is required")
        with self.config_lock:
            if name in self.config.vaults:
                raise ValueError("Vault already exists")
            vault = BCVault(
                name=name,
                item_keys=[k for k in data.get("item_keys", []) if k in self.config.items],
                password=data.get("password") or None,
                bcpignore=[p.strip() for p in data.get("bcpignore", []) if p.strip()],
            )
            self.config.vaults[name] = vault
            self.config.save()
        return vault.to_dict()

    def update_vault(self, name: str, data: dict) -> dict:
        with self.config_lock:
            if name not in self.config.vaults:
                raise ValueError("Vault not found")
            vault = self.config.vaults[name]
            vault.item_keys = [k for k in data.get("item_keys", []) if k in self.config.items]
            vault.password = data.get("password") or None
            vault.bcpignore = [p.strip() for p in data.get("bcpignore", []) if p.strip()]
            self.config.save()
        return vault.to_dict()

    def delete_vault(self, name: str):
        with self.config_lock:
            if name in self.config.vaults:
                del self.config.vaults[name]
                self.config.save()

    def add_store(self, data: dict) -> dict:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("Name is required")
        store_type = data.get("type", "local")
        cfg = {"type": store_type}
        if store_type == "local":
            cfg["path"] = data.get("path", "~/backups")
        elif store_type == "rclone":
            cfg["remote"] = data.get("remote", "")
            cfg["path"] = data.get("path", "")
        else:
            raise ValueError("Unknown store type")
        with self.config_lock:
            self.config.stores[name] = cfg
            self.config.save()
        return {"name": name, **cfg}

    def delete_store(self, name: str):
        with self.config_lock:
            if name in self.config.stores:
                del self.config.stores[name]
                self.config.save()

    def add_job(self, data: dict) -> dict:
        job_id = str(uuid.uuid4())[:8]
        period = RunPeriod(
            period_type=data.get("period_type", "once"),
            interval=int(data.get("interval", 1)),
        )
        job = BackupJob(
            id=job_id,
            target_type=data.get("target_type"),
            target_name=data.get("target_name"),
            store_name=data.get("store_name"),
            period=period,
            next_run=datetime.now().isoformat(),
        )
        with self.config_lock:
            self.config.jobs[job_id] = job
            self.config.save()
        return job.to_dict()

    def delete_job(self, job_id: str):
        with self.config_lock:
            if job_id in self.config.jobs:
                del self.config.jobs[job_id]
                self.config.save()

    def toggle_job(self, job_id: str) -> dict:
        with self.config_lock:
            if job_id not in self.config.jobs:
                raise ValueError("Job not found")
            self.config.jobs[job_id].enabled = not self.config.jobs[job_id].enabled
            self.config.save()
            return self.config.jobs[job_id].to_dict()

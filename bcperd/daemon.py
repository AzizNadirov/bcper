import asyncio
import logging
import os
import signal
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from bcper_core.config import Config
from bcper_core.engine import TarGzBackupEngine
from bcper_core.models import (
    BCItem,
    BCVault,
    Job,
    JobFrequency,
    BCItemTarget,
    BCVaultTarget,
    JobFrequencyTrigger,
)
from bcper_core.storage import create_store


class Daemon:
    SOCKET_PATH = os.path.expanduser("~/.config/bcper/daemon.sock")
    LOG_PATH = os.path.expanduser("~/.config/bcper/daemon.log")

    def __init__(self):
        self.config = Config()
        self.engine = TarGzBackupEngine()
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
        loop = asyncio.get_event_loop()
        from .server import IPCProtocol
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
            freq = self.config.frequencies.get(job.frequency_id)
            if not freq:
                continue
            trigger = JobFrequencyTrigger(freq)
            if trigger.should_run(job.last_run, job.next_run):
                self._executor.submit(self._run_job, job)

    def _run_job(self, job: Job):
        self.logger.info(f"Running job {job.id}: {job.target_type}/{job.target_name}")
        try:
            result = self.run_backup(job.target_type, job.target_name, job.store_name)
            self.logger.info(f"Job {job.id} succeeded: {result.get('archive')}")
        except Exception as e:
            self.logger.error(f"Job {job.id} failed: {e}")
        finally:
            with self.config_lock:
                job.last_run = datetime.now().isoformat()
                freq = self.config.frequencies.get(job.frequency_id)
                if freq:
                    trigger = JobFrequencyTrigger(freq)
                    job.next_run = trigger.calculate_next_run(job.last_run)
                self.config.save()

    # ---- Operations ----

    def _resolve_target(self, target_type: str, target_name: str) -> object:
        if target_type == "item":
            item = self.config.items.get(target_name)
            if not item:
                raise RuntimeError(f"Item not found: {target_name}")
            return BCItemTarget(item)
        elif target_type == "vault":
            vault = self.config.vaults.get(target_name)
            if not vault:
                raise RuntimeError(f"Vault not found: {target_name}")
            items = {k: self.config.items[k] for k in vault.item_keys if k in self.config.items}
            return BCVaultTarget(vault, items)
        else:
            raise ValueError(f"Invalid target type: {target_type}")

    def run_backup(self, target_type: str, target_name: str, store_name: str) -> dict:
        self.logger.info(f"BACKUP {target_type}/{target_name} → {store_name}")
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise RuntimeError(f"Store not found: {store_name}")
        store = create_store(store_cfg)
        target = self._resolve_target(target_type, target_name)
        result = self.engine.backup(target, store)
        self.logger.info(f"BACKUP done archive={result.get('archive')}")
        return result

    def run_restore(self, archive_name: str, store_name: str, password: str = None, target_dir: str = None) -> dict:
        self.logger.info(f"RESTORE {archive_name} from {store_name}")
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise RuntimeError(f"Store not found: {store_name}")
        store = create_store(store_cfg)
        result = self.engine.restore(archive_name, store, password=password, target_dir=target_dir)
        self.logger.info(f"RESTORE done target={result.get('target_dir')}")
        return result

    # ---- Config CRUD helpers ----

    def add_item(self, data: dict) -> dict:
        key = data.get("key", "").strip()
        self.logger.info(f"ADD_ITEM key={key}")
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
            self.logger.info(f"ADD_ITEM saved key={key}")
        return item.to_dict()

    def update_item(self, key: str, data: dict) -> dict:
        self.logger.info(f"UPDATE_ITEM key={key}")
        with self.config_lock:
            if key not in self.config.items:
                raise ValueError("Item not found")
            item = self.config.items[key]
            item.paths = [p.strip() for p in data.get("paths", []) if p.strip()]
            item.password = data.get("password") or None
            item.bcpignore = [p.strip() for p in data.get("bcpignore", []) if p.strip()]
            self.config.save()
            self.logger.info(f"UPDATE_ITEM saved key={key}")
        return item.to_dict()

    def delete_item(self, key: str):
        self.logger.info(f"DELETE_ITEM key={key}")
        with self.config_lock:
            if key in self.config.items:
                del self.config.items[key]
                for vault in self.config.vaults.values():
                    if key in vault.item_keys:
                        vault.item_keys.remove(key)
                self.config.save()
                self.logger.info(f"DELETE_ITEM done key={key}")

    def add_vault(self, data: dict) -> dict:
        name = data.get("name", "").strip()
        self.logger.info(f"ADD_VAULT name={name}")
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
            self.logger.info(f"ADD_VAULT saved name={name}")
        return vault.to_dict()

    def update_vault(self, name: str, data: dict) -> dict:
        self.logger.info(f"UPDATE_VAULT name={name}")
        with self.config_lock:
            if name not in self.config.vaults:
                raise ValueError("Vault not found")
            vault = self.config.vaults[name]
            vault.item_keys = [k for k in data.get("item_keys", []) if k in self.config.items]
            vault.password = data.get("password") or None
            vault.bcpignore = [p.strip() for p in data.get("bcpignore", []) if p.strip()]
            self.config.save()
            self.logger.info(f"UPDATE_VAULT saved name={name}")
        return vault.to_dict()

    def delete_vault(self, name: str):
        self.logger.info(f"DELETE_VAULT name={name}")
        with self.config_lock:
            if name in self.config.vaults:
                del self.config.vaults[name]
                self.config.save()
                self.logger.info(f"DELETE_VAULT done name={name}")

    def add_store(self, data: dict) -> dict:
        name = data.get("name", "").strip()
        self.logger.info(f"ADD_STORE name={name}")
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
            self.logger.info(f"ADD_STORE saved name={name}")
        return {"name": name, **cfg}

    def delete_store(self, name: str):
        self.logger.info(f"DELETE_STORE name={name}")
        with self.config_lock:
            if name in self.config.stores:
                del self.config.stores[name]
                self.config.save()
                self.logger.info(f"DELETE_STORE done name={name}")

    # ---- Frequencies ----

    def add_frequency(self, data: dict) -> dict:
        freq_id = data.get("id", "").strip() or str(uuid.uuid4())[:8]
        self.logger.info(f"ADD_FREQUENCY id={freq_id}")
        with self.config_lock:
            if freq_id in self.config.frequencies:
                raise ValueError("Frequency already exists")
            freq = JobFrequency(
                id=freq_id,
                name=data.get("name", "").strip(),
                period_type=data.get("period_type", "once"),
                interval=int(data.get("interval", 1)),
            )
            self.config.frequencies[freq_id] = freq
            self.config.save()
            self.logger.info(f"ADD_FREQUENCY saved id={freq_id}")
        return freq.to_dict()

    def update_frequency(self, freq_id: str, data: dict) -> dict:
        self.logger.info(f"UPDATE_FREQUENCY id={freq_id}")
        with self.config_lock:
            if freq_id not in self.config.frequencies:
                raise ValueError("Frequency not found")
            freq = self.config.frequencies[freq_id]
            freq.name = data.get("name", freq.name).strip()
            freq.period_type = data.get("period_type", freq.period_type)
            freq.interval = int(data.get("interval", freq.interval))
            self.config.save()
            self.logger.info(f"UPDATE_FREQUENCY saved id={freq_id}")
        return freq.to_dict()

    def delete_frequency(self, freq_id: str):
        self.logger.info(f"DELETE_FREQUENCY id={freq_id}")
        with self.config_lock:
            if freq_id in self.config.frequencies:
                for job in list(self.config.jobs.values()):
                    if job.frequency_id == freq_id:
                        del self.config.jobs[job.id]
                del self.config.frequencies[freq_id]
                self.config.save()
                self.logger.info(f"DELETE_FREQUENCY done id={freq_id}")

    # ---- Jobs ----

    def add_job(self, data: dict) -> dict:
        job_id = str(uuid.uuid4())[:8]
        freq_id = data.get("frequency_id")
        self.logger.info(f"ADD_JOB id={job_id} freq={freq_id}")
        if not freq_id or freq_id not in self.config.frequencies:
            raise ValueError("Frequency not found")
        job = Job(
            id=job_id,
            name=data.get("name", "").strip() or f"job_{job_id}",
            target_type=data.get("target_type"),
            target_name=data.get("target_name"),
            store_name=data.get("store_name"),
            frequency_id=freq_id,
            next_run=datetime.now().isoformat(),
        )
        with self.config_lock:
            self.config.jobs[job_id] = job
            self.config.save()
            self.logger.info(f"ADD_JOB saved id={job_id}")
        return job.to_dict()

    def update_job(self, job_id: str, data: dict) -> dict:
        self.logger.info(f"UPDATE_JOB id={job_id}")
        with self.config_lock:
            if job_id not in self.config.jobs:
                raise ValueError("Job not found")
            job = self.config.jobs[job_id]
            job.name = data.get("name", job.name).strip()
            job.target_type = data.get("target_type", job.target_type)
            job.target_name = data.get("target_name", job.target_name)
            job.store_name = data.get("store_name", job.store_name)
            if "frequency_id" in data:
                if data["frequency_id"] not in self.config.frequencies:
                    raise ValueError("Frequency not found")
                job.frequency_id = data["frequency_id"]
            job.enabled = data.get("enabled", job.enabled)
            self.config.save()
            self.logger.info(f"UPDATE_JOB saved id={job_id}")
        return job.to_dict()

    def delete_job(self, job_id: str):
        self.logger.info(f"DELETE_JOB id={job_id}")
        with self.config_lock:
            if job_id in self.config.jobs:
                del self.config.jobs[job_id]
                self.config.save()
                self.logger.info(f"DELETE_JOB done id={job_id}")

    def toggle_job(self, job_id: str) -> dict:
        self.logger.info(f"TOGGLE_JOB id={job_id}")
        with self.config_lock:
            if job_id not in self.config.jobs:
                raise ValueError("Job not found")
            self.config.jobs[job_id].enabled = not self.config.jobs[job_id].enabled
            self.config.save()
            self.logger.info(f"TOGGLE_JOB done id={job_id}")
            return self.config.jobs[job_id].to_dict()

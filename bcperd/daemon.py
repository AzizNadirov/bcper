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
from bcper_core.engine import TarGzBackupEngine, UserError
from bcper_core.models import (
    BCItem,
    BCVault,
    Job,
    JobFrequency,
    BCItemTarget,
    BCVaultTarget,
    JobFrequencyTrigger,
    validate_cron,
)
from bcper_core.storage import create_store
from bcper_core import db as run_db


class Daemon:
    SOCKET_PATH = os.path.expanduser("~/.config/bcper/daemon.sock")
    LOG_PATH = os.path.expanduser("~/.config/bcper/daemon.log")
    PID_PATH = os.path.expanduser("~/.config/bcper/daemon.pid")

    def __init__(self):
        self.config = Config()
        self.engine = TarGzBackupEngine()
        self.config_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread = None
        self._shutdown_event = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bcper_worker")
        self._running_jobs: set = set()
        self._running_jobs_lock = threading.Lock()
        self._setup_logging()
        run_db.init_db()
        self._cleanup_orphaned_jobs()

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

    def _cleanup_orphaned_jobs(self):
        """Remove jobs whose targets, stores, or frequencies no longer exist."""
        with self.config_lock:
            to_remove = []
            for jid, job in list(self.config.jobs.items()):
                if job.target_type == "item" and job.target_name not in self.config.items:
                    to_remove.append(jid)
                elif job.target_type == "vault" and job.target_name not in self.config.vaults:
                    to_remove.append(jid)
                elif job.store_name not in self.config.stores:
                    to_remove.append(jid)
                elif job.frequency_id not in self.config.frequencies:
                    to_remove.append(jid)
            if to_remove:
                for jid in to_remove:
                    self.logger.info(f"CLEANUP removing orphaned job {jid}")
                    del self.config.jobs[jid]
                self.config.save()
                self.logger.info(f"CLEANUP removed {len(to_remove)} orphaned job(s)")

    def _check_pid(self):
        if os.path.exists(self.PID_PATH):
            with open(self.PID_PATH) as f:
                old_pid = f.read().strip()
            if old_pid and os.path.exists(f"/proc/{old_pid}"):
                raise RuntimeError(f"Daemon already running (PID {old_pid}). Kill it or use `pkill -f bcperd`.")
            else:
                os.unlink(self.PID_PATH)
        with open(self.PID_PATH, "w") as f:
            f.write(str(os.getpid()))

    def _write_pid(self):
        with open(self.PID_PATH, "w") as f:
            f.write(str(os.getpid()))

    def _remove_pid(self):
        if os.path.exists(self.PID_PATH):
            os.unlink(self.PID_PATH)

    def start(self):
        self._check_pid()
        module_dir = os.path.dirname(os.path.abspath(__file__))
        self.logger.info(f"Daemon starting PID={os.getpid()} module={module_dir}")
        from .server import IPCProtocol
        commands = sorted([m[5:] for m in dir(IPCProtocol) if m.startswith("_cmd_")])
        self.logger.info(f"Registered commands: {commands}")
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        threading.Thread(target=self._catchup_missed_jobs, daemon=True).start()

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
        self._remove_pid()

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

    def _catchup_missed_jobs(self):
        """Run missed jobs sequentially on startup."""
        from datetime import datetime
        now = datetime.now()
        with self.config_lock:
            jobs = list(self.config.jobs.values())
        missed = []
        for job in jobs:
            if not job.enabled:
                continue
            if not job.next_run:
                continue
            try:
                if datetime.fromisoformat(job.next_run) <= now:
                    missed.append(job)
            except ValueError:
                continue
        if not missed:
            self.logger.info("CATCHUP no missed jobs")
            return
        missed.sort(key=lambda j: j.next_run or "")
        self.logger.info(f"CATCHUP {len(missed)} missed job(s) to run")
        for job in missed:
            self.logger.info(f"CATCHUP running job {job.id}: {job.name}")
            try:
                self._run_job(job)
            except Exception as e:
                self.logger.error(f"CATCHUP job {job.id} failed: {e}")
        self.logger.info("CATCHUP done")

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

    def run_job(self, job_id: str, progress_file: str = None) -> dict:
        self.logger.info(f"DAEMON run_job called id={job_id} progress_file={progress_file}")
        with self.config_lock:
            job = self.config.jobs.get(job_id)
            if not job:
                self.logger.error(f"DAEMON run_job: job {job_id} not found")
                raise ValueError("Job not found")
            self.logger.info(f"DAEMON run_job: found job {job_id} target={job.target_type}/{job.target_name} store={job.store_name}")
        return self._run_job(job, progress_file)

    def _run_job(self, job: Job, progress_file: str = None) -> dict:
        with self._running_jobs_lock:
            self._running_jobs.add(job.id)
        self.logger.info(f"DAEMON _run_job START {job.id}: {job.target_type}/{job.target_name} -> {job.store_name}")
        run_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        name_prefix = f"{job.name}/{run_id}/"
        archive_name = f"{job.target_name}_{timestamp}.tar.gz"

        run_db.insert_run({
            "id": run_id,
            "job_id": job.id,
            "job_name": job.name,
            "target_type": job.target_type,
            "target_name": job.target_name,
            "store_name": job.store_name,
            "store_path": name_prefix,
            "archive_name": archive_name,
            "started_at": datetime.now().isoformat(),
            "status": "running",
        })

        try:
            self.logger.info(f"DAEMON _run_job calling backup engine run_id={run_id}")
            from bcper_core.progress import make_progress_callback
            progress = make_progress_callback(progress_file)
            result = self.run_backup(
                job.target_type, job.target_name, job.store_name,
                timestamp=timestamp, name_prefix=name_prefix, progress_file=progress_file,
            )
            self.logger.info(f"DAEMON _run_job SUCCESS {job.id}: archive={result.get('archive')}")
            run_db.update_run(
                run_id,
                status="success",
                completed_at=datetime.now().isoformat(),
                hash=result.get("hash"),
                encrypted=result.get("encrypted"),
                archive_name=os.path.basename(result.get("archive", archive_name)),
            )
            self._apply_retention(job)
        except Exception as e:
            self.logger.error(f"DAEMON _run_job FAILED {job.id}: {e}")
            run_db.update_run(
                run_id,
                status="failed",
                completed_at=datetime.now().isoformat(),
                error_message=str(e),
            )
            raise
        finally:
            with self._running_jobs_lock:
                self._running_jobs.discard(job.id)
            with self.config_lock:
                job.last_run = datetime.now().isoformat()
                freq = self.config.frequencies.get(job.frequency_id)
                if freq:
                    trigger = JobFrequencyTrigger(freq)
                    job.next_run = trigger.calculate_next_run(job.last_run)
                    self.logger.info(f"DAEMON _run_job scheduled next_run={job.next_run} for {job.id}")
                self.config.save()
                self.logger.info(f"DAEMON _run_job config saved for {job.id}")
        return result

    def _apply_retention(self, job: Job):
        keep = job.keep_last
        if keep <= 0:
            return
        store_cfg = self.config.stores.get(job.store_name)
        if not store_cfg:
            return
        self.logger.info(f"DAEMON retention check for {job.id}: keep_last={keep}")
        try:
            to_delete = run_db.list_runs_for_retention(job.id, job.store_name, keep)
            self.logger.info(f"DAEMON retention found {len(to_delete)} old runs to prune")
            if to_delete:
                store = create_store(store_cfg)
                for run in to_delete:
                    rel = run["store_path"] + run["archive_name"]
                    self.logger.info(f"DAEMON retention deleting old backup: {rel}")
                    store.delete(rel)
                    run_db.delete_run(run["id"])
        except Exception as e:
            self.logger.warning(f"DAEMON retention failed for {job.id}: {e}")

    # ---- Operations ----

    def _resolve_target(self, target_type: str, target_name: str) -> object:
        if target_type == "item":
            item = self.config.items.get(target_name)
            if not item:
                raise UserError(f"Item not found: {target_name}")
            return BCItemTarget(item)
        elif target_type == "vault":
            vault = self.config.vaults.get(target_name)
            if not vault:
                raise UserError(f"Vault not found: {target_name}")
            items = {k: self.config.items[k] for k in vault.item_keys if k in self.config.items}
            return BCVaultTarget(vault, items)
        else:
            raise UserError(f"Invalid target type: {target_type}")

    def run_backup(self, target_type: str, target_name: str, store_name: str, timestamp: str = None, name_prefix: str = "", progress_file: str = None) -> dict:
        self.logger.info(f"BACKUP {target_type}/{target_name} → {store_name} prefix={name_prefix} progress_file={progress_file}")
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise UserError(f"Store not found: {store_name}")
        try:
            store = create_store(store_cfg)
        except RuntimeError as e:
            raise UserError(str(e))
        target = self._resolve_target(target_type, target_name)
        from bcper_core.progress import make_progress_callback
        progress = make_progress_callback(progress_file)
        try:
            result = self.engine.backup(target, store, timestamp=timestamp, name_prefix=name_prefix, progress=progress)
        except RuntimeError as e:
            raise UserError(str(e))
        self.logger.info(f"BACKUP done archive={result.get('archive')}")
        return result

    def run_restore(self, run_id: str, store_name: str, password: str = None, target_dir: str = None, progress_file: str = None) -> dict:
        self.logger.info(f"RESTORE run_id={run_id} from {store_name} progress_file={progress_file}")
        run = run_db.get_run(run_id)
        if not run:
            raise UserError(f"Run not found: {run_id}")
        store_cfg = self.config.stores.get(store_name)
        if not store_cfg:
            raise UserError(f"Store not found: {store_name}")
        try:
            store = create_store(store_cfg)
        except RuntimeError as e:
            raise UserError(str(e))
        archive_name = run["store_path"] + run["archive_name"]
        from bcper_core.progress import make_progress_callback
        progress = make_progress_callback(progress_file)
        try:
            result = self.engine.restore(archive_name, store, password=password, target_dir=target_dir, progress=progress)
        except RuntimeError as e:
            raise UserError(str(e))
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
                # Remove jobs that reference this item
                jobs_to_remove = [jid for jid, job in self.config.jobs.items()
                                  if job.target_type == "item" and job.target_name == key]
                for jid in jobs_to_remove:
                    del self.config.jobs[jid]
                    self.logger.info(f"DELETE_ITEM removed orphaned job {jid}")
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
                # Remove jobs that reference this vault
                jobs_to_remove = [jid for jid, job in self.config.jobs.items()
                                  if job.target_type == "vault" and job.target_name == name]
                for jid in jobs_to_remove:
                    del self.config.jobs[jid]
                    self.logger.info(f"DELETE_VAULT removed orphaned job {jid}")
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
                # Remove jobs that reference this store
                jobs_to_remove = [jid for jid, job in self.config.jobs.items()
                                  if job.store_name == name]
                for jid in jobs_to_remove:
                    del self.config.jobs[jid]
                    self.logger.info(f"DELETE_STORE removed orphaned job {jid}")
                self.config.save()
                self.logger.info(f"DELETE_STORE done name={name}")

    # ---- Frequencies ----

    def add_frequency(self, data: dict) -> dict:
        freq_id = data.get("id", "").strip() or str(uuid.uuid4())[:8]
        self.logger.info(f"ADD_FREQUENCY id={freq_id}")
        with self.config_lock:
            if freq_id in self.config.frequencies:
                raise ValueError("Frequency already exists")
            cron = data.get("cron", "").strip()
            if cron and not validate_cron(cron):
                raise ValueError(f"Invalid cron expression: {cron}")
            freq = JobFrequency(
                id=freq_id,
                name=data.get("name", "").strip(),
                cron=cron,
            )
            self.config.frequencies[freq_id] = freq
            self.config.save()
            self.logger.info(f"ADD_FREQUENCY saved id={freq_id} cron={cron}")
        return freq.to_dict()

    def update_frequency(self, freq_id: str, data: dict) -> dict:
        self.logger.info(f"UPDATE_FREQUENCY id={freq_id}")
        with self.config_lock:
            if freq_id not in self.config.frequencies:
                raise ValueError("Frequency not found")
            freq = self.config.frequencies[freq_id]
            freq.name = data.get("name", freq.name).strip()
            if "cron" in data:
                cron = data.get("cron", "").strip()
                if cron and not validate_cron(cron):
                    raise ValueError(f"Invalid cron expression: {cron}")
                freq.cron = cron
            self.config.save()
            self.logger.info(f"UPDATE_FREQUENCY saved id={freq_id} cron={freq.cron}")
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
            keep_last=int(data.get("keep_last", 3)),
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
            if "keep_last" in data:
                job.keep_last = int(data["keep_last"])
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

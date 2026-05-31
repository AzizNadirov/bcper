import logging
import os
import socket

from bcper_core import protocol

_client_logger = logging.getLogger("bcper.client")


class Client:
    DEFAULT_TIMEOUT = 120  # seconds; remote ops can be slow

    def __init__(self, socket_path: str = "~/.config/bcper/daemon.sock"):
        self.socket_path = os.path.expanduser(socket_path)

    def _call(self, cmd: str, **kwargs) -> dict:
        _client_logger.debug(f"CLIENT -> {cmd} {kwargs}")
        if not os.path.exists(self.socket_path):
            raise ConnectionError(f"Daemon is not running (socket not found: {self.socket_path})")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.DEFAULT_TIMEOUT)
        try:
            sock.connect(self.socket_path)
            msg = protocol.request(cmd, **kwargs)
            sock.sendall(msg)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Daemon closed connection")
                buf += chunk
            line, _ = buf.split(b"\n", 1)
            resp = protocol.decode(line)
            _client_logger.debug(f"CLIENT <- {cmd}: ok={resp.get('ok')} data={'<data>' if resp.get('data') is not None else 'None'} error={resp.get('error')}")
            return resp
        except (OSError, ConnectionError) as e:
            friendly = str(e)
            if isinstance(e, FileNotFoundError) or (getattr(e, 'errno', None) == 2):
                friendly = f"Daemon is not running (socket not found: {self.socket_path})"
            _client_logger.warning(f"CLIENT connection error for {cmd}: {friendly}")
            raise ConnectionError(friendly) from e
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def ping(self):
        return self._call("PING")

    def status(self):
        return self._call("STATUS")

    def reload(self):
        return self._call("RELOAD")

    def list_items(self):
        return self._call("LIST_ITEMS")

    def list_vaults(self):
        return self._call("LIST_VAULTS")

    def list_stores(self):
        return self._call("LIST_STORES")

    def list_frequencies(self):
        return self._call("LIST_FREQUENCIES")

    def list_jobs(self):
        return self._call("LIST_JOBS")

    def list_backups(self, store_name: str):
        return self._call("LIST_BACKUPS", store_name=store_name)

    def backup(self, target_type: str, target_name: str, store_name: str, progress_file: str = None):
        return self._call("BACKUP", target_type=target_type, target_name=target_name, store_name=store_name, progress_file=progress_file)

    def restore(self, run_id: str, store_name: str, password: str = None, target_dir: str = None, progress_file: str = None):
        return self._call("RESTORE", run_id=run_id, store_name=store_name, password=password, target_dir=target_dir, progress_file=progress_file)

    def restore_many(self, run_ids: list, store_name: str, password: str = None, target_dir: str = None, progress_file: str = None):
        return self._call("RESTORE_MANY", run_ids=run_ids, store_name=store_name, password=password, target_dir=target_dir, progress_file=progress_file)

    def delete_backup(self, run_id: str, store_name: str):
        return self._call("DELETE_BACKUP", run_id=run_id, store_name=store_name)

    def delete_backups(self, run_ids: list, store_name: str):
        return self._call("DELETE_BACKUPS", run_ids=run_ids, store_name=store_name)

    def add_item(self, **data):
        return self._call("ADD_ITEM", **data)

    def update_item(self, key: str, **data):
        return self._call("UPDATE_ITEM", key=key, **data)

    def delete_item(self, key: str):
        return self._call("DELETE_ITEM", key=key)

    def add_vault(self, **data):
        return self._call("ADD_VAULT", **data)

    def update_vault(self, name: str, **data):
        return self._call("UPDATE_VAULT", name=name, **data)

    def delete_vault(self, name: str):
        return self._call("DELETE_VAULT", name=name)

    def add_store(self, **data):
        return self._call("ADD_STORE", **data)

    def delete_store(self, name: str):
        return self._call("DELETE_STORE", name=name)

    def add_frequency(self, **data):
        return self._call("ADD_FREQUENCY", **data)

    def update_frequency(self, id: str, **data):
        return self._call("UPDATE_FREQUENCY", id=id, **data)

    def delete_frequency(self, id: str):
        return self._call("DELETE_FREQUENCY", id=id)

    def add_job(self, **data):
        return self._call("ADD_JOB", **data)

    def update_job(self, id: str, **data):
        return self._call("UPDATE_JOB", id=id, **data)

    def delete_job(self, job_id: str):
        return self._call("DELETE_JOB", job_id=job_id)

    def run_job(self, job_id: str, progress_file: str = None):
        return self._call("RUN_JOB", job_id=job_id, progress_file=progress_file)

    def toggle_job(self, job_id: str):
        return self._call("TOGGLE_JOB", job_id=job_id)

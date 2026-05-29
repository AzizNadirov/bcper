import logging
import os
import socket
import threading

from bcper_core import protocol

_client_logger = logging.getLogger("bcper.client")


class Client:
    def __init__(self, socket_path: str = "~/.config/bcper/daemon.sock"):
        self.socket_path = os.path.expanduser(socket_path)
        self._sock = None
        self._lock = threading.Lock()

    def connect(self):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self.socket_path)
        self._sock.settimeout(30)

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _call(self, cmd: str, **kwargs) -> dict:
        _client_logger.debug(f"CLIENT -> {cmd} {kwargs}")
        with self._lock:
            if self._sock is None:
                _client_logger.debug("CLIENT connecting to daemon")
                self.connect()
            try:
                msg = protocol.request(cmd, **kwargs)
                self._sock.sendall(msg)
                buf = b""
                while b"\n" not in buf:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("Daemon closed connection")
                    buf += chunk
                line, _ = buf.split(b"\n", 1)
                resp = protocol.decode(line)
                _client_logger.debug(f"CLIENT <- {cmd}: ok={resp.get('ok')} data={'<data>' if resp.get('data') is not None else 'None'} error={resp.get('error')}")
                return resp
            except (OSError, ConnectionError) as e:
                _client_logger.warning(f"CLIENT connection error for {cmd}: {e}")
                self.close()
                raise

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

    def backup(self, target_type: str, target_name: str, store_name: str):
        return self._call("BACKUP", target_type=target_type, target_name=target_name, store_name=store_name)

    def restore(self, archive: str, store_name: str, password: str = None, target_dir: str = None):
        return self._call("RESTORE", archive=archive, store_name=store_name, password=password, target_dir=target_dir)

    def delete_backup(self, archive: str, store_name: str):
        return self._call("DELETE_BACKUP", archive=archive, store_name=store_name)

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

    def run_job(self, job_id: str):
        return self._call("RUN_JOB", job_id=job_id)

    def toggle_job(self, job_id: str):
        return self._call("TOGGLE_JOB", job_id=job_id)

import logging
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import List

from .rclone_helper import get_rclone_path, run_rclone, ensure_rclone

_storage_logger = logging.getLogger("bcper.storage")


class BackupStore(ABC):
    @abstractmethod
    def save(self, name: str, data: bytes) -> str:
        pass

    @abstractmethod
    def load(self, name: str) -> bytes:
        pass

    @abstractmethod
    def list_backups(self) -> List[str]:
        pass

    @abstractmethod
    def delete(self, name: str) -> None:
        pass

    @abstractmethod
    def exists(self, name: str) -> bool:
        pass


class LocalStore(BackupStore):
    def __init__(self, base_path: str):
        self.base_path = os.path.expanduser(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.base_path, name)

    def save(self, name: str, data: bytes) -> str:
        path = self._path(name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def load(self, name: str) -> bytes:
        with open(self._path(name), "rb") as f:
            return f.read()

    def list_backups(self) -> List[str]:
        if not os.path.exists(self.base_path):
            return []
        files = [
            f for f in os.listdir(self.base_path)
            if not f.endswith((".sha256", ".meta.json"))
        ]
        return sorted(files)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if os.path.exists(path):
            os.remove(path)
        for ext in (".sha256", ".meta.json"):
            p = path + ext
            if os.path.exists(p):
                os.remove(p)

    def exists(self, name: str) -> bool:
        return os.path.exists(self._path(name))


class RcloneStore(BackupStore):
    def __init__(self, remote: str, path: str = ""):
        self.remote = remote
        self.path = path
        self._rclone = ensure_rclone()
        _storage_logger.info(f"RcloneStore init remote={remote} path={path} rclone={self._rclone}")

    def _remote_path(self, name: str) -> str:
        return f"{self.remote}:{os.path.join(self.path, name)}"

    def save(self, name: str, data: bytes) -> str:
        remote_path = self._remote_path(name)
        _storage_logger.info(f"RcloneStore save {name} -> {remote_path} ({len(data)} bytes)")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [self._rclone, "copyto", tmp_path, remote_path],
                capture_output=True,
            )
            if result.returncode != 0:
                err = result.stderr.decode() if result.stderr else "rclone copyto failed"
                _storage_logger.error(f"RcloneStore save FAILED: {err}")
                raise RuntimeError(err)
            _storage_logger.info(f"RcloneStore save OK {name}")
        finally:
            os.unlink(tmp_path)
        return remote_path

    def load(self, name: str) -> bytes:
        remote_path = self._remote_path(name)
        _storage_logger.info(f"RcloneStore load {name} from {remote_path}")
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                [self._rclone, "copyto", remote_path, tmp_path],
                capture_output=True,
            )
            if result.returncode != 0:
                err = result.stderr.decode() if result.stderr else "rclone copyto failed"
                _storage_logger.error(f"RcloneStore load FAILED: {err}")
                raise RuntimeError(err)
            with open(tmp_path, "rb") as f:
                data = f.read()
            _storage_logger.info(f"RcloneStore load OK {name} ({len(data)} bytes)")
            return data
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def list_backups(self) -> List[str]:
        remote_path = self._remote_path("")
        _storage_logger.info(f"RcloneStore list_backups {remote_path}")
        result = subprocess.run(
            [self._rclone, "lsf", remote_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            _storage_logger.warning(f"RcloneStore list_backups failed: {result.stderr}")
            return []
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        out = sorted([
            f for f in files
            if not f.endswith((".sha256", ".meta.json"))
        ])
        _storage_logger.info(f"RcloneStore list_backups -> {len(out)} items")
        return out

    def delete(self, name: str) -> None:
        remote_path = self._remote_path(name)
        _storage_logger.info(f"RcloneStore delete {name} -> {remote_path}")
        result = subprocess.run([self._rclone, "delete", remote_path], capture_output=True)
        if result.returncode != 0:
            err = result.stderr.decode() if result.stderr else f"rclone delete exited {result.returncode}"
            _storage_logger.error(f"RcloneStore delete FAILED {name}: {err}")
            raise RuntimeError(err)
        _storage_logger.info(f"RcloneStore delete OK {name}")
        for ext in (".sha256", ".meta.json"):
            sidecar = remote_path + ext
            _storage_logger.info(f"RcloneStore delete sidecar {sidecar}")
            result = subprocess.run(
                [self._rclone, "delete", sidecar],
                capture_output=True,
            )
            if result.returncode != 0:
                _storage_logger.debug(f"RcloneStore sidecar {ext} not found or delete failed (ok)")
            else:
                _storage_logger.info(f"RcloneStore delete sidecar OK {ext}")

    def exists(self, name: str) -> bool:
        remote_path = self._remote_path(name)
        result = subprocess.run(
            [self._rclone, "lsf", remote_path],
            capture_output=True, text=True,
        )
        exists = result.returncode == 0 and result.stdout.strip() != ""
        _storage_logger.debug(f"RcloneStore exists {name} = {exists}")
        return exists


def list_rclone_remotes() -> List[str]:
    result = run_rclone("listremotes")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return [
        r.strip().rstrip(":")
        for r in result.stdout.splitlines()
        if r.strip()
    ]


def create_store(config: dict) -> BackupStore:
    store_type = config.get("type", "local")
    if store_type == "local":
        return LocalStore(config["path"])
    elif store_type == "rclone":
        return RcloneStore(config["remote"], config.get("path", ""))
    else:
        raise ValueError(f"Unknown store type: {store_type}")

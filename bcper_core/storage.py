import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import List


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
        if shutil.which("rclone") is None:
            raise RuntimeError("rclone not found in PATH")

    def _remote_path(self, name: str) -> str:
        return f"{self.remote}:{os.path.join(self.path, name)}"

    def save(self, name: str, data: bytes) -> str:
        remote_path = self._remote_path(name)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["rclone", "copyto", tmp_path, remote_path],
                check=True, capture_output=True,
            )
        finally:
            os.unlink(tmp_path)
        return remote_path

    def load(self, name: str) -> bytes:
        remote_path = self._remote_path(name)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["rclone", "copyto", remote_path, tmp_path],
                check=True, capture_output=True,
            )
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def list_backups(self) -> List[str]:
        remote_path = self._remote_path("")
        result = subprocess.run(
            ["rclone", "lsf", remote_path],
            capture_output=True, text=True, check=True,
        )
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        return sorted([
            f for f in files
            if not f.endswith((".sha256", ".meta.json"))
        ])

    def delete(self, name: str) -> None:
        remote_path = self._remote_path(name)
        subprocess.run(["rclone", "delete", remote_path], check=True, capture_output=True)
        for ext in (".sha256", ".meta.json"):
            subprocess.run(
                ["rclone", "delete", remote_path + ext],
                check=True, capture_output=True,
            )

    def exists(self, name: str) -> bool:
        result = subprocess.run(
            ["rclone", "lsf", self._remote_path(name)],
            capture_output=True, text=True,
        )
        return result.returncode == 0 and result.stdout.strip() != ""


def create_store(config: dict) -> BackupStore:
    store_type = config.get("type", "local")
    if store_type == "local":
        return LocalStore(config["path"])
    elif store_type == "rclone":
        return RcloneStore(config["remote"], config.get("path", ""))
    else:
        raise ValueError(f"Unknown store type: {store_type}")

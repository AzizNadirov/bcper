from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict


# ---------------------------------------------------------------------------
# Domain entities
# ---------------------------------------------------------------------------

@dataclass
class BCItem:
    key: str
    paths: List[str]
    password: Optional[str] = None
    bcpignore: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "key": self.key,
            "paths": self.paths,
            "password": self.password,
            "bcpignore": self.bcpignore,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            key=d["key"],
            paths=d["paths"],
            password=d.get("password"),
            bcpignore=d.get("bcpignore", []),
        )


@dataclass
class BCVault:
    name: str
    item_keys: List[str]
    password: Optional[str] = None
    bcpignore: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "name": self.name,
            "item_keys": self.item_keys,
            "password": self.password,
            "bcpignore": self.bcpignore,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"],
            item_keys=d["item_keys"],
            password=d.get("password"),
            bcpignore=d.get("bcpignore", []),
        )


@dataclass
class JobFrequency:
    id: str
    name: str
    period_type: str  # "once", "hourly", "daily"
    interval: int = 1
    time: str = ""  # e.g. "14:30" for daily at 2:30 PM

    def to_dict(self):
        return {"id": self.id, "name": self.name, "period_type": self.period_type, "interval": self.interval, "time": self.time}

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            name=d["name"],
            period_type=d["period_type"],
            interval=d.get("interval", 1),
            time=d.get("time", ""),
        )


@dataclass
class Job:
    id: str
    name: str
    target_type: str  # "item" or "vault"
    target_name: str
    store_name: str
    frequency_id: str
    keep_last: int = 3
    enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "target_type": self.target_type,
            "target_name": self.target_name,
            "store_name": self.store_name,
            "frequency_id": self.frequency_id,
            "keep_last": self.keep_last,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            name=d["name"],
            target_type=d["target_type"],
            target_name=d["target_name"],
            store_name=d["store_name"],
            frequency_id=d["frequency_id"],
            keep_last=d.get("keep_last", 3),
            enabled=d.get("enabled", True),
            last_run=d.get("last_run"),
            next_run=d.get("next_run"),
        )


# ---------------------------------------------------------------------------
# Abstractions  (SOLID)
# ---------------------------------------------------------------------------

class BackupTarget(ABC):
    """Something that can be backed up."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def get_paths(self) -> List[str]:
        pass

    @abstractmethod
    def get_password(self) -> Optional[str]:
        pass

    @abstractmethod
    def get_ignore_patterns(self) -> List[str]:
        pass


class BCItemTarget(BackupTarget):
    def __init__(self, item: BCItem):
        self._item = item

    @property
    def name(self) -> str:
        return self._item.key

    def get_paths(self) -> List[str]:
        return self._item.paths

    def get_password(self) -> Optional[str]:
        return self._item.password

    def get_ignore_patterns(self) -> List[str]:
        return self._item.bcpignore


class BCVaultTarget(BackupTarget):
    def __init__(self, vault: BCVault, items: Dict[str, BCItem]):
        self._vault = vault
        self._items = items

    @property
    def name(self) -> str:
        return self._vault.name

    def get_paths(self) -> List[str]:
        return []

    def get_password(self) -> Optional[str]:
        return self._vault.password

    def get_ignore_patterns(self) -> List[str]:
        return self._vault.bcpignore

    def get_item_targets(self) -> List[BCItemTarget]:
        return [BCItemTarget(self._items[k]) for k in self._vault.item_keys if k in self._items]


class BackupTrigger(ABC):
    """Determines when a job should run."""

    @abstractmethod
    def should_run(self, last_run: Optional[str], next_run: Optional[str]) -> bool:
        pass

    @abstractmethod
    def calculate_next_run(self, last_run: str) -> Optional[str]:
        pass


class JobFrequencyTrigger(BackupTrigger):
    def __init__(self, frequency: JobFrequency):
        self._frequency = frequency

    def should_run(self, last_run: Optional[str], next_run: Optional[str]) -> bool:
        from datetime import datetime
        now = datetime.now()
        if self._frequency.period_type == "once":
            if last_run:
                return False
            return next_run is not None and datetime.fromisoformat(next_run) <= now
        next_run_dt = datetime.fromisoformat(next_run) if next_run else now
        return next_run_dt <= now

    def calculate_next_run(self, last_run: str) -> Optional[str]:
        from datetime import datetime, timedelta
        last = datetime.fromisoformat(last_run)
        freq = self._frequency
        if freq.period_type == "hourly":
            return (last + timedelta(hours=freq.interval)).isoformat()
        elif freq.period_type == "daily":
            base = last + timedelta(days=freq.interval)
            if freq.time:
                try:
                    hour, minute = map(int, freq.time.split(":", 1))
                    base = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if base <= last:
                        base = base + timedelta(days=freq.interval)
                except ValueError:
                    pass
            return base.isoformat()
        return None


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


class BackupEngine(ABC):
    """Performs backup / restore operations."""

    @abstractmethod
    def backup(self, target: BackupTarget, store: BackupStore, timestamp: str = None) -> dict:
        pass

    @abstractmethod
    def restore(self, archive_name: str, store: BackupStore, password: str = None, target_dir: str = None) -> dict:
        pass

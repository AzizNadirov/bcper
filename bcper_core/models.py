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
    cron: str = ""  # empty means "once"; otherwise standard 5-field cron

    def to_dict(self):
        return {"id": self.id, "name": self.name, "cron": self.cron}

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            name=d["name"],
            cron=d.get("cron", ""),
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


def validate_cron(cron: str) -> bool:
    """Validate a 5-field cron expression. Empty string is valid (means 'once')."""
    if not cron.strip():
        return True
    from croniter import croniter
    return croniter.is_valid(cron)


def validate_cron_interval(cron: str) -> bool:
    """Ensure no two cron occurrences are closer than 5 minutes."""
    if not cron.strip():
        return True
    from croniter import croniter
    from datetime import datetime, timedelta
    base = datetime(2020, 1, 6, 0, 0, 0)
    c = croniter(cron, base)
    prev = c.get_next(datetime)
    for _ in range(1000):
        nxt = c.get_next(datetime)
        if nxt - prev < timedelta(minutes=5):
            return False
        prev = nxt
        if nxt - base > timedelta(days=8):
            break
    return True


def describe_cron(cron: str) -> str:
    """Return a human-readable description of a cron expression."""
    if not cron.strip():
        return "Once"
    parts = cron.split()
    if len(parts) != 5:
        return cron
    minute, hour, dom, month, dow = parts

    # Every minute
    if cron == "* * * * *":
        return "Every minute"

    # Every N minutes
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return f"Every {minute[2:]} minutes"

    # Every hour at :MM
    if minute != "*" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return f"Every hour at :{minute.zfill(2)}"

    # Every N hours at :MM
    if minute != "*" and hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
        return f"Every {hour[2:]} hours at :{minute.zfill(2)}"

    # Daily at HH:MM
    if minute != "*" and hour != "*" and dom == "*" and month == "*" and dow == "*":
        return f"Daily at {hour.zfill(2)}:{minute.zfill(2)}"

    # Weekly on specific day
    days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    if minute != "*" and hour != "*" and dom == "*" and month == "*" and dow != "*":
        if "," not in dow:
            try:
                day_idx = int(dow)
                day_name = days[day_idx % 7]
                return f"Weekly on {day_name} at {hour.zfill(2)}:{minute.zfill(2)}"
            except ValueError:
                pass
        return f"Weekly ({dow}) at {hour.zfill(2)}:{minute.zfill(2)}"

    # Monthly on specific day
    if minute != "*" and hour != "*" and dom != "*" and month == "*" and dow == "*":
        return f"Monthly on day {dom} at {hour.zfill(2)}:{minute.zfill(2)}"

    return cron


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
        if not next_run:
            return False
        from datetime import datetime
        return datetime.fromisoformat(next_run) <= datetime.now()

    def calculate_next_run(self, last_run: str) -> Optional[str]:
        if not self._frequency.cron:
            return None  # "once" — never schedule again
        from datetime import datetime
        from croniter import croniter
        now = datetime.now()
        c = croniter(self._frequency.cron, now)
        return c.get_next(datetime).isoformat()


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

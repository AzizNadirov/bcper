from dataclasses import dataclass, field
from typing import List, Optional


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
class RunPeriod:
    period_type: str  # "once", "hourly", "daily"
    interval: int = 1

    def to_dict(self):
        return {"period_type": self.period_type, "interval": self.interval}

    @classmethod
    def from_dict(cls, d):
        return cls(period_type=d["period_type"], interval=d.get("interval", 1))


@dataclass
class BackupJob:
    id: str
    target_type: str  # "item" or "vault"
    target_name: str
    store_name: str
    period: RunPeriod
    enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None

    def to_dict(self):
        return {
            "id": self.id,
            "target_type": self.target_type,
            "target_name": self.target_name,
            "store_name": self.store_name,
            "period": self.period.to_dict(),
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d["id"],
            target_type=d["target_type"],
            target_name=d["target_name"],
            store_name=d["store_name"],
            period=RunPeriod.from_dict(d["period"]),
            enabled=d.get("enabled", True),
            last_run=d.get("last_run"),
            next_run=d.get("next_run"),
        )

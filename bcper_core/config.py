import json
import os
from typing import Dict

from .models import BCItem, BCVault, JobFrequency, Job


class Config:
    CONFIG_DIR = os.path.expanduser("~/.config/bcper")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

    def __init__(self):
        self.items: Dict[str, BCItem] = {}
        self.vaults: Dict[str, BCVault] = {}
        self.frequencies: Dict[str, JobFrequency] = {}
        self.jobs: Dict[str, Job] = {}
        self.stores: Dict[str, dict] = {}
        os.makedirs(self.CONFIG_DIR, exist_ok=True)
        self.load()

    def load(self):
        if not os.path.exists(self.CONFIG_FILE):
            return
        with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.items = {k: BCItem.from_dict(v) for k, v in data.get("items", {}).items()}
        self.vaults = {k: BCVault.from_dict(v) for k, v in data.get("vaults", {}).items()}
        self.stores = data.get("stores", {})

        # Frequencies
        self.frequencies = {
            k: JobFrequency.from_dict(v)
            for k, v in data.get("frequencies", {}).items()
        }

        # Jobs
        self.jobs = {
            k: Job.from_dict(v)
            for k, v in data.get("jobs", {}).items()
        }

    def save(self):
        data = {
            "items": {k: v.to_dict() for k, v in self.items.items()},
            "vaults": {k: v.to_dict() for k, v in self.vaults.items()},
            "frequencies": {k: v.to_dict() for k, v in self.frequencies.items()},
            "jobs": {k: v.to_dict() for k, v in self.jobs.items()},
            "stores": self.stores,
        }
        with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

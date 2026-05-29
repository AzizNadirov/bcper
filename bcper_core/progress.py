import os
import threading
import time
from typing import Callable, Optional


class ProgressReporter:
    """Thread-safe progress reporter that writes to a file."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._lock = threading.Lock()

    def report(self, step: str):
        if self.path:
            with self._lock:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(step + "\n")

    def clear(self):
        if self.path and os.path.exists(self.path):
            with self._lock:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write("")


def make_progress_callback(path: Optional[str]) -> Callable[[str], None]:
    """Create a no-op callback if path is None, else a file writer."""
    if not path:
        return lambda s: None
    reporter = ProgressReporter(path)
    return reporter.report

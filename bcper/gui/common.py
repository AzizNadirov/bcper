import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

# GUI logging -----------------------------------------------------------------
_log_dir = os.path.expanduser("~/.config/bcper")
os.makedirs(_log_dir, exist_ok=True)
_gui_logger = logging.getLogger("bcper.gui")
_gui_logger.setLevel(logging.INFO)
if not _gui_logger.handlers:
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    _fh = logging.FileHandler(os.path.join(_log_dir, "gui.log"), mode="a")
    _fh.setFormatter(_fmt)
    _gui_logger.addHandler(_sh)
    _gui_logger.addHandler(_fh)

_ui_queue = queue.Queue()


class ProgressDialog(tk.Toplevel):
    def __init__(self, master, text="Working..."):
        super().__init__(master)
        self.title("Please wait")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self.resizable(False, False)
        self._label = tk.Label(self, text=text, padx=24, pady=12)
        self._label.pack()
        self.bar = ttk.Progressbar(self, mode="indeterminate", length=240)
        self.bar.pack(padx=24, pady=(0, 12))
        self.bar.start(15)
        self._polling = False

    def set_text(self, text):
        self._label.config(text=text)

    def close(self):
        self._polling = False
        self.destroy()


def _poll_progress_file(prog: ProgressDialog, path: str):
    """Poll progress file and update dialog text."""
    prog._polling = True
    last_mtime = 0
    while prog._polling and prog.winfo_exists():
        try:
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                if mtime != last_mtime:
                    last_mtime = mtime
                    with open(path, "r", encoding="utf-8") as f:
                        lines = [l.strip() for l in f.readlines() if l.strip()]
                    if lines:
                        prog.set_text(lines[-1])
        except Exception:
            pass
        time.sleep(0.2)


def run_async(func, callback, master=None, progress_text=None):
    prog = None
    progress_path = None
    if master and progress_text:
        prog = ProgressDialog(master, progress_text)
        import tempfile
        fd, progress_path = tempfile.mkstemp(suffix=".progress", prefix="bcper_")
        os.close(fd)
        # Start polling thread
        threading.Thread(target=_poll_progress_file, args=(prog, progress_path), daemon=True).start()

    def wrapper():
        try:
            # Inject progress_path into func if it supports it
            if progress_path:
                result = func(progress_path)
            else:
                result = func()
            if isinstance(result, dict) and not result.get("ok", True):
                err = result.get("error") or "Unknown daemon error"
                _gui_logger.warning(f"Daemon error: {err}")
                if prog:
                    _ui_queue.put(lambda: prog.close())
                _ui_queue.put(lambda: callback(None, err))
            else:
                if prog:
                    _ui_queue.put(lambda: prog.close())
                _ui_queue.put(lambda: callback(result, None))
        except OSError as e:
            _gui_logger.debug(f"Async OSError: {e}")
            if prog:
                _ui_queue.put(lambda: prog.close())
            _ui_queue.put(lambda: callback(None, str(e)))
        except Exception as e:
            _gui_logger.warning(f"Async exception: {e}")
            if prog:
                _ui_queue.put(lambda: prog.close())
            _ui_queue.put(lambda: callback(None, str(e)))
        finally:
            if progress_path and os.path.exists(progress_path):
                try:
                    os.unlink(progress_path)
                except Exception:
                    pass
    threading.Thread(target=wrapper, daemon=True).start()

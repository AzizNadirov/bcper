import logging
import os
import queue
import sys
import threading

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


def run_async(func, callback):
    def wrapper():
        try:
            result = func()
            if isinstance(result, dict) and not result.get("ok", True):
                err = result.get("error") or "Unknown daemon error"
                _gui_logger.warning(f"Daemon error: {err}")
                _ui_queue.put(lambda: callback(None, err))
            else:
                _ui_queue.put(lambda: callback(result, None))
        except Exception as e:
            _gui_logger.warning(f"Async exception: {e}")
            _ui_queue.put(lambda: callback(None, str(e)))
    threading.Thread(target=wrapper, daemon=True).start()

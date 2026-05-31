import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

from .common import run_async


MARKER_START = "# >>> BCPER shell integration >>>"
MARKER_END = "# <<< BCPER shell integration <<"


def _get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_shell_rc_files() -> list:
    home = os.path.expanduser("~")
    candidates = []
    for name in (".zshrc", ".bashrc"):
        path = os.path.join(home, name)
        if os.path.isfile(path):
            candidates.append(path)
    return candidates


def _build_snippet(project_root: str) -> str:
    return (
        f"\n{MARKER_START}\n"
        f"export PYTHONPATH=\"{project_root}:$PYTHONPATH\"\n"
        f"alias bcper='python3 -m bcper'\n"
        f"alias bcperd='python3 -m bcperd'\n"
        f"alias bcper-cli='python3 -m bcper.cli'\n"
        f"{MARKER_END}\n"
    )


def _already_has_snippet(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return MARKER_START in f.read()
    except Exception:
        return False


def _append_snippet(path: str, snippet: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(snippet)


class ShellIntegrationDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Shell Integration")
        self.geometry("380x200")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        tk.Label(self, text="Add BCPER aliases to shell config:").pack(anchor="w", padx=12, pady=(12, 4))

        self.vars = {}
        for path in _find_shell_rc_files():
            var = tk.BooleanVar(value=True)
            self.vars[path] = var
            tk.Checkbutton(self, text=path, variable=var).pack(anchor="w", padx=24)

        if not self.vars:
            tk.Label(self, text="No .bashrc or .zshrc found in home directory.").pack(anchor="w", padx=24, pady=8)

        preview = _build_snippet(_get_project_root())
        tk.Label(self, text="Preview:").pack(anchor="w", padx=12, pady=(8, 2))
        text = tk.Text(self, wrap="word", height=5, state="disabled", bg="#f5f5f5")
        text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        text.configure(state="normal")
        text.insert("1.0", preview)
        text.configure(state="disabled")

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))
        tk.Button(btn_frame, text="Apply", command=self._apply).pack(side="right", padx=(8, 0))
        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right")

        self._result_label = tk.Label(self, text="")
        self._result_label.pack(anchor="w", padx=12)

    def _apply(self):
        project_root = _get_project_root()
        snippet = _build_snippet(project_root)
        results = []
        for path, var in self.vars.items():
            if not var.get():
                continue
            if _already_has_snippet(path):
                results.append(f"Skipped {path} (already present)")
                continue
            try:
                _append_snippet(path, snippet)
                results.append(f"Added to {path}")
            except Exception as e:
                results.append(f"Failed {path}: {e}")
        if results:
            self._result_label.config(text="\n".join(results), fg="green" if all("Added" in r or "Skipped" in r for r in results) else "red")
        else:
            self._result_label.config(text="Nothing selected.", fg="orange")


class StatusTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))
        self.status_label = tk.Label(toolbar, text="Status: unknown")
        self.status_label.pack(side="left")
        tk.Button(toolbar, text="Start Daemon", command=self._start_daemon).pack(side="left", padx=(8, 4))
        tk.Button(toolbar, text="Restart Daemon", command=self._restart_daemon).pack(side="left", padx=(0, 4))
        tk.Button(toolbar, text="Shell Integration", command=self._open_shell_dialog).pack(side="left", padx=(0, 4))
        tk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right")

        tk.Label(self, text="Daemon Log:").pack(anchor="w")
        self.log_text = tk.Text(self, wrap="none", state="disabled", height=20)
        self.log_text.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(self.log_text, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        run_async(self.client.ping, self._on_ping)
        self._load_log()

    def _on_ping(self, resp, err):
        if err:
            self.status_label.config(text=f"Status: disconnected ({err})")
        else:
            data = resp.get("data", "pong")
            self.status_label.config(text=f"Status: connected ({data})")

    def _load_log(self):
        log_path = os.path.expanduser("~/.config/bcper/daemon.log")
        if not os.path.exists(log_path):
            return
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            text = "".join(lines[-200:])
            self.log_text.configure(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.insert("1.0", text)
            self.log_text.configure(state="disabled")
            self.log_text.see("end")
        except Exception:
            pass

    def _start_daemon(self):
        pid_path = os.path.expanduser("~/.config/bcper/daemon.pid")
        if os.path.exists(pid_path):
            with open(pid_path) as f:
                old_pid = f.read().strip()
            if old_pid and os.path.exists(f"/proc/{old_pid}"):
                try:
                    self.client.ping()
                    messagebox.showinfo("Daemon", f"Daemon already running (PID {old_pid}).")
                    return
                except Exception:
                    try:
                        os.kill(int(old_pid), 9)
                        time.sleep(0.5)
                    except Exception:
                        pass
            try:
                os.unlink(pid_path)
            except Exception:
                pass
        sock_path = os.path.expanduser("~/.config/bcper/daemon.sock")
        if os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except Exception:
                pass
        subprocess.Popen([sys.executable, "-m", "bcperd"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(10):
            time.sleep(0.3)
            try:
                self.client.ping()
                self.refresh()
                return
            except Exception:
                pass
        messagebox.showerror("Daemon", "Failed to start daemon.")

    def _restart_daemon(self):
        pid_path = os.path.expanduser("~/.config/bcper/daemon.pid")
        old_pid = None
        if os.path.exists(pid_path):
            with open(pid_path) as f:
                old_pid = f.read().strip()
            if old_pid and os.path.exists(f"/proc/{old_pid}"):
                try:
                    os.kill(int(old_pid), 15)  # SIGTERM
                    for _ in range(20):
                        time.sleep(0.15)
                        if not os.path.exists(f"/proc/{old_pid}"):
                            break
                    else:
                        os.kill(int(old_pid), 9)  # SIGKILL
                        time.sleep(0.3)
                except Exception:
                    pass
            try:
                os.unlink(pid_path)
            except Exception:
                pass
        sock_path = os.path.expanduser("~/.config/bcper/daemon.sock")
        if os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except Exception:
                pass
        subprocess.Popen([sys.executable, "-m", "bcperd"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(10):
            time.sleep(0.3)
            try:
                self.client.ping()
                self.refresh()
                return
            except Exception:
                pass
        messagebox.showerror("Daemon", "Failed to restart daemon.")

    def _open_shell_dialog(self):
        ShellIntegrationDialog(self)

import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk

from .common import run_async


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
                    tk.messagebox.showinfo("Daemon", f"Daemon already running (PID {old_pid}).")
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
        tk.messagebox.showerror("Daemon", "Failed to start daemon.")

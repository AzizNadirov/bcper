import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, PhotoImage

from ..client import Client
from .common import _ui_queue, run_async
from .items_tab import ItemsTab
from .vaults_tab import VaultsTab
from .stores_tab import StoresTab
from .backups_tab import BackupsTab
from .frequencies_tab import FrequenciesTab
from .jobs_tab import JobsTab
from .status_tab import StatusTab


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BCPER Backup Manager")
        self.geometry("960x640")
        self.client = Client()

        # Load logos (keep reference to prevent GC)
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        self._logo_img = None
        self._logo_large = None
        try:
            logo_path = os.path.join(assets_dir, "logo.gif")
            if os.path.exists(logo_path):
                self._logo_img = PhotoImage(file=logo_path)
            logo_large_path = os.path.join(assets_dir, "logo_large.gif")
            if os.path.exists(logo_large_path):
                self._logo_large = PhotoImage(file=logo_large_path)
        except Exception:
            pass

        # Header
        header = tk.Frame(self, bg="#2c3e50", height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        if self._logo_img:
            tk.Label(header, image=self._logo_img, bg="#2c3e50").pack(side="left", padx=(12, 4))
        tk.Label(header, text="BCPER", bg="#2c3e50", fg="#ecf0f1",
                 font=("Helvetica", 16, "bold")).pack(side="left", padx=(4, 4), pady=8)
        tk.Label(header, text="Backup Manager", bg="#2c3e50", fg="#bdc3c7",
                 font=("Helvetica", 10)).pack(side="left", pady=8)

        # Window icon
        if self._logo_img:
            self.iconphoto(False, self._logo_img)

        # Daemon status banner (hidden when daemon is running)
        self._daemon_banner = tk.Frame(self, bg="#e74c3c", height=36)
        self._daemon_banner.pack(fill="x", side="top")
        self._daemon_banner.pack_propagate(False)
        tk.Label(self._daemon_banner, text="Daemon is not running — some features are unavailable",
                 bg="#e74c3c", fg="#ffffff", font=("Helvetica", 10, "bold")).pack(side="left", padx=12, pady=6)
        ttk.Button(self._daemon_banner, text="Start Daemon", command=self._start_daemon).pack(side="right", padx=12, pady=4)

        # Running jobs banner (hidden when idle)
        self._jobs_banner = tk.Frame(self, bg="#3498db", height=36)
        self._jobs_banner.pack(fill="x", side="top")
        self._jobs_banner.pack_propagate(False)
        self._jobs_label = tk.Label(self._jobs_banner, text="",
                 bg="#3498db", fg="#ffffff", font=("Helvetica", 10, "bold"))
        self._jobs_label.pack(side="left", padx=12, pady=6)
        self._jobs_banner_visible = False
        self._jobs_banner.pack_forget()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self.items_tab = ItemsTab(self.notebook, self.client)
        self.vaults_tab = VaultsTab(self.notebook, self.client)
        self.stores_tab = StoresTab(self.notebook, self.client)
        self.backups_tab = BackupsTab(self.notebook, self.client)
        self.frequencies_tab = FrequenciesTab(self.notebook, self.client)
        self.jobs_tab = JobsTab(self.notebook, self.client)
        self.status_tab = StatusTab(self.notebook, self.client)

        self.notebook.add(self.items_tab, text="  Items  ")
        self.notebook.add(self.vaults_tab, text="  Vaults  ")
        self.notebook.add(self.stores_tab, text="  Stores  ")
        self.notebook.add(self.backups_tab, text="  Backups  ")
        self.notebook.add(self.frequencies_tab, text="  Frequencies  ")
        self.notebook.add(self.jobs_tab, text="  Jobs  ")
        self.notebook.add(self.status_tab, text="  Status  ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)
        self._poll_queue()
        self._daemon_banner_visible = True  # banner is packed at startup
        self.after(200, self._check_daemon_loop)
        self.after(1000, self._check_running_jobs_loop)

    def _poll_queue(self):
        try:
            while True:
                fn = _ui_queue.get_nowait()
                fn()
        except Exception:
            pass
        self.after(100, self._poll_queue)

    def _check_daemon_loop(self):
        alive = self._daemon_alive()
        if alive and self._daemon_banner_visible:
            self._daemon_banner.pack_forget()
            self._daemon_banner_visible = False
        elif not alive and not self._daemon_banner_visible:
            self._daemon_banner.pack(fill="x", side="top", before=self.notebook)
            self._daemon_banner_visible = True
        self.after(3000, self._check_daemon_loop)

    def _daemon_alive(self):
        try:
            self.client.ping()
            return True
        except Exception:
            return False

    def _check_running_jobs_loop(self):
        try:
            resp = self.client.status()
            data = resp.get("data", {})
            running = data.get("running_jobs", [])
            if running and not self._jobs_banner_visible:
                names = []
                for jid in running:
                    # Try to resolve job name from local tabs if available
                    name = jid[:8]
                    try:
                        for j in self.jobs_tab.tree.get_children():
                            if j == jid:
                                vals = self.jobs_tab.tree.item(j, "values")
                                if vals:
                                    name = vals[0]
                                break
                    except Exception:
                        pass
                    names.append(name)
                self._jobs_label.config(text=f"⏳ Running backup(s): {', '.join(names)}")
                self._jobs_banner.pack(fill="x", side="top", before=self.notebook)
                self._jobs_banner_visible = True
            elif not running and self._jobs_banner_visible:
                self._jobs_banner.pack_forget()
                self._jobs_banner_visible = False
        except Exception:
            if self._jobs_banner_visible:
                self._jobs_banner.pack_forget()
                self._jobs_banner_visible = False
        self.after(2000, self._check_running_jobs_loop)

    def _start_daemon(self):
        pid_path = os.path.expanduser("~/.config/bcper/daemon.pid")
        # Check for stale daemon
        if os.path.exists(pid_path):
            with open(pid_path) as f:
                old_pid = f.read().strip()
            if old_pid and os.path.exists(f"/proc/{old_pid}"):
                # PID exists — try to ping it
                try:
                    self.client.ping()
                    self._hide_daemon_banner()
                    messagebox.showinfo("Daemon", f"Daemon already running (PID {old_pid}).")
                    return
                except Exception:
                    # Process exists but not responding — kill it
                    try:
                        os.kill(int(old_pid), 9)
                        time.sleep(0.5)
                    except Exception:
                        pass
            try:
                os.unlink(pid_path)
            except Exception:
                pass
        # Also clean up stale socket
        sock_path = os.path.expanduser("~/.config/bcper/daemon.sock")
        if os.path.exists(sock_path):
            try:
                os.unlink(sock_path)
            except Exception:
                pass
        # Start fresh
        subprocess.Popen([sys.executable, "-m", "bcperd"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait and verify
        for _ in range(10):
            time.sleep(0.3)
            if self._daemon_alive():
                self._hide_daemon_banner()
                return
        messagebox.showerror("Daemon", "Failed to start daemon.")

    def _hide_daemon_banner(self):
        if self._daemon_banner_visible:
            self._daemon_banner.pack_forget()
            self._daemon_banner_visible = False

    def _on_tab_change(self, event):
        tab = event.widget.nametowidget(event.widget.select())
        if hasattr(tab, "refresh"):
            tab.refresh()

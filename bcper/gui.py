import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from .client import Client

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
                err = result.get("error", "Unknown error")
                _gui_logger.warning(f"Daemon error: {err}")
                _ui_queue.put(lambda: callback(None, err))
            else:
                _ui_queue.put(lambda: callback(result, None))
        except Exception as e:
            _gui_logger.warning(f"Async exception: {e}")
            _ui_queue.put(lambda: callback(None, str(e)))
    threading.Thread(target=wrapper, daemon=True).start()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BCPER Backup Manager")
        self.geometry("960x640")
        self.client = Client()

        # Header
        header = tk.Frame(self, bg="#2c3e50", height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text=" BCPER ", bg="#2c3e50", fg="#ecf0f1",
                 font=("Helvetica", 16, "bold")).pack(side="left", padx=16, pady=8)
        tk.Label(header, text="Backup Manager", bg="#2c3e50", fg="#bdc3c7",
                 font=("Helvetica", 10)).pack(side="left", pady=8)

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
        self.after(200, self._check_daemon)

    def _poll_queue(self):
        try:
            while True:
                fn = _ui_queue.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _check_daemon(self):
        try:
            self.client.ping()
        except Exception:
            if messagebox.askyesno("Daemon", "bcperd daemon is not running. Start it now?"):
                self._start_daemon()
            else:
                messagebox.showwarning("Daemon", "Some features will not work without the daemon.")

    def _start_daemon(self):
        subprocess.Popen([sys.executable, "-m", "bcperd"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        try:
            self.client.ping()
        except Exception:
            messagebox.showerror("Daemon", "Failed to start daemon.")

    def _on_tab_change(self, event):
        tab = event.widget.nametowidget(event.widget.select())
        if hasattr(tab, "refresh"):
            tab.refresh()


# ---- Items Tab ----

class ItemsTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#ecf0f1")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="➕ Add", command=self._add).pack(side="left", padx=(8, 4), pady=6)
        ttk.Button(toolbar, text="✏️ Edit", command=self._edit).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="💾 Backup Now", command=self._backup).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("key", "paths", "enc", "ignores")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("key", text="Key")
        self.tree.heading("paths", text="Paths")
        self.tree.heading("enc", text="Encrypted")
        self.tree.heading("ignores", text="Ignores")
        self.tree.column("key", width=180)
        self.tree.column("paths", width=400)
        self.tree.column("enc", width=80, anchor="center")
        self.tree.column("ignores", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_items, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        data = resp.get("data", [])
        for item in data:
            self.tree.insert("", "end", values=(
                item["key"],
                ", ".join(item["paths"]),
                "Yes" if item.get("password") else "No",
                len(item.get("bcpignore", [])),
            ), iid=item["key"])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        ItemDialog(self, self.client, None, callback=self.refresh)

    def _edit(self):
        key = self._selected()
        if not key:
            return
        run_async(lambda: self.client.list_items(), lambda r, e: self._open_edit(r, e, key))

    def _open_edit(self, resp, err, key):
        if err:
            return
        for item in resp.get("data", []):
            if item["key"] == key:
                ItemDialog(self, self.client, item, callback=self.refresh)
                return

    def _delete(self):
        key = self._selected()
        if not key:
            return
        if messagebox.askyesno("Delete", f"Delete item '{key}'?"):
            run_async(lambda: self.client.delete_item(key), lambda r, e: self.refresh() if not e else None)

    def _backup(self):
        key = self._selected()
        if not key:
            return
        store = self._pick_store()
        if not store:
            return
        run_async(lambda: self.client.backup("item", key, store), self._on_backup_result)

    def _pick_store(self):
        resp = self.client.list_stores()
        stores = list(resp.get("data", {}).keys())
        if not stores:
            messagebox.showwarning("Store", "No stores configured.")
            return None
        if len(stores) == 1:
            return stores[0]
        # Simple dialog
        dlg = tk.Toplevel(self)
        dlg.title("Select Store")
        dlg.transient(self)
        dlg.wait_visibility()
        dlg.grab_set()
        var = tk.StringVar(value=stores[0])
        ttk.Combobox(dlg, values=stores, textvariable=var, state="readonly").pack(padx=12, pady=12)
        result = None
        def ok():
            nonlocal result
            result = var.get()
            dlg.destroy()
        tk.Button(dlg, text="OK", command=ok).pack(pady=(0, 12))
        self.wait_window(dlg)
        return result

    def _on_backup_result(self, resp, err):
        if err:
            messagebox.showerror("Backup", str(err))
        else:
            messagebox.showinfo("Backup", f"Created: {resp.get('data', {}).get('archive', 'ok')}")


class ItemDialog(tk.Toplevel):
    def __init__(self, master, client, item=None, callback=None):
        super().__init__(master)
        self.client = client
        self.item = item
        self.callback = callback
        self.title("Edit Backup Item" if item else "New Backup Item")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self.minsize(500, 400)
        self._build()
        if item:
            self.key_var.set(item["key"])
            self.key_entry.configure(state="disabled")
            for p in item["paths"]:
                self.paths_listbox.insert("end", p)
            if item.get("password"):
                self.pw_var.set(item["password"])
            self.ignore_text.insert("1.0", "\n".join(item.get("bcpignore", [])))

    def _build(self):
        tk.Label(self, text="Edit Backup Item" if self.item else "New Backup Item",
                 font=("Helvetica", 14, "bold")).pack(pady=(16, 8))

        form = tk.Frame(self)
        form.pack(fill="both", expand=True, padx=20, pady=8)

        # Key
        tk.Label(form, text="Key:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = tk.Entry(form, textvariable=self.key_var, font=("Helvetica", 10))
        self.key_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        # Paths
        paths_frame = tk.LabelFrame(form, text=" Backup Paths ", font=("Helvetica", 10, "bold"), padx=8, pady=8)
        paths_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        paths_frame.columnconfigure(0, weight=1)
        paths_frame.rowconfigure(0, weight=1)

        self.paths_listbox = tk.Listbox(paths_frame, height=6, selectmode="single", font=("Helvetica", 10))
        self.paths_listbox.grid(row=0, column=0, rowspan=3, sticky="nsew")
        sb = ttk.Scrollbar(paths_frame, orient="vertical", command=self.paths_listbox.yview)
        self.paths_listbox.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, rowspan=3, sticky="ns")

        tk.Button(paths_frame, text="Add Files...", command=self._add_files).grid(row=0, column=2, padx=(10, 0), sticky="ew")
        tk.Button(paths_frame, text="Add Folder...", command=self._add_folder).grid(row=1, column=2, padx=(10, 0), pady=6, sticky="ew")
        tk.Button(paths_frame, text="Remove", command=self._remove_path).grid(row=2, column=2, padx=(10, 0), sticky="ew")

        # Password
        tk.Label(form, text="Password (optional):", font=("Helvetica", 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.pw_var = tk.StringVar()
        tk.Entry(form, textvariable=self.pw_var, show="*", font=("Helvetica", 10)).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        # bcpignore
        tk.Label(form, text="bcpignore:", font=("Helvetica", 10, "bold")).grid(row=3, column=0, sticky="nw", pady=4)
        self.ignore_text = tk.Text(form, width=40, height=4, font=("Helvetica", 10))
        self.ignore_text.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)
        tk.Label(form, text="One pattern per line.  E.g.  *.log   temp/   !keep.txt",
                 fg="#666", font=("Helvetica", 9)).grid(row=4, column=1, sticky="w", padx=(8, 0))

        form.columnconfigure(1, weight=1)

        # Buttons
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=(0, 16), padx=20)
        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

    def _add_files(self):
        files = filedialog.askopenfilenames(parent=self, title="Select files to backup")
        for f in files:
            self.paths_listbox.insert("end", f)

    def _add_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Select folder to backup")
        if folder:
            self.paths_listbox.insert("end", folder)

    def _remove_path(self):
        sel = self.paths_listbox.curselection()
        if sel:
            self.paths_listbox.delete(sel[0])

    def _save(self):
        key = self.key_var.get().strip()
        paths = list(self.paths_listbox.get(0, "end"))
        pw = self.pw_var.get().strip() or None
        ignores = [p.strip() for p in self.ignore_text.get("1.0", "end").splitlines() if p.strip()]
        data = {"paths": paths, "password": pw, "bcpignore": ignores}
        if self.item:
            run_async(lambda: self.client.update_item(key, **data), self._on_save)
        else:
            run_async(lambda: self.client.add_item(key=key, **data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()


# ---- Vaults Tab ----

class VaultsTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#ecf0f1")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="➕ Add", command=self._add).pack(side="left", padx=(8, 4), pady=6)
        ttk.Button(toolbar, text="✏️ Edit", command=self._edit).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="💾 Backup Now", command=self._backup).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("name", "items", "enc", "ignores")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("items", text="Items")
        self.tree.heading("enc", text="Encrypted")
        self.tree.heading("ignores", text="Ignores")
        self.tree.column("name", width=180)
        self.tree.column("items", width=400)
        self.tree.column("enc", width=80, anchor="center")
        self.tree.column("ignores", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_vaults, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        for v in resp.get("data", []):
            self.tree.insert("", "end", values=(
                v["name"],
                ", ".join(v["item_keys"]),
                "Yes" if v.get("password") else "No",
                len(v.get("bcpignore", [])),
            ), iid=v["name"])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        VaultDialog(self, self.client, None, callback=self.refresh)

    def _edit(self):
        name = self._selected()
        if not name:
            return
        run_async(lambda: self.client.list_vaults(), lambda r, e: self._open_edit(r, e, name))

    def _open_edit(self, resp, err, name):
        if err:
            return
        for v in resp.get("data", []):
            if v["name"] == name:
                VaultDialog(self, self.client, v, callback=self.refresh)
                return

    def _delete(self):
        name = self._selected()
        if not name:
            return
        if messagebox.askyesno("Delete", f"Delete vault '{name}'?"):
            run_async(lambda: self.client.delete_vault(name), lambda r, e: self.refresh() if not e else None)

    def _backup(self):
        name = self._selected()
        if not name:
            return
        store = self._pick_store()
        if not store:
            return
        run_async(lambda: self.client.backup("vault", name, store), self._on_backup)

    def _on_backup(self, resp, err):
        if err:
            messagebox.showerror("Backup", str(err))
        else:
            messagebox.showinfo("Backup", f"Created: {resp.get('data', {}).get('archive', 'ok')}")

    def _pick_store(self):
        resp = self.client.list_stores()
        stores = list(resp.get("data", {}).keys())
        if not stores:
            messagebox.showwarning("Store", "No stores configured.")
            return None
        if len(stores) == 1:
            return stores[0]
        dlg = tk.Toplevel(self)
        dlg.title("Select Store")
        dlg.transient(self)
        dlg.wait_visibility()
        dlg.grab_set()
        var = tk.StringVar(value=stores[0])
        ttk.Combobox(dlg, values=stores, textvariable=var, state="readonly").pack(padx=12, pady=12)
        result = None
        def ok():
            nonlocal result
            result = var.get()
            dlg.destroy()
        tk.Button(dlg, text="OK", command=ok).pack(pady=(0, 12))
        self.wait_window(dlg)
        return result


class VaultDialog(tk.Toplevel):
    def __init__(self, master, client, vault=None, callback=None):
        super().__init__(master)
        self.client = client
        self.vault = vault
        self.callback = callback
        self.title("Edit Vault" if vault else "New Vault")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self.minsize(520, 480)
        self._build()
        if vault:
            self.name_var.set(vault["name"])
            self.name_entry.configure(state="disabled")
            if vault.get("password"):
                self.pw_var.set(vault["password"])
            self.ignore_text.insert("1.0", "\n".join(vault.get("bcpignore", [])))
        self._load_items()

    def _build(self):
        tk.Label(self, text="Edit Vault" if self.vault else "New Vault",
                 font=("Helvetica", 14, "bold")).pack(pady=(16, 8))

        form = tk.Frame(self)
        form.pack(fill="both", expand=True, padx=20, pady=8)

        # Name
        tk.Label(form, text="Name:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar()
        self.name_entry = tk.Entry(form, textvariable=self.name_var, font=("Helvetica", 10))
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

        # Items dual listbox
        items_frame = tk.LabelFrame(form, text=" Vault Items ", font=("Helvetica", 10, "bold"), padx=8, pady=8)
        items_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        items_frame.columnconfigure(0, weight=1)
        items_frame.columnconfigure(2, weight=1)
        items_frame.rowconfigure(1, weight=1)

        tk.Label(items_frame, text="Available", font=("Helvetica", 10, "bold"), fg="#555").grid(row=0, column=0, sticky="w")
        self.available_list = tk.Listbox(items_frame, height=8, selectmode="extended", font=("Helvetica", 10))
        self.available_list.grid(row=1, column=0, sticky="nsew")
        sb1 = ttk.Scrollbar(items_frame, orient="vertical", command=self.available_list.yview)
        self.available_list.configure(yscrollcommand=sb1.set)
        sb1.grid(row=1, column=1, sticky="ns")

        btn_col = tk.Frame(items_frame)
        btn_col.grid(row=1, column=2, padx=8)
        tk.Button(btn_col, text=">", width=4, command=self._add_items).pack(pady=3)
        tk.Button(btn_col, text=">>", width=4, command=self._add_all).pack(pady=3)
        tk.Button(btn_col, text="<", width=4, command=self._remove_items).pack(pady=3)
        tk.Button(btn_col, text="<<", width=4, command=self._remove_all).pack(pady=3)

        tk.Label(items_frame, text="In Vault", font=("Helvetica", 10, "bold"), fg="#555").grid(row=0, column=3, sticky="w")
        self.vault_list = tk.Listbox(items_frame, height=8, selectmode="extended", font=("Helvetica", 10))
        self.vault_list.grid(row=1, column=3, sticky="nsew")
        sb2 = ttk.Scrollbar(items_frame, orient="vertical", command=self.vault_list.yview)
        self.vault_list.configure(yscrollcommand=sb2.set)
        sb2.grid(row=1, column=4, sticky="ns")

        # Password
        tk.Label(form, text="Password (optional):", font=("Helvetica", 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.pw_var = tk.StringVar()
        tk.Entry(form, textvariable=self.pw_var, show="*", font=("Helvetica", 10)).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        # bcpignore
        tk.Label(form, text="bcpignore:", font=("Helvetica", 10, "bold")).grid(row=3, column=0, sticky="nw", pady=4)
        self.ignore_text = tk.Text(form, width=40, height=4, font=("Helvetica", 10))
        self.ignore_text.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)
        tk.Label(form, text="One pattern per line.  E.g.  *.log   temp/   !keep.txt",
                 fg="#666", font=("Helvetica", 9)).grid(row=4, column=1, sticky="w", padx=(8, 0))

        form.columnconfigure(1, weight=1)

        # Buttons
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=(0, 16), padx=20)
        tk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        tk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

    def _load_items(self):
        run_async(self.client.list_items, self._on_items)

    def _on_items(self, resp, err):
        if err:
            return
        all_keys = {item["key"] for item in resp.get("data", [])}
        vault_keys = set(self.vault.get("item_keys", [])) if self.vault else set()

        for key in sorted(all_keys - vault_keys):
            self.available_list.insert("end", key)
        for key in sorted(vault_keys):
            self.vault_list.insert("end", key)

    def _add_items(self):
        for idx in reversed(self.available_list.curselection()):
            self.vault_list.insert("end", self.available_list.get(idx))
            self.available_list.delete(idx)
        self._sort_list(self.vault_list)

    def _add_all(self):
        for i in range(self.available_list.size()):
            self.vault_list.insert("end", self.available_list.get(i))
        self.available_list.delete(0, "end")
        self._sort_list(self.vault_list)

    def _remove_items(self):
        for idx in reversed(self.vault_list.curselection()):
            self.available_list.insert("end", self.vault_list.get(idx))
            self.vault_list.delete(idx)
        self._sort_list(self.available_list)

    def _remove_all(self):
        for i in range(self.vault_list.size()):
            self.available_list.insert("end", self.vault_list.get(i))
        self.vault_list.delete(0, "end")
        self._sort_list(self.available_list)

    @staticmethod
    def _sort_list(lb: tk.Listbox):
        items = sorted(lb.get(0, "end"))
        lb.delete(0, "end")
        for item in items:
            lb.insert("end", item)

    def _save(self):
        name = self.name_var.get().strip()
        keys = list(self.vault_list.get(0, "end"))
        pw = self.pw_var.get().strip() or None
        ignores = [p.strip() for p in self.ignore_text.get("1.0", "end").splitlines() if p.strip()]
        data = {"item_keys": keys, "password": pw, "bcpignore": ignores}
        if self.vault:
            run_async(lambda: self.client.update_vault(name, **data), self._on_save)
        else:
            run_async(lambda: self.client.add_vault(name=name, **data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()


# ---- Stores Tab ----

class StoresTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#ecf0f1")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="📁 Local", command=self._add_local).pack(side="left", padx=(8, 4), pady=6)
        ttk.Button(toolbar, text="☁️ Rclone", command=self._add_rclone).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="📂 GDrive", command=self._add_gdrive).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("name", "type", "detail")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("detail", text="Detail")
        self.tree.column("name", width=180)
        self.tree.column("type", width=100)
        self.tree.column("detail", width=500)
        self.tree.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_stores, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        for name, cfg in resp.get("data", {}).items():
            detail = cfg.get("path", "")
            if cfg.get("type") == "rclone":
                detail = f"{cfg.get('remote', '')}:{detail}"
            self.tree.insert("", "end", values=(name, cfg.get("type", "local"), detail), iid=name)

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add_local(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Local Store")
        dlg.transient(self)
        dlg.wait_visibility()
        dlg.grab_set()
        tk.Label(dlg, text="Name:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        name_var = tk.StringVar()
        tk.Entry(dlg, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        tk.Label(dlg, text="Path:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        path_var = tk.StringVar(value="~/backups")
        path_entry = tk.Entry(dlg, textvariable=path_var)
        path_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        tk.Button(dlg, text="Browse...", command=lambda: path_var.set(filedialog.askdirectory(parent=dlg, title="Select backup folder") or path_var.get())).grid(row=1, column=2, padx=(4, 8), pady=4)
        def save():
            run_async(lambda: self.client.add_store(name=name_var.get(), type="local", path=path_var.get()),
                      lambda r, e: (dlg.destroy(), self.refresh()) if not e else messagebox.showerror("Error", str(e), parent=dlg))
        tk.Button(dlg, text="Save", command=save).grid(row=2, column=1, sticky="e", padx=8, pady=8)
        dlg.columnconfigure(1, weight=1)

    def _add_rclone(self):
        dlg = tk.Toplevel(self)
        dlg.title("Add Rclone Store")
        dlg.transient(self)
        dlg.wait_visibility()
        dlg.grab_set()
        tk.Label(dlg, text="Name:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        name_var = tk.StringVar()
        tk.Entry(dlg, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)
        tk.Label(dlg, text="Remote:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        remote_var = tk.StringVar()
        tk.Entry(dlg, textvariable=remote_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        tk.Label(dlg, text="Path:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        path_var = tk.StringVar()
        tk.Entry(dlg, textvariable=path_var).grid(row=2, column=1, sticky="ew", padx=8, pady=4)
        def save():
            run_async(lambda: self.client.add_store(name=name_var.get(), type="rclone", remote=remote_var.get(), path=path_var.get()),
                      lambda r, e: (dlg.destroy(), self.refresh()) if not e else messagebox.showerror("Error", str(e), parent=dlg))
        tk.Button(dlg, text="Save", command=save).grid(row=3, column=1, sticky="e", padx=8, pady=8)
        dlg.columnconfigure(1, weight=1)

    def _add_gdrive(self):
        try:
            from bcper_core.storage import list_rclone_remotes
            remotes = list_rclone_remotes()
        except Exception as e:
            messagebox.showerror("rclone", f"rclone error: {e}\n\nInstall rclone and run:\n  rclone config", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("Add Google Drive Store")
        dlg.transient(self)
        dlg.wait_visibility()
        dlg.grab_set()

        tk.Label(dlg, text="Name:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        name_var = tk.StringVar(value="gdrive")
        tk.Entry(dlg, textvariable=name_var).grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        tk.Label(dlg, text="Remote:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        remote_var = tk.StringVar(value="gdrive")
        if remotes:
            ttk.Combobox(dlg, values=remotes, textvariable=remote_var, state="readonly").grid(row=1, column=1, sticky="ew", padx=8, pady=4)
        else:
            tk.Entry(dlg, textvariable=remote_var).grid(row=1, column=1, sticky="ew", padx=8, pady=4)
            tk.Label(dlg, text="No remotes found. Run 'rclone config' first.", fg="red").grid(row=2, column=0, columnspan=2, padx=8)

        tk.Label(dlg, text="Path (optional):").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        path_var = tk.StringVar(value="Backups")
        tk.Entry(dlg, textvariable=path_var).grid(row=3, column=1, sticky="ew", padx=8, pady=4)

        def save():
            run_async(
                lambda: self.client.add_store(name=name_var.get(), type="rclone", remote=remote_var.get(), path=path_var.get()),
                lambda r, e: (dlg.destroy(), self.refresh()) if not e else messagebox.showerror("Error", str(e), parent=dlg),
            )
        tk.Button(dlg, text="Save", command=save).grid(row=4, column=1, sticky="e", padx=8, pady=8)
        dlg.columnconfigure(1, weight=1)

    def _delete(self):
        name = self._selected()
        if not name:
            return
        if messagebox.askyesno("Delete", f"Delete store '{name}'?"):
            run_async(lambda: self.client.delete_store(name), lambda r, e: self.refresh() if not e else None)


# ---- Backups Tab ----

class BackupsTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        top = tk.Frame(self, bg="#ecf0f1")
        top.pack(fill="x", pady=(0, 8))
        tk.Label(top, text="Store:", bg="#ecf0f1", font=("Helvetica", 10, "bold")).pack(side="left", padx=(8, 4), pady=6)
        self.store_var = tk.StringVar()
        self.store_combo = ttk.Combobox(top, textvariable=self.store_var, state="readonly", width=30)
        self.store_combo.pack(side="left", padx=(0, 8), pady=6)
        self.store_combo.bind("<<ComboboxSelected>>", lambda e: self._load_backups())
        ttk.Button(top, text="🔄 Refresh", command=self._load_backups).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(top, text="📥 Restore", command=self._restore).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(top, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("archive",)
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("archive", text="Archive")
        self.tree.column("archive", width=800)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._restore())

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        run_async(self.client.list_stores, self._on_stores)

    def _on_stores(self, resp, err):
        if err:
            return
        names = list(resp.get("data", {}).keys())
        self.store_combo["values"] = names
        if names and not self.store_var.get():
            self.store_var.set(names[0])
            self._load_backups()

    def _load_backups(self):
        store = self.store_var.get()
        if not store:
            return
        self.tree.delete(*self.tree.get_children())
        run_async(lambda: self.client.list_backups(store), self._on_backups)

    def _on_backups(self, resp, err):
        if err:
            return
        for name in resp.get("data", []):
            self.tree.insert("", "end", values=(name,), iid=name)

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _restore(self):
        archive = self._selected()
        if not archive:
            return
        store = self.store_var.get()
        target = filedialog.askdirectory(title="Restore to directory")
        if not target:
            return
        password = None
        if archive.endswith(".enc"):
            pw = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
            if pw is None:
                return
            password = pw
        run_async(lambda: self.client.restore(archive, store, password=password, target_dir=target), self._on_restore)

    def _on_restore(self, resp, err):
        if err:
            messagebox.showerror("Restore", str(err))
        else:
            data = resp.get("data", {})
            msg = f"Restored to: {data.get('target_dir')}"
            if data.get("warnings"):
                msg += "\nWarnings:\n" + "\n".join(data["warnings"])
            messagebox.showinfo("Restore", msg)

    def _delete(self):
        archive = self._selected()
        if not archive:
            return
        store = self.store_var.get()
        if messagebox.askyesno("Delete", f"Delete '{archive}' from store '{store}'?"):
            run_async(lambda: self.client.delete_backup(archive, store), lambda r, e: self._load_backups() if not e else None)


# ---- Frequencies Tab ----

class FrequenciesTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#ecf0f1")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="➕ Add", command=self._add).pack(side="left", padx=(8, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("id", "name", "type", "interval")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("interval", text="Interval")
        self.tree.column("id", width=100)
        self.tree.column("name", width=200)
        self.tree.column("type", width=100)
        self.tree.column("interval", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True)

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_frequencies, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        for f in resp.get("data", []):
            self.tree.insert("", "end", values=(
                f["id"], f["name"], f["period_type"], f["interval"]
            ), iid=f["id"])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        FrequencyDialog(self, self.client, callback=self.refresh)

    def _delete(self):
        fid = self._selected()
        if not fid:
            return
        if messagebox.askyesno("Delete", f"Delete frequency '{fid}'?\n\nJobs using this frequency will also be removed."):
            run_async(lambda: self.client.delete_frequency(fid), lambda r, e: self.refresh() if not e else None)


class FrequencyDialog(tk.Toplevel):
    def __init__(self, master, client, callback=None):
        super().__init__(master)
        self.client = client
        self.callback = callback
        self.title("Add Frequency")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self._build()
        tk.Button(self, text="Save", command=self._save).pack(pady=12)

    def _build(self):
        f = tk.Frame(self)
        f.pack(padx=12, pady=12, fill="both", expand=True)

        tk.Label(f, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        tk.Entry(f, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        tk.Label(f, text="Type:").grid(row=1, column=0, sticky="w")
        self.type_var = tk.StringVar(value="once")
        ttk.Combobox(f, values=["once", "hourly", "daily"], textvariable=self.type_var, state="readonly").grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)

        tk.Label(f, text="Interval:").grid(row=2, column=0, sticky="w")
        self.interval_var = tk.StringVar(value="1")
        tk.Spinbox(f, from_=1, to=365, textvariable=self.interval_var).grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)

        f.columnconfigure(1, weight=1)

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return s or "freq"

    def _save(self):
        name = self.name_var.get().strip()
        data = {
            "id": self._slugify(name),
            "name": name,
            "period_type": self.type_var.get(),
            "interval": int(self.interval_var.get()),
        }
        run_async(lambda: self.client.add_frequency(**data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()


# ---- Jobs Tab ----

class JobsTab(tk.Frame):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        toolbar = tk.Frame(self, bg="#ecf0f1")
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="➕ Add", command=self._add).pack(side="left", padx=(8, 4), pady=6)
        ttk.Button(toolbar, text="⏯ Toggle", command=self._toggle).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("name", "target", "store", "freq", "next", "enabled")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("target", text="Target")
        self.tree.heading("store", text="Store")
        self.tree.heading("freq", text="Frequency")
        self.tree.heading("next", text="Next Run")
        self.tree.heading("enabled", text="Enabled")
        self.tree.column("name", width=120)
        self.tree.column("target", width=160)
        self.tree.column("store", width=100)
        self.tree.column("freq", width=100)
        self.tree.column("next", width=140)
        self.tree.column("enabled", width=70, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._toggle())

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_jobs, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        for j in resp.get("data", []):
            self.tree.insert("", "end", values=(
                j.get("name", j["id"]),
                f"{j['target_type']}:{j['target_name']}",
                j["store_name"],
                j.get("frequency_id", ""),
                j.get("next_run", "")[:19].replace("T", " "),
                "Yes" if j.get("enabled") else "No",
            ), iid=j["id"])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        JobDialog(self, self.client, callback=self.refresh)

    def _toggle(self):
        jid = self._selected()
        if not jid:
            return
        run_async(lambda: self.client.toggle_job(jid), lambda r, e: self.refresh() if not e else None)

    def _delete(self):
        jid = self._selected()
        if not jid:
            return
        if messagebox.askyesno("Delete", f"Delete job '{jid}'?"):
            run_async(lambda: self.client.delete_job(jid), lambda r, e: self.refresh() if not e else None)


class JobDialog(tk.Toplevel):
    def __init__(self, master, client, callback=None):
        super().__init__(master)
        self.client = client
        self.callback = callback
        self.title("Add Job")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self._build()
        self._load_data()
        tk.Button(self, text="Save", command=self._save).pack(pady=12)

    def _build(self):
        f = tk.Frame(self)
        f.pack(padx=12, pady=12, fill="both", expand=True)

        tk.Label(f, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        tk.Entry(f, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=(6, 0), pady=2)

        tk.Label(f, text="Target Type:").grid(row=1, column=0, sticky="w")
        self.type_var = tk.StringVar(value="item")
        ttk.Combobox(f, values=["item", "vault"], textvariable=self.type_var, state="readonly").grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)
        self.type_var.trace_add("write", lambda *a: self._update_targets())

        tk.Label(f, text="Target:").grid(row=2, column=0, sticky="w")
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(f, textvariable=self.target_var, state="readonly")
        self.target_combo.grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=2)

        tk.Label(f, text="Store:").grid(row=3, column=0, sticky="w")
        self.store_var = tk.StringVar()
        self.store_combo = ttk.Combobox(f, textvariable=self.store_var, state="readonly")
        self.store_combo.grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=2)

        tk.Label(f, text="Frequency:").grid(row=4, column=0, sticky="w")
        self.freq_var = tk.StringVar()
        self.freq_combo = ttk.Combobox(f, textvariable=self.freq_var, state="readonly")
        self.freq_combo.grid(row=4, column=1, sticky="ew", padx=(6, 0), pady=2)

        f.columnconfigure(1, weight=1)

    def _load_data(self):
        run_async(self.client.list_stores, self._on_stores)
        run_async(self.client.list_frequencies, self._on_frequencies)
        self._update_targets()

    def _on_stores(self, resp, err):
        if err:
            return
        names = list(resp.get("data", {}).keys())
        self.store_combo["values"] = names
        if names:
            self.store_var.set(names[0])

    def _on_frequencies(self, resp, err):
        if err:
            return
        freqs = resp.get("data", [])
        self.freq_combo["values"] = [f["id"] for f in freqs]
        if freqs:
            self.freq_var.set(freqs[0]["id"])

    def _update_targets(self):
        if self.type_var.get() == "item":
            run_async(self.client.list_items, self._on_targets)
        else:
            run_async(self.client.list_vaults, self._on_targets)

    def _on_targets(self, resp, err):
        if err:
            return
        names = [x["key"] if "key" in x else x["name"] for x in resp.get("data", [])]
        self.target_combo["values"] = names
        if names and not self.target_var.get():
            self.target_var.set(names[0])

    def _save(self):
        data = {
            "name": self.name_var.get().strip(),
            "target_type": self.type_var.get(),
            "target_name": self.target_var.get(),
            "store_name": self.store_var.get(),
            "frequency_id": self.freq_var.get(),
        }
        run_async(lambda: self.client.add_job(**data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()


# ---- Status Tab ----

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
        subprocess.Popen([sys.executable, "-m", "bcperd"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1)
        self.refresh()

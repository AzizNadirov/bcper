import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .common import run_async


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

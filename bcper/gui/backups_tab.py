import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

from .common import run_async


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
        ttk.Button(top, text="Refresh", command=self._load_backups).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(top, text="Restore", command=self._restore).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(top, text="Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        self.status_label = tk.Label(self, text="", fg="#555555", font=("Helvetica", 9, "italic"))
        self.status_label.pack(anchor="w", padx=8)

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
        self.status_label.config(text=f"Loading backups from '{store}'...")
        run_async(lambda: self.client.list_backups(store), self._on_backups)

    def _on_backups(self, resp, err):
        if err:
            self.status_label.config(text=f"Error: {err}")
            return
        self.status_label.config(text="")
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
        self._restore_ctx = {"archive": archive, "store": store, "target": target}
        self._prompt_and_restore()

    def _prompt_and_restore(self, password=None):
        ctx = self._restore_ctx
        archive = ctx["archive"]
        store = ctx["store"]
        target = ctx["target"]
        if archive.endswith(".enc") and password is None:
            pw = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
            if pw is None:
                return
            password = pw
        run_async(
            lambda path: self.client.restore(archive, store, password=password, target_dir=target, progress_file=path),
            self._on_restore,
            master=self,
            progress_text="Restoring...",
        )

    def _on_restore(self, resp, err):
        if err:
            if "Incorrect password" in str(err):
                self._prompt_and_restore(password=None)
            else:
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
            run_async(lambda _: self.client.delete_backup(archive, store), lambda r, e: self._load_backups() if not e else None, master=self, progress_text="Deleting...")

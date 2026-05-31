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

        cols = ("run_id", "job", "target", "started", "status", "encrypted")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("run_id", text="Run ID")
        self.tree.heading("job", text="Job")
        self.tree.heading("target", text="Target")
        self.tree.heading("started", text="Started")
        self.tree.heading("status", text="Status")
        self.tree.heading("encrypted", text="Encrypted")
        self.tree.column("run_id", width=100)
        self.tree.column("job", width=120)
        self.tree.column("target", width=120)
        self.tree.column("started", width=160)
        self.tree.column("status", width=80)
        self.tree.column("encrypted", width=80)
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
        for run in resp.get("data", []):
            rid = run.get("id", "")
            short_id = rid[:8] if len(rid) >= 8 else rid
            self.tree.insert(
                "", "end",
                values=(
                    short_id,
                    run.get("job_name", ""),
                    run.get("target_name", ""),
                    run.get("started_at", ""),
                    run.get("status", ""),
                    "Yes" if run.get("encrypted") else "No",
                ),
                iid=rid,
            )

    def _selected(self):
        return list(self.tree.selection())

    def _restore(self):
        run_ids = self._selected()
        if not run_ids:
            return
        store = self.store_var.get()
        target = filedialog.askdirectory(title="Restore to directory")
        if not target:
            return
        encrypted = False
        for run_id in run_ids:
            try:
                vals = self.tree.item(run_id, "values")
                if vals[5] == "Yes":
                    encrypted = True
                    break
            except Exception:
                pass
        self._restore_ctx = {"run_ids": run_ids, "store": store, "target": target, "encrypted": encrypted}
        self._prompt_and_restore()

    def _prompt_and_restore(self, password=None):
        ctx = self._restore_ctx
        run_ids = ctx["run_ids"]
        store = ctx["store"]
        target = ctx["target"]
        encrypted = ctx["encrypted"]
        if encrypted and password is None:
            pw = simpledialog.askstring("Password", "Enter password:", show="*", parent=self)
            if pw is None:
                return
            password = pw
        run_async(
            lambda path: self.client.restore_many(run_ids, store, password=password, target_dir=target, progress_file=path),
            self._on_restore,
            master=self,
            progress_text=f"Restoring {len(run_ids)} backup(s)...",
        )

    def _on_restore(self, resp, err):
        if err:
            if "Incorrect password" in str(err):
                self._prompt_and_restore(password=None)
            else:
                messagebox.showerror("Restore", str(err))
        else:
            data = resp.get("data", {})
            restored = data.get("restored", [])
            errors = data.get("errors", [])
            msg_parts = [f"Restored {len(restored)} backup(s) to: {data.get('target_dir')}"]
            if errors:
                msg_parts.append("Errors:\n" + "\n".join(errors))
            warnings = data.get("warnings", [])
            if warnings:
                msg_parts.append("Warnings:\n" + "\n".join(warnings))
            messagebox.showinfo("Restore", "\n\n".join(msg_parts))

    def _delete(self):
        run_ids = self._selected()
        if not run_ids:
            return
        store = self.store_var.get()
        short_ids = [rid[:8] for rid in run_ids]
        names = ", ".join(short_ids)
        if messagebox.askyesno("Delete", f"Delete {len(run_ids)} backup(s) from store '{store}'?\n{names}"):
            run_async(
                lambda _: self.client.delete_backups(run_ids, store),
                self._on_delete,
                master=self,
                progress_text=f"Deleting {len(run_ids)} backup(s)...",
            )

    def _on_delete(self, resp, err):
        if err:
            messagebox.showerror("Delete", str(err))
        else:
            data = resp.get("data", {})
            deleted = data.get("deleted", 0)
            errors = data.get("errors", [])
            msg = f"Deleted {deleted} backup(s)."
            if errors:
                msg += "\nErrors:\n" + "\n".join(errors)
                messagebox.showwarning("Delete", msg)
            else:
                messagebox.showinfo("Delete", msg)
        self._load_backups()

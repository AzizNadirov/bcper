import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from .common import run_async


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

        tk.Label(form, text="Key:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = tk.Entry(form, textvariable=self.key_var, font=("Helvetica", 10))
        self.key_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

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

        tk.Label(form, text="Password (optional):", font=("Helvetica", 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.pw_var = tk.StringVar()
        tk.Entry(form, textvariable=self.pw_var, show="*", font=("Helvetica", 10)).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=4)

        tk.Label(form, text="bcpignore:", font=("Helvetica", 10, "bold")).grid(row=3, column=0, sticky="nw", pady=4)
        self.ignore_text = tk.Text(form, width=40, height=4, font=("Helvetica", 10))
        self.ignore_text.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=4)
        tk.Label(form, text="One pattern per line.  E.g.  *.log   temp/   !keep.txt",
                 fg="#666", font=("Helvetica", 9)).grid(row=4, column=1, sticky="w", padx=(8, 0))

        form.columnconfigure(1, weight=1)

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

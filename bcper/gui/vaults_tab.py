import tkinter as tk
from tkinter import ttk, messagebox

from .common import run_async


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
        ttk.Button(toolbar, text="Edit", command=self._edit).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="💾 Backup Now", command=self._backup).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
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
        run_async(lambda path: self.client.backup("vault", name, store, progress_file=path), self._on_backup, master=self, progress_text="Running backup...")

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

        tk.Label(form, text="Name:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.name_var = tk.StringVar()
        self.name_entry = tk.Entry(form, textvariable=self.name_var, font=("Helvetica", 10))
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)

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

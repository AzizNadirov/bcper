import tkinter as tk
from tkinter import ttk, messagebox

from .common import run_async, _gui_logger


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
        ttk.Button(toolbar, text="✏️ Edit", command=self._edit).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="▶ Run", command=self._run).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="⏯ Toggle", command=self._toggle).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🗑 Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="🔄 Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("name", "target", "store", "freq", "keep", "next", "enabled")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("name", text="Name")
        self.tree.heading("target", text="Target")
        self.tree.heading("store", text="Store")
        self.tree.heading("freq", text="Frequency")
        self.tree.heading("keep", text="Keep")
        self.tree.heading("next", text="Next Run")
        self.tree.heading("enabled", text="Enabled")
        self.tree.column("name", width=120)
        self.tree.column("target", width=140)
        self.tree.column("store", width=90)
        self.tree.column("freq", width=90)
        self.tree.column("keep", width=50, anchor="center")
        self.tree.column("next", width=130)
        self.tree.column("enabled", width=60, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit())

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
                j.get("keep_last", 3),
                j.get("next_run", "")[:19].replace("T", " "),
                "Yes" if j.get("enabled") else "No",
            ), iid=j["id"])

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        JobDialog(self, self.client, callback=self.refresh)

    def _edit(self):
        jid = self._selected()
        if not jid:
            return
        run_async(lambda: self.client.list_jobs(), lambda r, e: self._open_edit(r, e, jid))

    def _open_edit(self, resp, err, jid):
        if err:
            return
        for j in resp.get("data", []):
            if j["id"] == jid:
                JobDialog(self, self.client, job=j, callback=self.refresh)
                return

    def _run(self):
        jid = self._selected()
        _gui_logger.info(f"GUI JobsTab _run clicked job_id={jid}")
        if not jid:
            _gui_logger.warning("GUI JobsTab _run: no job selected")
            return
        _gui_logger.info(f"GUI JobsTab _run: calling client.run_job({jid})")
        run_async(lambda path: self.client.run_job(jid, progress_file=path), self._on_run, master=self, progress_text="Running job...")

    def _on_run(self, resp, err):
        _gui_logger.info(f"GUI JobsTab _on_run resp_type={type(resp)} err={err}")
        if err:
            _gui_logger.error(f"GUI JobsTab _on_run error: {err}")
            messagebox.showerror("Run Job", str(err))
        else:
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            archive = data.get('archive', 'ok') if isinstance(data, dict) else str(data)
            _gui_logger.info(f"GUI JobsTab _on_run success: archive={archive}")
            messagebox.showinfo("Run Job", f"Backup created: {archive}")
        self.refresh()

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
    def __init__(self, master, client, job=None, callback=None):
        super().__init__(master)
        self.client = client
        self.job = job
        self.callback = callback
        self.title("Edit Job" if job else "Add Job")
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
        self.type_combo = ttk.Combobox(f, values=["item", "vault"], textvariable=self.type_var, state="readonly")
        self.type_combo.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=2)
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

        tk.Label(f, text="Keep last:").grid(row=5, column=0, sticky="w")
        self.keep_var = tk.StringVar(value="3")
        tk.Spinbox(f, from_=1, to=50, textvariable=self.keep_var, width=8).grid(row=5, column=1, sticky="w", padx=(6, 0), pady=2)

        f.columnconfigure(1, weight=1)

    def _load_data(self):
        run_async(self.client.list_stores, self._on_stores)
        run_async(self.client.list_frequencies, self._on_frequencies)
        self._update_targets()
        if self.job:
            self.name_var.set(self.job.get("name", ""))
            self.type_var.set(self.job.get("target_type", "item"))
            self.target_var.set(self.job.get("target_name", ""))
            self.store_var.set(self.job.get("store_name", ""))
            self.freq_var.set(self.job.get("frequency_id", ""))
            self.keep_var.set(str(self.job.get("keep_last", 3)))

    def _on_stores(self, resp, err):
        if err:
            return
        names = list(resp.get("data", {}).keys())
        self.store_combo["values"] = names
        if names and not self.store_var.get():
            self.store_var.set(names[0])

    def _on_frequencies(self, resp, err):
        if err:
            return
        freqs = resp.get("data", []) if isinstance(resp, dict) else []
        ids = [f.get("id", "?") for f in freqs if isinstance(f, dict)]
        self.freq_combo["values"] = ids
        if ids and not self.freq_var.get():
            self.freq_var.set(ids[0])

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
            "keep_last": int(self.keep_var.get() or 3),
        }
        if self.job:
            run_async(lambda: self.client.update_job(self.job["id"], **data), self._on_save)
        else:
            run_async(lambda: self.client.add_job(**data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()

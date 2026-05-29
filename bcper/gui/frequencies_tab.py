import tkinter as tk
from tkinter import ttk, messagebox

from .common import run_async


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
        ttk.Button(toolbar, text="Edit", command=self._edit).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="Delete", command=self._delete).pack(side="left", padx=(0, 4), pady=6)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side="right", padx=(8, 0), pady=6)
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(0, 4))

        cols = ("id", "name", "type", "interval", "time")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("type", text="Type")
        self.tree.heading("interval", text="Interval")
        self.tree.heading("time", text="Time")
        self.tree.column("id", width=100)
        self.tree.column("name", width=160)
        self.tree.column("type", width=80)
        self.tree.column("interval", width=60, anchor="center")
        self.tree.column("time", width=70, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit())

        sb = ttk.Scrollbar(self.tree, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        run_async(self.client.list_frequencies, self._on_refresh)

    def _on_refresh(self, resp, err):
        if err:
            return
        for f in resp.get("data", []) if isinstance(resp, dict) else []:
            if not isinstance(f, dict):
                continue
            self.tree.insert("", "end", values=(
                f.get("id", "?"), f.get("name", "?"), f.get("period_type", "?"), f.get("interval", "?"), f.get("time", "")
            ), iid=f.get("id", "?"))

    def _selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _add(self):
        FrequencyDialog(self, self.client, callback=self.refresh)

    def _edit(self):
        fid = self._selected()
        if not fid:
            return
        run_async(lambda: self.client.list_frequencies(), lambda r, e: self._open_edit(r, e, fid))

    def _open_edit(self, resp, err, fid):
        if err:
            return
        for f in resp.get("data", []):
            if f.get("id") == fid:
                FrequencyDialog(self, self.client, freq=f, callback=self.refresh)
                return

    def _delete(self):
        fid = self._selected()
        if not fid:
            return
        if messagebox.askyesno("Delete", f"Delete frequency '{fid}'?\n\nJobs using this frequency will also be removed."):
            run_async(lambda: self.client.delete_frequency(fid), lambda r, e: self.refresh() if not e else None)


class FrequencyDialog(tk.Toplevel):
    def __init__(self, master, client, freq=None, callback=None):
        super().__init__(master)
        self.client = client
        self.freq = freq
        self.callback = callback
        self.title("Edit Frequency" if freq else "Add Frequency")
        self.transient(master)
        self.wait_visibility()
        self.grab_set()
        self._build()
        if freq:
            self.name_var.set(freq.get("name", ""))
            self.type_var.set(freq.get("period_type", "once"))
            self.interval_var.set(str(freq.get("interval", 1)))
            self.time_var.set(freq.get("time", ""))
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

        tk.Label(f, text="Time (HH:MM):").grid(row=3, column=0, sticky="w")
        self.time_var = tk.StringVar(value="")
        tk.Entry(f, textvariable=self.time_var).grid(row=3, column=1, sticky="ew", padx=(6, 0), pady=2)
        tk.Label(f, text="For daily: e.g. 14:30. Leave empty for immediate.", fg="#888", font=("Helvetica", 9)).grid(row=4, column=1, sticky="w", padx=(6, 0))

        f.columnconfigure(1, weight=1)

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return s or "freq"

    def _save(self):
        data = {
            "name": self.name_var.get().strip(),
            "period_type": self.type_var.get(),
            "interval": int(self.interval_var.get()),
            "time": self.time_var.get().strip(),
        }
        if self.freq:
            run_async(lambda: self.client.update_frequency(self.freq["id"], **data), self._on_save)
        else:
            data["id"] = self._slugify(data["name"])
            run_async(lambda: self.client.add_frequency(**data), self._on_save)

    def _on_save(self, resp, err):
        if err:
            messagebox.showerror("Error", str(err), parent=self)
        else:
            self.destroy()
            if self.callback:
                self.callback()

import tkinter as tk
from tkinter import ttk, messagebox

from bcper_core.models import describe_cron, validate_cron, validate_cron_interval
from .common import run_async


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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

        cols = ("id", "name", "cron", "description")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        self.tree.heading("id", text="ID")
        self.tree.heading("name", text="Name")
        self.tree.heading("cron", text="Cron")
        self.tree.heading("description", text="Schedule")
        self.tree.column("id", width=100)
        self.tree.column("name", width=160)
        self.tree.column("cron", width=120)
        self.tree.column("description", width=200)
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
            cron = f.get("cron", "")
            self.tree.insert("", "end", values=(
                f.get("id", "?"),
                f.get("name", "?"),
                cron or "—",
                describe_cron(cron),
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
        self.minsize(460, 380)
        self._build()
        if freq:
            self.name_var.set(freq.get("name", ""))
            self.cron_var.set(freq.get("cron", ""))
            self._parse_cron_to_ui(freq.get("cron", ""))
        self._update_preview()
        tk.Button(self, text="Save", command=self._save).pack(pady=(0, 12))

    def _build(self):
        f = tk.Frame(self)
        f.pack(padx=16, pady=12, fill="both", expand=True)

        # Name
        tk.Label(f, text="Name:", font=("Helvetica", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.name_var = tk.StringVar()
        tk.Entry(f, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))

        # Period builder
        builder = tk.LabelFrame(f, text=" Schedule ", font=("Helvetica", 10, "bold"), padx=10, pady=10)
        builder.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        builder.columnconfigure(1, weight=1)

        tk.Label(builder, text="Every").grid(row=0, column=0, sticky="w")
        self.n_var = tk.StringVar(value="1")
        self.n_spin = tk.Spinbox(builder, from_=1, to=31, textvariable=self.n_var, width=6)
        self.n_spin.grid(row=0, column=1, sticky="w", padx=(6, 0))

        self.period_var = tk.StringVar(value="hours")
        self.period_combo = ttk.Combobox(builder, values=["hours", "days", "weeks", "months"],
                                         textvariable=self.period_var, state="readonly", width=12)
        self.period_combo.grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.period_var.trace_add("write", lambda *a: self._on_period_change())

        # Time (shared)
        self.time_frame = tk.Frame(builder)
        self.time_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(self.time_frame, text="at").pack(side="left")
        self.hour_var = tk.StringVar(value="00")
        self.min_var = tk.StringVar(value="00")
        tk.Spinbox(self.time_frame, from_=0, to=23, textvariable=self.hour_var, width=4, format="%02.0f").pack(side="left", padx=(6, 2))
        tk.Label(self.time_frame, text=":").pack(side="left")
        tk.Spinbox(self.time_frame, from_=0, to=59, textvariable=self.min_var, width=4, format="%02.0f").pack(side="left", padx=(2, 0))

        # Weekday
        self.weekday_frame = tk.Frame(builder)
        self.weekday_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(self.weekday_frame, text="on").pack(side="left")
        self.weekday_var = tk.StringVar(value="Monday")
        ttk.Combobox(self.weekday_frame, values=_WEEKDAYS, textvariable=self.weekday_var, state="readonly", width=12).pack(side="left", padx=(6, 0))
        tk.Label(self.weekday_frame, text="(standard cron is weekly only)", fg="#888", font=("Helvetica", 9)).pack(side="left", padx=(6, 0))

        # Month day
        self.monthday_frame = tk.Frame(builder)
        self.monthday_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(self.monthday_frame, text="on day").pack(side="left")
        self.day_var = tk.StringVar(value="1")
        tk.Spinbox(self.monthday_frame, from_=1, to=31, textvariable=self.day_var, width=4).pack(side="left", padx=(6, 0))

        # Preview
        self.preview_label = tk.Label(builder, text="", fg="#2ecc71", font=("Helvetica", 9, "italic"))
        self.preview_label.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # Apply button
        tk.Button(builder, text="Apply to Cron", command=self._apply_builder).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Separator
        ttk.Separator(f, orient="horizontal").grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 10))

        # Custom cron
        tk.Label(f, text="Or paste custom cron:", font=("Helvetica", 10, "bold")).grid(row=3, column=0, sticky="w")
        self.cron_var = tk.StringVar()
        self.cron_var.trace_add("write", lambda *a: self._update_preview())
        tk.Entry(f, textvariable=self.cron_var).grid(row=3, column=1, sticky="ew", padx=(8, 0))

        # Validation / description
        self.desc_label = tk.Label(f, text="", fg="#555", font=("Helvetica", 9, "italic"))
        self.desc_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Help
        help_text = (
            "min  hour  dom  month  dow\n"
            "0    22    *    *      *   → daily at 22:00\n"
            "0    */6   *    *      *   → every 6 hours"
        )
        tk.Label(f, text=help_text, fg="#888", font=("Helvetica", 9), justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))

        f.columnconfigure(1, weight=1)

        self._on_period_change()

    def _on_period_change(self):
        period = self.period_var.get()
        if period == "hours":
            self.time_frame.grid_remove()
            self.weekday_frame.grid_remove()
            self.monthday_frame.grid_remove()
        elif period == "days":
            self.time_frame.grid()
            self.weekday_frame.grid_remove()
            self.monthday_frame.grid_remove()
        elif period == "weeks":
            self.time_frame.grid()
            self.weekday_frame.grid()
            self.monthday_frame.grid_remove()
        elif period == "months":
            self.time_frame.grid()
            self.weekday_frame.grid_remove()
            self.monthday_frame.grid()

    def _apply_builder(self):
        try:
            n = int(self.n_var.get())
            if n < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Interval must be a positive integer.", parent=self)
            return
        period = self.period_var.get()
        hh = self.hour_var.get().zfill(2)
        mm = self.min_var.get().zfill(2)

        if period == "hours":
            cron = f"0 */{n} * * *"
        elif period == "days":
            if n == 1:
                cron = f"{mm} {hh} * * *"
            else:
                cron = f"{mm} {hh} */{n} * *"
        elif period == "weeks":
            dow = _WEEKDAYS.index(self.weekday_var.get())
            cron = f"{mm} {hh} * * {dow}"
        elif period == "months":
            day = self.day_var.get()
            if n == 1:
                cron = f"{mm} {hh} {day} * *"
            else:
                cron = f"{mm} {hh} {day} */{n} *"
        else:
            return

        self.cron_var.set(cron)
        self._update_preview()

    def _parse_cron_to_ui(self, cron: str):
        """Try to populate builder fields from an existing cron."""
        parts = cron.split()
        if len(parts) != 5:
            return
        minute, hour, dom, month, dow = parts
        try:
            self.hour_var.set(hour.zfill(2))
            self.min_var.set(minute.zfill(2))
        except Exception:
            pass

        # Hours
        if minute == "0" and hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
            self.period_var.set("hours")
            self.n_var.set(hour[2:])
            return

        # Days
        if dom == "*" and month == "*" and dow == "*":
            self.period_var.set("days")
            self.n_var.set("1")
            return
        if dom.startswith("*/") and month == "*" and dow == "*":
            self.period_var.set("days")
            self.n_var.set(dom[2:])
            return

        # Weeks
        if dom == "*" and month == "*" and dow != "*":
            self.period_var.set("weeks")
            self.n_var.set("1")
            try:
                self.weekday_var.set(_WEEKDAYS[int(dow) % 7])
            except Exception:
                pass
            return

        # Months
        if dom != "*" and month == "*" and dow == "*":
            self.period_var.set("months")
            self.n_var.set("1")
            self.day_var.set(dom)
            return
        if dom != "*" and month.startswith("*/") and dow == "*":
            self.period_var.set("months")
            self.n_var.set(month[2:])
            self.day_var.set(dom)
            return

    def _update_preview(self):
        cron = self.cron_var.get().strip()
        if not cron:
            self.desc_label.config(text="Runs once", fg="#2ecc71")
            self.preview_label.config(text="")
            return
        if not validate_cron(cron):
            self.desc_label.config(text="Invalid cron expression", fg="#e74c3c")
            self.preview_label.config(text="")
            return
        if not validate_cron_interval(cron):
            self.desc_label.config(text="Interval too short — minimum is 5 minutes", fg="#e74c3c")
            self.preview_label.config(text="")
            return
        desc = describe_cron(cron)
        self.desc_label.config(text=desc, fg="#2ecc71")
        self.preview_label.config(text=f"Cron: {cron}")

    @staticmethod
    def _slugify(name: str) -> str:
        import re
        s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return s or "freq"

    def _save(self):
        cron = self.cron_var.get().strip()
        if cron:
            if not validate_cron(cron):
                messagebox.showerror("Error", f"Invalid cron expression: {cron}", parent=self)
                return
            if not validate_cron_interval(cron):
                messagebox.showerror("Error", "Interval too short — minimum is 5 minutes.", parent=self)
                return
        data = {
            "name": self.name_var.get().strip(),
            "cron": cron,
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

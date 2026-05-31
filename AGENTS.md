# BCPER Agent Guide

## Project Structure

```
bcper/
├── bcper_core/       # Shared library (no UI, no process logic)
│   ├── models.py     # BCItem, BCVault, JobFrequency, Job, BackupTarget, BackupStore, BackupEngine
│   ├── config.py     # JSON config at ~/.config/bcper/config.json
│   ├── db.py         # SQLite tracking of backup runs
│   ├── ignore.py     # Gitignore-style matcher for bcpignore
│   ├── engine.py     # TarGzBackupEngine: backup/restore, encryption, hashing
│   ├── storage.py    # BackupStore base + LocalStore + RcloneStore
│   ├── rclone_helper.py  # Auto-download and launch rclone
│   ├── progress.py   # Progress callback helpers
│   └── protocol.py   # IPC message encoding/decoding
├── bcperd/           # Daemon process
│   ├── daemon.py     # Main orchestrator: scheduler, catch-up, config CRUD
│   ├── server.py     # Unix-socket JSON IPC server
│   └── __main__.py   # Entry point: python -m bcperd
├── bcper/            # Desktop GUI
│   ├── client.py     # IPC client for talking to daemon
│   ├── gui/          # Tkinter tab modules
│   │   ├── app.py         # Main App(window) with banners and notebook
│   │   ├── common.py      # ProgressDialog, run_async, UI queue
│   │   ├── items_tab.py
│   │   ├── vaults_tab.py
│   │   ├── stores_tab.py
│   │   ├── backups_tab.py
│   │   ├── frequencies_tab.py
│   │   ├── jobs_tab.py
│   │   └── status_tab.py
│   └── __main__.py   # Entry point: python -m bcper
├── pyproject.toml
├── uv.lock
├── AGENTS.md
└── README.md
```

## Conventions

- **Python 3.8+** required.
- Use `dataclasses` for models.
- Config is a single JSON file; always acquire `config_lock` before modifying.
- SQLite DB (`bcper.db`) is accessed via plain functions with `threading.Lock`.
- All blocking I/O in the daemon runs inside `ThreadPoolExecutor` via `run_in_executor`.
- GUI runs client calls in background threads and uses `tk.after()` to update UI.
- `bcpignore` patterns follow gitignore semantics: `*` (no `/`), `**` (any depth), trailing `/` (directory only), `!` (negation).

## Key Concepts

### Frequencies

`JobFrequency` now uses a `cron` string (empty = "once"). `JobFrequencyTrigger` uses `croniter` for `should_run` and `calculate_next_run`. The minimum valid interval is 5 minutes.

### Runs / Backups

Every backup execution creates a UUID and a row in SQLite (`bcper_core/db.py`). The relative store path is `<job.name>/<uuid>/<archive_name>`. Ad-hoc backups use `ad-hoc/<uuid>/` as the prefix.

### Catch-Up

On startup, the daemon scans all enabled jobs. If `next_run` is in the past, the job is considered missed and is run sequentially in a background thread before the scheduler loop begins.

### Orphan Cleanup

Deleting an item, vault, or store cascades to jobs that reference it. On startup, `_cleanup_orphaned_jobs()` removes any jobs pointing to non-existent targets, stores, or frequencies.

## Running

```bash
# Install deps
uv sync

# Start daemon
python3 -m bcperd
# or
uv run python -m bcperd

# Start GUI
python3 -m bcper
# or
uv run python -m bcper

# CLI
bcper-cli item list
bcper-cli job list
```

## Testing

Run a quick CLI smoke test (see README.md).

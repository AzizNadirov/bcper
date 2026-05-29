# BCPER Agent Guide

## Project Structure

```
bcper/
├── bcper_core/       # Shared library (no UI, no process logic)
│   ├── models.py     # BCItem, BCVault, RunPeriod, BackupJob
│   ├── config.py     # JSON config at ~/.config/bcper/config.json
│   ├── ignore.py     # Gitignore-style matcher for bcpignore
│   ├── engine.py     # Backup/restore, encryption, hashing
│   ├── storage.py    # BackupStore base + LocalStore + RcloneStore
│   └── protocol.py   # IPC message encoding/decoding
├── bcperd/           # Daemon process
│   ├── daemon.py     # Main orchestrator: scheduler + config CRUD
│   ├── server.py     # Unix-socket JSON IPC server
│   └── __main__.py   # Entry point: python -m bcperd
├── bcper/            # Desktop GUI
│   ├── client.py     # IPC client for talking to daemon
│   ├── gui.py        # Tkinter application
│   └── __main__.py   # Entry point: python -m bcper
├── requirements.txt
├── AGENTS.md
└── README.md
```

## Conventions

- **Python 3.8+** required.
- Use `dataclasses` for models.
- Config is a single JSON file; always acquire `config_lock` before modifying.
- All blocking I/O in the daemon runs inside `ThreadPoolExecutor` via `run_in_executor`.
- GUI runs client calls in background threads and uses `tk.after()` to update UI.
- `bcpignore` patterns follow gitignore semantics: `*` (no `/`), `**` (any depth), trailing `/` (directory only), `!` (negation).

## Running

```bash
# Install deps
pip3 install -r requirements.txt

# Start daemon
python3 -m bcperd

# Start GUI
python3 -m bcper
```

## Testing

Run a quick CLI smoke test with the helper script (see README.md).

# BCPER

Lightweight desktop backup manager with a background daemon worker.

## Features

- **BCItem** — named backup item with paths, optional password, and `bcpignore` patterns.
- **BCVault** — named backup set composed of BCItems, with its own password and ignores.
- **bcpignore** — gitignore-style filters; item patterns override vault patterns.
- **Scheduling** — run once, hourly, or daily with configurable interval.
- **Encryption** — AES-256-GCM with PBKDF2 password derivation.
- **Integrity** — SHA-256 checksums stored alongside archives; warnings on mismatch.
- **Storage** — local directory or remote via rclone.
- **Desktop GUI** — Tkinter-based configuration and control panel.
- **Daemon** — background scheduler and worker process with Unix-socket IPC.

## Install

Uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

On Debian/Ubuntu you may need Tkinter for the GUI:

```bash
sudo apt-get install python3-tk
```

## Usage

### Start the daemon

```bash
uv run bcperd
```

Or:

```bash
uv run python -m bcperd
```

### Open the GUI

```bash
uv run bcper
```

Or:

```bash
uv run python -m bcper
```

### Quick CLI smoke test

```bash
python3 -c "
import tempfile, os, time
from bcper_core.config import Config
from bcper_core.models import BCItem
from bcper_core.engine import BackupEngine
from bcper_core.storage import LocalStore

with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, 'src')
    dst = os.path.join(td, 'backups')
    os.makedirs(src)
    with open(os.path.join(src, 'hello.txt'), 'w') as f:
        f.write('world')
    item = BCItem(key='test', paths=[src])
    store = LocalStore(dst)
    engine = BackupEngine()
    result = engine.backup_item(item, store)
    print('Backup:', result)
    restore = engine.restore(result['archive'], store, target_dir=os.path.join(td, 'restore'))
    print('Restore:', restore)
"
```

## Configuration

Stored at `~/.config/bcper/config.json`:

- `items` — BCItem dictionary.
- `vaults` — BCVault dictionary.
- `jobs` — scheduled backup jobs.
- `stores` — backup store configurations.

## Logs

Daemon logs to `~/.config/bcper/daemon.log`.

## IPC

The daemon listens on a Unix domain socket at `~/.config/bcper/daemon.sock`. The GUI communicates over this socket using newline-delimited JSON messages.

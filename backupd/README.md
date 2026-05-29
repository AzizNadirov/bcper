# backupd

Periodic backup of local directories to cloud storage (Google Drive, S3, OneDrive, SFTP…) with automatic **N-version retention**.  
Built on [rclone](https://rclone.org/) — supports 70+ cloud providers.

---

## Quick start

### 1 — Install rclone

```bash
curl https://rclone.org/install.sh | sudo bash
```

### 2 — Configure your cloud remote

```bash
rclone config
```

For **Google Drive**, choose:
- `n` → new remote
- name: `gdrive`
- storage type: `drive`
- follow the OAuth flow in your browser

For **S3 / R2 / Backblaze B2**, pick the relevant type and enter your keys.

Verify with:
```bash
rclone lsd gdrive:
```

---

### 3 — Install backupd

```bash
# 1. Copy the script and config somewhere permanent
mkdir -p ~/.config/backupd ~/.local/bin ~/.local/share/backupd

cp backupd.sh  ~/.local/bin/backupd.sh
cp backupd.conf ~/.config/backupd/backupd.conf
chmod +x ~/.local/bin/backupd.sh

# 2. Edit the config
nano ~/.config/backupd/backupd.conf
#   → set REMOTE, BACKUP_DIRS, KEEP_VERSIONS

# 3. Test with dry-run
backupd.sh --dry-run

# 4. Run once for real
backupd.sh --now
```

---

### 4 — Set up the systemd timer (runs daily)

```bash
# Install user systemd units
mkdir -p ~/.config/systemd/user/
cp backupd.service backupd.timer ~/.config/systemd/user/

# Enable + start
systemctl --user daemon-reload
systemctl --user enable --now backupd.timer

# Check status
systemctl --user list-timers backupd.timer
systemctl --user status backupd.service
```

Logs are written to `~/.local/share/backupd/backupd.log`.

To view live:
```bash
tail -f ~/.local/share/backupd/backupd.log
```

Or via journald:
```bash
journalctl --user -u backupd.service -f
```

---

## Remote layout

Each backed-up directory gets its own folder in the remote, with timestamped snapshots inside:

```
gdrive:Backups/
  home_aziz_Documents/
    2024-11-01T09-00-00/   ← oldest, will be pruned
    2024-11-02T09-00-05/
    2024-11-03T09-00-11/
    2024-11-04T09-00-07/
    2024-11-05T09-00-03/   ← newest, always kept
  home_aziz_Projects/
    2024-11-01T09-00-00/
    ...
```

With `KEEP_VERSIONS=5`, after the 6th run the oldest snapshot is deleted automatically.

---

## Configuration reference

| Key | Example | Description |
|-----|---------|-------------|
| `LABEL` | `home-backup` | Identifier used in log and lock files |
| `REMOTE` | `gdrive:Backups` | rclone remote + path |
| `BACKUP_DIRS` | `("$HOME/Docs" "$HOME/Projects")` | Bash array of dirs to back up |
| `KEEP_VERSIONS` | `5` | Number of snapshots to retain per dir |
| `SCHEDULE` | `daily` / `hourly` / `3600` | Minimum interval between runs |
| `COMPRESS` | `false` | `true` = tar.gz each dir before upload |
| `EXCLUDE_PATTERNS` | `"*.log node_modules/**"` | Space-separated rclone glob excludes |
| `RCLONE_FLAGS` | `"--transfers 8"` | Extra flags passed to rclone |
| `LOG_FILE` | `~/.local/share/backupd/backupd.log` | Absolute path to log file |
| `STAMP_FORMAT` | `%Y-%m-%dT%H-%M-%S` | `date` format for snapshot folder names |

---

## Manual operations

```bash
# Force a backup right now (bypass schedule)
backupd.sh --now

# Dry-run (see what would happen)
backupd.sh --dry-run

# Use a different config
backupd.sh --config /path/to/other.conf

# Restore a file from a snapshot
rclone copy "gdrive:Backups/home_aziz_Documents/2024-11-05T09-00-03/report.pdf" ~/Downloads/

# Restore an entire snapshot
rclone copy "gdrive:Backups/home_aziz_Documents/2024-11-05T09-00-03/" ~/Restore/Documents/

# List all snapshots for a directory
rclone lsd "gdrive:Backups/home_aziz_Documents/"
```

---

## Tips

- **Multiple configs**: run multiple instances with different `--config` flags (e.g. one for Documents/daily, one for /etc/weekly).
- **Bandwidth limiting**: add `--bwlimit 5M` to `RCLONE_FLAGS` to cap upload speed.
- **Encrypted backups**: use `rclone config` to create a `crypt` remote layered on top of your cloud remote, then point `REMOTE` at the crypt remote.
- **S3 / Backblaze B2**: replace `gdrive:Backups` with `s3:your-bucket/backups` — everything else is the same.

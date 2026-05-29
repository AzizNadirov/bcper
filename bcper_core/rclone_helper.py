import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RCLONE_DIR = Path.home() / ".local" / "share" / "bcper"
RCLONE_BIN = RCLONE_DIR / "rclone"

_DOWNLOAD_URLS = {
    ("Linux", "x86_64"): "https://downloads.rclone.org/rclone-current-linux-amd64.zip",
    ("Linux", "amd64"): "https://downloads.rclone.org/rclone-current-linux-amd64.zip",
    ("Linux", "aarch64"): "https://downloads.rclone.org/rclone-current-linux-arm64.zip",
    ("Linux", "arm64"): "https://downloads.rclone.org/rclone-current-linux-arm64.zip",
    ("Darwin", "x86_64"): "https://downloads.rclone.org/rclone-current-osx-amd64.zip",
    ("Darwin", "arm64"): "https://downloads.rclone.org/rclone-current-osx-arm64.zip",
}


def _platform_key():
    system = platform.system()
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        machine = "x86_64"
    elif machine in ("arm64", "aarch64"):
        machine = "arm64"
    return (system, machine)


def get_rclone_path() -> str:
    system_path = shutil.which("rclone")
    if system_path:
        return system_path
    if RCLONE_BIN.exists():
        return str(RCLONE_BIN)
    return None


def rclone_available() -> bool:
    return get_rclone_path() is not None


def ensure_rclone() -> str:
    path = get_rclone_path()
    if path:
        return path

    key = _platform_key()
    url = _DOWNLOAD_URLS.get(key)
    if not url:
        raise RuntimeError(f"Auto-download not supported for {key[0]} {key[1]}. Please install rclone manually.")

    RCLONE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RCLONE_DIR / "rclone.zip"

    urllib.request.urlretrieve(url, zip_path)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(RCLONE_DIR)

    extracted = None
    for item in RCLONE_DIR.iterdir():
        if item.is_dir() and item.name.startswith("rclone-"):
            candidate = item / "rclone"
            if candidate.exists():
                extracted = candidate
                break

    if not extracted:
        raise RuntimeError("Failed to locate rclone binary after extraction.")

    shutil.move(str(extracted), str(RCLONE_BIN))
    os.chmod(RCLONE_BIN, 0o755)

    zip_path.unlink(missing_ok=True)
    for item in RCLONE_DIR.iterdir():
        if item.is_dir() and item.name.startswith("rclone-"):
            shutil.rmtree(item)

    return str(RCLONE_BIN)


def run_rclone(*args) -> subprocess.CompletedProcess:
    path = ensure_rclone()
    return subprocess.run([path, *args], capture_output=True, text=True)


def _find_terminal() -> list:
    """Find a suitable terminal emulator command as a list."""
    candidates = [
        ["x-terminal-emulator", "-e"],
        ["gnome-terminal", "--wait", "--"],
        ["konsole", "-e"],
        ["xfce4-terminal", "-e"],
        ["kitty", "-e"],
        ["xterm", "-e"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            return cmd
    return None


def open_rclone_config():
    """Open a terminal running 'rclone config'."""
    path = ensure_rclone()
    term = _find_terminal()
    if term:
        subprocess.Popen(term + [path, "config"])
    else:
        raise RuntimeError("No terminal emulator found. Install gnome-terminal, konsole, xfce4-terminal, or xterm.")

import json
import os
import tarfile
import hashlib
import tempfile
from datetime import datetime
from typing import List, Optional, Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag


class UserError(ValueError):
    """Expected user-facing error (e.g. wrong password). No traceback needed."""

from .models import (
    BackupEngine,
    BackupStore,
    BackupTarget,
    BCItemTarget,
    BCVaultTarget,
)
from .ignore import IgnoreMatcher, effective_ignores


def _noop_progress(step: str):
    pass


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(password.encode())


def encrypt_data(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return salt + nonce + ciphertext


def decrypt_data(data: bytes, password: str) -> bytes:
    salt = data[:16]
    nonce = data[16:28]
    ciphertext = data[28:]
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        raise UserError("Incorrect password") from None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TarGzBackupEngine(BackupEngine):
    def backup(self, target: BackupTarget, store: BackupStore, timestamp: str = None, progress: Callable[[str], None] = None) -> dict:
        if progress is None:
            progress = _noop_progress
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        if isinstance(target, BCItemTarget):
            return self._backup_item(target, store, timestamp, progress)
        elif isinstance(target, BCVaultTarget):
            return self._backup_vault(target, store, timestamp, progress)
        else:
            raise ValueError(f"Unsupported target type: {type(target)}")

    def _backup_item(self, target: BCItemTarget, store: BackupStore, timestamp: str, progress: Callable[[str], None]) -> dict:
        archive_name = f"{target.name}_{timestamp}.tar.gz"
        meta_name = f"{target.name}_{timestamp}.meta.json"
        hash_name = f"{target.name}_{timestamp}.sha256"

        matcher = IgnoreMatcher(target.get_ignore_patterns())

        progress("Collecting files...")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with tarfile.open(tmp_path, "w:gz") as tar:
                for path in target.get_paths():
                    if not os.path.exists(path):
                        continue
                    self._add_path(tar, path, matcher, arcbase="")

        try:
            progress("Reading archive...")
            with open(tmp_path, "rb") as f:
                archive_data = f.read()

            progress("Computing hash...")
            original_hash = sha256_bytes(archive_data)
            password = target.get_password()
            encrypted = bool(password)

            if encrypted:
                progress("Encrypting...")
                archive_data = encrypt_data(archive_data, password)
                archive_name += ".enc"

            progress("Saving to store...")
            store.save(archive_name, archive_data)
            store.save(hash_name, original_hash.encode())

            meta = {
                "key": target.name,
                "timestamp": timestamp,
                "paths": target.get_paths(),
                "encrypted": encrypted,
                "hash": original_hash,
                "archive_name": archive_name,
            }
            store.save(meta_name, json.dumps(meta, indent=2).encode())

            progress("Done")
            return {
                "success": True,
                "archive": archive_name,
                "hash": original_hash,
                "encrypted": encrypted,
            }
        finally:
            os.unlink(tmp_path)

    def _backup_vault(self, target: BCVaultTarget, store: BackupStore, timestamp: str, progress: Callable[[str], None]) -> dict:
        archive_name = f"{target.name}_{timestamp}.tar.gz"
        meta_name = f"{target.name}_{timestamp}.meta.json"
        hash_name = f"{target.name}_{timestamp}.sha256"

        item_targets = target.get_item_targets()

        progress("Collecting files...")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with tarfile.open(tmp_path, "w:gz") as tar:
                for it in item_targets:
                    ignores = effective_ignores(target.get_ignore_patterns(), it.get_ignore_patterns())
                    matcher = IgnoreMatcher(ignores)
                    for path in it.get_paths():
                        if not os.path.exists(path):
                            continue
                        self._add_path(tar, path, matcher, arcbase=it.name)

        try:
            progress("Reading archive...")
            with open(tmp_path, "rb") as f:
                archive_data = f.read()

            progress("Computing hash...")
            original_hash = sha256_bytes(archive_data)
            password = target.get_password()
            encrypted = bool(password)

            if encrypted:
                progress("Encrypting...")
                archive_data = encrypt_data(archive_data, password)
                archive_name += ".enc"

            progress("Saving to store...")
            store.save(archive_name, archive_data)
            store.save(hash_name, original_hash.encode())

            meta = {
                "vault": target.name,
                "timestamp": timestamp,
                "items": [it.name for it in item_targets],
                "encrypted": encrypted,
                "hash": original_hash,
                "archive_name": archive_name,
            }
            store.save(meta_name, json.dumps(meta, indent=2).encode())

            progress("Done")
            return {
                "success": True,
                "archive": archive_name,
                "hash": original_hash,
                "encrypted": encrypted,
            }
        finally:
            os.unlink(tmp_path)

    def _add_path(self, tar: tarfile.TarFile, path: str, matcher: IgnoreMatcher, arcbase: str):
        basename = os.path.basename(path)
        if matcher.is_ignored(basename, is_dir=os.path.isdir(path)):
            return

        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                rel_root = os.path.relpath(root, path)
                if rel_root == ".":
                    rel_root = ""

                kept_dirs = []
                for d in dirs:
                    rel = os.path.join(rel_root, d).replace("\\", "/") if rel_root else d
                    if not matcher.is_ignored(rel, is_dir=True):
                        kept_dirs.append(d)
                dirs[:] = kept_dirs

                for f in files:
                    rel = os.path.join(rel_root, f).replace("\\", "/") if rel_root else f
                    if matcher.is_ignored(rel, is_dir=False):
                        continue
                    full = os.path.join(root, f)
                    arc = os.path.join(arcbase, rel).replace("\\", "/") if arcbase else rel
                    tar.add(full, arcname=arc)
        else:
            arc = os.path.join(arcbase, basename).replace("\\", "/") if arcbase else basename
            tar.add(path, arcname=arc)

    def restore(self, archive_name: str, store: BackupStore, password: str = None, target_dir: str = None, progress: Callable[[str], None] = None) -> dict:
        if progress is None:
            progress = _noop_progress

        progress("Loading from store...")
        archive_data = store.load(archive_name)
        encrypted = archive_name.endswith(".enc")

        if encrypted:
            if not password:
                raise ValueError("Password required for encrypted backup")
            progress("Decrypting...")
            archive_data = decrypt_data(archive_data, password)

        hash_name = archive_name.replace(".enc", "") + ".sha256"
        warnings = []
        if store.exists(hash_name):
            progress("Verifying hash...")
            expected_hash = store.load(hash_name).decode().strip()
            actual_hash = sha256_bytes(archive_data)
            if expected_hash != actual_hash:
                warnings.append(f"Hash mismatch! Expected {expected_hash}, got {actual_hash}")

        if target_dir is None:
            target_dir = os.getcwd()
        os.makedirs(target_dir, exist_ok=True)

        progress("Extracting...")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp.write(archive_data)
            tmp.flush()
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=target_dir)
        finally:
            os.unlink(tmp_path)

        progress("Done")
        return {
            "success": True,
            "warnings": warnings,
            "target_dir": target_dir,
        }

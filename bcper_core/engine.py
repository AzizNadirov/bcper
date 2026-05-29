import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime
from typing import List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from .models import BCItem, BCVault
from .storage import BackupStore
from .ignore import IgnoreMatcher, effective_ignores


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
    return aesgcm.decrypt(nonce, ciphertext, None)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BackupEngine:
    def backup_item(self, item: BCItem, store: BackupStore, timestamp: str = None) -> dict:
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        archive_name = f"{item.key}_{timestamp}.tar.gz"
        meta_name = f"{item.key}_{timestamp}.meta.json"
        hash_name = f"{item.key}_{timestamp}.sha256"

        matcher = IgnoreMatcher(item.bcpignore)

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with tarfile.open(tmp_path, "w:gz") as tar:
                for path in item.paths:
                    if not os.path.exists(path):
                        continue
                    self._add_path(tar, path, matcher, arcbase="")

        try:
            with open(tmp_path, "rb") as f:
                archive_data = f.read()

            original_hash = sha256_bytes(archive_data)
            encrypted = bool(item.password)

            if encrypted:
                archive_data = encrypt_data(archive_data, item.password)
                archive_name += ".enc"

            store.save(archive_name, archive_data)
            store.save(hash_name, original_hash.encode())

            meta = {
                "key": item.key,
                "timestamp": timestamp,
                "paths": item.paths,
                "encrypted": encrypted,
                "hash": original_hash,
                "archive_name": archive_name,
            }
            store.save(meta_name, json.dumps(meta, indent=2).encode())

            return {
                "success": True,
                "archive": archive_name,
                "hash": original_hash,
                "encrypted": encrypted,
            }
        finally:
            os.unlink(tmp_path)

    def backup_vault(self, vault: BCVault, items: List[BCItem], store: BackupStore, timestamp: str = None) -> dict:
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        archive_name = f"{vault.name}_{timestamp}.tar.gz"
        meta_name = f"{vault.name}_{timestamp}.meta.json"
        hash_name = f"{vault.name}_{timestamp}.sha256"

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name
            with tarfile.open(tmp_path, "w:gz") as tar:
                for item in items:
                    ignores = effective_ignores(vault.bcpignore, item.bcpignore)
                    matcher = IgnoreMatcher(ignores)
                    for path in item.paths:
                        if not os.path.exists(path):
                            continue
                        self._add_path(tar, path, matcher, arcbase=item.key)

        try:
            with open(tmp_path, "rb") as f:
                archive_data = f.read()

            original_hash = sha256_bytes(archive_data)
            password = vault.password
            encrypted = bool(password)

            if encrypted:
                archive_data = encrypt_data(archive_data, password)
                archive_name += ".enc"

            store.save(archive_name, archive_data)
            store.save(hash_name, original_hash.encode())

            meta = {
                "vault": vault.name,
                "timestamp": timestamp,
                "items": [item.key for item in items],
                "encrypted": encrypted,
                "hash": original_hash,
                "archive_name": archive_name,
            }
            store.save(meta_name, json.dumps(meta, indent=2).encode())

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

                # Filter directories
                kept_dirs = []
                for d in dirs:
                    rel = os.path.join(rel_root, d).replace("\\", "/") if rel_root else d
                    if not matcher.is_ignored(rel, is_dir=True):
                        kept_dirs.append(d)
                dirs[:] = kept_dirs

                # Add files
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

    def restore(self, archive_name: str, store: BackupStore, password: str = None, target_dir: str = None) -> dict:
        archive_data = store.load(archive_name)
        encrypted = archive_name.endswith(".enc")

        if encrypted:
            if not password:
                raise ValueError("Password required for encrypted backup")
            archive_data = decrypt_data(archive_data, password)

        hash_name = archive_name.replace(".enc", "") + ".sha256"
        warnings = []
        if store.exists(hash_name):
            expected_hash = store.load(hash_name).decode().strip()
            actual_hash = sha256_bytes(archive_data)
            if expected_hash != actual_hash:
                warnings.append(f"Hash mismatch! Expected {expected_hash}, got {actual_hash}")

        if target_dir is None:
            target_dir = os.getcwd()
        os.makedirs(target_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp.write(archive_data)
            tmp.flush()
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=target_dir)
        finally:
            os.unlink(tmp_path)

        return {
            "success": True,
            "warnings": warnings,
            "target_dir": target_dir,
        }

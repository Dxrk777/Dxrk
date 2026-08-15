from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROTATION_NEVER = "never"
ROTATION_DAILY = "daily"
ROTATION_WEEKLY = "weekly"
ROTATION_MONTHLY = "monthly"


@dataclass
class SecretEntry:
    value: str
    created: datetime
    updated: datetime
    rotation: str = ""
    env_var: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "value": self.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
        }
        if self.rotation:
            d["rotation"] = self.rotation
        if self.env_var:
            d["env_var"] = self.env_var
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecretEntry":
        return cls(
            value=data["value"],
            created=datetime.fromisoformat(data["created"]),
            updated=datetime.fromisoformat(data["updated"]),
            rotation=data.get("rotation", ""),
            env_var=data.get("env_var", ""),
        )


class Vault:
    def __init__(self, path: str, master_key: bytes):
        self._mu = threading.RLock()
        self._path = path
        self._master_key = master_key
        self._secrets: dict[str, SecretEntry] = {}

    @classmethod
    def create(cls, path: str, master_key_env: str = "") -> "Vault":
        key = None
        if master_key_env != "":
            ek = os.environ.get(master_key_env)
            if ek:
                key = hashlib.sha256(ek.encode()).digest()
        if key is None:
            key = os.urandom(32)
        v = cls(path, key)
        if path != "":
            try:
                v._load()
            except (ValueError, json.JSONDecodeError) as e:
                raise RuntimeError(f"load vault: {e}") from e
            except FileNotFoundError:
                pass
        return v

    def get(self, name: str) -> tuple[str, bool]:
        with self._mu:
            entry = self._secrets.get(name)
            if entry is None:
                return "", False
            return entry.value, True

    def set(self, name: str, value: str, *opts: Callable[[SecretEntry], None]) -> None:
        with self._mu:
            now = datetime.now()
            entry = SecretEntry(value=value, created=now, updated=now)
            for opt in opts:
                opt(entry)
            self._secrets[name] = entry
            self._save()

    def delete(self, name: str) -> None:
        with self._mu:
            self._secrets.pop(name, None)
            self._save()

    def rotate(self, name: str, new_value: str) -> None:
        with self._mu:
            entry = self._secrets.get(name)
            if entry is None:
                raise ValueError(f"secret {name!r} not found")
            entry.value = new_value
            entry.updated = datetime.now()
            self._secrets[name] = entry
            self._save()

    def list(self) -> list[str]:
        with self._mu:
            return list(self._secrets.keys())

    def resolve(self, name: str) -> str:
        val, ok = self.get(name)
        if ok:
            return val
        return os.environ.get(name, "")

    def bind_to_env(self, name: str, env_var: str) -> None:
        with self._mu:
            entry = self._secrets.get(name)
            if entry is not None:
                entry.env_var = env_var
                self._secrets[name] = entry
            else:
                val = os.environ.get(env_var, "")
                if val == "":
                    raise ValueError(
                        f"env var {env_var} not set and no vault entry for {name}"
                    )
                now = datetime.now()
                self._secrets[name] = SecretEntry(
                    value=val,
                    created=now,
                    updated=now,
                    env_var=env_var,
                )
            self._save()

    def _load(self) -> None:
        data = Path(self._path).read_bytes()
        decoded = base64.b64decode(data)
        try:
            plaintext = self._decrypt(decoded)
        except ValueError as e:
            raise ValueError(f"decrypt vault: {e}") from e
        payload = json.loads(plaintext.decode())
        self._secrets = {k: SecretEntry.from_dict(v) for k, v in payload.items()}

    def _save(self) -> None:
        if self._path == "":
            return
        plaintext = json.dumps(
            {k: v.to_dict() for k, v in self._secrets.items()}
        ).encode()
        try:
            ciphertext = self._encrypt(plaintext)
        except Exception as e:
            raise RuntimeError(f"encrypt vault: {e}") from e
        encoded = base64.b64encode(ciphertext).decode()
        Path(self._path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self._path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(encoded)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _encrypt(self, plaintext: bytes) -> bytes:
        aesgcm = AESGCM(self._master_key)
        nonce = os.urandom(12)
        return nonce + aesgcm.encrypt(nonce, plaintext, None)

    def _decrypt(self, data: bytes) -> bytes:
        nonce_size = 12
        if len(data) < nonce_size:
            raise ValueError("ciphertext too short")
        nonce, ciphertext = data[:nonce_size], data[nonce_size:]
        aesgcm = AESGCM(self._master_key)
        return aesgcm.decrypt(nonce, ciphertext, None)


def new(path: str, master_key_env: str = "") -> Vault:
    return Vault.create(path, master_key_env)


def with_rotation(rotation: str) -> Callable[[SecretEntry], None]:
    def opt(entry: SecretEntry) -> None:
        entry.rotation = rotation

    return opt


def with_env_var(env_var: str) -> Callable[[SecretEntry], None]:
    def opt(entry: SecretEntry) -> None:
        entry.env_var = env_var

    return opt

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROTATION_NEVER = "never"
ROTATION_DAILY = "daily"
ROTATION_WEEKLY = "weekly"
ROTATION_MONTHLY = "monthly"

# tenant_id validation mirrors dxrk.security.jwt.validate_id / dxrk.tenant.migration.TENANT_ID_RE
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,256}$")


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
    def from_dict(cls, data: dict[str, Any]) -> SecretEntry:
        return cls(
            value=data["value"],
            created=datetime.fromisoformat(data["created"]),
            updated=datetime.fromisoformat(data["updated"]),
            rotation=data.get("rotation", ""),
            env_var=data.get("env_var", ""),
        )


def _derive_tenant_key(master: bytes, tenant_id: str) -> bytes:
    """Derive per-tenant key via HKDF-SHA256.

    Uses ``salt=tenant_id`` and ``info=b"dxrk/vault/tenant"`` per spec
    ``dxrk/vault/__init__.py`` (cryptography>=43 HKDF). Master is expected
    to be 32 bytes (e.g. sha256 of DXRK_VAULT_KEY). Length is fixed 32
    for AES-256-GCM.
    """
    if not tenant_id:
        raise ValueError("tenant_id required for HKDF derivation")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=tenant_id.encode(),
        info=b"dxrk/vault/tenant",
    )
    return hkdf.derive(master)


def _validate_tenant_id(tenant_id: str) -> None:
    if not _TENANT_ID_RE.match(tenant_id):
        raise ValueError(f"invalid tenant id {tenant_id!r}")


def _tenant_env_name(tenant_id: str, prefix: str = "DXRK_VAULT_KEY") -> str:
    # DXRK_VAULT_KEY_{TENANT_UPPER} – hyphen becomes underscore for env compat
    return f"{prefix}_{tenant_id.upper().replace('-', '_')}"


def tenant_vault_path(tenant_id: str) -> str:
    """Return ``~/.dxrk/tenants/{id}/vault.enc`` (creates no dirs)."""
    _validate_tenant_id(tenant_id)
    try:
        from dxrk.tenant.migration import tenant_root  # lazy to avoid cycles

        return str(tenant_root(tenant_id) / "vault.enc")
    except Exception:
        return str(Path.home() / ".dxrk" / "tenants" / tenant_id / "vault.enc")


class Vault:
    def __init__(self, path: str, master_key: bytes, tenant_id: str = "") -> None:
        self._mu = threading.RLock()
        self._path = path
        self._master_key = master_key
        self._tenant_id = tenant_id
        self._secrets: dict[str, SecretEntry] = {}

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def path(self) -> str:
        return self._path

    @classmethod
    def create(cls, path: str, master_key_env: str = "", tenant_id: str = "") -> Vault:
        # Tenant-aware path + key derivation (HKDF per-tenant)
        if tenant_id != "":
            _validate_tenant_id(tenant_id)
            # 1) per-tenant env fallback before HKDF
            tenant_env = _tenant_env_name(tenant_id, "DXRK_VAULT_KEY")
            tenant_val = os.environ.get(tenant_env)
            if tenant_val:
                key = hashlib.sha256(tenant_val.encode()).digest()
            else:
                # 2) HKDF derive from master (DXRK_VAULT_KEY or master_key_env)
                master_env_name = master_key_env if master_key_env != "" else "DXRK_VAULT_KEY"
                master_val = os.environ.get(master_env_name)
                if master_val:
                    master_key = hashlib.sha256(master_val.encode()).digest()
                else:
                    # ephemeral master -> derived tenant key also ephemeral (same as non-tenant fallback)
                    master_key = os.urandom(32)
                key = _derive_tenant_key(master_key, tenant_id)
            # auto path if caller left empty
            if path == "":
                try:
                    from dxrk.tenant.migration import tenant_root

                    path = str(tenant_root(tenant_id) / "vault.enc")
                except Exception:
                    path = str(Path.home() / ".dxrk" / "tenants" / tenant_id / "vault.enc")
            v = cls(path, key, tenant_id=tenant_id)
            if path != "":
                try:
                    v._load()
                except (ValueError, json.JSONDecodeError) as e:
                    raise RuntimeError(f"load vault: {e}") from e
                except FileNotFoundError:
                    pass
            return v

        # Legacy single-tenant path (retrocompat)
        key_legacy: bytes | None = None
        if master_key_env != "":
            ek = os.environ.get(master_key_env)
            if ek:
                key_legacy = hashlib.sha256(ek.encode()).digest()
        if key_legacy is None:
            key_legacy = os.urandom(32)
        key = key_legacy
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
                    raise ValueError(f"env var {env_var} not set and no vault entry for {name}")
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
        plaintext = json.dumps({k: v.to_dict() for k, v in self._secrets.items()}).encode()
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


class TenantVaultRegistry:
    """Lazy dict[tenant_id -> Vault] for per-tenant vaults (R09)."""

    def __init__(self) -> None:
        self._mu = threading.RLock()
        self._vaults: dict[str, Vault] = {}

    def get(self, tenant_id: str, master_key_env: str = "") -> Vault:
        _validate_tenant_id(tenant_id)
        with self._mu:
            existing = self._vaults.get(tenant_id)
            if existing is not None:
                return existing
            vault = Vault.create("", master_key_env=master_key_env, tenant_id=tenant_id)
            self._vaults[tenant_id] = vault
            return vault

    # alias per spec
    def get_tenant_vault(self, tenant_id: str, master_key_env: str = "") -> Vault:
        return self.get(tenant_id, master_key_env)

    def clear(self) -> None:
        with self._mu:
            self._vaults.clear()

    def all(self) -> dict[str, Vault]:
        with self._mu:
            return dict(self._vaults)

    def __contains__(self, tenant_id: object) -> bool:
        if not isinstance(tenant_id, str):
            return False
        with self._mu:
            return tenant_id in self._vaults

    def __getitem__(self, tenant_id: str) -> Vault:
        return self.get(tenant_id)

    def __len__(self) -> int:
        with self._mu:
            return len(self._vaults)


# Global lazy registry (use get_tenant_vault for app code)
_registry = TenantVaultRegistry()


def get_tenant_vault(tenant_id: str, master_key_env: str = "") -> Vault:
    """Return per-tenant vault from global registry (lazy, HKDF derived)."""
    return _registry.get(tenant_id, master_key_env)


def new(path: str, master_key_env: str = "", tenant_id: str = "") -> Vault:
    return Vault.create(path, master_key_env, tenant_id)


def with_rotation(rotation: str) -> Callable[[SecretEntry], None]:
    def opt(entry: SecretEntry) -> None:
        entry.rotation = rotation

    return opt


def with_env_var(env_var: str) -> Callable[[SecretEntry], None]:
    def opt(entry: SecretEntry) -> None:
        entry.env_var = env_var

    return opt

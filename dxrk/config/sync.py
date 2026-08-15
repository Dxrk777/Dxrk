# SPDX-License-Identifier: MIT
"""Bidirectional settings synchronization"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("dxrk.config")

DEFAULT_SYNC_INTERVAL = 5 * 60  # seconds
SYNC_TIMEOUT = 30  # seconds


@dataclass
class SyncConfig:
    endpoint: str = ""
    api_key: str = ""
    device_id: str = ""
    interval: int = 0
    last_sync: Optional[datetime] = None


@dataclass
class SettingChange:
    key: str
    value: Any = None
    timestamp: Optional[datetime] = None
    device_id: str = ""
    operation: str = "set"


@dataclass
class SyncStatus:
    connected: bool = False
    last_sync: Optional[datetime] = None
    pending_push: int = 0
    error: str = ""


class ConflictResolution:
    LAST_WRITE_WINS = 0
    LOCAL_WINS = 1
    REMOTE_WINS = 2
    MANUAL = 3


ConflictLastWriteWins = ConflictResolution.LAST_WRITE_WINS
ConflictLocalWins = ConflictResolution.LOCAL_WINS
ConflictRemoteWins = ConflictResolution.REMOTE_WINS
ConflictManual = ConflictResolution.MANUAL


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SettingsSyncer:
    def __init__(self, config: SyncConfig, storage):
        if config.interval == 0:
            config.interval = DEFAULT_SYNC_INTERVAL
        self._mu = threading.RLock()
        self._config = config
        self._storage = storage
        self._resolver: int = ConflictLastWriteWins
        self._status = SyncStatus()
        self._queue: List[SettingChange] = []

    def SetResolver(self, resolver: int) -> None:
        with self._mu:
            self._resolver = resolver

    def Sync(self) -> None:
        with self._mu:
            self._status.error = ""
            local_changes = self._collect_local_changes()
            if local_changes:
                try:
                    self._push_locked(local_changes)
                except Exception as exc:
                    self._status.error = f"push: {exc}"
                    raise OSError(f"push changes: {exc}") from exc
            try:
                remote_changes = self._pull_locked()
            except Exception as exc:
                self._status.error = f"pull: {exc}"
                raise OSError(f"pull changes: {exc}") from exc
            if remote_changes:
                merged = self._resolve_conflicts_locked(local_changes, remote_changes)
                try:
                    self._apply_changes(merged)
                except Exception as exc:
                    self._status.error = f"apply: {exc}"
                    raise OSError(f"apply merged changes: {exc}") from exc
            self._status.last_sync = _now()
            self._config.last_sync = self._status.last_sync
            self._status.connected = True

    def Push(self, changes: List[SettingChange]) -> None:
        with self._mu:
            self._push_locked(changes)

    def _push_locked(self, changes: List[SettingChange]) -> None:
        if not self._config.endpoint:
            raise ValueError("no sync endpoint configured")
        payload = json.dumps([self._change_to_dict(c) for c in changes]).encode("utf-8")
        url = self._config.endpoint.rstrip("/") + "/api/v1/sync/push"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Device-ID", self._config.device_id)
        if self._config.api_key:
            req.add_header("Authorization", "Bearer " + self._config.api_key)
        try:
            with urllib.request.urlopen(req, timeout=SYNC_TIMEOUT) as resp:
                code = resp.getcode()
                if code != 200 and code != 201:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise OSError(f"push failed (status {code}): {body}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OSError(f"push failed (status {exc.code}): {body}") from exc

    def Pull(self) -> List[SettingChange]:
        with self._mu:
            return self._pull_locked()

    def _pull_locked(self) -> List[SettingChange]:
        if not self._config.endpoint:
            return []
        last = self._config.last_sync or datetime.fromtimestamp(0, tz=timezone.utc)
        since = last.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            self._config.endpoint.rstrip("/")
            + f"/api/v1/sync/pull?device_id={self._config.device_id}&since={since}"
        )
        req = urllib.request.Request(url, method="GET")
        if self._config.api_key:
            req.add_header("Authorization", "Bearer " + self._config.api_key)
        try:
            with urllib.request.urlopen(req, timeout=SYNC_TIMEOUT) as resp:
                if resp.getcode() != 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise OSError(f"pull failed (status {resp.getcode()}): {body}")
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OSError(f"pull failed (status {exc.code}): {body}") from exc
        return [self._change_from_dict(c) for c in raw]

    def ResolveConflicts(
        self, local: List[SettingChange], remote: List[SettingChange]
    ) -> List[SettingChange]:
        with self._mu:
            return self._resolve_conflicts_locked(local, remote)

    def _resolve_conflicts_locked(
        self, local: List[SettingChange], remote: List[SettingChange]
    ) -> List[SettingChange]:
        local_map: Dict[str, SettingChange] = {c.key: c for c in local}
        remote_map: Dict[str, SettingChange] = {c.key: c for c in remote}
        merged: Dict[str, SettingChange] = {}
        for key, rc in remote_map.items():
            lc = local_map.get(key)
            if lc is not None:
                if self._resolver == ConflictLocalWins:
                    merged[key] = lc
                elif self._resolver == ConflictRemoteWins:
                    merged[key] = rc
                elif self._resolver == ConflictLastWriteWins:
                    merged[key] = (
                        lc
                        if (lc.timestamp or _now()) > (rc.timestamp or _now())
                        else rc
                    )
                else:  # ConflictManual
                    merged[key] = rc
                    merged["__conflict__" + key] = lc
            else:
                merged[key] = rc
        for key, lc in local_map.items():
            if key not in remote_map:
                merged[key] = lc
        result = sorted(
            merged.values(),
            key=lambda c: c.timestamp or datetime.fromtimestamp(0, tz=timezone.utc),
        )
        return result

    def GetSyncStatus(self) -> SyncStatus:
        with self._mu:
            self._status.pending_push = len(self._queue)
            return SyncStatus(
                connected=self._status.connected,
                last_sync=self._status.last_sync,
                pending_push=self._status.pending_push,
                error=self._status.error,
            )

    def _collect_local_changes(self) -> List[SettingChange]:
        changes = []
        for key, val in self._storage.List().items():
            changes.append(
                SettingChange(
                    key=key,
                    value=val,
                    timestamp=_now(),
                    device_id=self._config.device_id,
                    operation="set",
                )
            )
        return changes

    def _apply_changes(self, changes: List[SettingChange]) -> None:
        for c in changes:
            if len(c.key) > 12 and c.key[:12] == "__conflict__":
                continue
            if c.operation == "delete":
                self._storage.Delete(c.key)
            else:
                self._storage.Set(c.key, c.value)

    def QueueChange(self, key: str, value: Any, operation: str = "set") -> None:
        with self._mu:
            self._queue.append(
                SettingChange(
                    key=key,
                    value=value,
                    timestamp=_now(),
                    device_id=self._config.device_id,
                    operation=operation,
                )
            )

    def FlushQueue(self) -> None:
        with self._mu:
            queue = self._queue
            self._queue = []
        if not queue:
            return
        self.Push(queue)

    @staticmethod
    def _change_to_dict(c: SettingChange) -> Dict[str, Any]:
        ts = c.timestamp
        return {
            "key": c.key,
            "value": c.value,
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None,
            "device_id": c.device_id,
            "operation": c.operation,
        }

    @staticmethod
    def _change_from_dict(d: Dict[str, Any]) -> SettingChange:
        ts = d.get("timestamp")
        parsed = None
        if ts:
            try:
                parsed = datetime.strptime(
                    str(ts).replace("Z", "+00:00"), "%Y-%m-%dT%H:%M:%S%z"
                )
            except ValueError:
                parsed = None
        return SettingChange(
            key=str(d.get("key", "")),
            value=d.get("value"),
            timestamp=parsed,
            device_id=str(d.get("device_id", "")),
            operation=str(d.get("operation", "set")),
        )


def NewSettingsSyncer(config: SyncConfig, storage) -> SettingsSyncer:
    return SettingsSyncer(config, storage)

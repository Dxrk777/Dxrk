# SPDX-License-Identifier: MIT
"""Permission store: capability gating for autonomy actions"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CapFSRead = "fs.read"
CapFSWrite = "fs.write"
CapGit = "git"
CapNetHTTP = "net.http"
CapDocker = "docker"
CapSudo = "sudo"
CapPkgInstall = "pkg.install"
CapExec = "exec"

CAPABILITIES = (
    CapFSRead,
    CapFSWrite,
    CapGit,
    CapNetHTTP,
    CapDocker,
    CapSudo,
    CapPkgInstall,
    CapExec,
)


class PermissionLevel(IntEnum):
    """Defined for parity; not used in current logic."""

    PermAllowed = 0
    PermAskBefore = 1
    PermDenied = 2


RequestFn = Callable[[str, str], tuple[bool, Optional[str]]]


class PermissionStore:
    """Tracks allowed, ask-first and denied capabilities plus one-off grants."""

    def __init__(self) -> None:
        self.allowed: set[str] = set()
        self.ask_first: set[str] = set()
        self.denied: set[str] = set()
        self.granted: dict[str, bool] = {}
        self.request_fn: Optional[RequestFn] = None

    def set_request_handler(self, fn: Optional[RequestFn]) -> None:
        self.request_fn = fn

    def check(self, cap: str, reason: str) -> Optional[str]:
        if cap in self.denied:
            return f'capability "{cap}" permanently denied'
        if cap in self.allowed:
            return None
        if cap in self.ask_first:
            return self._request_permission(cap, reason)
        return f'capability "{cap}" not granted'

    def grant(self, cap: str) -> None:
        self.granted[cap] = True
        self.allowed.add(cap)
        self.ask_first.discard(cap)

    def deny(self, cap: str, permanent: bool) -> None:
        if permanent:
            self.denied.add(cap)
        self.allowed.discard(cap)
        self.ask_first.discard(cap)

    def _request_permission(self, cap: str, reason: str) -> Optional[str]:
        if self.request_fn is None:
            return f'capability "{cap}" requires approval: {reason}'
        key = f"{cap}:{reason}"
        if self.granted.get(key):
            return None
        ok, err = self.request_fn(cap, reason)
        if err:
            return err
        if not ok:
            return f'capability "{cap}" denied: {reason}'
        self.granted[key] = True
        return None

    def all_granted(self) -> list[str]:
        return sorted(set(self.allowed) | set(self.granted))


def NewPermissionStore(caps: list[str], ask_before: list[str]) -> PermissionStore:
    store = PermissionStore()
    for cap in caps:
        cap = cap.strip()
        if cap == "":
            continue
        store.allowed.add(cap)
    for cap in ask_before:
        cap = cap.strip()
        if cap == "":
            continue
        store.ask_first.add(cap)
        store.allowed.discard(cap)
    return store

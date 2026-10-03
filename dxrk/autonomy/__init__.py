# SPDX-License-Identifier: MIT
"""Autonomy package (culled): only the capability store survives.

The self-update / self-verify / self-learn loop (autonomy, learner,
metrics, swarm, updater, evolution) was removed — unverified background
mutation has no place next to a memory palace. Verification lives on as
the external judge in :mod:`dxrk.judge` (observe-only, auto-fix
default-off). What remains here is the capability vocabulary
(``memory.maintain`` included) consumed by the RBAC layers in
:mod:`dxrk.security`.
"""

from .permissions import (
    CAPABILITIES,
    CapDocker,
    CapExec,
    CapFSRead,
    CapFSWrite,
    CapGit,
    CapMemoryMaintain,
    CapNetHTTP,
    CapPkgInstall,
    CapSudo,
    NewPermissionStore,
    PermissionStore,
)

__all__ = [
    "CAPABILITIES",
    "CapDocker",
    "CapExec",
    "CapFSRead",
    "CapFSWrite",
    "CapGit",
    "CapMemoryMaintain",
    "CapNetHTTP",
    "CapPkgInstall",
    "CapSudo",
    "NewPermissionStore",
    "PermissionStore",
]

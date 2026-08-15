# SPDX-License-Identifier: MIT
"""Autonomy package: self-update, self-verify, self-learn loop."""

from .autonomy import Autonomy, New
from .evolution import EvolutionEngine, Genome, NewEvolutionEngine
from .learner import Learner, MemoryItem, NewLearner, Pattern
from .metrics import IQMetrics, IQSnapshot, NewIQMetrics
from .permissions import (
    CapDocker,
    CapExec,
    CapFSRead,
    CapFSWrite,
    CapGit,
    CapNetHTTP,
    CapPkgInstall,
    CapSudo,
    NewPermissionStore,
    PermissionLevel,
    PermissionStore,
)
from .updater import NewUpdater, UpdateResult, Updater
from .verifier import NewVerifier, VerifyResult, Verifier

__all__ = [
    "Autonomy",
    "CapDocker",
    "CapExec",
    "CapFSRead",
    "CapFSWrite",
    "CapGit",
    "CapNetHTTP",
    "CapPkgInstall",
    "CapSudo",
    "EvolutionEngine",
    "Genome",
    "IQMetrics",
    "IQSnapshot",
    "Learner",
    "MemoryItem",
    "New",
    "NewEvolutionEngine",
    "NewIQMetrics",
    "NewLearner",
    "NewPermissionStore",
    "NewUpdater",
    "NewVerifier",
    "Pattern",
    "PermissionLevel",
    "PermissionStore",
    "UpdateResult",
    "Updater",
    "VerifyResult",
    "Verifier",
]

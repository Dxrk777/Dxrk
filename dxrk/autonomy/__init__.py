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
from .swarm import AgentRole, NewSwarmOrchestrator, SwarmOrchestrator, SwarmResult, SwarmTask
from .updater import NewUpdater, Updater, UpdateResult
from .verifier import NewVerifier, Verifier, VerifyResult

__all__ = [
    "AgentRole",
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
    "SwarmOrchestrator",
    "SwarmResult",
    "SwarmTask",
    "NewSwarmOrchestrator",
    "UpdateResult",
    "Updater",
    "VerifyResult",
    "Verifier",
]

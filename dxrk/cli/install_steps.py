# SPDX-License-Identifier: MIT
"""Pipeline steps used by the install runtime.

Facade over the install_steps_* submodules. Bodies live in the submodules;
this module re-exports the full namespace so existing imports
(`dxrk.cli.install`, `dxrk.cli.runtime_*`, patch targets in tests) keep working.
"""

from __future__ import annotations

from dxrk.cli.install_steps_agents import AgentInstallStep as AgentInstallStep
from dxrk.cli.install_steps_agents import CheckDependenciesStep as CheckDependenciesStep
from dxrk.cli.install_steps_agents import KimiSystemPromptHubStep as KimiSystemPromptHubStep
from dxrk.cli.install_steps_agents import OpenCodePluginInstallStep as OpenCodePluginInstallStep
from dxrk.cli.install_steps_backup import PrepareBackupStep as PrepareBackupStep
from dxrk.cli.install_steps_backup import RollbackRestoreStep as RollbackRestoreStep
from dxrk.cli.install_steps_base import NoopStep as NoopStep
from dxrk.cli.install_steps_base import _create_agent_adapter as _create_agent_adapter
from dxrk.cli.install_steps_base import _resolve_adapters as _resolve_adapters
from dxrk.cli.install_steps_base import log as log
from dxrk.cli.install_steps_components import ComponentApplyStep as ComponentApplyStep
from dxrk.cli.install_steps_components import _gga_available as _gga_available
from dxrk.cli.install_steps_components import _selected_skill_ids as _selected_skill_ids
from dxrk.cli.install_steps_components import _skills_for_preset as _skills_for_preset

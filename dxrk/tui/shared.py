# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any, cast

from dxrk.tui.context import TUIContext, ctx_var, get_ctx, set_ctx

# ---------------------------------------------------------------------------
# Legacy compatibility — AppState is now an alias of TUIContext.
# New code should import TUIContext from dxrk.tui.context and use
# ctx_var / get_ctx() / DxrkApp.ctx for DI.
# ---------------------------------------------------------------------------
AppState = TUIContext  # deprecated alias, kept for backward compat


class _StateProxy:
    """Proxy that forwards attribute access to the current ContextVar.

    This keeps `from dxrk.tui.shared import STATE` working after the
    migration to ContextVar DI. Legacy code mutates STATE.* and new
    code uses get_ctx() / app.ctx — both see the same underlying
    TUIContext via ctx_var.
    """

    def __getattr__(self, name: str) -> Any:
        return getattr(ctx_var.get(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(ctx_var.get(), name, value)

    def __repr__(self) -> str:
        return repr(ctx_var.get())


# STATE is deprecated — prefer get_ctx() or DxrkApp.ctx.
# Kept as proxy so existing imports remain functional and xdist-safe.
STATE: TUIContext = cast(TUIContext, _StateProxy())

# Re-export for convenience (allows `from dxrk.tui.shared import TUIContext`).
__all__ = [
    "AppState",
    "TUIContext",
    "ctx_var",
    "get_ctx",
    "set_ctx",
    "STATE",
    "SCREEN_FLOW",
    "NEXT",
    "PREV",
    "go_next",
    "go_back",
]


SCREEN_FLOW: dict[str, dict[str, str | None]] = {
    "welcome": {"forward": "detection", "backward": None},
    "detection": {"forward": "agents", "backward": "welcome"},
    "agents": {"forward": "persona", "backward": "detection"},
    "persona": {"forward": "preset", "backward": "agents"},
    "preset": {"forward": "claude_model_picker", "backward": "persona"},
    "claude_model_picker": {"forward": "kiro_model_picker", "backward": "preset"},
    "kiro_model_picker": {"forward": "sdd_mode", "backward": "claude_model_picker"},
    "sdd_mode": {"forward": "strict_tdd", "backward": "preset"},
    "strict_tdd": {"forward": "dependency_tree", "backward": "sdd_mode"},
    "model_picker": {"forward": "dependency_tree", "backward": "sdd_mode"},
    "model_select": {"forward": "model_picker", "backward": "model_picker"},
    "dependency_tree": {"forward": "review", "backward": "preset"},
    "skill_picker": {"forward": "review", "backward": "dependency_tree"},
    "review": {"forward": "installing", "backward": "dependency_tree"},
    "installing": {"forward": "complete", "backward": "review"},
    "complete": {"forward": None, "backward": "welcome"},
    "backups": {"forward": None, "backward": "welcome"},
    "upgrade": {"forward": None, "backward": "welcome"},
    "sync": {"forward": None, "backward": "welcome"},
    "upgrade_sync": {"forward": None, "backward": "welcome"},
    "model_config": {"forward": None, "backward": "welcome"},
    "profiles": {"forward": None, "backward": "welcome"},
    "uninstall_mode": {"forward": None, "backward": "welcome"},
    "restore_confirm": {"forward": None, "backward": "backups"},
    "restore_result": {"forward": None, "backward": "backups"},
    "delete_confirm": {"forward": None, "backward": "backups"},
    "delete_result": {"forward": None, "backward": "backups"},
    "rename_backup": {"forward": None, "backward": "backups"},
    "agent_builder_engine": {"forward": None, "backward": "welcome"},
    "opencode_plugins": {"forward": None, "backward": "welcome"},
    "uninstall": {"forward": None, "backward": "uninstall_mode"},
    "tenant_switcher": {"forward": None, "backward": "welcome"},
}

NEXT = {k: v["forward"] for k, v in SCREEN_FLOW.items()}
PREV = {k: v["backward"] for k, v in SCREEN_FLOW.items()}


def go_next(current: str) -> str | None:
    n = NEXT.get(current)
    if n is not None:
        return n
    return None


def go_back(current: str) -> str | None:
    return PREV.get(current)

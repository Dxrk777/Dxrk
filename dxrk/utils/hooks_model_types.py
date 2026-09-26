# SPDX-License-Identifier: MIT
"""Hook event types and parsing."""

from __future__ import annotations

from enum import IntEnum

# Mirrors dxrk/strconst.StrUnknown / dxrk/strconst.StrError.
_STR_UNKNOWN = "unknown"
_STR_ERROR = "error"

_DISCARD = "<discard>"


class HookType(IntEnum):
    """Represents the type of hook event. Mirrors hooks.HookType."""

    PRE_TOOL_USE = 0
    POST_TOOL_USE = 1
    USER_PROMPT_SUBMIT = 2
    NOTIFICATION = 3
    STOP = 4
    SUBAGENT_STOP = 5

    def string(self) -> str:
        """Return the hook type name. Mirrors HookType.String()."""
        names = (
            "pre_tool_use",
            "post_tool_use",
            "user_prompt_submit",
            "notification",
            "stop",
            "subagent_stop",
        )
        if int(self) < len(names):
            return names[int(self)]
        return _STR_UNKNOWN


PreToolUse = HookType.PRE_TOOL_USE
PostToolUse = HookType.POST_TOOL_USE
UserPromptSubmit = HookType.USER_PROMPT_SUBMIT
Notification = HookType.NOTIFICATION
Stop = HookType.STOP
SubagentStop = HookType.SUBAGENT_STOP


def _hook_type_name(ht: HookType | int) -> str:
    """Name of a hook type, allowing out-of-range ints."""
    if isinstance(ht, HookType):
        return ht.string()
    names = (
        "pre_tool_use",
        "post_tool_use",
        "user_prompt_submit",
        "notification",
        "stop",
        "subagent_stop",
    )
    if 0 <= int(ht) < len(names):
        return names[int(ht)]
    return _STR_UNKNOWN


def ParseHookType(s: str) -> tuple[HookType, bool]:
    """Parse a hook type name. Mirrors hooks.ParseHookType."""
    if s == "pre_tool_use":
        return PreToolUse, True
    if s == "post_tool_use":
        return PostToolUse, True
    if s == "user_prompt_submit":
        return UserPromptSubmit, True
    if s == "notification":
        return Notification, True
    if s == "stop":
        return Stop, True
    if s == "subagent_stop":
        return SubagentStop, True
    return HookType.PRE_TOOL_USE, False

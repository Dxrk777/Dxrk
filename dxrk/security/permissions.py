# SPDX-License-Identifier: MIT
"""Permission rule pipeline: 5-layer hierarchy with allow/deny rules"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---- Permission Rule Sources (5-layer hierarchy) ----


class SettingSource(IntEnum):
    USER = 0  # ~/.claude/settings.json
    PROJECT = 1  # .claude/settings.json (committed)
    LOCAL = 2  # .claude/settings.local.json (gitignored)
    FLAG = 3  # --allowedTools / --disallowedTools
    POLICY = 4  # Enterprise policy (highest priority)
    UNKNOWN = 99

    def __str__(self) -> str:
        if self == SettingSource.USER:
            return "user"
        if self == SettingSource.PROJECT:
            return "project"
        if self == SettingSource.LOCAL:
            return "local"
        if self == SettingSource.FLAG:
            return "flag"
        if self == SettingSource.POLICY:
            return "policy"
        return "unknown"

    def priority(self) -> int:
        """Return the evaluation priority (higher = evaluated first)."""
        if self == SettingSource.POLICY:
            return 50
        if self == SettingSource.FLAG:
            return 40
        if self == SettingSource.LOCAL:
            return 30
        if self == SettingSource.PROJECT:
            return 20
        if self == SettingSource.USER:
            return 10
        return 0


# ---- Permission Rules ----


class PermissionBehavior(IntEnum):
    ALLOW = 0
    DENY = 1

    def __str__(self) -> str:
        if self == PermissionBehavior.ALLOW:
            return "allow"
        return "deny"


@dataclass
class PermissionRule:
    tool: str  # "Bash", "Read", "Write", etc.
    prefix: str = ""  # "git commit" — exact prefix match
    pattern: str = ""  # "npm test *" — glob pattern
    behavior: PermissionBehavior = PermissionBehavior.ALLOW
    source: SettingSource = SettingSource.USER


@dataclass
class ToolPermissionRulesConfig:
    permissions: List[PermissionRule]


# ---- Permission Pipeline ----


class PermissionResult(IntEnum):
    ALLOWED = 0
    DENIED = 1
    NEEDS_PROMPT = 2
    UNKNOWN = 99

    def __str__(self) -> str:
        if self == PermissionResult.ALLOWED:
            return "allowed"
        if self == PermissionResult.DENIED:
            return "denied"
        if self == PermissionResult.NEEDS_PROMPT:
            return "needs_prompt"
        return "unknown"


class PermissionContext:
    """Hold the state for permission checking."""

    def __init__(self) -> None:
        self._rules: List[PermissionRule] = []
        self._denials: Dict[str, int] = {}
        self.max_denials: int = 5  # after 5 denials, auto-deny for session

    def load_rules_from_file(self, path: str, source: SettingSource) -> None:
        """Load permission rules from a JSON settings file.

        Raises ValueError on unreadable/unparseable files; a missing file is not an error.
        """
        p = Path(path)
        if not p.exists():
            return None
        try:
            data = p.read_text()
        except OSError as err:
            raise ValueError(f"read permissions file {path!r}: {err}") from err

        try:
            config = json.loads(data)
        except json.JSONDecodeError as err:
            raise ValueError(f"parse permissions file {path!r}: {err}") from err

        permissions = config.get("permissions", []) if isinstance(config, dict) else []
        for r in permissions:
            if not isinstance(r, dict):
                continue
            behavior = PermissionBehavior.ALLOW
            if r.get("behavior") == "deny":
                behavior = PermissionBehavior.DENY
            self._rules.append(
                PermissionRule(
                    tool=r.get("tool", ""),
                    prefix=r.get("prefix", ""),
                    pattern=r.get("pattern", ""),
                    behavior=behavior,
                    source=source,
                )
            )
        return None

    def load_all_sources(self, home_dir: str, project_dir: str) -> None:
        """Load rules from all standard file locations."""
        sources = [
            (str(Path(home_dir) / ".claude" / "settings.json"), SettingSource.USER),
            (
                str(Path(project_dir) / ".claude" / "settings.json"),
                SettingSource.PROJECT,
            ),
            (
                str(Path(project_dir) / ".claude" / "settings.local.json"),
                SettingSource.LOCAL,
            ),
        ]

        for path, source in sources:
            self.load_rules_from_file(path, source)
        return None

    def add_flag_rules(self, tools: List[str], behavior: PermissionBehavior) -> None:
        """Add rules from CLI flags."""
        for tool in tools:
            self._rules.append(
                PermissionRule(tool=tool, behavior=behavior, source=SettingSource.FLAG)
            )

    def add_policy_rules(self, rules: List[PermissionRule]) -> None:
        """Add rules from enterprise policy."""
        for r in rules:
            r.source = SettingSource.POLICY
            self._rules.append(r)

    def check(self, tool_name: str, command: str) -> Tuple[PermissionResult, str]:
        """Evaluate whether a tool+command is allowed, denied, or needs prompting.

        Priority: policy > flag > local > project > user.
        """
        # Check auto-deny threshold
        if self._denials.get(tool_name, 0) >= self.max_denials:
            return (
                PermissionResult.DENIED,
                f"auto-denied after {self.max_denials} denials",
            )

        # Stable sort by priority (descending)
        sorted_rules = sorted(
            self._rules, key=lambda r: r.source.priority(), reverse=True
        )

        # Evaluate rules: first matching rule at highest priority wins
        highest_priority = -1
        best_result = PermissionResult.NEEDS_PROMPT
        best_reason = "no matching rule"

        for rule in sorted_rules:
            if not _matches_rule(rule, tool_name, command):
                continue
            priority = rule.source.priority()
            if priority > highest_priority:
                highest_priority = priority
                if rule.behavior == PermissionBehavior.DENY:
                    best_result = PermissionResult.DENIED
                    best_reason = f"denied by {rule.source} rule"
                else:
                    best_result = PermissionResult.ALLOWED
                    best_reason = f"allowed by {rule.source} rule"

        if highest_priority >= 0:
            return best_result, best_reason

        # No rule matched — needs prompting
        return PermissionResult.NEEDS_PROMPT, "no matching rule"

    def record_denial(self, tool_name: str) -> None:
        """Increment the denial count for a tool."""
        self._denials[tool_name] = self._denials.get(tool_name, 0) + 1

    def reset_denials(self) -> None:
        """Clear all denial counts."""
        self._denials = {}

    def rules(self) -> List[PermissionRule]:
        """Return a copy of all loaded rules."""
        return list(self._rules)


# ---- Rule Matching ----


def _matches_rule(rule: PermissionRule, tool_name: str, command: str) -> bool:
    if rule.tool.casefold() != tool_name.casefold():
        return False

    # If no prefix/pattern, matches any invocation of the tool
    if rule.prefix == "" and rule.pattern == "":
        return True

    cmd = command.strip()

    # Exact prefix match (word-aligned)
    if rule.prefix != "":
        if cmd.startswith(rule.prefix):
            # Word boundary check
            rest = cmd[len(rule.prefix) :]
            if len(rest) == 0 or rest[0] == " " or rest[0] == "\t":
                return True

    # Glob pattern match
    if rule.pattern != "":
        if _match_glob(rule.pattern, cmd):
            return True

    return False


def _match_glob(pattern: str, s: str) -> bool:
    """Perform simple glob matching (* and ?)."""
    pi, si = 0, 0
    star_pi, star_si = -1, -1

    while si < len(s):
        if pi < len(pattern) and (pattern[pi] == "?" or pattern[pi] == s[si]):
            pi += 1
            si += 1
            continue
        if pi < len(pattern) and pattern[pi] == "*":
            star_pi = pi
            star_si = si
            pi += 1
            continue
        if star_pi >= 0:
            pi = star_pi + 1
            star_si += 1
            si = star_si
            continue
        return False

    while pi < len(pattern) and pattern[pi] == "*":
        pi += 1
    return pi == len(pattern)


# ---- Standard Tool Permissions ----


# SafeTools lists tools that are always allowed without prompting.
SAFE_TOOLS: Dict[str, bool] = {
    "Read": True,
    "Glob": True,
    "Grep": True,
    "LS": True,
    "ListFiles": True,
    "TodoRead": True,
}

# AlwaysAskTools lists tools that always require user approval.
ALWAYS_ASK_TOOLS: Dict[str, bool] = {
    "Bash": True,
    "Execute": True,
}

# ReadOnlyTools lists tools that are read-only.
READ_ONLY_TOOLS: Dict[str, bool] = {
    "Read": True,
    "Glob": True,
    "Grep": True,
    "LS": True,
    "ListFiles": True,
    "TodoRead": True,
    "WebFetch": True,
    "WebSearch": True,
}


def classify_tool(tool_name: str) -> PermissionResult:
    """Determine if a tool is safe, needs asking, or is denied."""
    if tool_name in SAFE_TOOLS:
        return PermissionResult.ALLOWED
    # Unknown tools need prompting
    return PermissionResult.NEEDS_PROMPT


def detect_unreachable_rules(rules: List[PermissionRule]) -> List[str]:
    """Find rules shadowed by higher-priority rules."""
    unreachable: List[str] = []

    # Group by tool+prefix/pattern
    groups: Dict[Tuple[str, str], List[PermissionRule]] = {}
    for r in rules:
        match = r.prefix
        if match == "":
            match = r.pattern
        key = (r.tool, match)
        groups.setdefault(key, []).append(r)

    for (tool, match), group in groups.items():
        if len(group) <= 1:
            continue
        # Find highest priority
        highest = group[0]
        for r in group[1:]:
            if r.source.priority() > highest.source.priority():
                highest = r
        # All others are unreachable
        for r in group:
            if r != highest:
                unreachable.append(
                    f"rule {r.tool}/{match} ({r.behavior}) shadowed by {highest.tool}/{match} ({highest.behavior})"
                )

    return unreachable

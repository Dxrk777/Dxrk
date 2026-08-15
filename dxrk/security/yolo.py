# SPDX-License-Identifier: MIT
"""Auto-mode tool classification, bash risk assessment, and circuit breaker"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from .ast import extract_command_name, is_read_only_command, parse_for_security

# ---- Auto-Mode Tool Classification ----


class RiskLevel(IntEnum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
    UNKNOWN = 99

    def __str__(self) -> str:
        if self == RiskLevel.NONE:
            return "none"
        if self == RiskLevel.LOW:
            return "low"
        if self == RiskLevel.MEDIUM:
            return "medium"
        if self == RiskLevel.HIGH:
            return "high"
        if self == RiskLevel.CRITICAL:
            return "critical"
        return "unknown"


@dataclass
class ClassificationDecision:
    action: str  # "allow", "ask", "deny"
    risk: RiskLevel
    reason: str
    tool_name: str
    command: str = ""


# ---- Tool Risk Profiles ----


# SafeForAutoMode tools that can run without user confirmation in auto mode.
SAFE_FOR_AUTO_MODE: dict[str, bool] = {
    "Read": True,
    "Glob": True,
    "Grep": True,
    "LS": True,
    "ListFiles": True,
    "TodoRead": True,
    "WebSearch": True,
    "WebFetch": True,
}

# NeedsConfirmation tools that always need user confirmation.
NEEDS_CONFIRMATION: dict[str, bool] = {
    "Bash": True,
    "Execute": True,
    "Write": True,
    "Edit": True,
    "MultiEdit": True,
}

# ReadTools tools that are read-only.
READ_TOOLS: dict[str, bool] = {
    "Read": True,
    "Glob": True,
    "Grep": True,
    "LS": True,
    "ListFiles": True,
    "TodoRead": True,
    "WebSearch": True,
    "WebFetch": True,
}


def classify_for_auto_mode(tool_name: str, command: str) -> ClassificationDecision:
    """Determine the action for a tool in auto mode."""
    # Always ask for dangerous tools
    if tool_name in NEEDS_CONFIRMATION:
        return ClassificationDecision(
            action="ask",
            risk=RiskLevel.HIGH,
            reason=f'tool "{tool_name}" requires confirmation',
            tool_name=tool_name,
            command=command,
        )

    # Safe for auto mode
    if tool_name in SAFE_FOR_AUTO_MODE:
        return ClassificationDecision(
            action="allow",
            risk=RiskLevel.NONE,
            reason=f'tool "{tool_name}" is safe for auto mode',
            tool_name=tool_name,
            command=command,
        )

    # Unknown tool — ask
    return ClassificationDecision(
        action="ask",
        risk=RiskLevel.MEDIUM,
        reason=f'unknown tool "{tool_name}" — requires confirmation',
        tool_name=tool_name,
        command=command,
    )


# ---- Bash Command Risk Assessment ----


def assess_bash_risk(command: str) -> RiskLevel:
    """Evaluate the risk level of a bash command."""
    if command == "":
        return RiskLevel.NONE

    result = parse_for_security(command)

    if not result.is_safe:
        return RiskLevel.HIGH

    name = extract_command_name(command)
    if name == "":
        return RiskLevel.MEDIUM

    # Check for read-only commands
    if is_read_only_command(command):
        return RiskLevel.LOW

    # Check for file modification commands
    modify_cmds: dict[str, bool] = {
        "rm": True,
        "mv": True,
        "cp": True,
        "chmod": True,
        "chown": True,
        "mkdir": True,
        "rmdir": True,
        "touch": True,
        "ln": True,
        "dd": True,
        "mkfs": True,
    }
    if name in modify_cmds:
        return RiskLevel.MEDIUM

    # Check for network commands
    network_cmds: dict[str, bool] = {
        "curl": True,
        "wget": True,
        "nc": True,
        "ncat": True,
        "socat": True,
        "ssh": True,
        "scp": True,
        "rsync": True,
        "telnet": True,
    }
    if name in network_cmds:
        return RiskLevel.MEDIUM

    # Check for system commands
    system_cmds: dict[str, bool] = {
        "kill": True,
        "pkill": True,
        "killall": True,
        "systemctl": True,
        "service": True,
        "mount": True,
        "umount": True,
        "fdisk": True,
        "crontab": True,
        "at": True,
    }
    if name in system_cmds:
        return RiskLevel.HIGH

    return RiskLevel.LOW


# ---- Dangerous Command Patterns ----


@dataclass
class DangerousPattern:
    pattern: str
    reason: str
    risk: RiskLevel
    tool_names: list[str] = field(default_factory=list)  # which tools this applies to


# KnownDangerousPatterns lists patterns that should always be flagged.
KNOWN_DANGEROUS_PATTERNS: list[DangerousPattern] = [
    DangerousPattern(
        pattern="rm -rf /",
        reason="recursive deletion of root filesystem",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="rm -rf ~",
        reason="recursive deletion of home directory",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="mkfs",
        reason="filesystem formatting",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern=":(){ :|:& };:",
        reason="fork bomb",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="dd if=/dev/zero",
        reason="disk zeroing",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="chmod -R 777",
        reason="world-writable recursive permissions",
        risk=RiskLevel.HIGH,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="curl | sh",
        reason="pipe remote code to shell",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="wget | sh",
        reason="pipe remote code to shell",
        risk=RiskLevel.CRITICAL,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="eval $",
        reason="eval of variable expansion",
        risk=RiskLevel.HIGH,
        tool_names=["Bash"],
    ),
    DangerousPattern(
        pattern="exec ",
        reason="process replacement",
        risk=RiskLevel.HIGH,
        tool_names=["Bash"],
    ),
]


def check_dangerous_patterns(command: str, tool_name: str) -> list[DangerousPattern]:
    """Scan a command against known dangerous patterns."""
    matches: list[DangerousPattern] = []
    cmd_lower = command.lower()

    for dp in KNOWN_DANGEROUS_PATTERNS:
        if len(dp.tool_names) > 0:
            found = False
            for t in dp.tool_names:
                if t == tool_name:
                    found = True
                    break
            if not found:
                continue
        if dp.pattern in cmd_lower:
            matches.append(dp)

    return matches


# ---- Circuit Breaker ----


class CircuitBreaker:
    """Track auto-mode circuit breaker status."""

    def __init__(self, threshold: int, reset_after_sec: int) -> None:
        self.tripped: bool = False
        self.trip_count: int = 0
        self.trip_threshold: int = threshold
        self.last_trip: int = 0  # unix timestamp
        self.reset_after: int = reset_after_sec  # seconds

    def record_failure(self) -> bool:
        """Record a failure and trip the breaker if threshold reached."""
        self.trip_count += 1
        if self.trip_count >= self.trip_threshold:
            self.tripped = True
            return True  # breaker tripped
        return False

    def reset(self) -> None:
        """Clear the circuit breaker state."""
        self.tripped = False
        self.trip_count = 0
        self.last_trip = 0

    def should_block(self) -> bool:
        """Return True if the circuit breaker is tripped."""
        return self.tripped

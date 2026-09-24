# SPDX-License-Identifier: MIT
"""Context-window management with token budgeting and compaction strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from dxrk.utils.messages_model import _ZERO_TIME, ContentType, EstimateTokens, Message, Role


class CompactStrategy(IntEnum):
    """how messages are selected for removal."""

    CompactOldest = 0
    CompactToolResults = 1
    CompactByImportance = 2
    CompactRecursive = 3


@dataclass
class MessageScore:
    """a message and its compaction score."""

    message: Message
    score: float
    reason: str


def ScoreMessages(msgs: list[Message]) -> list[MessageScore]:
    """Rank messages by importance for compaction decisions.

    Scoring factors: recency (newer = higher), role priority
    (user > system > assistant > tool), tool error status (errors kept
    longer), and content size (large tool results penalized).
    """
    if len(msgs) == 0:
        return []
    scores: list[MessageScore] = []
    now = msgs[-1].timestamp

    role_base = {
        Role.RoleUser: 100,
        Role.RoleSystem: 90,
        Role.RoleAssistant: 70,
        Role.RoleToolUse: 50,
        Role.RoleToolResult: 30,
    }

    for i, m in enumerate(msgs):
        score: float = role_base.get(m.role, 40)

        if now != _ZERO_TIME and m.timestamp != _ZERO_TIME:
            age = (now - m.timestamp).total_seconds() / 60.0
            recency_bonus = 50.0 / (1.0 + age / 30.0)
            score += recency_bonus

        token_size = m.EstimateTokens()
        if token_size > 500:
            score -= (token_size - 500) / 100.0

        if m.role is Role.RoleToolResult:
            for c in m.contents:
                if c.type is ContentType.ContentToolResult and c.tool_result is not None and c.tool_result.is_error:
                    score += 20

        if i == 0 or i == len(msgs) - 1:
            score += 30

        scores.append(
            MessageScore(
                message=m,
                score=score,
                reason=f"role={m.role.String()} tokens={token_size}",
            )
        )
    return scores


class WindowFullError(Exception):
    """the context window cannot accept more."""


class NoMessagesError(Exception):
    """compaction on an empty window."""


@dataclass
class ContextWindow:
    """messages within a token budget."""

    messages: list[Message] = field(default_factory=list)
    token_count: int = 0
    max_tokens: int = 0
    system_prompt: str = ""
    truncated: bool = False

    def SetSystemPrompt(self, prompt: str) -> None:
        """Set the system prompt, counting its tokens toward the budget."""
        self.system_prompt = prompt
        self._recount_tokens()

    def AddMessage(self, msg: Message) -> None:
        """Add a message, auto-dropping older messages on overflow."""
        tokens = msg.EstimateTokens()
        system_tokens = EstimateTokens(self.system_prompt)

        if tokens + system_tokens > self.max_tokens:
            raise WindowFullError(
                f"context window full: message ({tokens} tokens) exceeds window budget ({self.max_tokens} tokens)"
            )

        self.messages.append(msg)
        self.token_count += tokens

        while self.token_count + system_tokens > self.max_tokens and len(self.messages) > 1:
            self._drop_oldest()
            self.truncated = True

    def _drop_oldest(self) -> None:
        for i, m in enumerate(self.messages):
            if m.role is not Role.RoleSystem:
                self.token_count -= m.EstimateTokens()
                del self.messages[i]
                return
        if len(self.messages) > 0:
            self.token_count -= self.messages[0].EstimateTokens()
            del self.messages[0]

    def GetMessages(self) -> list[Message]:
        """Return the current window contents (a copy)."""
        return list(self.messages)

    def RemainingTokens(self) -> int:
        """Return how many tokens are left in the budget."""
        system_tokens = EstimateTokens(self.system_prompt)
        remaining = self.max_tokens - self.token_count - system_tokens
        if remaining < 0:
            return 0
        return remaining

    def NeedsCompaction(self) -> bool:
        """Return True if the window is above 80% capacity."""
        system_tokens = EstimateTokens(self.system_prompt)
        used = self.token_count + system_tokens
        return float(used) >= float(self.max_tokens) * 0.8

    def Compact(self, strategy: CompactStrategy) -> None:
        """Reduce the window contents using the specified strategy."""
        if len(self.messages) == 0:
            raise NoMessagesError("no messages to compact")

        if strategy is CompactStrategy.CompactOldest:
            self._compact_oldest()
        elif strategy is CompactStrategy.CompactToolResults:
            self._compact_tool_results()
        elif strategy is CompactStrategy.CompactByImportance:
            self._compact_by_importance()
        elif strategy is CompactStrategy.CompactRecursive:
            self._compact_recursive()
        else:
            raise ValueError(f"unknown compact strategy: {int(strategy)}")

        self._recount_tokens()

    def _compact_oldest(self) -> None:
        system_tokens = EstimateTokens(self.system_prompt)
        target = self.max_tokens // 2

        while self.token_count + system_tokens > target and len(self.messages) > 2:
            self._drop_oldest()
            self.truncated = True

    def _compact_tool_results(self) -> None:
        i = 0
        while i < len(self.messages):
            m = self.messages[i]
            if m.role is Role.RoleToolResult:
                self.token_count -= m.EstimateTokens()
                del self.messages[i]
                self.truncated = True
            else:
                i += 1

    def _compact_by_importance(self) -> None:
        system_tokens = EstimateTokens(self.system_prompt)
        target = self.max_tokens // 2

        scores = sorted(ScoreMessages(self.messages), key=lambda s: s.score)
        for s in scores:
            if self.token_count + system_tokens <= target:
                break
            for i, m in enumerate(self.messages):
                if m.id == s.message.id or (m.timestamp == s.message.timestamp and m.role is s.message.role):
                    self.token_count -= m.EstimateTokens()
                    del self.messages[i]
                    self.truncated = True
                    break

    def _compact_recursive(self) -> None:
        max_iters = 10
        for _ in range(max_iters):
            if not self.NeedsCompaction():
                break
            scores = ScoreMessages(self.messages)
            if len(scores) == 0:
                break

            min_score = min(scores, key=lambda s: s.score)
            target = min_score.message
            for i, m in enumerate(self.messages):
                if m.timestamp == target.timestamp and m.role is target.role:
                    self.token_count -= m.EstimateTokens()
                    del self.messages[i]
                    self.truncated = True
                    break

    def _recount_tokens(self) -> None:
        self.token_count = 0
        for m in self.messages:
            self.token_count += m.EstimateTokens()


def NewContextWindow(max_tokens: int) -> ContextWindow:
    """Create a window with the given maximum token budget."""
    return ContextWindow(max_tokens=max_tokens)

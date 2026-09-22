# SPDX-License-Identifier: MIT

"""Permission policy engine: rule matching and evaluation."""

from __future__ import annotations

import json
import re
import threading

from dxrk.utils.permissions_model import Action as Action
from dxrk.utils.permissions_model import Condition as Condition
from dxrk.utils.permissions_model import EvalContext as EvalContext
from dxrk.utils.permissions_model import Operator as Operator
from dxrk.utils.permissions_model import ParseOperator as ParseOperator
from dxrk.utils.permissions_model import Policy as Policy
from dxrk.utils.permissions_model import Rule as Rule
from dxrk.utils.permissions_model import Strategy as Strategy

# ---- Policy Engine ----


def _match_glob(pattern: str, s: str) -> bool:
    """Simple glob matching (* and ?). Mirrors permissions.matchGlob."""
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


def _match_field(pattern: str, value: str) -> bool:
    """Match a field value against a pattern. Mirrors permissions.matchField."""
    if pattern == "" or pattern == "*":
        return True
    return _match_glob(pattern, value)


class PolicyEngine:
    """Evaluates rules against contexts. Mirrors permissions.PolicyEngine."""

    def __init__(self, p: Policy) -> None:
        if p.strategy == 0:
            p = Policy(
                name=p.name,
                version=p.version,
                rules=p.rules,
                default_action=p.default_action,
                strategy=Strategy.FirstMatch,
            )
        self._mu = threading.RLock()
        self._policy = p
        self._compiled: dict[str, re.Pattern[str]] = {}

    def Evaluate(
        self, ctx: EvalContext
    ) -> tuple[Action, Rule | None, Exception | None]:
        """Evaluate all rules against the context."""
        with self._mu:
            matches: list[Rule] = []
            for rule in self._policy.rules:
                if self._matches_rule(rule, ctx):
                    matches.append(rule)

            if not matches:
                return self._policy.default_action, None, None

            if self._policy.strategy == Strategy.MostRestrictive:
                return self._most_restrictive(matches), matches[0], None

            best = matches[0]
            for m in matches[1:]:
                if m.priority > best.priority:
                    best = m
            return best.action, best, None

    def _most_restrictive(self, rules: list[Rule]) -> Action:
        best = Action.Allow
        for r in rules:
            if r.action == Action.Deny:
                return Action.Deny
            if r.action == Action.Ask and best == Action.Allow:
                best = Action.Ask
        return best

    def AddRule(self, rule: Rule) -> None:
        """Append a rule to the policy."""
        with self._mu:
            self._policy.rules.append(rule)

    def RemoveRule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        with self._mu:
            for i, r in enumerate(self._policy.rules):
                if r.id == rule_id:
                    del self._policy.rules[i]
                    return True
        return False

    def GetRules(self) -> list[Rule]:
        """Return a copy of all rules."""
        with self._mu:
            return list(self._policy.rules)

    def Merge(self, other: PolicyEngine) -> None:
        """Combine rules from another engine into this one (no dedup)."""
        other_rules = other.GetRules()
        with self._mu:
            self._policy.rules.extend(other_rules)

    def Validate(self) -> Exception | None:
        """Check for empty IDs and duplicate rule IDs."""
        with self._mu:
            seen: dict[str, int] = {}
            for i, r in enumerate(self._policy.rules):
                if r.id == "":
                    return Exception(f"rule at index {i} has empty ID")
                prev = seen.get(r.id)
                if prev is not None:
                    return Exception(
                        f"duplicate rule ID {json.dumps(r.id)} at indices {prev} and {i}"
                    )
                seen[r.id] = i
        return None

    def Policy(self) -> Policy:
        """Return a copy of the underlying policy."""
        with self._mu:
            return Policy(
                name=self._policy.name,
                version=self._policy.version,
                rules=list(self._policy.rules),
                default_action=self._policy.default_action,
                strategy=self._policy.strategy,
            )

    # ---- Rule matching ----

    def _matches_rule(self, r: Rule, ctx: EvalContext) -> bool:
        if not _match_field(r.subject, ctx.user):
            return False
        if not _match_field(r.resource, ctx.tool_name) and not _match_field(
            r.resource, ctx.resource
        ):
            return False
        for cond in r.conditions:
            if not self._eval_condition(cond, ctx):
                return False
        return True

    def _eval_condition(self, c: Condition, ctx: EvalContext) -> bool:
        val = ctx.fieldValue(c.field)
        op, err = ParseOperator(c.operator)
        if err is not None:
            return False

        if op == Operator.OpEq:
            return val == c.value
        if op == Operator.OpNeq:
            return val != c.value
        if op == Operator.OpGlob:
            return _match_glob(c.value, val)
        if op == Operator.OpRegex:
            return self._eval_regex(c.value, val)
        if op == Operator.OpIn:
            for item in c.value.split(","):
                if item.strip() == val:
                    return True
            return False
        if op == Operator.OpGt:
            return val > c.value
        if op == Operator.OpLt:
            return val < c.value
        return False

    def _eval_regex(self, pattern: str, value: str) -> bool:
        re_pat = self._compiled.get(pattern)
        if re_pat is not None:
            return re_pat.search(value) is not None
        try:
            re_pat = re.compile(pattern)
        except re.error:
            return False
        self._compiled[pattern] = re_pat
        return re_pat.search(value) is not None


def NewPolicyEngine(p: Policy) -> PolicyEngine:
    """Create an engine from a policy. Mirrors permissions.NewPolicyEngine."""
    return PolicyEngine(p)

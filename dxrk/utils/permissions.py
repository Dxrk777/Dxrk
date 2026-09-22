# SPDX-License-Identifier: MIT
"""Permission management, policy evaluation, and access control utilities.

Implements a multi-layered permission system: a rule-based policy engine with
conditions/priorities, a 5-layer policy hierarchy (Organization > Project >
User > Session > Default), a thread-safe TTL/LRU permission cache with disk
persistence, tool/resource classification with risk assessment, and a
ring-buffer audit trail with query, export, and streaming.

Concurrency mapping:

* ``time.Time`` -> ``datetime`` (UTC; zero time is ``_ZERO_TIME``)
* ``time.Duration`` -> ``datetime.timedelta``
* ``sync.RWMutex`` -> ``threading.RLock`` (``sync.Mutex`` -> ``threading.Lock``)
* channels -> ``queue.Queue``

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``ParseAction``/``ParseOperator`` are case-insensitive.
* ``Operator`` strings are ``eq``/``neq``/``glob``/``regex``/``in``/``gt``/``lt``;
  ``Condition.operator`` is a string parsed at evaluation time, and an invalid
  operator fails the condition.
* ``EvalContext.fieldValue`` lowercases field names, accepts the aliases
  ``tool``/``dir``, and falls back to ``env_vars`` then ``metadata``.
* ``matchesRule`` matches ``rule.resource`` against BOTH the tool name and the
  resource value.
* ``PolicyEngine.Evaluate`` with ``Strategy.FirstMatch`` returns the matching
  rule with the highest priority; ``MostRestrictive`` returns the first
  matching rule alongside the most restrictive action.
* ``PolicyEngine.Merge`` appends every rule from the other engine (no dedup).
* ``NewPolicyEngine``/``UnmarshalPolicyJSON`` default a zero strategy to
  ``FirstMatch``.
* Policy JSON mirrors the original json tags exactly: lowercase keys (``name``/
  ``version``/``rules``/``default_action``/``strategy``, rule fields
  ``id``/``subject``/``resource``/``action``/``conditions``/``priority``,
  ``conditions`` omitted when empty) and actions/strategies serialized as ints.
  The layered-policy wrapper uses capitalized ``Layer``/``Policy`` keys because
  the original ``LayerPolicy`` struct has no json tags.
* ``_policy_from_dict`` returns an empty ``Policy()`` when ``rules`` is not a
  list, and drops non-dict entries defensively (JSON may carry ``null``).
* ``LayeredPolicy.Evaluate`` falls through Ask results and returns Ask with
  layer ``"none"`` when no layer decides; ``LayeredPolicy`` is not internally
  synchronized.
* ``LayerMerge`` takes rule slices (not policies), de-duplicates by ID with
  override precedence, and sorts by priority descending.
* ``AuditLog.ExportJSON`` appends a trailing newline (as ``json.Encoder``).
* ``AuditStreamer.Close`` marks the streamer closed; later ``Send`` calls are
  no-ops (the original would panic sending on a closed channel).
* ``AuditFilter.min_risk_level`` only applies when the entry records a risk
  level; ``PermissionCache.Purge`` returns the number of removed entries.
* ``CacheKey`` is the hex of the first 16 bytes of the SHA-256 digest.
"""

from __future__ import annotations

from dxrk.utils.permissions_audit import AuditEntry as AuditEntry
from dxrk.utils.permissions_audit import AuditFilter as AuditFilter
from dxrk.utils.permissions_audit import AuditLog as AuditLog
from dxrk.utils.permissions_audit import AuditStreamer as AuditStreamer
from dxrk.utils.permissions_audit import NewAuditLog as NewAuditLog
from dxrk.utils.permissions_audit import NewAuditStreamer as NewAuditStreamer
from dxrk.utils.permissions_audit import NewStreamingAuditLog as NewStreamingAuditLog
from dxrk.utils.permissions_audit import StreamingAuditLog as StreamingAuditLog
from dxrk.utils.permissions_audit import _parse_risk_level as _parse_risk_level
from dxrk.utils.permissions_cache import CacheEntry as CacheEntry
from dxrk.utils.permissions_cache import CacheKey as CacheKey
from dxrk.utils.permissions_cache import NewPermissionCache as NewPermissionCache
from dxrk.utils.permissions_cache import PermissionCache as PermissionCache
from dxrk.utils.permissions_classify import AssessRisk as AssessRisk
from dxrk.utils.permissions_classify import ClassifyResource as ClassifyResource
from dxrk.utils.permissions_classify import ClassifyTool as ClassifyTool
from dxrk.utils.permissions_classify import DangerousCommandPrefixes as DangerousCommandPrefixes
from dxrk.utils.permissions_classify import IsReadOnly as IsReadOnly
from dxrk.utils.permissions_classify import RequireConfirmation as RequireConfirmation
from dxrk.utils.permissions_classify import ResourceType as ResourceType
from dxrk.utils.permissions_classify import RiskLevel as RiskLevel
from dxrk.utils.permissions_classify import ToolCategory as ToolCategory
from dxrk.utils.permissions_classify import ToolRiskSummary as ToolRiskSummary
from dxrk.utils.permissions_classify import read_only_tools as read_only_tools
from dxrk.utils.permissions_classify import sensitive_tool_resources as sensitive_tool_resources
from dxrk.utils.permissions_classify import tool_categories as tool_categories
from dxrk.utils.permissions_engine import NewPolicyEngine as NewPolicyEngine
from dxrk.utils.permissions_engine import PolicyEngine as PolicyEngine
from dxrk.utils.permissions_engine import _match_field as _match_field
from dxrk.utils.permissions_engine import _match_glob as _match_glob
from dxrk.utils.permissions_model import _STR_CRITICAL as _STR_CRITICAL
from dxrk.utils.permissions_model import _STR_EXECUTE as _STR_EXECUTE
from dxrk.utils.permissions_model import _STR_FORMAT as _STR_FORMAT
from dxrk.utils.permissions_model import _STR_LISTFILES as _STR_LISTFILES
from dxrk.utils.permissions_model import _STR_MEDIUM as _STR_MEDIUM
from dxrk.utils.permissions_model import _STR_PROJECT as _STR_PROJECT
from dxrk.utils.permissions_model import _STR_TODOREAD as _STR_TODOREAD
from dxrk.utils.permissions_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.permissions_model import _STR_WEBFETCH as _STR_WEBFETCH
from dxrk.utils.permissions_model import _STR_WEBSEARCH as _STR_WEBSEARCH
from dxrk.utils.permissions_model import _STR_WRITE as _STR_WRITE
from dxrk.utils.permissions_model import _ZERO_TIME as _ZERO_TIME
from dxrk.utils.permissions_model import Action as Action
from dxrk.utils.permissions_model import Condition as Condition
from dxrk.utils.permissions_model import EvalContext as EvalContext
from dxrk.utils.permissions_model import Operator as Operator
from dxrk.utils.permissions_model import ParseAction as ParseAction
from dxrk.utils.permissions_model import ParseOperator as ParseOperator
from dxrk.utils.permissions_model import Policy as Policy
from dxrk.utils.permissions_model import Rule as Rule
from dxrk.utils.permissions_model import Strategy as Strategy
from dxrk.utils.permissions_model import _anonymous_enum_member as _anonymous_enum_member
from dxrk.utils.permissions_model import _as_int as _as_int
from dxrk.utils.permissions_model import _go_time_fmt as _go_time_fmt
from dxrk.utils.permissions_model import _is_zero as _is_zero
from dxrk.utils.permissions_model import _now as _now
from dxrk.utils.permissions_model import _parse_go_time as _parse_go_time
from dxrk.utils.permissions_model import _rfc3339 as _rfc3339
from dxrk.utils.permissions_policy import Layer as Layer
from dxrk.utils.permissions_policy import LayeredPolicy as LayeredPolicy
from dxrk.utils.permissions_policy import LayerMerge as LayerMerge
from dxrk.utils.permissions_policy import LayerPolicy as LayerPolicy
from dxrk.utils.permissions_policy import LoadPolicyFile as LoadPolicyFile
from dxrk.utils.permissions_policy import LoadProjectPolicy as LoadProjectPolicy
from dxrk.utils.permissions_policy import LoadUserPolicy as LoadUserPolicy
from dxrk.utils.permissions_policy import MarshalLayeredPolicyJSON as MarshalLayeredPolicyJSON
from dxrk.utils.permissions_policy import MarshalPolicyJSON as MarshalPolicyJSON
from dxrk.utils.permissions_policy import NewLayeredPolicy as NewLayeredPolicy
from dxrk.utils.permissions_policy import SavePolicyFile as SavePolicyFile
from dxrk.utils.permissions_policy import UnmarshalPolicyJSON as UnmarshalPolicyJSON
from dxrk.utils.permissions_policy import _default_policy as _default_policy
from dxrk.utils.permissions_policy import _policy_from_dict as _policy_from_dict
from dxrk.utils.permissions_policy import _policy_to_dict as _policy_to_dict

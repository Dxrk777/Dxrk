# SPDX-License-Identifier: MIT
"""Hook system utilities — facade over the hooks_* submodules.

Provides hook types/events, a pattern matcher (glob/regex), a thread-safe
hook registry, a circuit breaker, an executor with timeout/retry, an async
worker-pool queue, and a structured logger with metrics.

Concurrency mapping:

* ``time.Duration`` -> ``datetime.timedelta``
* ``json.RawMessage`` -> ``Any`` (``bytes``/``str``/``dict``/``list``)
* ``io.Writer`` -> a text-mode file-like object
* ``context.Context`` -> the private :class:`_Context` (module-local)
* channels -> ``queue.Queue`` / ``threading.Event``-based watchers

Fidelity notes (mirrored intentionally):

* ``HookMatcher.MatchEvent`` matches the *tool name* against tool-name,
  path and command criteria.
* The registry's hook matching (``matchesHook``) uses ``filepath.Match``
  semantics for globs (``*`` does not cross ``/``) and ignores ``Path``
  and ``Paths`` criteria, while the matcher's ``matchGlob`` compiles
  globs to regexes (``*`` -> ``.*``).
* ``ValidateConfig`` validates a hook's type via
  ``ParseHookType(Type.String())``, so an out-of-range type value is a
  parse error.
* JSON: durations marshal as integer nanoseconds, the logger writes a
  compact JSON line per entry and ``SaveConfig`` writes 2-space
  indented JSON.
"""

from __future__ import annotations

from dxrk.utils.hooks_circuit import CircuitBreaker as CircuitBreaker
from dxrk.utils.hooks_circuit import CircuitBreakerState as CircuitBreakerState
from dxrk.utils.hooks_circuit import CircuitClosed as CircuitClosed
from dxrk.utils.hooks_circuit import CircuitHalfOpen as CircuitHalfOpen
from dxrk.utils.hooks_circuit import CircuitOpen as CircuitOpen
from dxrk.utils.hooks_circuit import NewCircuitBreaker as NewCircuitBreaker
from dxrk.utils.hooks_exec import _CTX_CANCELED as _CTX_CANCELED
from dxrk.utils.hooks_exec import _CTX_DEADLINE as _CTX_DEADLINE
from dxrk.utils.hooks_exec import HookExecutor as HookExecutor
from dxrk.utils.hooks_exec import HookExecutorOption as HookExecutorOption
from dxrk.utils.hooks_exec import NewHookExecutor as NewHookExecutor
from dxrk.utils.hooks_exec import WithCircuitBreaker as WithCircuitBreaker
from dxrk.utils.hooks_exec import WithExecutorRetries as WithExecutorRetries
from dxrk.utils.hooks_exec import WithExecutorRetryDelay as WithExecutorRetryDelay
from dxrk.utils.hooks_exec import WithExecutorTimeout as WithExecutorTimeout
from dxrk.utils.hooks_exec import _background as _background
from dxrk.utils.hooks_exec import _Context as _Context
from dxrk.utils.hooks_exec import _exec_env as _exec_env
from dxrk.utils.hooks_exec import _exec_not_found as _exec_not_found
from dxrk.utils.hooks_exec import _with_cancel as _with_cancel
from dxrk.utils.hooks_exec import _with_timeout as _with_timeout
from dxrk.utils.hooks_match import DefaultHookDefaults as DefaultHookDefaults
from dxrk.utils.hooks_match import HookDefaults as HookDefaults
from dxrk.utils.hooks_match import HookMatcher as HookMatcher
from dxrk.utils.hooks_match import HookRegistry as HookRegistry
from dxrk.utils.hooks_match import _filepath_match as _filepath_match
from dxrk.utils.hooks_match import _glob_to_regex as _glob_to_regex
from dxrk.utils.hooks_match import _matches_hook as _matches_hook
from dxrk.utils.hooks_match import _Watcher as _Watcher
from dxrk.utils.hooks_metrics import HookLogEntry as HookLogEntry
from dxrk.utils.hooks_metrics import HookLogger as HookLogger
from dxrk.utils.hooks_metrics import HookMetrics as HookMetrics
from dxrk.utils.hooks_metrics import HookMetricsEntry as HookMetricsEntry
from dxrk.utils.hooks_metrics import HookMetricsEntrySnapshot as HookMetricsEntrySnapshot
from dxrk.utils.hooks_metrics import HookMetricsSnapshot as HookMetricsSnapshot
from dxrk.utils.hooks_metrics import LogLevel as LogLevel
from dxrk.utils.hooks_metrics import LogLevelDebug as LogLevelDebug
from dxrk.utils.hooks_metrics import LogLevelError as LogLevelError
from dxrk.utils.hooks_metrics import LogLevelInfo as LogLevelInfo
from dxrk.utils.hooks_metrics import LogLevelWarn as LogLevelWarn
from dxrk.utils.hooks_metrics import NewHookLogger as NewHookLogger
from dxrk.utils.hooks_metrics import TypeMetrics as TypeMetrics
from dxrk.utils.hooks_metrics import TypeMetricsSnapshot as TypeMetricsSnapshot
from dxrk.utils.hooks_metrics import _DiscardWriter as _DiscardWriter
from dxrk.utils.hooks_metrics import _entry_dump as _entry_dump
from dxrk.utils.hooks_model import _DISCARD as _DISCARD
from dxrk.utils.hooks_model import _STR_ERROR as _STR_ERROR
from dxrk.utils.hooks_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.hooks_model import DefaultConfig as DefaultConfig
from dxrk.utils.hooks_model import ErrCircuitOpen as ErrCircuitOpen
from dxrk.utils.hooks_model import ErrConfigNotFound as ErrConfigNotFound
from dxrk.utils.hooks_model import ErrConfigParse as ErrConfigParse
from dxrk.utils.hooks_model import ErrDuplicateHookID as ErrDuplicateHookID
from dxrk.utils.hooks_model import ErrExecutionTimeout as ErrExecutionTimeout
from dxrk.utils.hooks_model import ErrHookAborted as ErrHookAborted
from dxrk.utils.hooks_model import ErrHookDisabled as ErrHookDisabled
from dxrk.utils.hooks_model import ErrHookNotFound as ErrHookNotFound
from dxrk.utils.hooks_model import ErrInvalidConfig as ErrInvalidConfig
from dxrk.utils.hooks_model import ErrLoggerClosed as ErrLoggerClosed
from dxrk.utils.hooks_model import ErrMaxRetriesExceeded as ErrMaxRetriesExceeded
from dxrk.utils.hooks_model import ErrQueueClosed as ErrQueueClosed
from dxrk.utils.hooks_model import ErrQueueFull as ErrQueueFull
from dxrk.utils.hooks_model import ErrRegistryClosed as ErrRegistryClosed
from dxrk.utils.hooks_model import ErrWorkerStopped as ErrWorkerStopped
from dxrk.utils.hooks_model import FilterByType as FilterByType
from dxrk.utils.hooks_model import FilterEnabled as FilterEnabled
from dxrk.utils.hooks_model import HookConfig as HookConfig
from dxrk.utils.hooks_model import HookConfigFile as HookConfigFile
from dxrk.utils.hooks_model import HookError as HookError
from dxrk.utils.hooks_model import HookEvent as HookEvent
from dxrk.utils.hooks_model import HookExecutionContext as HookExecutionContext
from dxrk.utils.hooks_model import HookMatch as HookMatch
from dxrk.utils.hooks_model import HookResult as HookResult
from dxrk.utils.hooks_model import HookType as HookType
from dxrk.utils.hooks_model import LoadConfig as LoadConfig
from dxrk.utils.hooks_model import MergeConfigs as MergeConfigs
from dxrk.utils.hooks_model import Notification as Notification
from dxrk.utils.hooks_model import ParseHookType as ParseHookType
from dxrk.utils.hooks_model import PostToolUse as PostToolUse
from dxrk.utils.hooks_model import PreToolUse as PreToolUse
from dxrk.utils.hooks_model import SaveConfig as SaveConfig
from dxrk.utils.hooks_model import Stop as Stop
from dxrk.utils.hooks_model import SubagentStop as SubagentStop
from dxrk.utils.hooks_model import UserPromptSubmit as UserPromptSubmit
from dxrk.utils.hooks_model import ValidateConfig as ValidateConfig
from dxrk.utils.hooks_model import _cfg_dump as _cfg_dump
from dxrk.utils.hooks_model import _cfg_load as _cfg_load
from dxrk.utils.hooks_model import _evt_dump as _evt_dump
from dxrk.utils.hooks_model import _evt_load as _evt_load
from dxrk.utils.hooks_model import _file_dump as _file_dump
from dxrk.utils.hooks_model import _file_load as _file_load
from dxrk.utils.hooks_model import _go_time_fmt as _go_time_fmt
from dxrk.utils.hooks_model import _go_time_parse as _go_time_parse
from dxrk.utils.hooks_model import _hook_type_name as _hook_type_name
from dxrk.utils.hooks_model import _match_dump as _match_dump
from dxrk.utils.hooks_model import _match_load as _match_load
from dxrk.utils.hooks_model import _ns_td as _ns_td
from dxrk.utils.hooks_model import _odict as _odict
from dxrk.utils.hooks_model import _raw_dump as _raw_dump
from dxrk.utils.hooks_model import _raw_load as _raw_load
from dxrk.utils.hooks_model import _result_dump as _result_dump
from dxrk.utils.hooks_model import _result_load as _result_load
from dxrk.utils.hooks_model import _td_ns as _td_ns
from dxrk.utils.hooks_queue import _SENTINEL as _SENTINEL
from dxrk.utils.hooks_queue import HookQueue as HookQueue
from dxrk.utils.hooks_queue import HookTask as HookTask
from dxrk.utils.hooks_queue import NewHookQueue as NewHookQueue
from dxrk.utils.hooks_queue import QueueStats as QueueStats
from dxrk.utils.hooks_queue import WithQueueBuffer as WithQueueBuffer
from dxrk.utils.hooks_queue import WithQueueExecutor as WithQueueExecutor
from dxrk.utils.hooks_queue import WithQueueWorkers as WithQueueWorkers

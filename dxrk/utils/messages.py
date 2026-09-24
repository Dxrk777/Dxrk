# SPDX-License-Identifier: MIT
"""Conversation message primitives.

Provides message/role/content models, a fluent message builder, context-window
management with token budgeting and compaction strategies, message
normalization (merging, dedup, ordering), formatting in several output styles,
and conversation search/statistics helpers.

Concurrency mapping:

* ``time.Time`` -> ``datetime`` (UTC; zero time is ``_ZERO_TIME``)
* ``time.Duration`` -> ``datetime.timedelta``
* ``map[string]any`` -> ``dict[str, object]``

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``EstimateTokens`` uses ``len(s) // 4``; the original counts *bytes*, Python counts
  characters, so multi-byte strings may estimate slightly lower.
* ``Message.EstimateTokens`` returns 1 for a message with no content.
* ``formatToolInput`` iterates maps in random order; Python keeps dict
  insertion order (deterministic output).
* ``formatVerbose`` metadata lines use dict order (map order is random).
* ``truncStr``/``TruncateMiddle`` slice the string for ``maxLen < 4`` /
  ``maxLen < 5``; the original slices bytes (can split a rune), Python slices
  characters (cannot).
* The emoji glyphs in ``format_markdown``/``FormatToolResult`` are mirrored
  verbatim from the original output strings.
* ``Compact`` with an unknown strategy raises ``ValueError`` (the original returns a
  wrapped error).
* ``GetConversationStats`` uses ``len(TextContent())``; the original counts *bytes*,
  Python counts characters, so ``longest_message``/``avg_message_length``
  may be slightly lower for multi-byte text.
* ``Role`` is an ``IntEnum`` with ``_missing_`` defaulting to ``RoleUser``,
  matching the original ``ParseRole`` fallback for unknown values."""

from __future__ import annotations

from dxrk.utils.messages_builder import MessageBuilder as MessageBuilder
from dxrk.utils.messages_builder import NewMessage as NewMessage
from dxrk.utils.messages_format import _ANSI_RE as _ANSI_RE
from dxrk.utils.messages_format import CharCount as CharCount
from dxrk.utils.messages_format import FormatDiff as FormatDiff
from dxrk.utils.messages_format import FormatError as FormatError
from dxrk.utils.messages_format import FormatMessage as FormatMessage
from dxrk.utils.messages_format import FormatProgress as FormatProgress
from dxrk.utils.messages_format import FormatStyle as FormatStyle
from dxrk.utils.messages_format import FormatToolResult as FormatToolResult
from dxrk.utils.messages_format import FormatToolUse as FormatToolUse
from dxrk.utils.messages_format import StripANSI as StripANSI
from dxrk.utils.messages_format import TruncateMiddle as TruncateMiddle
from dxrk.utils.messages_format import WordCount as WordCount
from dxrk.utils.messages_format import WrapCode as WrapCode
from dxrk.utils.messages_format import _format_compact as _format_compact
from dxrk.utils.messages_format import _format_duration as _format_duration
from dxrk.utils.messages_format import _format_markdown as _format_markdown
from dxrk.utils.messages_format import _format_plain as _format_plain
from dxrk.utils.messages_format import _format_rich as _format_rich
from dxrk.utils.messages_format import _format_tool_input as _format_tool_input
from dxrk.utils.messages_format import _format_verbose as _format_verbose
from dxrk.utils.messages_format import _round_ms as _round_ms
from dxrk.utils.messages_format import _trunc_str as _trunc_str
from dxrk.utils.messages_model import _STR_ASSISTANT as _STR_ASSISTANT
from dxrk.utils.messages_model import _STR_ERROR as _STR_ERROR
from dxrk.utils.messages_model import _STR_SYSTEM as _STR_SYSTEM
from dxrk.utils.messages_model import _STR_TOOL_RESULT as _STR_TOOL_RESULT
from dxrk.utils.messages_model import _STR_TOOL_USE as _STR_TOOL_USE
from dxrk.utils.messages_model import _STR_UNKNOWN as _STR_UNKNOWN
from dxrk.utils.messages_model import _ZERO_TIME as _ZERO_TIME
from dxrk.utils.messages_model import Content as Content
from dxrk.utils.messages_model import ContentType as ContentType
from dxrk.utils.messages_model import EstimateTokens as EstimateTokens
from dxrk.utils.messages_model import ImageData as ImageData
from dxrk.utils.messages_model import Message as Message
from dxrk.utils.messages_model import ParseRole as ParseRole
from dxrk.utils.messages_model import Role as Role
from dxrk.utils.messages_model import ToolResultData as ToolResultData
from dxrk.utils.messages_model import ToolUseData as ToolUseData
from dxrk.utils.messages_normalize import CompactContent as CompactContent
from dxrk.utils.messages_normalize import CountTokens as CountTokens
from dxrk.utils.messages_normalize import DeduplicateToolResults as DeduplicateToolResults
from dxrk.utils.messages_normalize import FixToolResultOrder as FixToolResultOrder
from dxrk.utils.messages_normalize import MergeConsecutiveRole as MergeConsecutiveRole
from dxrk.utils.messages_normalize import NormalizeMessages as NormalizeMessages
from dxrk.utils.messages_normalize import StripSystemMessages as StripSystemMessages
from dxrk.utils.messages_normalize import TruncateByTokens as TruncateByTokens
from dxrk.utils.messages_normalize import _compact_message_contents as _compact_message_contents
from dxrk.utils.messages_query import FilterByRegex as FilterByRegex
from dxrk.utils.messages_query import FilterByRole as FilterByRole
from dxrk.utils.messages_query import FilterByTime as FilterByTime
from dxrk.utils.messages_query import FilterByTokenRange as FilterByTokenRange
from dxrk.utils.messages_query import FilterByTool as FilterByTool
from dxrk.utils.messages_query import FindToolCalls as FindToolCalls
from dxrk.utils.messages_query import GetConversationStats as GetConversationStats
from dxrk.utils.messages_query import SearchMessages as SearchMessages
from dxrk.utils.messages_query import SearchResult as SearchResult
from dxrk.utils.messages_query import Stats as Stats
from dxrk.utils.messages_query import ToolCall as ToolCall
from dxrk.utils.messages_window import CompactStrategy as CompactStrategy
from dxrk.utils.messages_window import ContextWindow as ContextWindow
from dxrk.utils.messages_window import MessageScore as MessageScore
from dxrk.utils.messages_window import NewContextWindow as NewContextWindow
from dxrk.utils.messages_window import NoMessagesError as NoMessagesError
from dxrk.utils.messages_window import ScoreMessages as ScoreMessages
from dxrk.utils.messages_window import WindowFullError as WindowFullError

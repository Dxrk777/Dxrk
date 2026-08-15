# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.messages (mirrors internal/utils/messages port)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dxrk.utils import messages

_ZERO = datetime.fromtimestamp(0, tz=timezone.utc)


def _msg(role, text="", token_count=0, ts=None):
    b = messages.NewMessage(role).WithTimestamp(_ZERO if ts is None else ts)
    if token_count > 0:
        b.WithTokenCount(token_count)
    if text != "":
        b.Text(text)
    return b.Build()


class TestRole_String:
    def test_all_roles(self):
        cases = [
            (messages.Role.RoleUser, "user"),
            (messages.Role.RoleAssistant, "assistant"),
            (messages.Role.RoleSystem, "system"),
            (messages.Role.RoleToolUse, "tool_use"),
            (messages.Role.RoleToolResult, "tool_result"),
        ]
        for role, want in cases:
            assert role.String() == want, role


class TestParseRole:
    def test_known_roles(self):
        assert messages.ParseRole("USER") is messages.Role.RoleUser
        assert messages.ParseRole("assistant") is messages.Role.RoleAssistant
        assert messages.ParseRole("System") is messages.Role.RoleSystem
        assert messages.ParseRole("tool_use") is messages.Role.RoleToolUse
        assert messages.ParseRole("tool_result") is messages.Role.RoleToolResult

    def test_unknown_defaults_to_user(self):
        assert messages.ParseRole("bogus") is messages.Role.RoleUser
        assert messages.ParseRole("") is messages.Role.RoleUser


class TestContentType_String:
    def test_all_types(self):
        cases = [
            (messages.ContentType.ContentText, "text"),
            (messages.ContentType.ContentImage, "image"),
            (messages.ContentType.ContentToolUse, "tool_use"),
            (messages.ContentType.ContentToolResult, "tool_result"),
        ]
        for ctype, want in cases:
            assert ctype.String() == want, ctype


class TestEstimateTokens:
    def test_counts(self):
        assert messages.EstimateTokens("") == 0
        assert messages.EstimateTokens("a") == 1
        assert messages.EstimateTokens("abcd") == 1
        assert messages.EstimateTokens("abcdef") == 1
        assert messages.EstimateTokens("abcdefgh") == 2


class TestMessage_EstimateTokens:
    def test_uses_set_token_count(self):
        assert _msg(messages.Role.RoleUser, token_count=17).EstimateTokens() == 17

    def test_estimates_from_text(self):
        assert _msg(messages.Role.RoleUser, text="abcdefgh").EstimateTokens() == 2

    def test_empty_message_counts_one(self):
        assert _msg(messages.Role.RoleUser).EstimateTokens() == 1

    def test_counts_tool_use_input(self):
        b = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b.ToolUse("t1", "search", {"q": "abcd"})
        assert b.Build().EstimateTokens() == 1 + 1 + 1 + 1

    def test_counts_tool_result_content(self):
        b = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b.ToolResult("t1", "abcdefgh", False)
        assert b.Build().EstimateTokens() == 2


class TestMessage_HasToolUse:
    def test_matches_name(self):
        b = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b.ToolUse("t1", "search", {"q": "x"})
        m = b.Build()
        assert m.HasToolUse("search")
        assert not m.HasToolUse("other")

    def test_empty_name_matches_any(self):
        b = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b.ToolUse("t1", "search")
        assert b.Build().HasToolUse("")

    def test_no_tool_use(self):
        assert not _msg(messages.Role.RoleUser, "hi").HasToolUse("search")


class TestMessage_TextContent:
    def test_joins_text_blocks(self):
        b = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("a")
        b.Text("b")
        assert b.Build().TextContent() == "a\nb"

    def test_skips_empty_blocks(self):
        b = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("")
        b.Text("x")
        assert b.Build().TextContent() == "x"

    def test_empty(self):
        assert _msg(messages.Role.RoleUser).TextContent() == ""


class TestMessageBuilder:
    def test_fluent_chain(self):
        ts = _ZERO + timedelta(minutes=5)
        m = (
            messages.NewMessage(messages.Role.RoleAssistant)
            .WithID("msg-1")
            .WithTimestamp(ts)
            .WithModel("test-model")
            .WithTokenCount(42)
            .WithStopReason("end_turn")
            .WithMetadata("source", "test")
            .Text("hello")
            .Build()
        )
        assert m.id == "msg-1"
        assert m.role is messages.Role.RoleAssistant
        assert m.timestamp == ts
        assert m.model == "test-model"
        assert m.token_count == 42
        assert m.stop_reason == "end_turn"
        assert m.metadata == {"source": "test"}
        assert len(m.contents) == 1
        assert m.contents[0].type is messages.ContentType.ContentText
        assert m.contents[0].text == "hello"

    def test_image_and_image_url(self):
        m = (
            messages.NewMessage(messages.Role.RoleUser)
            .WithTimestamp(_ZERO)
            .Image("image/png", "AAAA")
            .ImageURL("https://x/y.png", "image/png")
            .Build()
        )
        assert m.contents[0].image is not None
        assert m.contents[0].image.source == "base64"
        assert m.contents[0].image.data == "AAAA"
        assert m.contents[1].image is not None
        assert m.contents[1].image.source == "url"
        assert m.contents[1].image.data == "https://x/y.png"

    def test_tool_use_default_input(self):
        m = (
            messages.NewMessage(messages.Role.RoleToolUse)
            .WithTimestamp(_ZERO)
            .ToolUse("t1", "search")
            .Build()
        )
        assert m.contents[0].tool_use is not None
        assert m.contents[0].tool_use.id == "t1"
        assert m.contents[0].tool_use.name == "search"
        assert m.contents[0].tool_use.input == {}

    def test_tool_result(self):
        m = (
            messages.NewMessage(messages.Role.RoleToolResult)
            .WithTimestamp(_ZERO)
            .ToolResult("t1", "boom", True)
            .Build()
        )
        assert m.contents[0].tool_result is not None
        assert m.contents[0].tool_result.tool_use_id == "t1"
        assert m.contents[0].tool_result.content == "boom"
        assert m.contents[0].tool_result.is_error


class TestNewMessage:
    def test_defaults(self):
        m = messages.NewMessage(messages.Role.RoleUser).Build()
        assert m.role is messages.Role.RoleUser
        assert m.contents == []
        assert m.metadata == {}
        assert m.timestamp.tzinfo is not None


class TestFormatMessage_Plain:
    def test_user_text(self):
        assert (
            messages.FormatMessage(
                _msg(messages.Role.RoleUser, "hello"), messages.FormatStyle.Plain
            )
            == "[user] hello"
        )

    def test_assistant_text(self):
        assert (
            messages.FormatMessage(
                _msg(messages.Role.RoleAssistant, "hi"), messages.FormatStyle.Plain
            )
            == "[assistant] hi"
        )


class TestFormatMessage_Markdown:
    def test_text_only(self):
        out = messages.FormatMessage(
            _msg(messages.Role.RoleUser, "hello"), messages.FormatStyle.Markdown
        )
        assert out == "**USER**\n\nhello\n"

    def test_tool_use_marker(self):
        b = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b.ToolUse("t1", "search", {"q": "x"})
        out = messages.FormatMessage(b.Build(), messages.FormatStyle.Markdown)
        assert "tool_use" in out
        assert "search" in out


class TestFormatMessage_Rich:
    def test_timestamp_role_text(self):
        out = messages.FormatMessage(
            _msg(messages.Role.RoleUser, "hello"), messages.FormatStyle.Rich
        )
        assert out == "[00:00:00] user: hello"


class TestFormatMessage_Compact:
    def test_first_letter_role(self):
        assert (
            messages.FormatMessage(
                _msg(messages.Role.RoleUser, "hello"), messages.FormatStyle.Compact
            )
            == "u: hello"
        )


class TestFormatMessage_Verbose:
    def test_fields_present(self):
        b = (
            messages.NewMessage(messages.Role.RoleUser)
            .WithTimestamp(_ZERO)
            .WithID("m1")
            .WithModel("m")
        )
        b.Text("hello")
        out = messages.FormatMessage(b.Build(), messages.FormatStyle.Verbose)
        assert "Message ID:    m1" in out
        assert "Role:          user" in out
        assert "Model:         m" in out
        assert "Contents (1):" in out


class TestFormatToolUse:
    def test_format(self):
        assert messages.FormatToolUse("search", {"q": "x"}) == '→ search({"q": "x"})'

    def test_empty_input(self):
        assert messages.FormatToolUse("search", {}) == "→ search({})"


class TestFormatToolResult:
    def test_ok(self):
        result = messages.ToolResultData(content="done", is_error=False)
        assert messages.FormatToolResult(result) == "✓ done"

    def test_error(self):
        result = messages.ToolResultData(content="oops", is_error=True)
        assert messages.FormatToolResult(result) == "✗ oops"

    def test_with_duration(self):
        result = messages.ToolResultData(
            content="done", is_error=False, duration=timedelta(milliseconds=500)
        )
        out = messages.FormatToolResult(result)
        assert out.startswith("✓ done [")
        assert "500000" in out


class TestFormatError:
    def test_none(self):
        assert messages.FormatError(None) == ""

    def test_error(self):
        assert messages.FormatError(ValueError("x")) == "Error: x"


class TestFormatProgress:
    def test_format(self):
        assert (
            messages.FormatProgress("search", timedelta(seconds=1))
            == "  search.. 0:00:01"
        )


class TestFormatDiff:
    def test_format(self):
        assert messages.FormatDiff("A", "B") == "--- before\nA\n+++ after\nB"


class TestTruncateMiddle:
    def test_short_passthrough(self):
        assert messages.TruncateMiddle("abc", 10) == "abc"

    def test_long_middle_ellipsis(self):
        assert messages.TruncateMiddle("abcdefghij", 8) == "ab...ij"

    def test_tiny_limit(self):
        assert messages.TruncateMiddle("abcdef", 3) == "abc"


class TestWrapCode:
    def test_format(self):
        assert messages.WrapCode("x=1", "py") == "```py\nx=1\n```"


class TestStripANSI:
    def test_strips_codes(self):
        assert messages.StripANSI("\x1b[31mred\x1b[0m") == "red"

    def test_no_codes(self):
        assert messages.StripANSI("plain") == "plain"


class TestWordCount:
    def test_count(self):
        assert messages.WordCount("a b  c") == 3
        assert messages.WordCount("") == 0


class TestCharCount:
    def test_count(self):
        assert messages.CharCount("abc") == 3


class TestScoreMessages:
    def test_empty(self):
        assert messages.ScoreMessages([]) == []

    def test_role_priority(self):
        msgs = [
            _msg(messages.Role.RoleUser, token_count=1),
            _msg(messages.Role.RoleAssistant, token_count=1),
            _msg(messages.Role.RoleToolResult, token_count=1),
        ]
        scores = messages.ScoreMessages(msgs)
        assert [s.score for s in scores] == [130.0, 70.0, 60.0]
        assert scores[0].message is msgs[0]
        assert "role=user" in scores[0].reason

    def test_tool_error_boost(self):
        b = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b.ToolResult("t1", "boom", True)
        scores = messages.ScoreMessages([b.Build()])
        assert scores[0].score == 80.0


class TestContextWindow_AddMessage:
    def test_add_counts_tokens(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=60))
        assert window.token_count == 60
        assert not window.truncated

    def test_overflow_drops_oldest(self):
        window = messages.NewContextWindow(100)
        m1 = _msg(messages.Role.RoleUser, token_count=60)
        m2 = _msg(messages.Role.RoleAssistant, token_count=60)
        window.AddMessage(m1)
        window.AddMessage(m2)
        assert window.truncated
        assert window.token_count == 60
        assert window.GetMessages() == [m2]

    def test_oversized_message_raises(self):
        window = messages.NewContextWindow(20)
        with pytest.raises(messages.WindowFullError):
            window.AddMessage(_msg(messages.Role.RoleUser, token_count=30))


class TestContextWindow_GetMessages:
    def test_returns_copy(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=10))
        got = window.GetMessages()
        got.clear()
        assert len(window.GetMessages()) == 1


class TestContextWindow_RemainingTokens:
    def test_counts_system_prompt(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=40))
        window.SetSystemPrompt("abcd")
        assert window.RemainingTokens() == 59
        window.SetSystemPrompt("")
        assert window.RemainingTokens() == 60


class TestContextWindow_NeedsCompaction:
    def test_above_eighty_percent(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=80))
        assert window.NeedsCompaction()

    def test_below_eighty_percent(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=79))
        assert not window.NeedsCompaction()


class TestContextWindow_Compact:
    def test_empty_raises(self):
        window = messages.NewContextWindow(100)
        with pytest.raises(messages.NoMessagesError):
            window.Compact(messages.CompactStrategy.CompactOldest)

    def test_oldest(self):
        window = messages.NewContextWindow(200)
        for _ in range(4):
            window.AddMessage(_msg(messages.Role.RoleUser, token_count=40))
        window.Compact(messages.CompactStrategy.CompactOldest)
        assert window.token_count == 80
        assert len(window.GetMessages()) == 2
        assert window.truncated

    def test_tool_results(self):
        window = messages.NewContextWindow(200)
        window.AddMessage(_msg(messages.Role.RoleToolResult, token_count=40))
        window.AddMessage(_msg(messages.Role.RoleToolResult, token_count=40))
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=40))
        window.Compact(messages.CompactStrategy.CompactToolResults)
        assert window.token_count == 40
        assert [m.role for m in window.GetMessages()] == [messages.Role.RoleUser]

    def test_by_importance(self):
        window = messages.NewContextWindow(200)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=40))
        window.AddMessage(_msg(messages.Role.RoleAssistant, token_count=40))
        window.AddMessage(_msg(messages.Role.RoleToolResult, token_count=40))
        window.Compact(messages.CompactStrategy.CompactByImportance)
        assert window.token_count == 80
        assert len(window.GetMessages()) == 2
        assert window.truncated

    def test_recursive(self):
        window = messages.NewContextWindow(100)
        for _ in range(3):
            window.AddMessage(_msg(messages.Role.RoleUser, token_count=30))
        window.Compact(messages.CompactStrategy.CompactRecursive)
        assert not window.NeedsCompaction()
        assert len(window.GetMessages()) == 2

    def test_unknown_strategy(self):
        window = messages.NewContextWindow(100)
        window.AddMessage(_msg(messages.Role.RoleUser, token_count=10))
        with pytest.raises(ValueError):
            window.Compact(messages.CompactStrategy(99))


class TestNormalizeMessages:
    def test_empty(self):
        assert messages.NormalizeMessages([]) == []

    def test_known_roles(self):
        msgs = [
            _msg(messages.Role.RoleUser, "a"),
            _msg(messages.Role.RoleUser, "b"),
            _msg(messages.Role.RoleAssistant, "c"),
        ]
        got = messages.NormalizeMessages(msgs)
        assert len(got) == 2
        assert got[0].TextContent() == "a\nb"
        assert got[0].role is messages.Role.RoleUser
        assert got[1].role is messages.Role.RoleAssistant


class TestMergeConsecutiveRole:
    def test_merges_and_keeps_others(self):
        late = _ZERO + timedelta(hours=1)
        m1 = _msg(messages.Role.RoleUser, "a", token_count=10, ts=late)
        m2 = _msg(messages.Role.RoleUser, "b", token_count=20, ts=_ZERO)
        m3 = _msg(messages.Role.RoleAssistant, "c", token_count=5)
        got = messages.MergeConsecutiveRole([m1, m2, m3], messages.Role.RoleUser)
        assert len(got) == 2
        assert got[0].TextContent() == "a\nb"
        assert got[0].token_count == 30
        assert got[0].timestamp == _ZERO
        assert got[1].contents[0].text == "c"

    def test_non_consecutive_not_merged(self):
        m1 = _msg(messages.Role.RoleUser, "a")
        m2 = _msg(messages.Role.RoleAssistant, "b")
        m3 = _msg(messages.Role.RoleUser, "c")
        got = messages.MergeConsecutiveRole([m1, m2, m3], messages.Role.RoleUser)
        assert len(got) == 3


class TestStripSystemMessages:
    def test_strips_system(self):
        msgs = [
            _msg(messages.Role.RoleSystem, "s"),
            _msg(messages.Role.RoleUser, "u"),
            _msg(messages.Role.RoleSystem, "s2"),
        ]
        got = messages.StripSystemMessages(msgs)
        assert len(got) == 1
        assert got[0].role is messages.Role.RoleUser


class TestDeduplicateToolResults:
    def test_keeps_first(self):
        b1 = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b1.ToolResult("t1", "first", False)
        b2 = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b2.ToolResult("t1", "second", False)
        b3 = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b3.Text("u")
        got = messages.DeduplicateToolResults([b1.Build(), b2.Build(), b3.Build()])
        assert len(got) == 2
        assert got[0].contents[0].tool_result is not None
        assert got[0].contents[0].tool_result.content == "first"
        assert got[1].role is messages.Role.RoleUser


class TestFixToolResultOrder:
    def test_keeps_messages(self):
        b1 = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b1.ToolResult("tu1", "res", False)
        b2 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b2.ToolUse("tu1", "search", {})
        msgs = [b1.Build(), b2.Build()]
        got = messages.FixToolResultOrder(msgs)
        assert len(got) == 2
        assert got[0].role is messages.Role.RoleToolResult
        assert got[1].role is messages.Role.RoleToolUse


class TestCompactContent:
    def test_merges_text_blocks(self):
        b = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("a")
        b.Text("b")
        got = messages.CompactContent([b.Build()])
        assert len(got[0].contents) == 1
        assert got[0].contents[0].text == "a\nb"

    def test_single_block_unchanged(self):
        b = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("a")
        got = messages.CompactContent([b.Build()])
        assert len(got[0].contents) == 1


class TestTruncateByTokens:
    def test_keeps_most_recent_within_budget(self):
        msgs = [
            _msg(messages.Role.RoleSystem, token_count=10),
            _msg(messages.Role.RoleUser, token_count=20),
            _msg(messages.Role.RoleAssistant, token_count=30),
        ]
        got = messages.TruncateByTokens(msgs, 50)
        assert len(got) == 2
        assert got[0].role is messages.Role.RoleSystem
        assert got[1].role is messages.Role.RoleAssistant

    def test_invalid_budget(self):
        assert messages.TruncateByTokens([_msg(messages.Role.RoleUser)], 0) == []

    def test_system_only_when_over_budget(self):
        msgs = [
            _msg(messages.Role.RoleSystem, token_count=60),
            _msg(messages.Role.RoleUser, token_count=20),
        ]
        got = messages.TruncateByTokens(msgs, 50)
        assert len(got) == 1
        assert got[0].role is messages.Role.RoleSystem


class TestCountTokens:
    def test_sums(self):
        msgs = [
            _msg(messages.Role.RoleUser, token_count=10),
            _msg(messages.Role.RoleAssistant, token_count=20),
        ]
        assert messages.CountTokens(msgs) == 30

    def test_empty(self):
        assert messages.CountTokens([]) == 0


class TestSearchMessages:
    def test_empty_query(self):
        assert messages.SearchMessages([_msg(messages.Role.RoleUser, "hi")], "") == []

    def test_no_match(self):
        assert (
            messages.SearchMessages([_msg(messages.Role.RoleUser, "hi")], "zzz") == []
        )

    def test_match_and_order(self):
        m1 = _msg(messages.Role.RoleUser, "cat dog cat")
        m2 = _msg(messages.Role.RoleAssistant, "cat")
        results = messages.SearchMessages([m1, m2], "cat")
        assert len(results) == 2
        assert results[0].message is m1
        assert results[0].score > results[1].score
        assert len(results[0].highlight) == 2
        assert results[1].message is m2


class TestFilterByRole:
    def test_filters(self):
        msgs = [
            _msg(messages.Role.RoleUser, "u"),
            _msg(messages.Role.RoleAssistant, "a"),
        ]
        got = messages.FilterByRole(msgs, messages.Role.RoleUser)
        assert len(got) == 1
        assert got[0].role is messages.Role.RoleUser


class TestFilterByTime:
    def test_inclusive_bounds(self):
        t5 = _ZERO + timedelta(minutes=5)
        t20 = _ZERO + timedelta(minutes=20)
        msgs = [
            _msg(messages.Role.RoleUser, ts=_ZERO),
            _msg(messages.Role.RoleUser, ts=t5),
            _msg(messages.Role.RoleUser, ts=t20),
        ]
        got = messages.FilterByTime(msgs, _ZERO, _ZERO + timedelta(minutes=10))
        assert [m.timestamp for m in got] == [_ZERO, t5]

    def test_zero_bounds_open(self):
        t5 = _ZERO + timedelta(minutes=5)
        msgs = [
            _msg(messages.Role.RoleUser, ts=_ZERO),
            _msg(messages.Role.RoleUser, ts=t5),
        ]
        got = messages.FilterByTime(msgs, t5, _ZERO)
        assert [m.timestamp for m in got] == [t5]


class TestFilterByTokenRange:
    def test_closed_range(self):
        msgs = [
            _msg(messages.Role.RoleUser, token_count=10),
            _msg(messages.Role.RoleUser, token_count=30),
        ]
        got = messages.FilterByTokenRange(msgs, 0, 20)
        assert len(got) == 1
        assert got[0].token_count == 10
        got = messages.FilterByTokenRange(msgs, 15, -1)
        assert len(got) == 1
        assert got[0].token_count == 30


class TestFilterByTool:
    def test_specific_and_any(self):
        b1 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b1.ToolUse("t1", "search")
        b2 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b2.ToolUse("t2", "read")
        msgs = [b1.Build(), b2.Build()]
        assert len(messages.FilterByTool(msgs, "search")) == 1
        assert len(messages.FilterByTool(msgs, "")) == 2


class TestFilterByRegex:
    def test_matches(self):
        msgs = [_msg(messages.Role.RoleUser, "hello world")]
        got = messages.FilterByRegex(msgs, "h.llo")
        assert len(got) == 1

    def test_invalid_pattern(self):
        msgs = [_msg(messages.Role.RoleUser, "hello")]
        assert messages.FilterByRegex(msgs, "[") == []


class TestFindToolCalls:
    def test_pairs_resolved(self):
        b1 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b1.ToolUse("tu1", "search", {"q": "x"})
        b2 = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b2.ToolResult("tu1", "res", False)
        b3 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b3.ToolUse("tu2", "other")
        use_msg, result_msg, other_msg = b1.Build(), b2.Build(), b3.Build()

        calls = messages.FindToolCalls([use_msg, result_msg, other_msg], "search")
        assert len(calls) == 1
        assert calls[0].tool_use.id == "tu1"
        assert calls[0].result is not None
        assert calls[0].result.content == "res"
        assert calls[0].result_msg is result_msg

        assert len(messages.FindToolCalls([use_msg, result_msg, other_msg], "")) == 2
        assert messages.FindToolCalls([use_msg, result_msg, other_msg], "nope") == []


class TestGetConversationStats:
    def test_stats(self):
        b1 = messages.NewMessage(messages.Role.RoleUser).WithTimestamp(_ZERO)
        b1.Text("hello")
        b1.WithTokenCount(10)
        b2 = messages.NewMessage(messages.Role.RoleAssistant).WithTimestamp(_ZERO)
        b2.WithTokenCount(5)
        b3 = messages.NewMessage(messages.Role.RoleToolResult).WithTimestamp(_ZERO)
        b3.ToolResult("t1", "boom", True)
        b3.WithTokenCount(3)
        b4 = messages.NewMessage(messages.Role.RoleToolUse).WithTimestamp(_ZERO)
        b4.ToolUse("t1", "search")
        b4.WithTokenCount(2)
        stats = messages.GetConversationStats(
            [b1.Build(), b2.Build(), b3.Build(), b4.Build()]
        )
        assert stats.total_messages == 4
        assert stats.total_tokens == 20
        assert stats.by_role[messages.Role.RoleUser] == 1
        assert stats.by_role[messages.Role.RoleAssistant] == 1
        assert stats.by_role[messages.Role.RoleToolResult] == 1
        assert stats.by_role[messages.Role.RoleToolUse] == 1
        assert stats.longest_message == 5
        assert stats.tool_call_count == 1
        assert stats.tool_result_count == 1
        assert stats.error_count == 1
        assert stats.avg_token_per_msg == 5.0
        assert "Messages: 4" in stats.String()

    def test_empty(self):
        stats = messages.GetConversationStats([])
        assert stats.total_messages == 0
        assert stats.by_role == {}

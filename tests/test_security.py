# SPDX-License-Identifier: MIT
"""Tests for dxrk.security (mirrors internal/security/*_test.go)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dxrk.security import (
    ALWAYS_ASK_TOOLS,
    KNOWN_DANGEROUS_PATTERNS,
    MAX_COMMAND_LENGTH,
    NEEDS_CONFIRMATION,
    READ_ONLY_TOOLS,
    READ_TOOLS,
    SAFE_FOR_AUTO_MODE,
    SAFE_TOOLS,
    CircuitBreaker,
    ClassificationDecision,
    NodeType,
    PermissionBehavior,
    PermissionContext,
    PermissionResult,
    PermissionRule,
    RefreshConfig,
    RiskLevel,
    SettingSource,
    TokenKind,
    TokenRefreshScheduler,
    TrustedDevice,
    assess_bash_risk,
    check_dangerous_patterns,
    classify_for_auto_mode,
    classify_token,
    classify_tool,
    decode_jwt_payload,
    detect_unreachable_rules,
    extract_command_name,
    has_dangerous_patterns,
    is_ascii,
    is_device_trusted,
    is_quiet,
    is_read_only_command,
    is_token_expired,
    parse_for_security,
    parse_token_safe,
    quote_safety,
    redact_sensitive,
    redact_token,
    sanitize_for_log,
    strip_ansi,
    truncate_with_suffix,
    validate_id,
    validate_ingress_url,
)

TEST_JWT_SECRET = b"test-secret-key-0123456789"


# ---- Helpers (mirror jwt_test.go signTestToken / testKeyFunc) ----


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_test_token(claims: dict) -> str:
    """Build a signed JWT with the given registered claims."""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    sig = _b64url(
        hmac.new(TEST_JWT_SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest()
    )
    return f"{h}.{p}.{sig}"


def _key_func(header: dict, claims: dict) -> bytes:
    if header.get("alg") != "HS256":
        raise ValueError("unexpected signing method")
    return TEST_JWT_SECRET


# ---- ast_test.go ----


def test_node_type_string() -> None:
    cases = {
        NodeType.COMMAND: "command",
        NodeType.PIPELINE: "pipeline",
        NodeType.LIST: "list",
        NodeType.SUBSHELL: "subshell",
        NodeType.REDIRECT: "redirect",
        NodeType.VARIABLE: "variable",
        NodeType.ASSIGNMENT: "assignment",
        NodeType.WORD: "word",
        NodeType.OPERATOR: "operator",
        NodeType.HEREDOC: "heredoc",
        NodeType.COMMENT: "comment",
        NodeType.UNKNOWN: "unknown",
        NodeType(999): "unknown",
    }
    for typ, want in cases.items():
        assert str(typ) == want, f"NodeType({typ}).String() = {typ}, want {want}"


def test_parse_for_security_safe_commands() -> None:
    safe = [
        "",
        "ls -la",
        "git status",
        "echo hello",
        "cat file.txt | grep foo",
        "python3 script.py",
        "mkdir -p /tmp/test",
        "printf '%s\\n' hi",
    ]
    for cmd in safe:
        res = parse_for_security(cmd)
        assert res.is_safe, (
            f"ParseForSecurity({cmd!r}) IsSafe = False, violations: {res.violations}"
        )


def test_parse_for_security_dangerous() -> None:
    dangerous = [
        "$(rm -rf /)",
        "`ls`",
        "echo ${SECRET}",
        "eval echo hi",
        "exec ls",
        "sudo rm -rf /",
        "rm file.txt",
        "dd if=/dev/zero of=/dev/sda",
        "echo 'unterminated",
    ]
    for cmd in dangerous:
        res = parse_for_security(cmd)
        assert not res.is_safe, f"ParseForSecurity({cmd!r}) IsSafe = True, want false"
        assert len(res.violations) >= 1, f"ParseForSecurity({cmd!r}) has no violations"


def test_parse_for_security_length_guard() -> None:
    long_cmd = "a" * (MAX_COMMAND_LENGTH + 1)
    res = parse_for_security(long_cmd)
    assert not res.is_safe, "command over 10000 bytes should be unsafe"
    assert len(res.violations) >= 1, "expected length violation"


def test_parse_for_security_null_byte() -> None:
    res = parse_for_security("ls\x00-rf")
    assert not res.is_safe, "null byte command should be unsafe"


def test_parse_for_security_env_assignment() -> None:
    res = parse_for_security("FOO=bar echo hi")
    assert res.is_safe, f"expected safe, violations: {res.violations}"
    assert "FOO=bar" in res.env_vars, (
        f"EnvVars = {res.env_vars}, want to contain FOO=bar"
    )


def test_parse_for_security_operators() -> None:
    res = parse_for_security("echo a && echo b; echo c")
    assert res.is_safe, f"expected safe, violations: {res.violations}"
    joined = " ".join(res.operators)
    assert "&&" in joined and ";" in joined, (
        f"Operators = {res.operators}, want && and ;"
    )


def test_extract_command_name() -> None:
    cases = [
        ("ls -la", "ls"),
        ("git status --short", "git"),
        ("", ""),
        ("   ", ""),
    ]
    for cmd, want in cases:
        assert extract_command_name(cmd) == want, (
            f"ExtractCommandName({cmd!r}) = {extract_command_name(cmd)!r}, want {want!r}"
        )


def test_has_dangerous_patterns() -> None:
    assert not has_dangerous_patterns("ls -la")
    assert has_dangerous_patterns("$(ls)")
    assert has_dangerous_patterns("sudo apt update")


def test_sanitize_for_log() -> None:
    cases = [
        ("token=abcdefghijklmnopqrstuvwxyz123456", "[REDACTED]"),
        ("key sk-abcdefghijklmnopqrstuvwxyz123456", "key [REDACTED]"),
        ("hello world", "hello world"),
        ("\x1b[31mred\x1b[0m", "red"),
    ]
    for inp, want in cases:
        assert sanitize_for_log(inp) == want, (
            f"SanitizeForLog({inp!r}) = {sanitize_for_log(inp)!r}, want {want!r}"
        )


def test_sanitize_for_log_truncation() -> None:
    long_cmd = "a" * 600
    got = sanitize_for_log(long_cmd)
    assert len(got) == 500 + len("...[truncated]")
    assert got.endswith("...[truncated]"), (
        f"SanitizeForLog = {got!r}, want truncation suffix"
    )


def test_is_read_only_command() -> None:
    cases = [
        ("ls -la", True),
        ("echo hi", True),
        ("git status", False),
        ("rm file", False),
        ("", False),
    ]
    for cmd, want in cases:
        assert is_read_only_command(cmd) == want, (
            f"IsReadOnlyCommand({cmd!r}) = {is_read_only_command(cmd)}, want {want}"
        )


def test_quote_safety() -> None:
    assert quote_safety("hello") == "hello"
    assert quote_safety("echo hi") == "'echo hi'"
    assert quote_safety("it's") == "'it'\"'\"'s'"


def test_strip_ansi() -> None:
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert strip_ansi("plain") == "plain"


def test_is_quiet() -> None:
    assert is_quiet("")
    assert is_quiet("  \t ")
    assert not is_quiet("x")


def test_truncate_with_suffix() -> None:
    assert truncate_with_suffix("hello", 10, "...") == "hello"
    assert truncate_with_suffix("hello world", 8, "...") == "hello..."


def test_redact_sensitive() -> None:
    cases = [
        ("sk-abcdefghijklmnopqrstuvwxyz123456", "[REDACTED]"),
        ("API_KEY=supersecret", "[REDACTED]"),
        ("password: hunter2", "[REDACTED]"),
        ("hello world", "hello world"),
    ]
    for inp, want in cases:
        assert redact_sensitive(inp) == want, (
            f"RedactSensitive({inp!r}) = {redact_sensitive(inp)!r}, want {want!r}"
        )


def test_is_ascii() -> None:
    assert is_ascii("hello")
    assert not is_ascii("héllo")


# ---- jwt_test.go ----


def test_decode_jwt_payload() -> None:
    tok = sign_test_token({"sub": "user1", "iss": "dxrk"})
    claims = decode_jwt_payload(tok)
    assert claims is not None, "DecodeJwtPayload returned None for valid token"
    assert claims["sub"] == "user1" and claims["iss"] == "dxrk"

    # Malformed: not 2 or 3 parts
    assert decode_jwt_payload("singleton") is None
    # Invalid base64 payload
    assert decode_jwt_payload("a.!!!.c") is None
    # Invalid JSON payload
    assert decode_jwt_payload("a.bm90LWpzb24=.c") is None


def test_classify_token() -> None:
    cases = [
        ("sk-ant-si-abcdef", TokenKind.SESSION_INGRESS),
        ("sk-ant-oa-abcdef", TokenKind.ACCESS_TOKEN),
        ("sk-ant-abcdef", TokenKind.UNKNOWN),
        ("random", TokenKind.UNKNOWN),
        ("", TokenKind.UNKNOWN),
    ]
    for tok, want in cases:
        assert classify_token(tok) == want, (
            f"ClassifyToken({tok!r}) = {classify_token(tok)}, want {want}"
        )


def test_token_kind_string() -> None:
    assert str(TokenKind.SESSION_INGRESS) == "session_ingress"
    assert str(TokenKind.ACCESS_TOKEN) == "access_token"
    assert str(TokenKind.UNKNOWN) == "unknown"


def test_is_token_expired() -> None:
    past = sign_test_token({"exp": int(time.time()) - 3600})
    future = sign_test_token({"exp": int(time.time()) + 3600})
    no_exp = sign_test_token({"sub": "x"})

    assert is_token_expired(past, timedelta(0))
    assert not is_token_expired(past, timedelta(hours=2))
    assert not is_token_expired(future, timedelta(0))
    assert not is_token_expired(no_exp, timedelta(0))
    assert not is_token_expired("malformed", timedelta(0))


def test_parse_token_safe() -> None:
    tok = sign_test_token(
        {
            "sub": "user42",
            "iss": "dxrk",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
    )

    info = parse_token_safe(tok, _key_func)
    assert info.is_valid, "token should be valid"
    assert not info.is_expired, "token should not be expired"
    assert info.subject == "user42" and info.issuer == "dxrk"
    assert info.kind == TokenKind.UNKNOWN, (
        f"kind = {info.kind}, want unknown (no prefix)"
    )

    # Tampered signature must fail
    tampered = tok[:-4] + "AAAA"
    with pytest.raises(ValueError):
        parse_token_safe(tampered, _key_func)

    # Wrong key must fail
    wrong_key = lambda header, claims: b"wrong-key"  # noqa: E731
    with pytest.raises(ValueError):
        parse_token_safe(tok, wrong_key)


def test_token_refresh_scheduler_defaults() -> None:
    called = False

    def refresh() -> str:
        nonlocal called
        called = True
        return ""

    s = TokenRefreshScheduler("", refresh, RefreshConfig())
    s.start()
    time.sleep(0.02)
    s.stop()

    assert not called, "empty token should never trigger refresh"
    assert s.token() == ""


def test_token_refresh_scheduler_refreshes_expired() -> None:
    expired = sign_test_token({"exp": int(time.time()) - 3600})

    cfg = RefreshConfig(
        poll_interval=timedelta(milliseconds=5),
        refresh_before=timedelta(minutes=1),
        retry_interval=timedelta(milliseconds=1),
        max_retries=1,
        clock_skew=timedelta(0),
    )
    s = TokenRefreshScheduler(expired, lambda: "fresh-token", cfg)

    s.start()
    time.sleep(0.05)
    s.stop()

    assert s.token() == "fresh-token"
    refreshes, failures, _, last_err = s.refresh_stats()
    assert refreshes >= 1, f"refreshCount = {refreshes}, want >= 1"
    assert failures == 0, f"failureCount = {failures}, want 0 (lastErr={last_err})"


def test_token_refresh_scheduler_retries_on_failure() -> None:
    expired = sign_test_token({"exp": int(time.time()) - 3600})

    def fail() -> str:
        raise RuntimeError("upstream down")

    cfg = RefreshConfig(
        poll_interval=timedelta(milliseconds=5),
        refresh_before=timedelta(minutes=1),
        retry_interval=timedelta(milliseconds=1),
        max_retries=1,
        clock_skew=timedelta(0),
    )
    s = TokenRefreshScheduler(expired, fail, cfg)

    s.start()
    time.sleep(0.05)
    s.stop()

    _, failures, _, last_err = s.refresh_stats()
    assert failures >= 1, f"failureCount = {failures}, want >= 1"
    assert last_err is not None, "lastError should be set after failures"


def test_is_device_trusted() -> None:
    now = datetime.now(UTC)
    cases = [
        (
            "empty token",
            TrustedDevice(token="", device_id="", created_at=now, expires_at=now),
            False,
        ),
        (
            "expired",
            TrustedDevice(
                token="x",
                device_id="",
                created_at=now - timedelta(minutes=20),
                expires_at=now - timedelta(minutes=1),
            ),
            False,
        ),
        (
            "too young",
            TrustedDevice(
                token="x",
                device_id="",
                created_at=now - timedelta(minutes=5),
                expires_at=now + timedelta(hours=1),
            ),
            False,
        ),
        (
            "valid",
            TrustedDevice(
                token="x",
                device_id="",
                created_at=now - timedelta(minutes=20),
                expires_at=now + timedelta(hours=1),
            ),
            True,
        ),
    ]
    for name, device, want in cases:
        assert is_device_trusted(device) == want, (
            f"{name}: IsDeviceTrusted = {is_device_trusted(device)}, want {want}"
        )


def test_validate_ingress_url() -> None:
    # Dev mode allows anything
    validate_ingress_url("http://insecure.example.com", True)
    # localhost exceptions
    validate_ingress_url("http://localhost:8080", False)
    validate_ingress_url("http://127.0.0.1:3000", False)
    # https ok
    validate_ingress_url("https://api.example.com", False)
    # plain http rejected in production
    with pytest.raises(ValueError):
        validate_ingress_url("http://api.example.com", False)


def test_validate_id() -> None:
    assert validate_id("abc123_-")
    assert not validate_id("")
    assert not validate_id("has space")
    assert not validate_id("a/b")
    assert not validate_id("a" * 257)


def test_redact_token() -> None:
    assert redact_token("short") == "[REDACTED]"
    got = redact_token("sk-ant-si-abcdefghijklmnopqrstuvwxyz1234")
    want = "sk-ant-s..." + "1234"
    assert got == want


# ---- permissions_test.go ----


def test_setting_source_string_and_priority() -> None:
    cases = [
        (SettingSource.USER, "user", 10),
        (SettingSource.PROJECT, "project", 20),
        (SettingSource.LOCAL, "local", 30),
        (SettingSource.FLAG, "flag", 40),
        (SettingSource.POLICY, "policy", 50),
        (SettingSource(99), "unknown", 0),
    ]
    for source, want_str, want_priority in cases:
        assert str(source) == want_str, (
            f"SettingSource({source}).String() = {source}, want {want_str}"
        )
        assert source.priority() == want_priority


def test_permission_behavior_string() -> None:
    assert str(PermissionBehavior.ALLOW) == "allow"
    assert str(PermissionBehavior.DENY) == "deny"


def test_permission_result_string() -> None:
    cases = {
        PermissionResult.ALLOWED: "allowed",
        PermissionResult.DENIED: "denied",
        PermissionResult.NEEDS_PROMPT: "needs_prompt",
        PermissionResult(99): "unknown",
    }
    for result, want in cases.items():
        assert str(result) == want, (
            f"PermissionResult({result}).String() = {result}, want {want}"
        )


def test_new_permission_context() -> None:
    pc = PermissionContext()
    assert pc.max_denials == 5, f"maxDenials = {pc.max_denials}, want 5"
    assert pc.rules() == [], f"Rules() = {pc.rules()}, want empty"


def test_load_rules_from_file(tmp_path) -> None:
    pc = PermissionContext()

    # Missing file is not an error
    pc.load_rules_from_file(str(tmp_path / "nope.json"), SettingSource.USER)

    path = tmp_path / "settings.json"
    content = """{"permissions":[
        {"tool":"Bash","prefix":"git commit","behavior":"deny"},
        {"tool":"Read","behavior":"allow"},
        {"tool":"Bash","pattern":"npm test *","behavior":"allow"}
    ]}"""
    path.write_text(content)
    pc.load_rules_from_file(str(path), SettingSource.PROJECT)

    rules = pc.rules()
    assert len(rules) == 3, f"rules = {len(rules)}, want 3"
    assert rules[0].prefix == "git commit"
    assert rules[0].behavior == PermissionBehavior.DENY
    assert rules[0].source == SettingSource.PROJECT
    assert rules[1].behavior == PermissionBehavior.ALLOW
    assert rules[2].pattern == "npm test *"


def test_load_rules_from_file_invalid_json(tmp_path) -> None:
    pc = PermissionContext()
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        pc.load_rules_from_file(str(path), SettingSource.USER)


def test_load_all_sources(tmp_path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "proj"

    def write(dir_: Path, name: str, content: str) -> None:
        (dir_ / ".claude").mkdir(parents=True, exist_ok=True)
        (dir_ / ".claude" / name).write_text(content)

    write(home, "settings.json", '{"permissions":[{"tool":"Read","behavior":"allow"}]}')
    write(
        proj,
        "settings.json",
        '{"permissions":[{"tool":"Bash","prefix":"git status","behavior":"allow"}]}',
    )
    write(
        proj,
        "settings.local.json",
        '{"permissions":[{"tool":"Bash","behavior":"deny"}]}',
    )

    pc = PermissionContext()
    pc.load_all_sources(str(home), str(proj))

    rules = pc.rules()
    assert len(rules) == 3, f"rules = {len(rules)}, want 3"
    sources = {}
    for r in rules:
        sources[r.source] = sources.get(r.source, 0) + 1
    assert sources.get(SettingSource.USER) == 1
    assert sources.get(SettingSource.PROJECT) == 1
    assert sources.get(SettingSource.LOCAL) == 1


def test_add_flag_rules() -> None:
    pc = PermissionContext()
    pc.add_flag_rules(["Bash", "Write"], PermissionBehavior.DENY)
    rules = pc.rules()
    assert len(rules) == 2, f"rules = {len(rules)}, want 2"
    for r in rules:
        assert r.source == SettingSource.FLAG, f"rule = {r}, want flag/deny"
        assert r.behavior == PermissionBehavior.DENY


def test_add_policy_rules_overrides_source() -> None:
    pc = PermissionContext()
    pc.add_policy_rules(
        [
            PermissionRule(
                tool="Bash", behavior=PermissionBehavior.DENY, source=SettingSource.USER
            )
        ]
    )
    rules = pc.rules()
    assert len(rules) == 1 and rules[0].source == SettingSource.POLICY


def test_check_no_rules() -> None:
    pc = PermissionContext()
    res, reason = pc.check("Bash", "ls")
    assert res == PermissionResult.NEEDS_PROMPT, (
        f"Check = {res} ({reason}), want needs_prompt"
    )


def test_check_allow_deny_and_priority() -> None:
    # user allow
    pc = PermissionContext()
    pc.add_flag_rules(["Bash"], PermissionBehavior.ALLOW)
    res, _ = pc.check("Bash", "ls")
    assert res == PermissionResult.ALLOWED

    # policy deny beats flag allow
    pc = PermissionContext()
    pc.add_flag_rules(["Bash"], PermissionBehavior.ALLOW)
    pc.add_policy_rules([PermissionRule(tool="Bash", behavior=PermissionBehavior.DENY)])
    res, reason = pc.check("Bash", "ls")
    assert res == PermissionResult.DENIED, f"Check = {res} ({reason}), want denied"

    # flag deny beats local allow
    pc = PermissionContext()
    pc.add_flag_rules(["Bash"], PermissionBehavior.DENY)
    pc.add_policy_rules(
        [PermissionRule(tool="Bash", behavior=PermissionBehavior.ALLOW)]
    )
    res, _ = pc.check("Bash", "ls")
    assert res == PermissionResult.ALLOWED, "want allowed (policy=50 wins)"

    # case insensitive tool match
    pc = PermissionContext()
    pc.add_flag_rules(["bash"], PermissionBehavior.ALLOW)
    res, _ = pc.check("Bash", "ls")
    assert res == PermissionResult.ALLOWED, "want allowed (case-insensitive)"


def test_check_prefix_word_boundary() -> None:
    pc = PermissionContext()
    pc.add_flag_rules(["Bash"], PermissionBehavior.ALLOW)
    pc.add_policy_rules(
        [
            PermissionRule(
                tool="Bash", prefix="git commit", behavior=PermissionBehavior.DENY
            )
        ]
    )

    res, reason = pc.check("Bash", "git commit -m hello")
    assert res == PermissionResult.DENIED, (
        f"git commit -m: {res} ({reason}), want denied"
    )
    res, _ = pc.check("Bash", "git commitx --amend")
    assert res == PermissionResult.ALLOWED, (
        "git commitx: want allowed (no word boundary match)"
    )


def test_check_glob_pattern() -> None:
    pc = PermissionContext()
    pc.add_policy_rules(
        [
            PermissionRule(
                tool="Bash", pattern="npm test *", behavior=PermissionBehavior.ALLOW
            )
        ]
    )

    res, _ = pc.check("Bash", "npm test --watch")
    assert res == PermissionResult.ALLOWED, "npm test --watch: want allowed"
    res, _ = pc.check("Bash", "npm install")
    assert res == PermissionResult.NEEDS_PROMPT, "npm install: want needs_prompt"


def test_check_auto_deny() -> None:
    pc = PermissionContext()
    for _ in range(5):
        pc.record_denial("Bash")
    res, reason = pc.check("Bash", "ls")
    assert res == PermissionResult.DENIED, (
        f"Check = {res}, want denied after threshold"
    )
    assert reason != "", "auto-deny should include a reason"

    pc.reset_denials()
    res, _ = pc.check("Bash", "ls")
    assert res == PermissionResult.NEEDS_PROMPT, (
        f"after ResetDenials: {res}, want needs_prompt"
    )


def test_match_glob() -> None:
    from dxrk.security.permissions import _match_glob

    cases = [
        ("*", "", True),
        ("*", "abc", True),
        ("a*", "abc", True),
        ("a*", "xabc", False),
        ("a?c", "abc", True),
        ("a?c", "ac", False),
        ("a*c", "abbbc", True),
        ("a*c", "aXc", True),
        ("exact", "exact", True),
        ("exact", "exacto", False),
    ]
    for pattern, s, want in cases:
        assert _match_glob(pattern, s) == want, (
            f"matchGlob({pattern!r}, {s!r}) = {_match_glob(pattern, s)}, want {want}"
        )


def test_classify_tool() -> None:
    assert classify_tool("Read") == PermissionResult.ALLOWED
    assert classify_tool("Bash") == PermissionResult.NEEDS_PROMPT
    assert classify_tool("MysteryTool") == PermissionResult.NEEDS_PROMPT


def test_detect_unreachable_rules() -> None:
    # shadowed rule detected
    rules = [
        PermissionRule(
            tool="Bash",
            prefix="git commit",
            behavior=PermissionBehavior.DENY,
            source=SettingSource.USER,
        ),
        PermissionRule(
            tool="Bash",
            prefix="git commit",
            behavior=PermissionBehavior.ALLOW,
            source=SettingSource.FLAG,
        ),
    ]
    got = detect_unreachable_rules(rules)
    assert len(got) == 1, f"unreachable = {got}, want 1"
    assert got[0] == "rule Bash/git commit (deny) shadowed by Bash/git commit (allow)"

    # no duplicates
    rules = [
        PermissionRule(
            tool="Bash",
            prefix="git commit",
            behavior=PermissionBehavior.DENY,
            source=SettingSource.USER,
        ),
        PermissionRule(
            tool="Bash",
            prefix="git push",
            behavior=PermissionBehavior.DENY,
            source=SettingSource.USER,
        ),
    ]
    assert detect_unreachable_rules(rules) == []

    # same priority different behavior
    rules = [
        PermissionRule(
            tool="Read", behavior=PermissionBehavior.DENY, source=SettingSource.USER
        ),
        PermissionRule(
            tool="Read", behavior=PermissionBehavior.ALLOW, source=SettingSource.USER
        ),
    ]
    assert len(detect_unreachable_rules(rules)) == 1

    # identical duplicates not flagged
    rules = [
        PermissionRule(
            tool="Read", behavior=PermissionBehavior.ALLOW, source=SettingSource.USER
        ),
        PermissionRule(
            tool="Read", behavior=PermissionBehavior.ALLOW, source=SettingSource.USER
        ),
    ]
    assert detect_unreachable_rules(rules) == []


# ---- yolo_test.go ----


def test_risk_level_string() -> None:
    cases = {
        RiskLevel.NONE: "none",
        RiskLevel.LOW: "low",
        RiskLevel.MEDIUM: "medium",
        RiskLevel.HIGH: "high",
        RiskLevel.CRITICAL: "critical",
        RiskLevel(99): "unknown",
    }
    for level, want in cases.items():
        assert str(level) == want, f"RiskLevel({level}).String() = {level}, want {want}"


def test_classify_for_auto_mode() -> None:
    # Confirmation-required tools
    d = classify_for_auto_mode("Bash", "ls")
    assert d.action == "ask" and d.risk == RiskLevel.HIGH
    # Safe tools
    s = classify_for_auto_mode("Read", "file.txt")
    assert s.action == "allow" and s.risk == RiskLevel.NONE
    # Unknown tools
    u = classify_for_auto_mode("TotallyUnknownTool", "")
    assert u.action == "ask" and u.risk == RiskLevel.MEDIUM


def test_assess_bash_risk() -> None:
    cases = [
        ("", RiskLevel.NONE),
        ("ls -la", RiskLevel.LOW),
        ("echo hi", RiskLevel.LOW),
        ("git status", RiskLevel.LOW),
        ("mkdir -p /tmp/x", RiskLevel.MEDIUM),
        ("cp a b", RiskLevel.MEDIUM),
        ("curl https://example.com", RiskLevel.MEDIUM),
        ("ssh host", RiskLevel.MEDIUM),
        ("systemctl restart nginx", RiskLevel.HIGH),
        ("kill -9 1234", RiskLevel.HIGH),
        ("sudo rm -rf /", RiskLevel.HIGH),
        ("rm file.txt", RiskLevel.HIGH),
        ("$(ls)", RiskLevel.HIGH),
        ("eval echo hi", RiskLevel.HIGH),
    ]
    for cmd, want in cases:
        assert assess_bash_risk(cmd) == want, (
            f"AssessBashRisk({cmd!r}) = {assess_bash_risk(cmd)}, want {want}"
        )


def test_check_dangerous_patterns() -> None:
    matches = check_dangerous_patterns("rm -rf /", "Bash")
    assert len(matches) == 1 and matches[0].risk == RiskLevel.CRITICAL

    # Tool filtering: pattern only applies to Bash
    assert check_dangerous_patterns("rm -rf /", "Read") == []

    # Case-insensitive matching
    assert len(check_dangerous_patterns("RM -RF /", "Bash")) == 1

    # curl | sh
    assert check_dangerous_patterns("curl -sSL https://x | sh", "Bash") == []
    literal = check_dangerous_patterns("curl | sh", "Bash")
    assert len(literal) == 1 and literal[0].risk == RiskLevel.CRITICAL

    # Benign command
    assert check_dangerous_patterns("echo hello", "Bash") == []


def test_circuit_breaker() -> None:
    cb = CircuitBreaker(3, 60)
    assert cb.trip_threshold == 3 and cb.reset_after == 60

    assert not cb.should_block(), "fresh breaker should not block"

    assert not cb.record_failure(), "first failure should not trip"
    assert not cb.record_failure(), "second failure should not trip"
    assert cb.record_failure(), "third failure should trip the breaker"
    assert cb.should_block(), "tripped breaker should block"

    cb.reset()
    assert not cb.should_block()
    assert cb.trip_count == 0
    assert cb.last_trip == 0


def test_circuit_breaker_threshold_one() -> None:
    cb = CircuitBreaker(1, 30)
    assert cb.record_failure(), "single failure should trip with threshold 1"
    assert cb.should_block(), "breaker should block after trip"
    assert cb.trip_count == 1, f"TripCount = {cb.trip_count}, want 1"


# ---- Tool set sanity (mirrors yolo.go / permissions.go maps) ----


def test_tool_sets() -> None:
    for tool in ("Read", "Glob", "Grep", "LS", "ListFiles", "TodoRead"):
        assert SAFE_TOOLS[tool]
        assert READ_ONLY_TOOLS[tool]
        assert SAFE_FOR_AUTO_MODE[tool]
        assert READ_TOOLS[tool]
    assert SAFE_TOOLS["Read"]
    assert ALWAYS_ASK_TOOLS["Bash"] and ALWAYS_ASK_TOOLS["Execute"]
    assert NEEDS_CONFIRMATION["Bash"] and NEEDS_CONFIRMATION["Write"]
    assert len(KNOWN_DANGEROUS_PATTERNS) == 10


def test_classification_decision_fields() -> None:
    d = classify_for_auto_mode("Read", "file.txt")
    assert isinstance(d, ClassificationDecision)
    assert d.tool_name == "Read" and d.command == "file.txt" and d.reason != ""

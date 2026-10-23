# SPDX-License-Identifier: MIT
"""Cobertura 100% final6 — sdd, security/ast, memory/production, memory/judge_continuous, app.

Tests reales de comportamiento: tmp dirs, fakes y mocks puntuales. Sin red real.
"""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from dxrk.app import SelfUpdateChecker, resolve_version, run_cli
from dxrk.components import sdd
from dxrk.memory.eval_harness import EvalReport
from dxrk.memory.judge_continuous import ContinuousJudge, _now_iso
from dxrk.memory.production import (
    AutoRollbackManager,
    HealthMetrics,
    SLOConfig,
    check_slo,
    check_slo_compliance,
    collect_health_metrics,
    get_circuit_breaker,
    get_circuit_breakers,
    load_production_state,
    load_slo_config,
    run_production_health_check,
    save_production_state,
)
from dxrk.models import AgentID, ModelAssignment, Profile, SDDModeID
from dxrk.security.ast import (
    ASTNode,
    NodeType,
    Token,
    TokenType,
    analyze_ast,
    command_name,
    detect_dangerous_patterns,
    extract_command_name,
    has_dangerous_patterns,
    is_ascii,
    is_dangerous_command,
    is_env_assignment,
    is_quiet,
    is_read_only_command,
    parse_for_security,
    parse_shell,
    quote_safety,
    redact_sensitive,
    sanitize_for_log,
    strip_ansi,
    tokenize,
    truncate_with_suffix,
    validate_ast,
)

# ─── app.py ────────────────────────────────────────────────────────────────


class TestAppVersion:
    def test_dev_passthrough(self) -> None:
        assert resolve_version("dev") == "dev"

    def test_ldflags_version(self) -> None:
        assert resolve_version("v1.2.3") == "v1.2.3"

    def test_print_help_embeds_version(self) -> None:
        from dxrk.app import print_help

        assert "v9.9.9" in print_help("v9.9.9")
        assert "dxrk" in print_help()


class TestAppSelfUpdateChecker:
    def test_skip_done(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DXRK_SELF_UPDATE_DONE", "1")
        c = SelfUpdateChecker(version="v1.0.0")
        assert c.skip_reason() == "ya actualizado en esta invocación"
        assert c.check() is None

    def test_skip_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.setenv("DXRK_NO_SELF_UPDATE", "1")
        c = SelfUpdateChecker(version="v1.0.0")
        assert c.skip_reason() == "exclusión vía DXRK_NO_SELF_UPDATE"
        assert c.check() is None

    def test_skip_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        assert SelfUpdateChecker(version="dev").skip_reason() == "versión dev"

    def test_no_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        assert SelfUpdateChecker(version="v1.0.0").skip_reason() is None

    def test_check_no_target(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        monkeypatch.setattr("dxrk.app.check_filtered", lambda *a, **k: [])
        assert SelfUpdateChecker(version="v1.0.0", profile=object()).check() is None

    def test_check_up_to_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.app.check_filtered", lambda *a, **k: [res])
        assert SelfUpdateChecker(version="v1.0.0", profile=object()).check() is None

    def test_check_ignores_other_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        res = UpdateResult(
            tool=ToolInfo(name="other"),
            status=UpdateStatus.UPDATE_AVAILABLE,
            latest_version="v2.0.0",
        )
        monkeypatch.setattr("dxrk.app.check_filtered", lambda *a, **k: [res])
        assert SelfUpdateChecker(version="v1.0.0", profile=object()).check() is None

    def test_check_update_available(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        monkeypatch.delenv("DXRK_SELF_UPDATE_DONE", raising=False)
        monkeypatch.delenv("DXRK_NO_SELF_UPDATE", raising=False)
        res = UpdateResult(
            tool=ToolInfo(name="dxrk"),
            status=UpdateStatus.UPDATE_AVAILABLE,
            latest_version="v2.0.0",
        )
        monkeypatch.setattr("dxrk.app.check_filtered", lambda *a, **k: [res])
        checker = SelfUpdateChecker(version="v1.0.0", profile=object())
        assert checker.check() == "v2.0.0"
        buf = StringIO()
        assert checker.check(stdout=buf) == "v2.0.0"
        assert "v2.0.0" in buf.getvalue()


def _ok_detection():  # type: ignore[no-untyped-def]
    from dxrk.system import DetectionResult, PlatformProfile, SystemInfo

    return DetectionResult(system=SystemInfo(supported=True, profile=PlatformProfile(supported=True)))


def _patch_cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda goos: None)
    monkeypatch.setattr("dxrk.app.detect", _ok_detection)
    monkeypatch.setattr("dxrk.cli.install.resolve_install_profile", lambda det: SimpleNamespace())
    monkeypatch.setattr(SelfUpdateChecker, "check", lambda self, stdout=None: None)


class TestAppRunCli:
    def test_version(self, capsys: pytest.CaptureFixture) -> None:
        assert run_cli(["version"]) == 0
        assert "dxrk" in capsys.readouterr().out

    def test_version_flags(self, capsys: pytest.CaptureFixture) -> None:
        assert run_cli(["--version"]) == 0
        assert run_cli(["-v"]) == 0

    def test_help(self, capsys: pytest.CaptureFixture) -> None:
        assert run_cli(["help"]) == 0
        assert "dxrk" in capsys.readouterr().out
        assert run_cli(["--help"]) == 0
        assert run_cli(["-h"]) == 0

    def test_uninstall_ok(self) -> None:
        assert run_cli(["uninstall", "--all"]) == 0

    def test_uninstall_bad_flags(self, capsys: pytest.CaptureFixture) -> None:
        assert run_cli(["uninstall"]) == 1
        assert "Error" in capsys.readouterr().err

    def test_unsupported_os(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        def _raise(goos: str) -> None:
            raise OSError("OS no soportado")

        monkeypatch.setattr("dxrk.app.ensure_supported_os", _raise)
        assert run_cli([]) == 1
        assert "Error" in capsys.readouterr().err

    def test_detect_failure(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda goos: None)

        def _boom() -> None:
            raise RuntimeError("sin sistema")

        monkeypatch.setattr("dxrk.app.detect", _boom)
        assert run_cli([]) == 1
        assert "detectar" in capsys.readouterr().err

    def test_unsupported_platform(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        from dxrk.system import DetectionResult, PlatformProfile, SystemInfo

        monkeypatch.setattr("dxrk.app.ensure_supported_os", lambda goos: None)
        det = DetectionResult(system=SystemInfo(supported=False, profile=PlatformProfile()))
        monkeypatch.setattr("dxrk.app.detect", lambda: det)

        def _raise(profile):  # type: ignore[no-untyped-def]
            raise OSError("plataforma no soportada")

        monkeypatch.setattr("dxrk.app.ensure_supported_platform", _raise)
        assert run_cli([]) == 1
        assert "Error" in capsys.readouterr().err

    def test_checker_warning_then_tui(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        _patch_cli_env(monkeypatch)

        def _boom(self, stdout=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("red caída")

        monkeypatch.setattr(SelfUpdateChecker, "check", _boom)
        assert run_cli([]) == 0
        captured = capsys.readouterr()
        assert "autoactualización" in captured.err
        assert "TUI" in captured.out

    def test_update_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        _patch_cli_env(monkeypatch)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.update.check_all", lambda *a, **k: [res])
        assert run_cli(["update"]) == 0

    def test_update_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        _patch_cli_env(monkeypatch)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.CHECK_FAILED)
        monkeypatch.setattr("dxrk.update.check_all", lambda *a, **k: [res])
        assert run_cli(["update"]) == 1

    def test_upgrade_filtered_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus

        _patch_cli_env(monkeypatch)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.CHECK_FAILED)
        monkeypatch.setattr("dxrk.update.check_filtered", lambda *a, **k: [res])
        assert run_cli(["upgrade", "dxrk"]) == 1

    def test_upgrade_dry_run_ok(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus, UpgradeReport

        _patch_cli_env(monkeypatch)
        monkeypatch.setattr("dxrk.app.os.path.expanduser", lambda p: str(tmp_path))
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.update.check_filtered", lambda *a, **k: [res])
        monkeypatch.setattr("dxrk.update.execute", lambda *a, **k: UpgradeReport(backup_id="b1", results=[]))
        assert run_cli(["upgrade", "--dry-run"]) == 0

    def test_upgrade_report_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from dxrk.update import (
            InstallMethod,
            ToolInfo,
            ToolUpgradeResult,
            ToolUpgradeStatus,
            UpdateResult,
            UpdateStatus,
            UpgradeReport,
        )

        _patch_cli_env(monkeypatch)
        monkeypatch.setattr("dxrk.app.os.path.expanduser", lambda p: str(tmp_path))
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.update.check_filtered", lambda *a, **k: [res])
        bad = ToolUpgradeResult(
            tool_name="dxrk",
            method=InstallMethod.BINARY,
            status=ToolUpgradeStatus.FAILED,
            err="boom",
        )
        monkeypatch.setattr("dxrk.update.execute", lambda *a, **k: UpgradeReport(backup_id="b1", results=[bad]))
        assert run_cli(["upgrade"]) == 1

    def test_upgrade_unknown_flag_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import ToolInfo, UpdateResult, UpdateStatus, UpgradeReport

        _patch_cli_env(monkeypatch)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.update.check_filtered", lambda *a, **k: [res])
        monkeypatch.setattr("dxrk.update.execute", lambda *a, **k: UpgradeReport(backup_id="b1", results=[]))
        assert run_cli(["upgrade", "--bogus"]) == 0

    def test_upgrade_multi_result_report(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.update import (
            InstallMethod,
            ToolInfo,
            ToolUpgradeResult,
            ToolUpgradeStatus,
            UpdateResult,
            UpdateStatus,
            UpgradeReport,
        )

        _patch_cli_env(monkeypatch)
        res = UpdateResult(tool=ToolInfo(name="dxrk"), status=UpdateStatus.UP_TO_DATE)
        monkeypatch.setattr("dxrk.update.check_filtered", lambda *a, **k: [res])
        clean = ToolUpgradeResult(tool_name="dxrk", method=InstallMethod.BINARY, status=ToolUpgradeStatus.SUCCEEDED)
        monkeypatch.setattr("dxrk.update.execute", lambda *a, **k: UpgradeReport(backup_id="b1", results=[clean]))
        assert run_cli(["upgrade"]) == 0

        bad = ToolUpgradeResult(
            tool_name="dxrk",
            method=InstallMethod.BINARY,
            status=ToolUpgradeStatus.FAILED,
            err="boom",
        )
        monkeypatch.setattr(
            "dxrk.update.execute",
            lambda *a, **k: UpgradeReport(backup_id="b1", results=[clean, bad]),
        )
        assert run_cli(["upgrade"]) == 1

    def test_install_dry_run(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        from dxrk.cli.run import InstallResult

        _patch_cli_env(monkeypatch)
        monkeypatch.setattr("dxrk.app.run_install", lambda args, det: InstallResult(dry_run=True))
        assert run_cli(["install"]) == 0
        assert "Simulación" in capsys.readouterr().out

    def test_install_verify_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.cli.run import InstallResult

        _patch_cli_env(monkeypatch)
        bad = InstallResult(dry_run=False, verify=SimpleNamespace(ready=False))
        monkeypatch.setattr("dxrk.app.run_install", lambda args, det: bad)
        assert run_cli(["install"]) == 1

    def test_install_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.cli.run import InstallResult

        _patch_cli_env(monkeypatch)
        monkeypatch.setattr("dxrk.app.run_install", lambda args, det: InstallResult(dry_run=False))
        assert run_cli(["install"]) == 0

    def test_sync_ok(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        _patch_cli_env(monkeypatch)
        assert run_cli(["sync"]) == 0
        assert "Sincronización" in capsys.readouterr().out

    def test_sync_bad_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_cli_env(monkeypatch)
        assert run_cli(["sync", "--bogus-flag"]) == 1

    def test_restore(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_cli_env(monkeypatch)
        assert run_cli(["restore"]) == 0

    def test_unknown_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_cli_env(monkeypatch)
        assert run_cli(["frobnicate"]) == 1

    def test_outer_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_cli_env(monkeypatch)

        def _boom(*a, **k):  # type: ignore[no-untyped-def]
            raise ValueError("mal")

        monkeypatch.setattr("dxrk.update.check_all", _boom)
        assert run_cli(["update"]) == 1

    def test_outer_os_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_cli_env(monkeypatch)

        def _boom(*a, **k):  # type: ignore[no-untyped-def]
            raise OSError("disco")

        monkeypatch.setattr("dxrk.update.check_all", _boom)
        assert run_cli(["update"]) == 1


# ─── security/ast.py ───────────────────────────────────────────────────────


class TestAstPatterns:
    def test_hex_escape(self) -> None:
        assert "hex escape sequence detected" in detect_dangerous_patterns("echo \\x41")

    def test_token_str(self) -> None:
        assert "hi" in str(Token(typ=TokenType.WORD, value="hi", pos=0))

    def test_node_unknown_str(self) -> None:
        assert str(NodeType(99)) == "unknown"
        assert str(NodeType.UNKNOWN) == "unknown"
        assert str(NodeType.COMMAND) == "command"

    def test_has_dangerous(self) -> None:
        assert has_dangerous_patterns("echo $(ls)") is True
        assert has_dangerous_patterns("echo hi") is False

    def test_is_dangerous_command(self) -> None:
        assert is_dangerous_command("rm") is True
        assert is_dangerous_command("ls") is False

    def test_validate_dangerous(self) -> None:
        assert validate_ast(parse_shell("rm -rf /")) == ["dangerous command: rm"]

    def test_sudo_unsafe(self) -> None:
        assert parse_for_security("sudo ls").is_safe is False

    def test_safe_command(self) -> None:
        assert parse_for_security("echo hi").is_safe is True


class TestAstTokenize:
    def test_newline_tokens(self) -> None:
        toks = tokenize("echo a\necho b")
        assert any(t.typ == TokenType.NEWLINE for t in toks)

    def test_comment_with_newline(self) -> None:
        toks = tokenize("echo a # c\n echo b")
        words = [t.value for t in toks if t.typ == TokenType.WORD]
        assert words == ["echo", "a", "echo", "b"]

    def test_comment_at_eof(self) -> None:
        toks = tokenize("echo hi # trailing")
        words = [t.value for t in toks if t.typ == TokenType.WORD]
        assert words == ["echo", "hi"]

    def test_unterminated_string(self) -> None:
        with pytest.raises(ValueError):
            tokenize('"abc')

    def test_parse_error_fail_closed(self) -> None:
        res = parse_for_security('"abc')
        assert res.is_safe is False
        assert any("parse error" in v for v in res.violations)
        assert res.root is None

    def test_dollar_substitution(self) -> None:
        toks = tokenize("echo $(ls)")
        assert [t.typ for t in toks] == [
            TokenType.WORD,
            TokenType.DOLLAR,
            TokenType.WORD,
            TokenType.RPAREN,
            TokenType.EOF,
        ]

    def test_dollar_var(self) -> None:
        toks = tokenize("$foo Bar")
        assert toks[0].value == "$foo"
        assert toks[1].value == "Bar"

    def test_dollar_braced(self) -> None:
        toks = tokenize("echo ${HOME}")
        assert toks[1].value == "${HOME}"

    def test_dollar_braced_unclosed(self) -> None:
        toks = tokenize("${unclosed")
        assert toks[0].value == "${unclosed"

    def test_backtick(self) -> None:
        toks = tokenize("echo `ls`")
        assert toks[1].typ == TokenType.BACKTICK
        assert toks[3].typ == TokenType.BACKTICK

    def test_rparen_depth_zero(self) -> None:
        toks = tokenize("echo hi)")
        assert toks[-2].typ == TokenType.RPAREN

    def test_subshell_parens(self) -> None:
        toks = tokenize("(echo hi)")
        assert toks[0].typ == TokenType.LPAREN
        assert toks[-2].typ == TokenType.RPAREN

    def test_redirect_append(self) -> None:
        toks = tokenize("echo a >> f")
        assert toks[2].typ == TokenType.REDIRECT_APPEND

    def test_redirect_out(self) -> None:
        toks = tokenize("echo a > f")
        assert toks[2].typ == TokenType.REDIRECT_OUT

    def test_heredoc_triple(self) -> None:
        toks = tokenize("cat <<< x")
        assert toks[1].typ == TokenType.HEREDOC
        assert toks[1].value == "<<<"

    def test_heredoc_double(self) -> None:
        toks = tokenize("cat << EOF")
        assert toks[1].typ == TokenType.HEREDOC
        assert toks[1].value == "<<"

    def test_redirect_in(self) -> None:
        toks = tokenize("cat < f")
        assert toks[1].typ == TokenType.REDIRECT_IN

    def test_pipe_pipe(self) -> None:
        assert tokenize("a || b")[1].typ == TokenType.PIPE_PIPE

    def test_pipe(self) -> None:
        assert tokenize("a | b")[1].typ == TokenType.PIPE

    def test_amp_amp(self) -> None:
        assert tokenize("a && b")[1].typ == TokenType.AMP_AMP

    def test_background_amp(self) -> None:
        toks = tokenize("a &")
        assert toks[1].typ == TokenType.WORD
        assert toks[1].value == "&"

    def test_semicolon(self) -> None:
        assert tokenize("a; b")[1].typ == TokenType.SEMICOLON

    def test_embedded_double_quotes(self) -> None:
        toks = tokenize('echo "a b" c')
        assert [t.value for t in toks if t.typ == TokenType.WORD] == ["echo", "c"]

    def test_embedded_escaped_quote(self) -> None:
        toks = tokenize('echo a"b\\"c"d')
        assert toks[1].value == 'a"b\\"c"d'

    def test_embedded_single_quotes(self) -> None:
        toks = tokenize("echo a'b c'd")
        assert toks[1].value == "a'b c'd"

    def test_dollar_breaks_word(self) -> None:
        toks = tokenize("echo foo$bar")
        assert [t.value for t in toks if t.typ == TokenType.WORD] == ["echo", "foo", "$bar"]

    def test_cmdsubst_breaks_word(self) -> None:
        toks = tokenize("echo foo$(bar)")
        typs = [t.typ for t in toks]
        assert TokenType.DOLLAR in typs

    def test_tilde_progress(self) -> None:
        toks = tokenize("~")
        assert toks[0].value == "~"
        assert toks[-1].typ == TokenType.EOF

    def test_unterminated_embedded_quote(self) -> None:
        toks = tokenize('echo a"b')
        assert toks[1].value == 'a"b'

    def test_unbalanced_paren_no_hang(self) -> None:
        root = parse_shell("(echo hi")
        assert root.children[0].type == NodeType.SUBSHELL

    def test_tilde_word(self) -> None:
        toks = tokenize("echo ~/docs")
        assert "~" in [t.value for t in toks if t.typ == TokenType.WORD]
        assert parse_for_security("echo ~/docs").is_safe is True


class TestAstBuild:
    def test_multiline_two_commands(self) -> None:
        root = parse_shell("echo a\necho b")
        assert len([c for c in root.children if c.type == NodeType.COMMAND]) == 2

    def test_redirect_without_target(self) -> None:
        root = parse_shell("echo hi >")
        cmd = root.children[0]
        assert cmd.children[1].type == NodeType.REDIRECT
        assert cmd.children[1].children == []

    def test_redirect_with_target(self) -> None:
        root = parse_shell("echo hi > f")
        redir = root.children[0].children[1]
        assert redir.children[0].value == "f"

    def test_double_pipe_wraps_pipeline(self) -> None:
        root = parse_shell("a | b | c")
        assert any(c.type == NodeType.PIPELINE for c in root.children)

    def test_subshell(self) -> None:
        root = parse_shell("(echo hi)")
        assert root.children[0].type == NodeType.SUBSHELL
        assert root.children[0].children[0].type == NodeType.COMMAND

    def test_nested_subshell(self) -> None:
        root = parse_shell("(a; (b))")
        assert root.children[0].type == NodeType.SUBSHELL

    def test_dollar_skipped_in_ast(self) -> None:
        root = parse_shell("echo $(ls)")
        assert root.children[0].value == "echo"


class TestAstAnalysis:
    def test_none_roots(self) -> None:
        assert analyze_ast(None) == ([], [])
        assert validate_ast(None) == []

    def test_unknown_node_ignored(self) -> None:
        root = ASTNode(
            type=NodeType.LIST,
            value="root",
            children=[
                ASTNode(type=NodeType.WORD, value="stray"),
                ASTNode(type=NodeType.COMMAND, value="echo"),
            ],
        )
        assert analyze_ast(root) == ([], ["echo"])

    def test_env_assignment_collected(self) -> None:
        env_vars, operators = analyze_ast(parse_shell("FOO=bar"))
        assert env_vars == ["FOO=bar"]
        assert operators == [""]

    def test_operators_chain(self) -> None:
        _, operators = analyze_ast(parse_shell("a && b"))
        assert operators == ["a", "&&", "b"]

    def test_pipeline_recursion(self) -> None:
        env_vars, operators = analyze_ast(parse_shell("a | b | c"))
        assert "a" in operators and "b" in operators

    def test_subshell_recursion(self) -> None:
        _, operators = analyze_ast(parse_shell("(echo hi)"))
        assert "echo" in operators

    def test_validate_subshell_recursion(self) -> None:
        assert validate_ast(parse_shell("(rm x)")) == ["dangerous command: rm"]

    def test_command_name_edges(self) -> None:
        assert command_name(None) == ""
        assert command_name(ASTNode(type=NodeType.WORD, value="x")) == ""
        assert command_name(ASTNode(type=NodeType.COMMAND, value="=foo")) == "=foo"
        assert command_name(ASTNode(type=NodeType.COMMAND, value="FOO=bar")) == ""
        assert command_name(ASTNode(type=NodeType.COMMAND, value="ls")) == "ls"

    def test_env_assignment_edges(self) -> None:
        assert is_env_assignment(None) is False
        assert is_env_assignment(ASTNode(type=NodeType.WORD, value="x")) is False
        assert is_env_assignment(ASTNode(type=NodeType.COMMAND, value="FOO=")) is False
        assert is_env_assignment(ASTNode(type=NodeType.COMMAND, value="FOO-BAR=x")) is False
        assert is_env_assignment(ASTNode(type=NodeType.COMMAND, value="plain")) is False
        assert is_env_assignment(ASTNode(type=NodeType.COMMAND, value="FOO=bar")) is True
        assert is_env_assignment(ASTNode(type=NodeType.COMMAND, value="A1_=x")) is True

    def test_extract_edges(self) -> None:
        assert extract_command_name('"oops') == ""
        assert extract_command_name("(echo hi)") == ""
        assert extract_command_name("echo hi") == "echo"

    def test_read_only(self) -> None:
        assert is_read_only_command("ls -la") is True
        assert is_read_only_command("rm x") is False

    def test_quote_safety(self) -> None:
        assert quote_safety("abc") == "abc"
        assert quote_safety("a b") == "'a b'"
        assert quote_safety("a'b") == "'a'\"'\"'b'"

    def test_strip_ansi(self) -> None:
        assert strip_ansi("\x1b[31mhi\x1b[0m") == "hi"

    def test_is_quiet(self) -> None:
        assert is_quiet("   ") is True
        assert is_quiet("x") is False

    def test_truncate(self) -> None:
        assert truncate_with_suffix("abc", 10, "...") == "abc"
        assert truncate_with_suffix("abcdef", 5, "...") == "ab..."

    def test_redact(self) -> None:
        assert "[REDACTED]" in redact_sensitive("key sk-abcdefghij1234567890")
        assert "[REDACTED]" in redact_sensitive("api_key=secret123")

    def test_ascii(self) -> None:
        assert is_ascii("hello") is True
        assert is_ascii("héllo") is False

    def test_sanitize_log(self) -> None:
        assert "[REDACTED]" in sanitize_for_log("token=abc123")


# ─── memory/production.py ──────────────────────────────────────────────────


def _good_metrics(**over: object) -> HealthMetrics:
    from dxrk.memory.production import _now_iso

    base: dict[str, object] = {
        "timestamp": _now_iso(),
        "search_latency_p50_ms": 50.0,
        "search_latency_p95_ms": 150.0,
        "search_latency_p99_ms": 180.0,
        "mine_throughput_files_per_sec": 100.0,
        "calibration_ece": {"w1": 0.03},
        "quarantine_count": 0,
        "stress_level": 0.2,
        "memory_usage_mb": 500.0,
        "memory_usage_percent": 50.0,
        "disk_usage_mb": 1000.0,
        "disk_usage_percent": 30.0,
    }
    base.update(over)
    return HealthMetrics(**base)  # type: ignore[arg-type]


class TestProductionState:
    def test_status_aliases(self) -> None:
        status = check_slo_compliance(_good_metrics(), SLOConfig())
        assert status.compliant is True
        assert status.details == []

    def test_load_slo_corrupted(self, tmp_path: Path) -> None:
        (tmp_path / ".slo_config.json").write_text("not json{")
        assert load_slo_config(tmp_path) == SLOConfig()

    def test_production_state_missing(self, tmp_path: Path) -> None:
        assert load_production_state(tmp_path) == {
            "health_history": [],
            "last_calibration_rollback": "",
        }

    def test_production_state_roundtrip(self, tmp_path: Path) -> None:
        save_production_state(tmp_path, {"health_history": [{"a": 1}], "last_calibration_rollback": "x"})
        assert load_production_state(tmp_path)["last_calibration_rollback"] == "x"

    def test_production_state_corrupted(self, tmp_path: Path) -> None:
        (tmp_path / ".production_state.json").write_text("zzz")
        assert load_production_state(tmp_path)["health_history"] == []

    def test_production_state_non_dict(self, tmp_path: Path) -> None:
        (tmp_path / ".production_state.json").write_text("[1, 2]")
        assert load_production_state(tmp_path)["health_history"] == []

    def test_quarantine_zero_ok(self) -> None:
        status = check_slo_compliance(_good_metrics(quarantine_count=0), SLOConfig())
        assert status.quarantine_rate_ok is True
        assert status.overall_ok is True

    def test_collect_metrics(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dxrk.memory.stress.compute_system_stress", lambda p: SimpleNamespace(level=0.3))
        malla = SimpleNamespace(
            search=lambda query, n_results: [],
            list_partitions=lambda: ["w1"],
            partition_usage=lambda partition: {"quarantined": 1, "count": 5, "budget": 10},
        )
        metrics = collect_health_metrics(malla)
        assert metrics.calibration_ece == {"w1": 0.05}
        assert metrics.quarantine_count == 1
        assert metrics.stress_level == 0.3

    def test_circuit_registry(self) -> None:
        first = get_circuit_breaker("final6-cb")
        assert get_circuit_breaker("final6-cb") is first
        assert "final6-cb" in get_circuit_breakers()

    def test_health_check_and_slo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("dxrk.memory.stress.compute_system_stress", lambda p: SimpleNamespace(level=0.1))
        malla = SimpleNamespace(
            _path=str(tmp_path),
            search=lambda query, n_results: [],
            list_partitions=lambda: [],
            partition_usage=lambda partition: {},
        )
        metrics, status = run_production_health_check(malla)
        assert metrics.timestamp != ""
        assert isinstance(status.overall_ok, bool)
        assert (tmp_path / ".production_state.json").exists()
        assert check_slo(malla).overall_ok == status.overall_ok

    def test_health_history_truncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.production import HEALTH_HISTORY_MAX

        monkeypatch.setattr("dxrk.memory.stress.compute_system_stress", lambda p: SimpleNamespace(level=0.1))
        malla = SimpleNamespace(
            _path=str(tmp_path),
            search=lambda query, n_results: [],
            list_partitions=lambda: [],
            partition_usage=lambda partition: {},
        )
        save_production_state(
            tmp_path,
            {
                "health_history": [{"n": i} for i in range(HEALTH_HISTORY_MAX + 1)],
                "last_calibration_rollback": "",
            },
        )
        _, _ = run_production_health_check(malla)
        assert len(load_production_state(tmp_path)["health_history"]) == HEALTH_HISTORY_MAX


def _rep(recall10: float, mrr: float, ece: float):  # type: ignore[no-untyped-def]
    return SimpleNamespace(recall_at_k={10: recall10}, mrr=mrr, ece=ece)


class TestAutoRollback:
    def test_baseline_none(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        assert mgr.check_and_rollback(object(), "w", "t", _rep(0.5, 0.5, 0.05), None) is False

    def test_no_regression(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        assert mgr.check_and_rollback(object(), "w", "t", _rep(0.9, 0.8, 0.05), _rep(0.9, 0.8, 0.05)) is False

    def test_warning_needs_confirmation(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path, confirmation_required=True)
        current = _rep(0.9, 0.3, 0.05)
        baseline = _rep(0.9, 0.8, 0.05)
        assert mgr.check_and_rollback(object(), "w", "t", current, baseline) is False

    def test_warning_no_confirmation_rolls_back(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path, confirmation_required=False)
        current = _rep(0.9, 0.3, 0.05)
        baseline = _rep(0.9, 0.8, 0.05)
        assert mgr.check_and_rollback(object(), "w", "t", current, baseline) is True

    def test_critical_rolls_back(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        current = _rep(0.5, 0.3, 0.2)
        baseline = _rep(0.9, 0.8, 0.05)
        assert mgr.check_and_rollback(object(), "w", "t", current, baseline) is True
        assert len(mgr._rollback_history) == 2

    def test_detect_all_skip(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        out = mgr._detect_regression(_rep(0.0, 0.0, 0.05), _rep(0.0, 0.0, 0.05))
        assert out["detected"] is False

    def test_detect_critical_covers_all(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        out = mgr._detect_regression(_rep(0.5, 0.3, 0.2), _rep(0.9, 0.8, 0.05))
        assert out["severity"] == "critical"
        assert len(out["details"]) == 3

    def test_rollback_direct(self, tmp_path: Path) -> None:
        mgr = AutoRollbackManager(tmp_path)
        assert mgr._rollback("w", "t") is True
        assert mgr._rollback_history[-1]["action"] == "rollback"

    def test_check_regression_rollback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        report = EvalReport(
            partition="w",
            num_queries=10,
            recall_at_k={10: 0.1, 5: 0.1},
            mrr=0.5,
            ndcg=0.5,
            ece=0.05,
            latency_p50=1.0,
            latency_p95=2.0,
            latency_p99=3.0,
            evaluated_at="2024-01-01T00:00:00+00:00",
        )

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        class FakeHarness:
            def __init__(self, dm: object, path: object) -> None:
                pass

            def run(self, partition: str) -> EvalReport:
                return report

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr("dxrk.memory.eval_harness.EvalHarness", FakeHarness)
        out = AutoRollbackManager(tmp_path).check_regression()
        assert out["should_rollback"] is True
        assert out["severity"] == "critical"

    def test_check_regression_clean(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        report = EvalReport(
            partition="w",
            num_queries=10,
            recall_at_k={10: 0.9, 5: 0.9},
            mrr=0.9,
            ndcg=0.9,
            ece=0.01,
            latency_p50=1.0,
            latency_p95=2.0,
            latency_p99=3.0,
            evaluated_at="2024-01-01T00:00:00+00:00",
        )

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        class FakeHarness:
            def __init__(self, dm: object, path: object) -> None:
                pass

            def run(self, partition: str) -> EvalReport:
                return report

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr("dxrk.memory.eval_harness.EvalHarness", FakeHarness)
        out = AutoRollbackManager(tmp_path).check_regression()
        assert out["should_rollback"] is False


# ─── memory/judge_continuous.py ────────────────────────────────────────────


def _eval_dict(partition: str = "w1", **over: object) -> dict:
    base: dict[str, object] = {
        "partition": partition,
        "num_queries": 10,
        "recall_at_k": {1: 0.9, 3: 0.9, 5: 0.9, 10: 0.8, 20: 0.8},
        "mrr": 0.7,
        "ndcg": 0.75,
        "ece": 0.05,
        "latency_p50": 1.0,
        "latency_p95": 2.0,
        "latency_p99": 3.0,
        "evaluated_at": "2024-01-01T00:00:00+00:00",
    }
    base.update(over)
    return base


def _eval_report(partition: str = "w1", **over: object) -> EvalReport:
    return EvalReport(**_eval_dict(partition, **over))  # type: ignore[arg-type]


class TestJudgeBasics:
    def test_now_iso(self) -> None:
        from datetime import datetime

        assert datetime.fromisoformat(_now_iso()).tzinfo is not None

    def test_save_baseline_noop(self, tmp_path: Path) -> None:
        from dxrk.memory.judge_continuous import save_baseline_report

        assert save_baseline_report(tmp_path, "w", {}) is None

    def test_load_baseline_report(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        closed = []

        class FakeDM:
            def __init__(self, path: str) -> None:
                self.malla_path = str(path)

            def init(self) -> None:
                pass

            def close(self) -> None:
                closed.append(True)

        class FakeHarness:
            def __init__(self, dm: object, path: object) -> None:
                pass

            def run(self, partition: str) -> EvalReport:
                return _eval_report(partition)

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr("dxrk.memory.eval_harness.EvalHarness", FakeHarness)
        out = jc.load_baseline_report(tmp_path, "w1")
        assert out is not None
        assert out["partition"] == "w1"
        assert closed == [True]


class TestJudgeLoop:
    def _judge(self, tmp_path: Path) -> ContinuousJudge:
        harness = SimpleNamespace(eval_dir=tmp_path)
        return ContinuousJudge(tmp_path, harness, interval_hours=24)  # type: ignore[arg-type]

    def test_start_stop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ContinuousJudge, "_run_verification_cycle", lambda self: None)
        judge = self._judge(tmp_path)
        judge.start()
        assert judge._running is True
        judge.start()
        assert judge._running is True
        judge.stop()
        assert judge._running is False

    def test_stop_without_start(self, tmp_path: Path) -> None:
        judge = self._judge(tmp_path)
        judge.stop()
        assert judge._running is False

    def test_run_loop_error_and_break(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        judge = self._judge(tmp_path)
        judge.interval_seconds = 2
        calls: list[int] = []

        def fake_cycle():  # type: ignore[no-untyped-def]
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            judge._running = False

        judge._run_verification_cycle = fake_cycle  # type: ignore[method-assign]
        judge._running = True
        judge._run_loop()
        assert len(calls) == 2
        assert "Judge cycle error" in capsys.readouterr().out

    def test_cycle_empty_partitions(self, tmp_path: Path) -> None:
        from dxrk.memory.judge_continuous import Verdict

        judge = self._judge(tmp_path)
        verdict = judge._run_verification_cycle()
        assert isinstance(verdict, Verdict)
        assert verdict.passed is True

    def test_cycle_pass_and_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.judge_continuous import Verdict, load_judge_state

        (tmp_path / "partition1.jsonl").write_text("{}\n")
        harness = SimpleNamespace(eval_dir=tmp_path)

        ok_judge = ContinuousJudge(tmp_path, harness, interval_hours=24)  # type: ignore[arg-type]
        ok = Verdict(True, False, "none", [], {}, None)
        monkeypatch.setattr(ContinuousJudge, "_verify_partition", lambda self, partition: ok)
        ok_judge._run_verification_cycle()
        assert load_judge_state(tmp_path).consecutive_passes == 1

        bad_judge = ContinuousJudge(tmp_path, harness, interval_hours=24)  # type: ignore[arg-type]
        bad = Verdict(False, True, "critical", ["x"], {}, None)
        monkeypatch.setattr(ContinuousJudge, "_verify_partition", lambda self, partition: bad)
        bad_judge._run_verification_cycle()
        state = load_judge_state(tmp_path)
        assert state.consecutive_failures == 1
        assert state.consecutive_passes == 0
        assert state.last_run != ""


class TestJudgeVerifyVena:
    def _judge(self, tmp_path: Path, **kw: object) -> ContinuousJudge:
        harness = SimpleNamespace(eval_dir=tmp_path, run=lambda partition: _eval_report())
        return ContinuousJudge(tmp_path, harness, auto_rollback=True, **kw)  # type: ignore[arg-type]

    def test_no_current_eval(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr(jc, "load_baseline_report", lambda *a, **k: None)
        verdict = self._judge(tmp_path)._verify_partition("w1")
        assert verdict.passed is True
        assert verdict.details == ["No current evaluation available"]

    def test_first_run_baseline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        saved: list[tuple] = []
        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr(jc, "load_baseline_report", lambda *a, **k: _eval_dict() if len(saved) == 0 else None)

        def _save(*a, **k):  # type: ignore[no-untyped-def]
            saved.append(a)

        monkeypatch.setattr(jc, "save_baseline_report", _save)
        # first call returns current, second (baseline) returns None
        calls = {"n": 0}

        def _load(*a, **k):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return _eval_dict() if calls["n"] == 1 else None

        monkeypatch.setattr(jc, "load_baseline_report", _load)
        verdict = self._judge(tmp_path)._verify_partition("w1")
        assert verdict.details == ["First run - established baseline"]
        assert len(saved) == 1

    def test_regression_auto_rollback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        current = _eval_dict(recall_at_k={1: 0.2, 3: 0.2, 5: 0.2, 10: 0.2, 20: 0.2}, mrr=0.2)
        baseline = _eval_dict()
        calls = {"n": 0}

        def _load(*a, **k):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return current if calls["n"] == 1 else baseline

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr(jc, "load_baseline_report", _load)
        monkeypatch.setattr(jc, "get_calibration_chain", lambda *a, **k: [SimpleNamespace(), SimpleNamespace()])
        saved_cal: list[tuple] = []
        monkeypatch.setattr("dxrk.memory.calibrate_v2.save_calibration", lambda *a, **k: saved_cal.append(a))
        verdict = self._judge(tmp_path)._verify_partition("w1")
        assert verdict.regression_detected is True
        assert verdict.severity == "critical"
        assert verdict.auto_rollback is True
        assert "Auto-rollback triggered" in verdict.details
        assert len(saved_cal) == 1

    def test_regression_short_chain_no_rollback_save(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        current = _eval_dict(recall_at_k={1: 0.2, 3: 0.2, 5: 0.2, 10: 0.2, 20: 0.2}, mrr=0.2)
        baseline = _eval_dict()
        calls = {"n": 0}

        def _load(*a, **k):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return current if calls["n"] == 1 else baseline

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr(jc, "load_baseline_report", _load)
        monkeypatch.setattr(jc, "get_calibration_chain", lambda *a, **k: [SimpleNamespace()])
        saved_cal: list[tuple] = []
        monkeypatch.setattr("dxrk.memory.calibrate_v2.save_calibration", lambda *a, **k: saved_cal.append(a))
        verdict = self._judge(tmp_path)._verify_partition("w1")
        assert verdict.regression_detected is True
        assert verdict.auto_rollback is True
        assert saved_cal == []

    def test_regression_no_auto_rollback_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import judge_continuous as jc

        class FakeDM:
            def __init__(self, path: str) -> None:
                pass

            def init(self) -> None:
                pass

            def close(self) -> None:
                pass

        current = _eval_dict(recall_at_k={1: 0.2, 3: 0.2, 5: 0.2, 10: 0.2, 20: 0.2}, mrr=0.2)
        baseline = _eval_dict()
        calls = {"n": 0}

        def _load(*a, **k):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return current if calls["n"] == 1 else baseline

        monkeypatch.setattr("dxrk.memory.malla.DxrkMemory", FakeDM)
        monkeypatch.setattr(jc, "load_baseline_report", _load)
        judge = ContinuousJudge(
            tmp_path,
            SimpleNamespace(eval_dir=tmp_path, run=lambda partition: _eval_report()),
            auto_rollback=False,
        )
        verdict = judge._verify_partition("w1")
        assert verdict.regression_detected is True
        assert verdict.auto_rollback is False


class TestJudgeCompare:
    def test_clean(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        verdict = judge._compare_reports(_eval_report(), _eval_report(), "w1")
        assert verdict.passed is True
        assert verdict.severity == "none"

    def test_zero_baselines_skip(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        current = _eval_report()
        baseline = _eval_report(mrr=0.0, ndcg=0.0, recall_at_k={})
        verdict = judge._compare_reports(current, baseline, "w1")
        assert verdict.passed is True

    def test_critical_covers_all_signals(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        current = _eval_report(
            recall_at_k={1: 0.2, 3: 0.2, 5: 0.2, 10: 0.2, 20: 0.2},
            mrr=0.2,
            ndcg=0.2,
            ece=0.2,
        )
        verdict = judge._compare_reports(current, _eval_report(), "w1")
        assert verdict.severity == "critical"
        assert any("recall@" in d for d in verdict.details)
        assert any("MRR" in d for d in verdict.details)
        assert any("NDCG" in d for d in verdict.details)
        assert any("ECE" in d for d in verdict.details)

    def test_recall_critical(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(
            tmp_path,
            SimpleNamespace(eval_dir=tmp_path),
            regression_thresholds={"recall_drop_pct": 0.05, "mrr_drop_pct": 0.10, "ece_increase": 0.05},
        )
        current = _eval_report(recall_at_k={1: 0.5, 3: 0.5, 5: 0.5, 10: 0.5, 20: 0.5})
        verdict = judge._compare_reports(current, _eval_report(), "w1")
        assert verdict.severity == "critical"
        assert any("recall@" in d for d in verdict.details)

    def test_mrr_critical(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(
            tmp_path,
            SimpleNamespace(eval_dir=tmp_path),
            regression_thresholds={"recall_drop_pct": 0.99, "mrr_drop_pct": 0.10, "ece_increase": 0.05},
        )
        current = _eval_report(mrr=0.2)
        verdict = judge._compare_reports(current, _eval_report(), "w1")
        assert verdict.severity == "critical"
        assert any("MRR" in d for d in verdict.details)

    def test_ndcg_warning_only(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        current = _eval_report(ndcg=0.3)
        verdict = judge._compare_reports(current, _eval_report(), "w1")
        assert verdict.severity == "warning"
        assert verdict.regression_detected is True

    def test_ece_warning_only(self, tmp_path: Path) -> None:
        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        current = _eval_report(ece=0.2)
        verdict = judge._compare_reports(current, _eval_report(), "w1")
        assert verdict.severity == "warning"
        assert any("ECE" in d for d in verdict.details)

    def test_log_rollback_status_run_once(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.judge_continuous import Verdict

        judge = ContinuousJudge(tmp_path, SimpleNamespace(eval_dir=tmp_path))  # type: ignore[arg-type]
        judge._log_rollback("w1", "", "manual")
        status = judge.get_status()
        assert status["running"] is False
        assert len(status["rollback_history"]) == 1
        assert status["last_verdict"] is None

        sentinel = Verdict(True, False, "none", [], {}, None)
        monkeypatch.setattr(judge, "_run_verification_cycle", lambda: sentinel)
        assert judge.run_once() is sentinel


# ─── components/sdd.py ─────────────────────────────────────────────────────


def _write_settings(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestSddProfiles:
    def test_detect_empty_pname_skipped(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        _write_settings(
            settings,
            {"agent": {"sdd-orchestrator-": {}, "other-key": {}, "sdd-orchestrator-blue": {}}},
        )
        profiles = sdd.detect_profiles(str(settings))
        assert [p.name for p in profiles] == ["blue"]

    def test_detect_invalid_shapes(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("not json", encoding="utf-8")
        assert sdd.detect_profiles(str(settings)) == []
        _write_settings(settings, {"agent": ["not", "a", "dict"]})
        assert sdd.detect_profiles(str(settings)) == []
        _write_settings(settings, {"no-agent": {}})
        assert sdd.detect_profiles(str(settings)) == []
        assert sdd.detect_profiles(str(tmp_path / "missing.json")) == []

    def test_detect_full_assignment(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        _write_settings(
            settings,
            {
                "agent": {
                    "sdd-orchestrator-zen": "not-a-dict",
                    "sdd-orchestrator-zen2": {"model": "opencode/m1"},
                    "sdd-init-zen2": {"model": "opencode/m2"},
                    "sdd-apply-zen2": {"model": "prov-only"},
                    "sdd-verify-zen2": "junk",
                    "unrelated": {"model": "x/y"},
                }
            },
        )
        profiles = sdd.detect_profiles(str(settings))
        by_name = {p.name: p for p in profiles}
        assert by_name["zen2"].phase_assignments["sdd-init"].model_id == "m2"
        assert "sdd-apply" not in by_name["zen2"].phase_assignments

    def test_extract_model_edges(self) -> None:
        assert sdd._extract_model_from_agent("nope") == sdd._extract_model_from_agent({})
        assert sdd._extract_model_from_agent({}).provider_id == ""
        assert sdd._extract_model_from_agent({"model": 123}).provider_id == ""
        assert sdd._extract_model_from_agent({"model": ""}).provider_id == ""
        assert sdd._extract_model_from_agent({"model": "nomodel"}).provider_id == ""
        assert sdd._extract_model_from_agent({"model": "prov/"}).model_id == ""
        assert sdd._extract_model_from_agent({"model": "prov:model"}).model_id == "model"
        assert sdd._extract_model_from_agent({"model": "prov/model"}).provider_id == "prov"

    def test_overlay_without_orchestrator_model(self, tmp_path: Path) -> None:
        profile = Profile(name="lite")
        overlay = json.loads(sdd.generate_profile_overlay(profile, str(tmp_path)))
        assert "sdd-orchestrator-lite" in overlay["agent"]
        assert "model" not in overlay["agent"]["sdd-orchestrator-lite"]

    def test_overlay_with_phase_models(self, tmp_path: Path) -> None:
        profile = Profile(
            name="full",
            orchestrator_model=ModelAssignment(provider_id="opencode", model_id="m0"),
            phase_assignments={"sdd-init": ModelAssignment(provider_id="opencode", model_id="m1")},
        )
        overlay = json.loads(sdd.generate_profile_overlay(profile, str(tmp_path)))
        assert overlay["agent"]["sdd-orchestrator-full"]["model"] == "opencode/m0"
        assert overlay["agent"]["sdd-init-full"]["model"] == "opencode/m1"

    def test_build_prompt_without_markers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sdd, "_must_read", lambda path: "plain without markers")
        profile = Profile(name="nomark")
        assert sdd._build_profile_orchestrator_prompt(profile) == "plain without markers"

    def test_replace_phase_ref(self) -> None:
        assert sdd._replace_phase_ref("sdd-init x", "sdd-init", "other") == "sdd-init x"
        assert sdd._replace_phase_ref("run sdd-init now", "sdd-init", "sdd-init-b") == "run sdd-init-b now"
        assert sdd._replace_phase_ref("sdd-init-b", "sdd-init", "sdd-init-b") == "sdd-init-b"

    def test_remove_profile_agents(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        _write_settings(settings, {"agent": {"sdd-orchestrator-x": {}, "sdd-init-x": {}, "keep": {}}})
        sdd.remove_profile_agents(str(settings), "x")
        remaining = json.loads(settings.read_text(encoding="utf-8"))["agent"]
        assert "keep" in remaining
        assert "sdd-init-x" not in remaining

    def test_remove_profile_edges(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            sdd.remove_profile_agents(str(tmp_path / "s.json"), "default")
        assert sdd.remove_profile_agents(str(tmp_path / "missing.json"), "x") is None
        bad = tmp_path / "bad.json"
        bad.write_text("nope{", encoding="utf-8")
        assert sdd.remove_profile_agents(str(bad), "x") is None
        nodict = tmp_path / "nodict.json"
        _write_settings(nodict, {"agent": [1]})
        assert sdd.remove_profile_agents(str(nodict), "x") is None
        nomatch = tmp_path / "nomatch.json"
        before = json.dumps({"agent": {"keep": {}}})
        nomatch.write_text(before, encoding="utf-8")
        sdd.remove_profile_agents(str(nomatch), "x")
        assert nomatch.read_text(encoding="utf-8") == before

    def test_shared_prompts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        assert sdd.shared_prompt_dir(str(tmp_path)).endswith(os.path.join("sdd"))
        assert sdd.shared_prompt_phases()[0] == "sdd-init"
        assert sdd.write_shared_prompt_files(str(tmp_path)) is True
        assert sdd.write_shared_prompt_files(str(tmp_path)) is False
        monkeypatch.setattr(sdd, "_SUB_AGENT_PROMPT_CONTENT", {})
        assert sdd.write_shared_prompt_files(str(tmp_path)) is False

    def test_find_project_root(self, tmp_path: Path) -> None:
        mono = tmp_path / "mono"
        mono.mkdir()
        (mono / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
        assert sdd._find_project_root(str(mono)) == str(mono)
        gitproj = tmp_path / "gitproj"
        gitproj.mkdir()
        (gitproj / ".git").mkdir()
        assert sdd._find_project_root(str(gitproj)) == str(gitproj)
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "package.json").write_text("{}", encoding="utf-8")
        assert sdd._find_project_root(str(pkg)) == str(pkg)
        assert sdd._find_project_root("") is None

    def test_find_project_root_depth_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        monkeypatch.setattr(sdd, "_MAX_ANCESTOR_DEPTH", 1)
        assert sdd._find_project_root(str(deep)) is None
        (deep / "package.json").write_text("{}", encoding="utf-8")
        assert sdd._find_project_root(str(deep)) == str(deep)

    def test_asset_paths(self) -> None:
        from dxrk.models import AgentID, SDDModeID

        assert sdd._sdd_orchestrator_asset(AgentID.GEMINI_CLI) == "gemini/sdd-orchestrator.md"
        assert sdd._sdd_orchestrator_asset(AgentID.PI) == "generic/sdd-orchestrator.md"
        assert sdd._overlay_asset_path(SDDModeID.MULTI) == "opencode/sdd-overlay-multi.json"
        assert sdd._overlay_asset_path(SDDModeID.SINGLE) == "opencode/sdd-overlay-single.json"


class _NoPromptAdapter:
    @property
    def agent(self):  # type: ignore[no-untyped-def]
        return AgentID.PI

    @property
    def supports_system_prompt(self):  # type: ignore[no-untyped-def]
        return False

    @property
    def supports_slash_commands(self):  # type: ignore[no-untyped-def]
        return False

    @property
    def supports_skills(self):  # type: ignore[no-untyped-def]
        return False

    @property
    def supports_sub_agents(self):  # type: ignore[no-untyped-def]
        return False


class TestSddInjectBranches:
    def test_options_direct(self, tmp_path: Path) -> None:
        from dxrk.agents.opencode.adapter import OpenCodeAdapter

        result = sdd.inject(str(tmp_path), OpenCodeAdapter(), SDDModeID.SINGLE, sdd.InjectOptions())
        assert result.Changed is True

    def test_no_system_prompt(self, tmp_path: Path) -> None:
        result = sdd.inject(str(tmp_path), _NoPromptAdapter(), SDDModeID.SINGLE)
        assert result.Changed is False
        assert result.Files == []

    def test_kimi_jinja(self, tmp_path: Path) -> None:
        from dxrk.agents.kimi.adapter import KimiAdapter

        result = sdd.inject(str(tmp_path), KimiAdapter(), SDDModeID.SINGLE)
        assert result.Changed is True
        assert (Path(str(tmp_path)) / ".kimi" / "sdd-orchestrator.md").exists()

    def test_kimi_bootstrap(self, tmp_path: Path) -> None:
        from dxrk.agents.kimi.adapter import KimiAdapter

        class BootKimi(KimiAdapter):
            def __init__(self) -> None:
                self.bootstrapped: list[str] = []

            def bootstrap_template(self, home_dir: str) -> None:
                self.bootstrapped.append(home_dir)

        adapter = BootKimi()
        sdd.inject(str(tmp_path), adapter, SDDModeID.SINGLE)
        assert adapter.bootstrapped == [str(tmp_path)]

    def test_strict_tdd_jinja(self, tmp_path: Path) -> None:
        from dxrk.agents.kimi.adapter import KimiAdapter

        result = sdd.inject(str(tmp_path), KimiAdapter(), SDDModeID.SINGLE, sdd.InjectOptions(strict_tdd=True))
        assert (Path(str(tmp_path)) / ".kimi" / "strict-tdd-mode.md").exists()
        assert result.Changed is True

    def test_strict_tdd_claude(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        result = sdd.inject(str(tmp_path), ClaudeAdapter(), SDDModeID.SINGLE, sdd.InjectOptions(strict_tdd=True))
        content = (Path(str(tmp_path)) / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "strict-tdd-mode" in content
        assert result.Changed is True

    def test_codex_file_replace_twice(self, tmp_path: Path) -> None:
        from dxrk.agents.codex.adapter import CodexAdapter

        first = sdd.inject(str(tmp_path), CodexAdapter(), SDDModeID.SINGLE)
        assert first.Changed is True
        prompt = CodexAdapter().system_prompt_file(str(tmp_path))
        assert "sdd-orchestrator" in Path(prompt).read_text(encoding="utf-8")
        sdd.inject(str(tmp_path), CodexAdapter(), SDDModeID.SINGLE)

    def test_vscode_instructions_frontmatter(self, tmp_path: Path) -> None:
        from dxrk.agents.vscode.adapter import VSCodeAdapter

        sdd.inject(str(tmp_path), VSCodeAdapter(), SDDModeID.SINGLE)
        prompt = VSCodeAdapter().system_prompt_file(str(tmp_path))
        assert "Dxrk AI Persona" in Path(prompt).read_text(encoding="utf-8")

    def test_kiro_steering_frontmatter(self, tmp_path: Path) -> None:
        from dxrk.agents.kiro.adapter import KiroAdapter

        sdd.inject(str(tmp_path), KiroAdapter(), SDDModeID.SINGLE)
        prompt = KiroAdapter().system_prompt_file(str(tmp_path))
        assert "inclusion: always" in Path(prompt).read_text(encoding="utf-8")

    def test_claude_assignments_merge(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        opts = sdd.InjectOptions(claude_model_assignments={"sdd-explore": "opus", "sdd-verify": "bogus-alias"})
        sdd.inject(str(tmp_path), ClaudeAdapter(), SDDModeID.SINGLE, opts)
        content = (Path(str(tmp_path)) / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        assert "| sdd-explore | opus |" in content

    def test_claude_bare_orchestrator_stripped(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        claude_md = Path(str(tmp_path)) / ".claude" / "CLAUDE.md"
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text("## Agent Teams Orchestrator\nsome old\n## Other\nnew\n", encoding="utf-8")
        sdd.inject(str(tmp_path), ClaudeAdapter(), SDDModeID.SINGLE)
        content = claude_md.read_text(encoding="utf-8")
        assert "some old" not in content
        assert "new" in content

    def test_opencode_multi_profiles(self, tmp_path: Path) -> None:
        from dxrk.agents.opencode.adapter import OpenCodeAdapter

        settings = Path(str(tmp_path)) / ".config" / "opencode" / "settings.json"
        _write_settings(
            settings,
            {
                "model": "opencode/root-model",
                "agent": {
                    "dxrk": {"mode": "primary"},
                    "sdd-init": {"mode": "subagent", "model": "opencode/keep-me"},
                    "sdd-apply": {"mode": "subagent", "custom": 1},
                },
            },
        )
        opts = sdd.InjectOptions(
            opencode_model_assignments={
                "sdd-orchestrator": ModelAssignment("opencode", "model-x"),
                "sdd-init": ModelAssignment("opencode", "model-y"),
                "sdd-archive": ModelAssignment("", ""),
            },
            profiles=[
                Profile(
                    name="blue",
                    orchestrator_model=ModelAssignment("opencode", "model-z"),
                    phase_assignments={"sdd-init": ModelAssignment("opencode", "model-w")},
                ),
                Profile(name="default"),
                Profile(name=""),
            ],
        )
        result = sdd.inject(str(tmp_path), OpenCodeAdapter(), SDDModeID.MULTI, opts)
        assert result.Changed is True
        merged = json.loads(settings.read_text(encoding="utf-8"))
        assert merged["agent"]["sdd-init"]["model"] == "opencode/model-y"
        assert merged["agent"]["dxrk"]["model"] == "opencode/model-x"
        assert "model" not in merged["agent"]["sdd-apply"]
        assert "sdd-orchestrator-blue" in merged["agent"]
        assert (Path(str(tmp_path)) / ".config" / "opencode" / "plugins" / "background-agents.ts").exists()
        assert (Path(str(tmp_path)) / ".config" / "opencode" / "prompts" / "sdd" / "sdd-init.md").exists()
        sdd.inject(str(tmp_path), OpenCodeAdapter(), SDDModeID.MULTI, opts)

    def test_empty_commands_dir(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        class EmptyCommands(ClaudeAdapter):
            def commands_dir(self, home_dir: str = "") -> str:
                return ""

        result = sdd.inject(str(tmp_path), EmptyCommands(), SDDModeID.SINGLE)
        assert result.Changed is True

    def test_kilocode_skips_plugin(self, tmp_path: Path) -> None:
        from dxrk.agents.kilocode.adapter import KiloCodeAdapter

        result = sdd.inject(str(tmp_path), KiloCodeAdapter(), SDDModeID.SINGLE)
        assert result.Changed is True
        assert (Path(str(tmp_path)) / ".config" / "kilo" / "opencode.json").exists()
        assert not (Path(str(tmp_path)) / ".config" / "opencode" / "plugins").exists()

    def test_opencode_empty_settings_path(self, tmp_path: Path) -> None:
        from dxrk.agents.kilocode.adapter import KiloCodeAdapter

        class NoSettings(KiloCodeAdapter):
            def settings_path(self, home_dir: str = "") -> str:
                return ""

        result = sdd.inject(str(tmp_path), NoSettings(), SDDModeID.SINGLE)
        assert isinstance(result.Changed, bool)

    def test_no_skills_support(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        class NoSkills(ClaudeAdapter):
            @property
            def supports_skills(self) -> bool:  # type: ignore[override]
                return False

        result = sdd.inject(str(tmp_path), NoSkills(), SDDModeID.SINGLE)
        assert result.Changed is True

    def test_empty_skills_dir(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        class NoSkillsDir(ClaudeAdapter):
            def skills_dir(self, home_dir: str = "") -> str:
                return ""

        result = sdd.inject(str(tmp_path), NoSkillsDir(), SDDModeID.SINGLE)
        assert result.Changed is True

    def test_legacy_bare_file_prompt_marked(self, tmp_path: Path) -> None:
        from dxrk.agents.codex.adapter import CodexAdapter

        prompt = CodexAdapter().system_prompt_file(str(tmp_path))
        Path(prompt).parent.mkdir(parents=True, exist_ok=True)
        Path(prompt).write_text(
            "head\n# Agent Teams Lite — Orchestrator Instructions\nlegacy stuff\n"
            "<!-- dxrk:sdd-orchestrator -->\nmarked\n",
            encoding="utf-8",
        )
        sdd.inject(str(tmp_path), CodexAdapter(), SDDModeID.SINGLE)
        assert "legacy stuff" not in Path(prompt).read_text(encoding="utf-8")

    def test_legacy_bare_file_prompt_unmarked(self, tmp_path: Path) -> None:
        from dxrk.agents.codex.adapter import CodexAdapter

        prompt = CodexAdapter().system_prompt_file(str(tmp_path))
        Path(prompt).parent.mkdir(parents=True, exist_ok=True)
        Path(prompt).write_text("## Spec-Driven Development (SDD)\nold legacy\n", encoding="utf-8")
        sdd.inject(str(tmp_path), CodexAdapter(), SDDModeID.SINGLE)
        assert "old legacy" not in Path(prompt).read_text(encoding="utf-8")


class TestSddWorkflowsSubagents:
    def test_workflows(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        class FlowAdapter(ClaudeAdapter):
            @property
            def supports_workflows(self):  # type: ignore[no-untyped-def]
                return True

            def workflows_dir(self, project_root: str) -> str:
                return os.path.join(project_root, ".windsurf", "workflows")

            def embedded_workflows_dir(self) -> str:
                return "windsurf/workflows"

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        opts = sdd.InjectOptions(workspace_dir=str(proj))
        result = sdd.inject(str(tmp_path), FlowAdapter(), SDDModeID.SINGLE, opts)
        assert (proj / ".windsurf" / "workflows").is_dir()
        assert result.Changed is True
        empty_opts = sdd.InjectOptions(workspace_dir="")
        sdd.inject(str(tmp_path), FlowAdapter(), SDDModeID.SINGLE, empty_opts)

    def test_workflows_defaults(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter

        class MinimalFlow(ClaudeAdapter):
            @property
            def supports_workflows(self):  # type: ignore[no-untyped-def]
                return True

        proj = tmp_path / "proj2"
        proj.mkdir()
        (proj / "pyproject.toml").write_text("[project]\nname='y'\n", encoding="utf-8")
        opts = sdd.InjectOptions(workspace_dir=str(proj))
        result = sdd.inject(str(tmp_path), MinimalFlow(), SDDModeID.SINGLE, opts)
        assert (proj / ".windsurf" / "workflows").is_dir()
        assert result.Changed is True

    def test_subagent_model_ids(self, tmp_path: Path) -> None:
        from dxrk.agents.claude.adapter import ClaudeAdapter
        from dxrk.models import ClaudeModelAlias

        class ModelAdapter(ClaudeAdapter):
            def kiro_model_id(self, alias: ClaudeModelAlias) -> str:
                return f"kiro-{alias.value}"

            def claude_model_id(self, alias: ClaudeModelAlias) -> str:
                return f"claude-{alias.value}"

        opts = sdd.InjectOptions(
            kiro_model_assignments={"sdd-init": "opus", "default": "sonnet", "bad": "nope"},
            claude_model_assignments={"sdd-init": "haiku", "bad": "nope"},
        )
        result = sdd.inject(str(tmp_path), ModelAdapter(), SDDModeID.SINGLE, opts)
        agents_dir = Path(str(tmp_path)) / ".claude" / "agents"
        texts = [p.read_text(encoding="utf-8") for p in agents_dir.glob("*.md")]
        assert texts, "expected sub-agent files"
        assert any("kiro-opus" in t or "claude-haiku" in t for t in texts)
        assert result.Changed is True


class TestSddInternals:
    def test_claude_assignments_missing_markers(self) -> None:
        with pytest.raises(ValueError):
            sdd._inject_claude_model_assignments("no markers here", {})

    def test_resolve_alias_edges(self) -> None:
        from dxrk.models import ClaudeModelAlias

        assert sdd._resolve_claude_model_alias({"sdd-init": "opus"}, "sdd-init") == ClaudeModelAlias.OPUS
        assert sdd._resolve_claude_model_alias({"sdd-init": "bogus"}, "sdd-init") == ClaudeModelAlias.SONNET
        assert sdd._resolve_claude_model_alias({"default": "haiku"}, "sdd-zzz") == ClaudeModelAlias.HAIKU

    def test_has_orchestrator(self) -> None:
        assert sdd._has_sdd_orchestrator("## Agent Teams Orchestrator") is True
        assert sdd._has_sdd_orchestrator("plain") is False

    def test_strip_bare_passthrough(self) -> None:
        assert sdd._strip_bare_orchestrator_section("plain content") == "plain content"

    def test_strip_bare_with_sections(self) -> None:
        content = "head\n## Agent Teams Orchestrator\nold\n## Next\nnew\n"
        out = sdd._strip_bare_orchestrator_section(content)
        assert "old" not in out
        assert "new" in out

    def test_strip_bare_no_following_section(self) -> None:
        out = sdd._strip_bare_orchestrator_section("head\n## Agent Teams Orchestrator\nold\n")
        assert out == "head\n"
        out2 = sdd._strip_bare_orchestrator_section("head\n\n\n## Agent Teams Orchestrator\nold\n")
        assert out2 == "head\n"

    def test_has_legacy_edges(self) -> None:
        assert sdd._has_legacy_bare_orchestrator("plain") is False
        marked_clean = "head\n<!-- dxrk:sdd-orchestrator -->\nbody\n"
        assert sdd._has_legacy_bare_orchestrator(marked_clean) is False
        legacy = "# Agent Teams Lite — Orchestrator Instructions\nold\n<!-- dxrk:sdd-orchestrator -->\n"
        assert sdd._has_legacy_bare_orchestrator(legacy) is True
        assert sdd._has_legacy_bare_orchestrator("## SDD Orchestrator for Cascade\nold\n") is True

    def test_strip_file_prompt_edges(self) -> None:
        assert sdd._strip_bare_orchestrator_for_file_prompt("plain") == "plain"
        only_after = "<!-- dxrk:sdd-orchestrator -->\nmarked\n"
        assert "marked" in sdd._strip_bare_orchestrator_for_file_prompt(only_after)
        assert sdd._strip_bare_orchestrator_for_file_prompt("# SDD Orchestrator for Cascade\nonly\n") == ""
        mid = "## Agent Teams Orchestrator\nold\n<!-- dxrk:memory -->\nnew\n"
        assert "new" in sdd._strip_bare_orchestrator_for_file_prompt(mid)
        both = "head\n## Agent Teams Orchestrator\nold\n<!-- dxrk:memory -->\nnew\n"
        out = sdd._strip_bare_orchestrator_for_file_prompt(both)
        assert "head" in out and "new" in out and "old" not in out
        no_after = "head\n## Agent Teams Orchestrator\nold"
        assert sdd._strip_bare_orchestrator_for_file_prompt(no_after) == "head\n"

    def test_inline_prompts_edges(self, tmp_path: Path) -> None:
        bad = b"{not json"
        assert sdd._inline_opencode_sdd_prompts(bad, "", "", False) == bad
        no_agent = json.dumps({"other": {}}).encode()
        assert sdd._inline_opencode_sdd_prompts(no_agent, "", "", False) == no_agent
        no_orch = json.dumps({"agent": {"sdd-init": {}}}).encode()
        assert sdd._inline_opencode_sdd_prompts(no_orch, "", "", False) == no_orch

    def test_inline_prompts_preserve(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        _write_settings(settings, {"agent": {"sdd-orchestrator": {"prompt": "KEEP-ME"}}})
        overlay = json.dumps({"agent": {"sdd-orchestrator": {"prompt": "orig"}, "sdd-init": {"prompt": "x"}}}).encode()
        out = json.loads(sdd._inline_opencode_sdd_prompts(overlay, "", str(settings), True))
        assert out["agent"]["sdd-orchestrator"]["prompt"] == "KEEP-ME"

    def test_inline_prompts_preserve_missing(self, tmp_path: Path) -> None:
        overlay = json.dumps({"agent": {"sdd-orchestrator": {"prompt": "orig"}}}).encode()
        out = json.loads(sdd._inline_opencode_sdd_prompts(overlay, "", str(tmp_path / "no.json"), True))
        assert "sdd-orchestrator" in out["agent"]["sdd-orchestrator"]["prompt"]

    def test_inline_prompts_replace(self, tmp_path: Path) -> None:
        overlay = json.dumps(
            {
                "agent": {
                    "sdd-orchestrator": {"prompt": "orig"},
                    "sdd-init": {"prompt": "__PROMPT_FILE_sdd-init__"},
                    "sdd-verify": {"prompt": "keep"},
                }
            }
        ).encode()
        out = json.loads(sdd._inline_opencode_sdd_prompts(overlay, str(tmp_path), str(tmp_path / "no.json"), False))
        assert "sdd-orchestrator" in out["agent"]["sdd-orchestrator"]["prompt"]
        assert out["agent"]["sdd-init"]["prompt"].startswith("{file:")
        assert out["agent"]["sdd-init"]["prompt"].endswith("sdd-init.md}")
        assert out["agent"]["sdd-verify"]["prompt"] == "keep"

    def test_read_opencode_agent_prompt(self, tmp_path: Path) -> None:
        assert sdd._read_opencode_agent_prompt("", "sdd-orchestrator") is None
        assert sdd._read_opencode_agent_prompt(str(tmp_path / "no.json"), "x") is None
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        assert sdd._read_opencode_agent_prompt(str(bad), "x") is None
        nodict = tmp_path / "nodict.json"
        _write_settings(nodict, {"agent": [1]})
        assert sdd._read_opencode_agent_prompt(str(nodict), "x") is None
        missing = tmp_path / "missing.json"
        _write_settings(missing, {"agent": {"other": {}}})
        assert sdd._read_opencode_agent_prompt(str(missing), "sdd-orchestrator") is None
        nonstr = tmp_path / "nonstr.json"
        _write_settings(nonstr, {"agent": {"sdd-orchestrator": {"prompt": 42}}})
        assert sdd._read_opencode_agent_prompt(str(nonstr), "sdd-orchestrator") is None
        ok = tmp_path / "ok.json"
        _write_settings(ok, {"agent": {"sdd-orchestrator": {"prompt": "hello"}}})
        assert sdd._read_opencode_agent_prompt(str(ok), "sdd-orchestrator") == "hello"

    def test_read_root_model(self, tmp_path: Path) -> None:
        assert sdd._read_opencode_root_model(str(tmp_path / "no.json")) is None
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        assert sdd._read_opencode_root_model(str(bad)) is None
        nonstr = tmp_path / "nonstr.json"
        _write_settings(nonstr, {"model": 42})
        assert sdd._read_opencode_root_model(str(nonstr)) is None
        ok = tmp_path / "ok.json"
        _write_settings(ok, {"model": "opencode/m"})
        assert sdd._read_opencode_root_model(str(ok)) == "opencode/m"

    def test_read_existing_models(self, tmp_path: Path) -> None:
        assert sdd._read_existing_agent_models(str(tmp_path / "no.json")) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        assert sdd._read_existing_agent_models(str(bad)) == {}
        nodict = tmp_path / "nodict.json"
        _write_settings(nodict, {"agent": [1]})
        assert sdd._read_existing_agent_models(str(nodict)) == {}
        ok = tmp_path / "ok.json"
        _write_settings(ok, {"agent": {"sdd-init": {}}})
        assert sdd._read_existing_agent_models(str(ok)) == {"sdd-init": True}

    def test_inject_model_assignments(self) -> None:
        bad = b"{nope"
        assert sdd._inject_model_assignments(bad, {}, None, {}) == bad
        no_agent = json.dumps({"x": 1}).encode()
        assert sdd._inject_model_assignments(no_agent, {}, None, {}) == no_agent
        overlay = json.dumps(
            {
                "agent": {
                    "sdd-init": {"mode": "x"},
                    "sdd-verify": {"mode": "x"},
                    "sdd-tasks": {"mode": "x"},
                    "gentleman": {"mode": "y"},
                    "dxrk": {},
                }
            }
        ).encode()
        out = json.loads(
            sdd._inject_model_assignments(
                overlay,
                {
                    "sdd-init": ModelAssignment("opencode", "m1"),
                    "sdd-verify": ModelAssignment("opencode", "m2"),
                    "sdd-orchestrator": ModelAssignment("opencode", "mx"),
                },
                "opencode/root",
                {"gentleman": True},
            )
        )
        assert out["agent"]["sdd-init"]["model"] == "opencode/m1"
        assert out["agent"]["sdd-verify"]["model"] == "opencode/m2"
        assert out["agent"]["sdd-tasks"]["model"] == "opencode/root"
        assert out["agent"]["dxrk"]["model"] == "opencode/mx"

    def test_inject_model_skip_existing(self) -> None:
        overlay = json.dumps({"agent": {"sdd-init": {"mode": "x"}, "sdd-tasks": {"mode": "y"}}}).encode()
        out = json.loads(sdd._inject_model_assignments(overlay, {}, None, {"sdd-init": True}))
        assert "model" not in out["agent"]["sdd-init"]
        assert "model" not in out["agent"]["sdd-tasks"]

    def test_inject_model_junk_and_mirror(self) -> None:
        overlay = json.dumps({"agent": {"junk": "str", "sdd-init": {"mode": "x"}, "dxrk": "junk"}}).encode()
        out = json.loads(
            sdd._inject_model_assignments(
                overlay,
                {"sdd-orchestrator": ModelAssignment("opencode", "mx")},
                None,
                {"dxrk": True},
            )
        )
        assert out["agent"]["junk"] == "str"
        assert out["agent"]["dxrk"] == "junk"

    def test_read_current_assignments(self, tmp_path: Path) -> None:
        assert sdd.read_current_model_assignments(str(tmp_path / "no.json")) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        assert sdd.read_current_model_assignments(str(bad)) == {}
        nodict = tmp_path / "nodict.json"
        _write_settings(nodict, {"agent": [1]})
        assert sdd.read_current_model_assignments(str(nodict)) == {}
        mixed = tmp_path / "mixed.json"
        _write_settings(
            mixed,
            {
                "agent": {
                    "unrelated": {"model": "a/b"},
                    "sdd-init": "junk",
                    "sdd-spec": {"model": ""},
                    "sdd-design": {"model": "nosep"},
                    "sdd-tasks": {"model": "prov:"},
                    "sdd-apply": {"model": 42},
                    "sdd-verify": {"model": "prov/mod"},
                }
            },
        )
        out = sdd.read_current_model_assignments(str(mixed))
        assert list(out) == ["sdd-verify"]
        assert out["sdd-verify"].model_id == "mod"

    def test_merge_and_read_empty(self, tmp_path: Path) -> None:
        target = tmp_path / "merged.json"
        wr, _ = sdd._merge_json_file(str(target), json.dumps({"a": 1}).encode())
        assert wr.Changed is True
        assert sdd._read_file_or_empty(str(target)) != ""
        assert sdd._read_file_or_empty(str(tmp_path / "nope.json")) == ""

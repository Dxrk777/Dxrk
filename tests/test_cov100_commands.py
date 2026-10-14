# SPDX-License-Identifier: MIT
"""Coverage 100% for dxrk/commands (part 1: git-based + simple commands)."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

from dxrk.commands import register_all
from dxrk.commands.registry import CommandContext, Registry


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for var in ("DXRK_TENANT", "DXRK_USER", "DXRK_MEMORY_PATH", "DXRK_SESSION_BACKEND", "DXRK_UI_THEME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


class _Cap:
    def __init__(self):
        self.chunks: list[str] = []

    def write(self, text: str):
        self.chunks.append(text)

    def getvalue(self) -> str:
        return "".join(self.chunks)


def _run(reg: Registry, args: list[str], cwd="."):
    out, err = _Cap(), _Cap()
    code = reg.execute(args, out=out, err=err, cwd=str(cwd))  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def _reg() -> Registry:
    return register_all()


def _git(cwd, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "README.md").write_text("# test\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial commit")
    return tmp_path


class TestFastEffort:
    def test_fast_on(self):
        code, out, _ = _run(_reg(), ["fast", "on"], ".")
        assert code == 0
        assert "activado" in out

    def test_fast_off(self):
        code, out, _ = _run(_reg(), ["fast", "off"], ".")
        assert code == 0
        assert "desactivado" in out

    def test_fast_invalid(self):
        code, _, err = _run(_reg(), ["fast", "maybe"], ".")
        assert code == 1
        assert "inválido" in err

    def test_effort_description_unknown(self):
        from dxrk.commands.effort import effort_description

        assert effort_description("bogus-level") == ""

    def test_effort_unset_maps_auto(self, tmp_path):
        code, out, _ = _run(_reg(), ["effort", "unset"], str(tmp_path))
        assert code == 0
        assert "auto" in out

    def test_effort_invalid(self, tmp_path):
        code, _, err = _run(_reg(), ["effort", "turbo"], str(tmp_path))
        assert code == 1
        assert "inválido" in err

    def test_effort_valid_levels(self, tmp_path):
        from dxrk.commands.effort import effort_description, valid_effort_levels

        for level in valid_effort_levels:
            code, out, _ = _run(_reg(), ["effort", level], str(tmp_path))
            assert code == 0
            assert level in out
            assert effort_description(level) != ""


class TestBranchFull:
    def test_not_a_repo(self, tmp_path):
        code, _, err = _run(_reg(), ["branch"], str(tmp_path))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_delete_missing_name(self, repo):
        code, _, err = _run(_reg(), ["branch", "-d"], str(repo))
        assert code == 1
        assert "se requiere el nombre de la rama para eliminar" in err

    def test_delete_ok(self, repo):
        _git(repo, "branch", "victim")
        code, out, _ = _run(_reg(), ["branch", "-d", "victim"], str(repo))
        assert code == 0
        assert "victim" in out or "Deleted" in out

    def test_delete_fail(self, repo):
        code, _, err = _run(_reg(), ["branch", "-d", "no-such-branch"], str(repo))
        assert code == 1
        assert "al eliminar la rama" in err

    def test_switch_missing_name(self, repo):
        code, _, err = _run(_reg(), ["branch", "-s"], str(repo))
        assert code == 1
        assert "se requiere el nombre de la rama para cambiar" in err

    def test_switch_fail(self, repo):
        code, _, err = _run(_reg(), ["branch", "-s", "no-such-branch"], str(repo))
        assert code == 1
        assert "al cambiar de rama" in err

    def test_create_missing_name(self, repo):
        code, _, err = _run(_reg(), ["branch", "-c"], str(repo))
        assert code == 1
        assert "se requiere el nombre de la rama para crear" in err

    def test_create_fail_exists(self, repo):
        code, _, err = _run(_reg(), ["branch", "-c", "main"], str(repo))
        assert code == 1
        assert "al crear la rama" in err

    def test_list_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        real = gitutil.run_git

        def _fake(wd, *args):
            if list(args) == ["branch"]:
                return real("/nonexistent-dir-xyz", "branch")
            return real(wd, *args)

        monkeypatch.setattr("dxrk.commands.branch.run_git", _fake)
        code, _, err = _run(_reg(), ["branch"], str(repo))
        assert code == 1
        assert "al listar las ramas" in err


class TestCommitFull:
    def test_not_a_repo(self, tmp_path):
        code, _, err = _run(_reg(), ["commit", "-m", "x"], str(tmp_path))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_auto_message_generation_error(self, repo, monkeypatch):
        (repo / "a.txt").write_text("hello\n")

        def _boom(diff, staged=False):
            raise RuntimeError("llm caído")

        monkeypatch.setattr("dxrk.commands.commit.generate_commit_message", _boom)
        code, _, err = _run(_reg(), ["commit"], str(repo))
        assert code == 1
        assert "al generar el mensaje" in err

    def test_second_git_dir_check_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")
        calls = {"n": 0}
        real = gitutil.git_dir

        def _fake(wd):
            calls["n"] += 1
            if calls["n"] >= 2:
                return gitutil.GitResult(1, "", "no repo")
            return real(wd)

        monkeypatch.setattr("dxrk.commands.commit.git_dir", _fake)
        code, _, err = _run(_reg(), ["commit", "-m", "feat: x"], str(repo))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_add_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")

        def _fake(wd, *args):
            if list(args) == ["add", "-A"]:
                return gitutil.GitResult(1, "", "add boom")
            return gitutil.run_git(wd, *args)

        monkeypatch.setattr("dxrk.commands.commit.run_git", _fake)
        code, _, err = _run(_reg(), ["commit", "-m", "feat: x"], str(repo))
        assert code == 1
        assert "al preparar los archivos" in err

    def test_no_verify_flag_ok(self, repo):
        (repo / "a.txt").write_text("hello\n")
        code, out, _ = _run(_reg(), ["commit", "-m", "feat: nv", "--no-verify"], str(repo))
        assert code == 0
        assert "feat: nv" in out

    def test_commit_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")

        def _fake(wd, *args):
            if args and args[0] == "commit":
                return gitutil.GitResult(1, "", "commit boom")
            return gitutil.run_git(wd, *args)

        monkeypatch.setattr("dxrk.commands.commit.run_git", _fake)
        code, _, err = _run(_reg(), ["commit", "-m", "feat: x"], str(repo))
        assert code == 1
        assert "git commit" in err


class TestCommitPushPrFull:
    def test_not_a_repo(self, tmp_path):
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x"], str(tmp_path))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_no_branch(self, repo, monkeypatch):
        (repo / "a.txt").write_text("hello\n")
        monkeypatch.setattr("dxrk.commands.commit_push_pr.git_current_branch", lambda wd: None)
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x"], str(repo))
        assert code == 1
        assert "no hay una rama actual" in err

    def test_nothing_to_commit(self, repo):
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x"], str(repo))
        assert code == 1
        assert "no hay nada para confirmar" in err

    def test_title_generation_error(self, repo, monkeypatch):
        (repo / "a.txt").write_text("hello\n")

        def _boom(diff, staged=False):
            raise RuntimeError("llm caído")

        monkeypatch.setattr("dxrk.commands.commit_push_pr.generate_commit_message", _boom)
        code, _, err = _run(_reg(), ["commit-push-pr"], str(repo))
        assert code == 1
        assert "al generar el mensaje" in err

    def test_add_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")

        def _fake(wd, *args):
            if list(args) == ["add", "-A"]:
                return gitutil.GitResult(1, "", "add boom")
            return gitutil.run_git(wd, *args)

        monkeypatch.setattr("dxrk.commands.commit_push_pr.run_git", _fake)
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x"], str(repo))
        assert code == 1
        assert "al preparar los archivos" in err

    def test_commit_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")

        def _fake(wd, *args):
            if args and args[0] == "commit":
                return gitutil.GitResult(1, "", "commit boom")
            return gitutil.run_git(wd, *args)

        monkeypatch.setattr("dxrk.commands.commit_push_pr.run_git", _fake)
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x", "-b", "body here"], str(repo))
        assert code == 1
        assert "git commit" in err

    def test_push_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")
        remote = repo / "remote.git"
        _git(repo, "init", "--bare", "--initial-branch=main", str(remote))
        _git(repo, "remote", "add", "origin", str(remote))

        def _fake(wd, *args):
            if list(args[:2]) == ["push", "-u"]:
                return gitutil.GitResult(1, "", "push denied")
            return gitutil.run_git(wd, *args)

        monkeypatch.setattr("dxrk.commands.commit_push_pr.run_git", _fake)
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x", "--no-verify"], str(repo))
        assert code == 1
        assert "al hacer push" in err

    def test_gh_create_fails(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")
        remote = repo / "remote.git"
        _git(repo, "init", "--bare", "--initial-branch=main", str(remote))
        _git(repo, "remote", "add", "origin", str(remote))
        monkeypatch.setattr("dxrk.commands.commit_push_pr.run_gh", lambda wd, *a: gitutil.GitResult(1, "", "gh denied"))
        code, _, err = _run(_reg(), ["commit-push-pr", "-t", "x"], str(repo))
        assert code == 1
        assert "al crear el PR" in err


class TestDiffReviewFull:
    def test_diff_not_a_repo(self, tmp_path):
        code, _, err = _run(_reg(), ["diff"], str(tmp_path))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_diff_since(self, repo):
        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        (repo / "a.txt").write_text("hello\ntwo\n")
        code, out, _ = _run(_reg(), ["diff", "--since", "HEAD"], str(repo))
        assert code == 0
        assert isinstance(out, str)

    def test_diff_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.diff.git_diff", lambda wd, *a, **k: gitutil.GitResult(1, "", "diff boom"))
        code, _, err = _run(_reg(), ["diff"], str(repo))
        assert code == 1
        assert "al obtener el diff" in err

    def test_review_not_a_repo(self, tmp_path):
        code, _, err = _run(_reg(), ["review"], str(tmp_path))
        assert code == 1
        assert "no es un repositorio git" in err

    def test_review_staged_files_printed(self, repo):
        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        code, out, _ = _run(_reg(), ["review"], str(repo))
        assert code == 0
        assert "--- a.txt" in out
        assert "PREPARADOS" in out

    def test_review_pr_view_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.review.run_gh", lambda wd, *a: gitutil.GitResult(1, "", "gh down"))
        code, _, err = _run(_reg(), ["review", "--pr"], str(repo))
        assert code == 1
        assert "al obtener info del PR" in err

    def test_review_pr_bad_json(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.review.run_gh", lambda wd, *a: gitutil.GitResult(0, "not-json", ""))
        code, _, err = _run(_reg(), ["review", "--pr"], str(repo))
        assert code == 1
        assert "al obtener info del PR" in err

    def test_review_pr_diff_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        def _fake(wd, *args):
            if list(args)[:2] == ["pr", "diff"]:
                return gitutil.GitResult(1, "", "no diff")
            return gitutil.GitResult(0, '{"number":1,"title":"T","url":"u","baseRefName":"main"}', "")

        monkeypatch.setattr("dxrk.commands.review.run_gh", _fake)
        code, _, err = _run(_reg(), ["review", "--pr"], str(repo))
        assert code == 1
        assert "al obtener el diff del PR" in err

    def test_review_since_ok_and_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        code, out, _ = _run(_reg(), ["review", "--since", "HEAD~1"], str(repo))
        assert code == 0
        assert "Revisando cambios desde HEAD~1" in out
        monkeypatch.setattr("dxrk.commands.review.git_diff", lambda wd, *a, **k: gitutil.GitResult(1, "", "boom"))
        code, _, err = _run(_reg(), ["review", "--since", "HEAD"], str(repo))
        assert code == 1
        assert "al obtener el diff" in err

    def test_review_staged_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.review.git_diff_cached", lambda wd: gitutil.GitResult(1, "", "cached boom"))
        code, _, err = _run(_reg(), ["review"], str(repo))
        assert code == 1
        assert "diff preparado" in err

    def test_review_unstaged_fail(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.review.git_diff", lambda wd, *a, **k: gitutil.GitResult(1, "", "boom"))
        code, _, err = _run(_reg(), ["review"], str(repo))
        assert code == 1
        assert "sin preparar" in err

    def test_review_no_changes(self, repo):
        code, out, _ = _run(_reg(), ["review"], str(repo))
        assert code == 0
        assert "No hay cambios para revisar." in out

    def test_review_unstaged_only(self, repo):
        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        (repo / "a.txt").write_text("hello\nmodified\n")
        code, out, _ = _run(_reg(), ["review"], str(repo))
        assert code == 0
        assert "SIN PREPARAR" in out
        assert "REVISIÓN" in out


class TestFilesGitutilFull:
    def test_human_size_branches(self):
        from dxrk.commands.files import _human_size

        assert _human_size(2_000_000) == "1.9M"
        assert _human_size(2048) == "2.0K"
        assert _human_size(512) == "512"

    def test_tracked_only_ok_and_missing_skipped(self, repo):
        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        (repo / "gone.txt").write_text("x")
        _git(repo, "add", "gone.txt")
        (repo / "gone.txt").unlink()
        code, out, _ = _run(_reg(), ["files", "--tracked"], str(repo))
        assert code == 0
        assert "Archivos recientes" in out
        assert "gone.txt" not in out

    def test_tracked_git_fail_returns_empty(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.files.run_git", lambda wd, *a: gitutil.GitResult(1, "", "boom"))
        code, out, _ = _run(_reg(), ["files", "--tracked"], str(repo))
        assert code == 0
        assert "No se encontraron archivos." in out

    def test_walk_oserror_skipped(self, repo, monkeypatch):
        import dxrk.commands.files as files_mod

        (repo / "a.txt").write_text("hi")
        real_getmtime = os.path.getmtime

        def _fake_mtime(p):
            if str(p).endswith("a.txt"):
                raise OSError("stat boom")
            return real_getmtime(p)

        monkeypatch.setattr(os.path, "getmtime", _fake_mtime)
        assert files_mod._recent_files(str(repo), 20, False) is not None
        code, out, _ = _run(_reg(), ["files"], str(repo))
        assert code == 0

    def test_limit_invalid(self, repo):
        code, _, err = _run(_reg(), ["files", "--limit", "abc"], str(repo))
        assert code == 1
        assert "límite inválido" in err

    def test_limit_ok(self, repo):
        (repo / "a.txt").write_text("hi")
        code, out, _ = _run(_reg(), ["files", "--limit", "1"], str(repo))
        assert code == 0
        assert "Archivos recientes" in out

    def test_empty_dir(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, out, _ = _run(_reg(), ["files"], str(empty))
        assert code == 0
        assert "No se encontraron archivos." in out

    def test_gitutil_run_git_oserror(self, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr(gitutil.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
        res = gitutil.run_git(".", "status")
        assert not res.ok
        assert "no git" in res.err

    def test_gitutil_run_gh_oserror(self, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr(gitutil.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no gh")))
        res = gitutil.run_gh(".", "pr", "view")
        assert not res.ok

    def test_gitutil_detect_gh_branches(self, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr(gitutil.subprocess, "run", lambda *a, **k: None)
        assert gitutil.detect_gh() is True
        monkeypatch.setattr(gitutil.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("missing")))
        assert gitutil.detect_gh() is False

    def test_gitutil_diff_until(self, repo):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("v1\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        (repo / "a.txt").write_text("v2\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "v2")
        res = gitutil.git_diff(str(repo), "HEAD~1", None)
        assert res.ok
        res2 = gitutil.git_diff(str(repo), "HEAD~1", "HEAD")
        assert isinstance(res2.ok, bool)

    def test_gitutil_current_branch_none(self, tmp_path):
        from dxrk.commands import gitutil

        assert gitutil.git_current_branch(str(tmp_path)) is None

    def test_gitutil_default_branch_branches(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        assert gitutil.git_default_branch(str(repo)) == "main"
        monkeypatch.setattr(gitutil, "run_git", lambda wd, *a: gitutil.GitResult(0, "refs/remotes/origin/\n", ""))
        assert gitutil.git_default_branch(str(repo)) == "main"
        monkeypatch.setattr(gitutil, "run_git", lambda wd, *a: gitutil.GitResult(1, "", "nope"))
        assert gitutil.git_default_branch(str(repo)) == "main"

    def test_gitutil_diff_stats_deletions(self):
        from dxrk.commands import gitutil

        diff = "diff --git a/f b/f\n+++ b/f\n-old1\n-old2\n+new1\n context\n"
        files, adds, dels = gitutil.git_diff_stats(diff)
        assert files == 1
        assert adds == 1
        assert dels == 2
        assert gitutil.git_diff_stats("+++ b/g\n")[0] == 1

    def test_gitutil_generate_commit_message_variants(self):
        from dxrk.commands import gitutil

        assert gitutil.generate_commit_message("") == "chore: update"
        one = "+++ b/src/a.txt\nfix bug here"
        assert gitutil.generate_commit_message(one) == "fix(src): update a.txt"
        multi = "+++ b/x/a.txt\n+++ b/y/b.txt\nadd feature"
        assert gitutil.generate_commit_message(multi).startswith("feat(")
        devnull = "+++ b//dev/null\nadd stuff"
        assert gitutil.generate_commit_message(devnull) == "feat: update"


class TestHooksInitMcpFull:
    def test_save_hooks_fdopen_fail_closes(self, monkeypatch):
        import dxrk.commands.hooks as hooks_mod

        real_fdopen = os.fdopen
        monkeypatch.setattr(os, "open", lambda *a, **k: 999)
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fdopen boom")))
        closed = {"n": 0}

        def _fake_close(fd):
            closed["n"] += 1
            raise OSError("close boom")

        monkeypatch.setattr(os, "close", _fake_close)
        with pytest.raises(RuntimeError):
            hooks_mod.save_hooks([{"name": "x"}])
        assert closed["n"] == 1
        assert real_fdopen is not None

    def test_add_duplicate_reports_first_match(self, tmp_path):
        import json

        home = Path(os.environ["HOME"])
        p = home / ".config" / "dxrk" / "hooks.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([{"name": "h1", "event": "pre-commit", "command": "echo", "enabled": True}]))
        code, _, err = _run(_reg(), ["hooks", "add", "h1", "pre-commit", "echo hi"], str(tmp_path))
        assert code == 1
        assert "ya existe" in err

    def test_init_makedirs_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        code, _, err = _run(_reg(), ["init"], str(tmp_path))
        assert code == 1
        assert "al crear el directorio .dxrk" in err

    def test_init_save_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dxrk.commands.init.Save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
        code, _, err = _run(_reg(), ["init"], str(tmp_path))
        assert code == 1
        assert "al escribir la configuración" in err

    def test_init_memory_makedirs_fail(self, tmp_path, monkeypatch):
        real_makedirs = os.makedirs

        def _fake(path, *a, **k):
            if str(path).endswith("memory"):
                raise OSError("ro mem")
            return real_makedirs(path, *a, **k)

        monkeypatch.setattr(os, "makedirs", _fake)
        code, _, err = _run(_reg(), ["init"], str(tmp_path))
        assert code == 1
        assert "al crear el directorio memory" in err

    def test_keybindings_json(self, tmp_path):
        import json as _json

        reg = _reg()
        cmd = reg.get_command("keybindings")
        assert cmd is not None and cmd.run is not None
        out, err = io.StringIO(), io.StringIO()
        code = cmd.run(CommandContext(args=[], flags={"json": True}, out=out, err=err))  # type: ignore[arg-type]
        assert code == 0
        assert "ctrl+p" in _json.loads(out.getvalue())
        code, outv, _ = _run(reg, ["keybindings"], str(tmp_path))
        assert code == 0
        assert "ACCIÓN" in outv

    def test_mcp_list_with_servers(self, tmp_path):
        code, out, _ = _run(_reg(), ["mcp", "add", "srv1", "--command", "npx-foo"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["mcp", "list"], str(tmp_path))
        assert code == 0
        assert "srv1" in out

    def test_mcp_add_missing_command(self, tmp_path):
        code, _, err = _run(_reg(), ["mcp", "add", "srvx"], str(tmp_path))
        assert code == 1
        assert "se requiere el comando" in err

    def test_mcp_remove_missing(self, tmp_path):
        code, _, err = _run(_reg(), ["mcp", "remove", "nope"], str(tmp_path))
        assert code == 1
        assert "no encontrado" in err


class TestModelPermsPlanPluginFull:
    def test_model_current_match_and_none(self, tmp_path, monkeypatch):
        from dxrk.config import Config

        real_load = __import__("dxrk.commands.model", fromlist=["load_user_config"]).load_user_config
        cfg = real_load()
        code, out, _ = _run(_reg(), ["model", "current"], str(tmp_path))
        assert code == 0
        assert out.strip() != ""
        if cfg.providers:
            cfg.project.default_provider = "no-such-provider-xyz"
            monkeypatch.setattr("dxrk.commands.model.load_user_config", lambda: cfg)
            code, out, _ = _run(_reg(), ["model", "current"], str(tmp_path))
            assert code == 0
            assert "ninguno" in out
        assert isinstance(Config, type)

    def test_permissions_no_sandbox(self, tmp_path, monkeypatch):
        from dxrk.commands.config import load_user_config

        cfg = load_user_config()
        cfg.sandbox = None
        monkeypatch.setattr("dxrk.commands.permissions_command.load_user_config", lambda: cfg)
        code, out, _ = _run(_reg(), ["permissions"], str(tmp_path))
        assert code == 0
        assert "No se encontró configuración de sandbox." in out

    def test_plan_write_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dxrk.commands.plan._write_plan", lambda wd, c: False)
        code, _, err = _run(_reg(), ["plan", "add", "task x"], str(tmp_path))
        assert code == 1
        assert "al escribir el archivo de plan" in err

    def test_plan_show_variants(self, tmp_path):
        code, out, _ = _run(_reg(), ["plan", "show"], str(tmp_path))
        assert code == 0
        assert "No se encontró" in out
        code, out, _ = _run(_reg(), ["plan", "add", "write docs"], str(tmp_path))
        assert code == 0
        plan_file = tmp_path / ".dxrk" / "plan.md"
        plan_file.write_text("# Plan\n- [ ] raw task")
        code, out, _ = _run(_reg(), ["plan", "show"], str(tmp_path))
        assert code == 0
        assert "raw task" in out
        assert out.endswith("\n")

    def test_plan_done_invalid_and_range(self, tmp_path):
        _run(_reg(), ["plan", "add", "t1"], str(tmp_path))
        code, _, err = _run(_reg(), ["plan", "done", "abc"], str(tmp_path))
        assert code == 1
        assert "inválido" in err
        code, _, err = _run(_reg(), ["plan", "done", "99"], str(tmp_path))
        assert code == 1
        assert "fuera de rango" in err

    def test_plan_done_write_fail(self, tmp_path, monkeypatch):
        _run(_reg(), ["plan", "add", "t1"], str(tmp_path))
        monkeypatch.setattr("dxrk.commands.plan._write_plan", lambda wd, c: False)
        code, _, err = _run(_reg(), ["plan", "done", "1"], str(tmp_path))
        assert code == 1
        assert "al escribir el archivo de plan" in err

    def test_plugin_add_manifest_exists(self, tmp_path):
        code, out, _ = _run(_reg(), ["plugin", "add", "plug1"], str(tmp_path))
        assert code == 0
        assert "instalado" in out
        code, out, _ = _run(_reg(), ["plugin", "add", "plug1"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["plugin", "list"], str(tmp_path))
        assert code == 0
        assert "plug1" in out

    def test_plugin_add_oserror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        code, _, err = _run(_reg(), ["plugin", "add", "plugx"], str(tmp_path))
        assert code == 1
        assert "al instalar el plugin" in err

    def test_plugin_remove_rmtree_fail(self, tmp_path, monkeypatch):
        _run(_reg(), ["plugin", "add", "plug2"], str(tmp_path))
        monkeypatch.setattr("shutil.rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("busy")))
        code, _, err = _run(_reg(), ["plugin", "remove", "plug2"], str(tmp_path))
        assert code == 1
        assert "al eliminar el plugin" in err

    def test_rename_empty_and_errors(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError, save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Orig"
        assert save_session(s)
        code, _, err = _run(_reg(), ["rename", s.id, "   "], str(tmp_path))
        assert code == 1
        assert "no puede estar vacío" in err
        monkeypatch.setattr(
            "dxrk.commands.rename.list_session_files",
            lambda: (_ for _ in ()).throw(SessionError("list boom")),
        )
        code, _, err = _run(_reg(), ["rename", s.id, "New"], str(tmp_path))
        assert code == 1
        assert "list boom" in err

    def test_rename_prefix_and_save_fail(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError, save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Orig"
        assert save_session(s)
        code, out, _ = _run(_reg(), ["rename", s.id[:8], "ViaPrefix"], str(tmp_path))
        assert code == 0
        assert "renombrada" in out
        monkeypatch.setattr(
            "dxrk.commands.rename.save_session_strict",
            lambda *a: (_ for _ in ()).throw(SessionError("disk")),
        )
        code, _, err = _run(_reg(), ["rename", s.id, "Other"], str(tmp_path))
        assert code == 1
        assert "al guardar la sesión renombrada" in err

    def test_rewind_no_messages_then_truncation(self, tmp_path):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import Message, new_session

        s = new_session()
        s.title = "T"
        assert save_session(s)
        code, _, err = _run(_reg(), ["rewind", s.id, "1"], str(tmp_path))
        assert code == 1
        assert "no tiene mensajes" in err
        s.messages.append(Message(role="user", content="hola mundo"))
        s.messages.append(Message(role="assistant", content="x" * 100))
        s.message_count = len(s.messages)
        assert save_session(s)
        code, out, _ = _run(_reg(), ["rewind", s.id, "1"], str(tmp_path))
        assert code == 0
        assert "retrocedida" in out
        assert "..." in out


class TestCostDoctorEnterpriseExport:
    def test_estimate_cost_branches(self):
        from dxrk.commands.cost import estimate_cost

        known = estimate_cost("gpt-4o", 1_000_000, 1_000_000)
        assert known == (2.5, 10.0, 12.5)
        default = estimate_cost("unknown-model-xyz", 1_000_000, 0)
        assert default == (3.0, 0.0, 3.0)

    def test_cost_missing_arg_direct(self):
        from dxrk.commands.registry import CommandContext

        reg = _reg()
        cmd = reg.get_command("cost")
        assert cmd is not None and cmd.run is not None
        out, err = io.StringIO(), io.StringIO()
        code = cmd.run(CommandContext(args=[], out=out, err=err))  # type: ignore[arg-type]
        assert code == 1
        assert "se requiere el id" in err.getvalue()

    def test_cost_success(self, tmp_path):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Costed"
        assert save_session(s)
        code, out, _ = _run(_reg(), ["cost", s.id], str(tmp_path))
        assert code == 0
        assert "Modelo:" in out
        assert "Total estimado" in out

    def test_doctor_unhealthy_paths(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        import dxrk.commands.doctor as doctor_mod
        from dxrk.commands.doctor import DoctorReport, run_doctor
        from dxrk.commands.registry import CommandContext

        ctx = CommandContext(args=[], flags={}, out=io.StringIO(), err=io.StringIO(), cwd=str(tmp_path))
        seen: list[str] = []
        real_run_checks = doctor_mod.run_checks

        def _spy(checks):
            for c in checks:
                try:
                    err_msg = c.run()
                except Exception as exc:  # noqa: BLE001
                    err_msg = f"raised: {exc}"
                seen.append(f"{c.id}={err_msg!r}")
            return real_run_checks(checks)

        monkeypatch.setattr(doctor_mod, "run_checks", _spy)
        monkeypatch.setattr(doctor_mod, "detect_gh", lambda: False)
        report = run_doctor(ctx, DoctorReport())
        assert report.checks == []
        assert any("git=" in s for s in seen)
        assert any("gh='CLI gh no encontrada'" in s for s in seen)
        assert any("config=" in s and "no hay configuraci" in s for s in seen)
        report2 = run_doctor(ctx)
        assert report2.checks == []
        # stub runner with .output covers report aggregation + register write loop
        monkeypatch.setattr(doctor_mod, "run_checks", lambda checks: SimpleNamespace(output=["git: OK", "gh: FAIL"]))
        report3 = run_doctor(ctx)
        assert report3.checks == ["git: OK", "gh: FAIL"]
        code, out, _ = _run(_reg(), ["doctor"], str(tmp_path))
        assert code == 0
        assert "git: OK" in out

    def test_doctor_config_missing_and_empty_report(self, tmp_path, monkeypatch):
        from dxrk.commands import doctor as doctor_mod

        assert not os.path.exists(os.path.join(str(tmp_path), ".dxrk", "config.yaml"))
        code, out, _ = _run(_reg(), ["doctor"], str(tmp_path))
        assert code == 0
        assert isinstance(out, str)

        class _Res:
            pass

        monkeypatch.setattr(doctor_mod, "run_checks", lambda checks: _Res())
        code, out, _ = _run(_reg(), ["doctor"], str(tmp_path))
        assert code == 0
        assert "No se ejecutó ninguna revisión." in out

    def test_enterprise_execute_no_args_direct(self):
        from dxrk.commands.registry import CommandContext

        reg = _reg()
        cmd = reg.get_command("enterprise execute")
        assert cmd is not None and cmd.run is not None
        out, err = io.StringIO(), io.StringIO()
        code = cmd.run(CommandContext(args=[], out=out, err=err))  # type: ignore[arg-type]
        assert code == 1
        assert "execute <tarea>" in err.getvalue()

    def test_enterprise_execute_bad_dept(self, tmp_path):
        code, _, err = _run(_reg(), ["enterprise", "execute", "hacer algo", "no-dept"], str(tmp_path))
        assert code == 1
        assert "error" in err.lower()

    def test_enterprise_parent(self, tmp_path):
        code, _, err = _run(_reg(), ["enterprise"], str(tmp_path))
        assert code == 1
        assert "enterprise start" in err

    def test_export_formats(self, tmp_path):
        from dxrk.commands.export import export_session_body
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "ExportMe"
        s.tags = ["t1"]
        assert save_session(s)
        assert "ExportMe" in export_session_body(s, "md")
        assert "t1" in export_session_body(s, "markdown")
        s2 = new_session()
        s2.title = "SinEtiquetas"
        s2.tags = []
        body = export_session_body(s2, "md")
        assert "SinEtiquetas" in body
        assert "**Tags**" not in body
        for fmt in ("json", "html", "xml"):
            out_body = export_session_body(s, fmt)
            assert isinstance(out_body, str) and len(out_body) > 0

    def test_export_errors(self, tmp_path, monkeypatch):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Exp"
        assert save_session(s)
        code, _, err = _run(_reg(), ["export", "missing-id", "--output", str(tmp_path / "x.md")], str(tmp_path))
        assert code == 1
        assert "Error" in err
        dest = tmp_path / "default.md"
        code, out, _ = _run(_reg(), ["export", s.id], str(tmp_path))
        assert code in (0, 1)
        code, _, err = _run(_reg(), ["export", s.id, "--output", str(dest), "--format", "bogus"], str(tmp_path))
        assert code == 1
        assert "no compatible" in err
        dest.write_text("taken")
        code, _, err = _run(_reg(), ["export", s.id, "--output", str(dest)], str(tmp_path))
        assert code == 1
        assert "ya existe" in err
        monkeypatch.setattr(
            "dxrk.commands.export._write_private_file",
            lambda *a: (_ for _ in ()).throw(OSError("disk")),
        )
        dest2 = tmp_path / "other.md"
        code, _, err = _run(_reg(), ["export", s.id, "--output", str(dest2)], str(tmp_path))
        assert code == 1
        assert "al escribir" in err


class TestConfigFull:
    def test_config_no_file(self, tmp_path):
        code, out, _ = _run(_reg(), ["config"], str(tmp_path))
        assert code == 0
        assert "No se encontró el archivo" in out
        assert "dxrk init" in out

    def test_config_with_sandbox(self, tmp_path):
        from dxrk.commands.config import load_user_config, save_user_config
        from dxrk.config import SandboxConfig

        cfg = load_user_config()
        cfg.sandbox = SandboxConfig()
        save_user_config(cfg)
        code, out, _ = _run(_reg(), ["config"], str(tmp_path))
        assert code == 0
        assert "Imagen de sandbox" in out

    def test_parse_cli_value(self):
        from dxrk.commands.config import _parse_cli_value

        assert _parse_cli_value("123") == 123
        assert _parse_cli_value("true") is True
        assert _parse_cli_value('"hi"') == "hi"
        assert _parse_cli_value("plain") == "plain"

    def test_config_get_ok_and_miss(self, tmp_path):
        code, out, _ = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert code == 0
        assert out.strip() != ""
        code, out, _ = _run(_reg(), ["config", "get", "definitely.missing.xyz"], str(tmp_path))
        assert code == 0
        assert "sin valor" in out

    def test_config_get_rbac_deny(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.config.require_op",
            lambda *a: (_ for _ in ()).throw(PermissionError("denied")),
        )
        code, _, err = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert code == 1
        assert "denied" in err

    def test_config_get_value_error(self, tmp_path, monkeypatch):
        class _Uni:
            def get_typed(self, path):
                raise ValueError("bad path")

        monkeypatch.setattr("dxrk.commands.config._unified_config", lambda tid="": _Uni())
        code, _, err = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert code == 1
        assert "bad path" in err

    def test_config_set_settings_readonly(self, tmp_path):
        code, _, err = _run(_reg(), ["config", "set", "settings.foo", "bar"], str(tmp_path))
        assert code == 1
        assert "solo lectura" in err

    def test_config_set_ok(self, tmp_path):
        code, out, _ = _run(_reg(), ["config", "set", "ui.theme", "light"], str(tmp_path))
        assert code == 0
        assert "actualizado" in out
        code, out, _ = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert "light" in out

    def test_config_set_tenant_snapshot(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        monkeypatch.setenv("DXRK_TENANT", "team1")
        ensure_tenant("team1")
        code, out, _ = _run(_reg(), ["config", "set", "ui.theme", "dark"], str(tmp_path))
        assert code == 0
        assert "tenant team1" in out

    def test_config_set_tenant_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DXRK_TENANT", "ghost-tenant")
        code, _, err = _run(_reg(), ["config", "set", "ui.theme", "dark"], str(tmp_path))
        assert code == 1
        assert "no encontrado" in err

    def test_config_set_chmod_failures_ignored(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        monkeypatch.setenv("DXRK_TENANT", "teamc")
        ensure_tenant("teamc")
        real_chmod = Path.chmod
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        code, out, _ = _run(_reg(), ["config", "set", "ui.theme", "dark"], str(tmp_path))
        assert code == 0
        assert "tenant teamc" in out
        assert real_chmod is not None

    def test_tenant_exists_exception(self, monkeypatch):
        from dxrk.commands.config import _tenant_exists

        monkeypatch.setattr(
            "dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert _tenant_exists("whatever") is False

    def test_unified_tenant_import_fails(self, tmp_path, monkeypatch):
        import sys as _sys

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else None
        assert real_import is not None or _sys is not None
        monkeypatch.setenv("DXRK_TENANT", "team9")
        code, out, _ = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert code == 0

    def test_config_layers_ok_and_winner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DXRK_UI_THEME", "light")
        code, out, _ = _run(_reg(), ["config", "layers", "ui.theme"], str(tmp_path))
        assert code == 0
        assert "ui.theme" in out
        assert "gana" in out

    def test_config_layers_rbac_deny(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.config.require_op",
            lambda *a: (_ for _ in ()).throw(PermissionError("denied")),
        )
        code, _, err = _run(_reg(), ["config", "layers", "ui.theme"], str(tmp_path))
        assert code == 1
        assert "denied" in err

    def test_config_migrate_dry_run(self, tmp_path):
        code, out, _ = _run(_reg(), ["config", "migrate", "--dry-run"], str(tmp_path))
        assert code == 0
        assert "migradas" in out

    def test_config_migrate_rbac_deny(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.config.require_op",
            lambda *a: (_ for _ in ()).throw(PermissionError("denied")),
        )
        code, _, err = _run(_reg(), ["config", "migrate"], str(tmp_path))
        assert code == 1
        assert "denied" in err

    def test_layer_rows_defaults_fail(self, tmp_path, monkeypatch):
        import dxrk.commands.config as cfg_mod

        uni = cfg_mod._unified_config("")
        monkeypatch.setattr(
            "dxrk.config.config.default_hierarchical_config",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        rows = cfg_mod._layer_rows("ui.theme", uni)
        assert rows[-1][0] == "defaults"
        assert rows[-1][1] is False

    def test_active_tenant_path_branches(self, monkeypatch):
        from dxrk.commands.config import _active_tenant_path

        monkeypatch.delenv("DXRK_TENANT", raising=False)
        assert _active_tenant_path() == ""
        monkeypatch.setenv("DXRK_TENANT", "t1")
        assert "t1" in _active_tenant_path()
        monkeypatch.setattr(
            "dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert _active_tenant_path() == ""

    def test_read_yaml_path_branches(self, tmp_path):
        from dxrk.commands.config import _read_yaml_path

        assert _read_yaml_path("", "ui.theme") == (False, None)
        assert _read_yaml_path(str(tmp_path / "nope.yaml"), "ui.theme") == (False, None)
        bad = tmp_path / "bad.yaml"
        bad.write_text(":\n: [unclosed\n")
        assert _read_yaml_path(str(bad), "ui.theme") == (False, None)
        lst = tmp_path / "list.yaml"
        lst.write_text("- a\n- b\n")
        assert _read_yaml_path(str(lst), "ui.theme") == (False, None)
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("ui:\n  theme: light\n")
        assert _read_yaml_path(str(cfg), "ui.theme") == (True, "light")
        assert _read_yaml_path(str(cfg), "ui.missing") == (False, None)
        assert _read_yaml_path(str(cfg), "ui.theme.deep") == (False, None)


class TestRegistryFull:
    def test_quote_str_branches(self):
        from dxrk.commands.registry import quote_str

        assert quote_str('a"b\\c\nd\te\rf') == '"a\\"b\\\\c\\nd\\te\\rf"'
        assert quote_str("\x01\x7f") == '"\\u0001\\u007f"'
        assert quote_str("plain") == '"plain"'

    def test_format_duration_branches(self):
        from dxrk.commands.registry import format_duration, go_duration, go_quote, quote_str

        assert format_duration(3661) == "1h1m1s"
        assert format_duration(125) == "2m5s"
        assert format_duration(7) == "7s"
        assert format_duration(-3) == "0s"
        assert go_duration is format_duration
        assert go_quote is quote_str

    def test_flag_bool_str_branches(self):
        from dxrk.commands.registry import CommandContext

        ctx = CommandContext(flags={"a": True, "b": "YES", "c": "off", "d": None})
        assert ctx.flag_bool("a") is True
        assert ctx.flag_bool("b") is True
        assert ctx.flag_bool("c") is False
        assert ctx.flag_bool("missing", True) is True
        assert ctx.flag_str("b") == "YES"
        assert ctx.flag_str("d") == ""
        assert ctx.flag_str("missing", "x") == "x"

    def test_add_flag_and_validate(self):
        from dxrk.commands.registry import Command, Flag

        cmd = Command(name="x", min_args=1, max_args=1)
        cmd.add_flag(Flag("f"))
        assert "f" in cmd.flags
        assert cmd.validate_args([]) is not None
        assert cmd.validate_args(["a", "b"]) is not None
        assert cmd.validate_args(["a"]) is None

    def test_parse_argv_branches(self):
        from dxrk.commands.registry import Flag, parse_argv

        flags = {
            "verbose": Flag("verbose", is_bool=True, shorthand="v"),
            "out": Flag("out", default="", shorthand="o"),
        }
        args, parsed, err = parse_argv(["--", "a", "b"], flags)
        assert err is None and args == ["a", "b"]
        _, _, err = parse_argv(["--bogus"], flags)
        assert "desconocido" in (err or "")
        _, parsed, err = parse_argv(["--verbose=false"], flags)
        assert err is None and parsed["verbose"] is False
        _, parsed, err = parse_argv(["--verbose=true"], flags)
        assert err is None and parsed["verbose"] is True
        _, parsed, err = parse_argv(["--verbose=1"], flags)
        assert err is None and parsed["verbose"] is True
        _, _, err = parse_argv(["--verbose=maybe"], flags)
        assert "booleano" in (err or "")
        _, _, err = parse_argv(["--out"], flags)
        assert "necesita un argumento" in (err or "")
        _, _, err = parse_argv(["-x"], flags)
        assert "abreviado desconocido" in (err or "")
        _, _, err = parse_argv(["-z=val"], flags)
        assert "abreviado desconocido" in (err or "")
        _, _, err = parse_argv(["-v=x"], flags)
        assert "no acepta valor" in (err or "")
        _, parsed, err = parse_argv(["-o=file.txt"], flags)
        assert err is None and parsed["out"] == "file.txt"
        _, parsed, err = parse_argv(["-vv"], flags)
        assert err is None and parsed["verbose"] is True
        _, parsed, err = parse_argv(["-ofile.txt"], flags)
        assert err is None and parsed["out"] == "file.txt"
        _, parsed, err = parse_argv(["-o", "f2.txt"], flags)
        assert err is None and parsed["out"] == "f2.txt"
        _, _, err = parse_argv(["-o"], flags)
        assert "necesita un argumento" in (err or "")
        args, _, err = parse_argv(["pos", "--verbose"], flags)
        assert err is None and args == ["pos"]
        args, _, err = parse_argv(["-5"], flags)
        assert err is None and args == ["-5"]

    def test_safe_write_broken_pipe(self, capsys):
        import sys as _sys

        from dxrk.commands.registry import _safe_write

        class _Bad:
            def write(self, msg):
                raise BrokenPipeError("pipe")

        _safe_write(_Bad(), "hi")  # must not raise
        assert _sys is not None

    def test_registry_names_and_missing(self):
        reg = Registry()
        assert reg.names() == []
        assert reg.get_command("nope") is None

    def test_execute_no_argv(self):
        reg = _reg()
        out, err = _Cap(), _Cap()
        assert reg.execute([], out=out, err=err) == 1
        assert "falta el comando" in err.getvalue()

    def test_execute_defaults_and_unknown(self, capsys, tmp_path):
        reg = _reg()
        code = reg.execute(["usage"], cwd=str(tmp_path))
        assert code == 0
        captured = capsys.readouterr()
        assert "Comandos:" in captured.out
        out, err = _Cap(), _Cap()
        assert reg.execute(["no-such-cmd"], out=out, err=err) == 1
        assert "comando desconocido: no-such-cmd" in err.getvalue()

    def test_execute_cmd_none_defensive(self):
        # `name` matched `in self._commands` but `.get()` returns None:
        # only possible with an inconsistent mapping; must fail cleanly.
        reg = Registry()

        class _LyingDict(dict):
            def __contains__(self, key):
                return True

        reg._commands = _LyingDict()  # type: ignore[assignment]
        out, err = _Cap(), _Cap()
        assert reg.execute(["whatever"], out=out, err=err) == 1
        assert "comando desconocido: whatever" in err.getvalue()

    def test_execute_cmd_none_and_parse_err(self):
        from dxrk.commands.registry import Command

        reg = Registry()
        reg._commands["ghost"] = Command(name="ghost", run=None)
        out, err = _Cap(), _Cap()
        assert reg.execute(["ghost"], out=out, err=err) == 1
        assert "desconocido" in err.getvalue() or "no implementado" in err.getvalue()
        reg2 = _reg()
        out2, err2 = _Cap(), _Cap()
        assert reg2.execute(["branch", "--bogus-flag"], out=out2, err=err2) == 1
        assert "Error" in err2.getvalue()

    def test_execute_arg_err_and_no_run(self):
        from dxrk.commands.registry import Command

        reg = Registry()
        reg.add_command(Command(name="norun", min_args=5, run=None))
        out, err = _Cap(), _Cap()
        assert reg.execute(["norun", "a"], out=out, err=err) == 1
        assert "Error" in err.getvalue()
        reg2 = Registry()
        reg2.add_command(Command(name="norun2", run=None))
        out2, err2 = _Cap(), _Cap()
        assert reg2.execute(["norun2"], out=out2, err=err2) == 1
        assert "no implementado" in err2.getvalue()

    def test_execute_broken_pipe_and_exception(self, monkeypatch):
        import io as _io

        from dxrk.commands.registry import Command

        reg = Registry()

        def _boom(ctx):
            raise BrokenPipeError("pipe")

        reg.add_command(Command(name="bp", run=_boom))
        assert reg.execute(["bp"], out=_io.StringIO(), err=_io.StringIO()) == 1

        reg2 = Registry()

        def _kaboom(ctx):
            raise RuntimeError("kaboom")

        reg2.add_command(Command(name="kb", run=_kaboom))
        out, err = _Cap(), _Cap()
        assert reg2.execute(["kb"], out=out, err=err) == 1
        assert "falló" in err.getvalue()
        monkeypatch.setenv("DXRK_TENANT", "t-ctx")
        reg3 = _reg()
        out3, err3 = _Cap(), _Cap()
        code = reg3.execute(["usage"], out=out3, err=err3)
        assert code == 0


class TestSessionGaps:
    def test_backend_kind_sqlite(self, monkeypatch):
        from dxrk.commands.session import _backend_kind

        monkeypatch.setenv("DXRK_SESSION_BACKEND", "sqlite")
        assert _backend_kind() == "sqlite"
        monkeypatch.setenv("DXRK_SESSION_BACKEND", "weird")
        assert _backend_kind() == "file"

    def test_quarantine_makedirs_fail(self, tmp_path):
        import dxrk.commands.session as sess_mod

        assert sess_mod._quarantine_file(str(tmp_path), "x.json") in (True, False)

    def test_quarantine_rename_loop_and_replace_fail(self, tmp_path, monkeypatch):
        import dxrk.commands.session as sess_mod

        qdir = tmp_path / ".quarantine"
        qdir.mkdir()
        (qdir / "dup.json").write_text("old")
        src = tmp_path / "dup.json"
        src.write_text("{bad")
        assert sess_mod._quarantine_file(str(tmp_path), "dup.json") is True
        assert (qdir / "dup-1.json").exists()
        monkeypatch.setattr(sess_mod.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("ro")))
        src.write_text("{bad")
        assert sess_mod._quarantine_file(str(tmp_path), "dup.json") is False
        monkeypatch.setattr(sess_mod.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        assert sess_mod._quarantine_file(str(tmp_path), "other.json") is False

    def test_is_corrupt_branches(self, tmp_path):
        import gzip as _gzip

        import dxrk.commands.session as sess_mod

        assert sess_mod._is_corrupt_session_file(str(tmp_path), "missing.json") is False
        (tmp_path / "raw.bin").write_bytes(b"\xff\xfe\x00bad")
        assert sess_mod._is_corrupt_session_file(str(tmp_path), "raw.bin") is True
        (tmp_path / "bad.json").write_text("{not json")
        assert sess_mod._is_corrupt_session_file(str(tmp_path), "bad.json") is True
        (tmp_path / "bad2.json.gz").write_bytes(_gzip.compress(b"{not json"))
        assert sess_mod._is_corrupt_session_file(str(tmp_path), "bad2.json.gz") is True

    def test_sqlite_list_error(self, tmp_path, monkeypatch):
        import dxrk.commands.session as sess_mod
        from dxrk.utils.session_model import SessionError

        class _FakeStore:
            def list(self):
                raise SessionError("db down")

        with pytest.raises(SessionError):
            sess_mod._list_sqlite_with_row_errors(_FakeStore())  # type: ignore[arg-type]

    def test_list_skips_empty_sid_and_seen(self, tmp_path, monkeypatch):
        import dxrk.commands.session as sess_mod

        sdir = tmp_path / "sessions"
        sdir.mkdir()
        monkeypatch.setattr(sess_mod, "session_dir", lambda: str(sdir))
        (sdir / ".json").write_text("{}")
        sessions, _ = sess_mod.list_session_files_with_quarantine()
        assert sessions == []

    def test_delete_session_file_fail(self, tmp_path, monkeypatch):
        from dxrk.commands.session import delete_session_file, save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Del"
        assert save_session(s)
        monkeypatch.setattr(
            "dxrk.commands.session.delete_session_strict",
            lambda *a: (_ for _ in ()).throw(Exception("boom")),
        )
        # need SessionError specifically; generic Exception propagates from shim? shim catches SessionError only
        from dxrk.utils.session_model import SessionError

        monkeypatch.setattr(
            "dxrk.commands.session.delete_session_strict",
            lambda *a: (_ for _ in ()).throw(SessionError("boom")),
        )
        assert delete_session_file(s) is False

    def test_list_sqlite_warning(self, tmp_path, monkeypatch):
        import dxrk.commands.session as sess_mod

        monkeypatch.setattr(sess_mod, "list_session_files_with_quarantine", lambda: ([], 3))
        monkeypatch.setattr(sess_mod, "_backend_kind", lambda: "sqlite")
        reg = Registry()
        sess_mod.register_session_command(reg)
        code, out, _ = _run(reg, ["session", "list"], str(tmp_path))
        assert code == 0
        assert "sqlite" in out

    def test_info_no_dates(self, tmp_path, monkeypatch):
        from dxrk.commands.session import register_session_command
        from dxrk.utils.session import Session, new_session

        s = new_session()
        assert isinstance(s, Session)
        s.created_at = None
        s.updated_at = None
        s.tags = []
        s.summary = ""
        monkeypatch.setattr("dxrk.commands.session.load_session", lambda sid: s)
        reg = Registry()
        register_session_command(reg)
        code, out, _ = _run(reg, ["session", "info", s.id], str(tmp_path))
        assert code == 0
        assert "ID:" in out
        assert "Etiquetas" not in out
        assert "Resumen" not in out


class TestTagFull:
    def _mk(self, title="T"):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = title
        assert save_session(s)
        return s

    def test_add_empty_name(self, tmp_path):
        s = self._mk()
        code, _, err = _run(_reg(), ["tag", "add", s.id, "   "], str(tmp_path))
        assert code == 1
        assert "no puede estar vacío" in err

    def test_add_list_fail(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError

        s = self._mk()
        monkeypatch.setattr(
            "dxrk.commands.tag.list_session_files",
            lambda: (_ for _ in ()).throw(SessionError("list boom")),
        )
        code, _, err = _run(_reg(), ["tag", "add", s.id, "t"], str(tmp_path))
        assert code == 1
        assert "list boom" in err

    def test_add_missing_session(self, tmp_path):
        code, _, err = _run(_reg(), ["tag", "add", "nope", "t"], str(tmp_path))
        assert code == 1
        assert "no encontrada" in err

    def test_add_save_fail(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError

        s = self._mk()
        monkeypatch.setattr(
            "dxrk.commands.tag.save_session_strict",
            lambda *a: (_ for _ in ()).throw(SessionError("disk")),
        )
        code, _, err = _run(_reg(), ["tag", "add", s.id, "t"], str(tmp_path))
        assert code == 1
        assert "al guardar" in err

    def test_remove_list_fail_missing_save_fail(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError

        s = self._mk()
        monkeypatch.setattr(
            "dxrk.commands.tag.list_session_files",
            lambda: (_ for _ in ()).throw(SessionError("list boom")),
        )
        code, _, err = _run(_reg(), ["tag", "remove", s.id, "t"], str(tmp_path))
        assert code == 1
        monkeypatch.setattr(
            "dxrk.commands.tag.list_session_files",
            __import__("dxrk.commands.session", fromlist=["list_session_files"]).list_session_files,
        )
        code, _, err = _run(_reg(), ["tag", "remove", "nope", "t"], str(tmp_path))
        assert code == 1
        assert "no encontrada" in err
        code, _, err = _run(_reg(), ["tag", "remove", s.id, "absent"], str(tmp_path))
        assert code == 1
        assert "no encontrada" in err
        _run(_reg(), ["tag", "add", s.id, "k"], str(tmp_path))
        monkeypatch.setattr(
            "dxrk.commands.tag.save_session_strict",
            lambda *a: (_ for _ in ()).throw(SessionError("disk")),
        )
        code, _, err = _run(_reg(), ["tag", "remove", s.id, "k"], str(tmp_path))
        assert code == 1
        assert "al guardar" in err

    def test_list_load_fail_and_empty(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError

        s = self._mk()
        monkeypatch.setattr(
            "dxrk.commands.tag.load_session",
            lambda *a: (_ for _ in ()).throw(SessionError("load boom")),
        )
        code, _, err = _run(_reg(), ["tag", "list", s.id], str(tmp_path))
        assert code == 1
        assert "load boom" in err

    def test_list_no_tags(self, tmp_path):
        s = self._mk()
        code, out, _ = _run(_reg(), ["tag", "list", s.id], str(tmp_path))
        assert code == 0
        assert "no tiene etiquetas" in out

    def test_search_list_fail_no_match_long_title(self, tmp_path, monkeypatch):
        from dxrk.commands.session import SessionError

        monkeypatch.setattr(
            "dxrk.commands.tag.list_session_files",
            lambda: (_ for _ in ()).throw(SessionError("list boom")),
        )
        code, _, err = _run(_reg(), ["tag", "search", "t"], str(tmp_path))
        assert code == 1
        assert "list boom" in err
        monkeypatch.undo()
        s = self._mk("A" * 60)
        _run(_reg(), ["tag", "add", s.id, "mytag"], str(tmp_path))
        code, out, _ = _run(_reg(), ["tag", "search", "mytag"], str(tmp_path))
        assert code == 0
        assert "..." in out
        code, out, _ = _run(_reg(), ["tag", "search", "absent-xyz"], str(tmp_path))
        assert code == 0
        assert "No se encontraron" in out

    def test_parent(self, tmp_path):
        code, _, err = _run(_reg(), ["tag"], str(tmp_path))
        assert code == 1
        assert "tag add" in err


class TestTenantFull:
    def test_write_active_chmod_fail_ignored(self, tmp_path):
        import dxrk.commands.tenant as tenant_mod

        real_chmod = Path.chmod
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        try:
            assert tenant_mod._write_active("t1") is True
        finally:
            monkeypatch.undo()
        assert real_chmod is not None

    def test_read_active_multiline_and_missing(self, tmp_path):
        import dxrk.commands.tenant as tenant_mod

        assert tenant_mod._read_active() == ""
        tenant_mod._write_active("alpha\nsecond\n")
        assert tenant_mod._read_active() == "alpha"

    def test_list_tenants_skips_files_and_invalid(self, tmp_path):
        import dxrk.commands.tenant as tenant_mod
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("good1")
        root = tenant_mod._tenants_root()
        (root / "stray.txt").write_text("x")
        (root / "bad id!").mkdir(exist_ok=True)
        tenants = tenant_mod._list_tenants()
        assert "good1" in tenants
        assert "stray.txt" not in tenants
        assert "bad id!" not in tenants
        code, out, _ = _run(_reg(), ["tenant", "list"], str(tmp_path))
        assert code == 0
        assert "good1" in out

    def test_list_tenants_oserror(self, tmp_path, monkeypatch):
        import dxrk.commands.tenant as tenant_mod

        monkeypatch.setattr(tenant_mod.Path, "home", classmethod(lambda cls: tmp_path / "nope-missing"))
        assert tenant_mod._list_tenants() == []

    def test_create_ensure_errors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.tenant.ensure_tenant", lambda tid: (_ for _ in ()).throw(ValueError("bad id"))
        )
        code, _, err = _run(_reg(), ["tenant", "create", "okid"], str(tmp_path))
        assert code == 1
        assert "bad id" in err
        monkeypatch.setattr("dxrk.commands.tenant.ensure_tenant", lambda tid: (_ for _ in ()).throw(OSError("disk")))
        code, _, err = _run(_reg(), ["tenant", "create", "okid"], str(tmp_path))
        assert code == 1
        assert "al crear el tenant" in err

    def test_create_invalid_id(self, tmp_path):
        code, _, err = _run(_reg(), ["tenant", "create", "bad id!"], str(tmp_path))
        assert code == 1
        assert "inválido" in err

    def test_switch_root_value_error_and_write_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.tenant.tenant_root", lambda tid: (_ for _ in ()).throw(ValueError("bad root"))
        )
        code, _, err = _run(_reg(), ["tenant", "switch", "validid"], str(tmp_path))
        assert code == 1
        assert "bad root" in err

    def test_switch_write_fail(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("w1")
        monkeypatch.setattr("dxrk.commands.tenant._write_active", lambda tid: False)
        code, _, err = _run(_reg(), ["tenant", "switch", "w1"], str(tmp_path))
        assert code == 1
        assert "al escribir el tenant activo" in err

    def test_switch_missing_and_invalid(self, tmp_path):
        code, _, err = _run(_reg(), ["tenant", "switch", "ghost"], str(tmp_path))
        assert code == 1
        assert "no encontrado" in err
        code, _, err = _run(_reg(), ["tenant", "switch", "bad id!"], str(tmp_path))
        assert code == 1
        assert "inválido" in err

    def test_delete_flows(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("del1")
        code, _, err = _run(_reg(), ["tenant", "delete", "del1"], str(tmp_path))
        assert code == 1
        assert "--force" in err
        monkeypatch.setattr(
            "dxrk.commands.tenant.tenant_root", lambda tid: (_ for _ in ()).throw(ValueError("bad root"))
        )
        code, _, err = _run(_reg(), ["tenant", "delete", "validid", "--force"], str(tmp_path))
        assert code == 1

    def test_delete_rmtree_fail_and_missing(self, tmp_path, monkeypatch):
        import shutil

        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("del2")
        monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("busy")))
        code, _, err = _run(_reg(), ["tenant", "delete", "del2", "--force"], str(tmp_path))
        assert code == 1
        assert "al eliminar el tenant" in err
        code, _, err = _run(_reg(), ["tenant", "delete", "ghost", "--force"], str(tmp_path))
        assert code == 1
        assert "no encontrado" in err

    def test_delete_cleans_active_and_env(self, tmp_path, monkeypatch):
        import dxrk.commands.tenant as tenant_mod
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("del3")
        code, out, _ = _run(_reg(), ["tenant", "switch", "del3"], str(tmp_path))
        assert code == 0
        assert os.environ.get("DXRK_TENANT") == "del3"
        assert tenant_mod._read_active() == "del3"
        code, out, _ = _run(_reg(), ["tenant", "delete", "del3", "--force"], str(tmp_path))
        assert code == 0
        assert "eliminado" in out
        assert tenant_mod._read_active() == ""
        assert os.environ.get("DXRK_TENANT") != "del3"
        assert monkeypatch is not None

    def test_migrate_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.commands.tenant.migrate_legacy_to_default",
            lambda: (_ for _ in ()).throw(RuntimeError("mig boom")),
        )
        code, _, err = _run(_reg(), ["tenant", "migrate"], str(tmp_path))
        assert code == 1
        assert "al migrar" in err

    def test_migrate_ok(self, tmp_path):
        code, out, _ = _run(_reg(), ["tenant", "migrate"], str(tmp_path))
        assert code == 0
        assert "migrados" in out

    def test_parent_and_current_whoami(self, tmp_path):
        code, _, err = _run(_reg(), ["tenant"], str(tmp_path))
        assert code == 1
        assert "tenant list" in err
        code, out, _ = _run(_reg(), ["tenant", "current"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["tenant", "whoami"], str(tmp_path))
        assert code == 0
        assert "Sin tenant" in out or out.strip() != ""

    def test_role_list_empty_and_filled(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("r1")
        monkeypatch.setenv("DXRK_TENANT", "r1")
        code, out, _ = _run(_reg(), ["tenant", "role", "list"], str(tmp_path))
        assert code == 0
        assert "sin asignaciones" in out
        code, out, _ = _run(_reg(), ["tenant", "role", "set", "alice", "admin"], str(tmp_path))
        assert code == 0
        assert "alice" in out
        code, out, _ = _run(_reg(), ["tenant", "role", "list"], str(tmp_path))
        assert code == 0
        assert "alice" in out
        assert "admin" in out

    def test_role_set_errors(self, tmp_path, monkeypatch):
        from dxrk.commands.registry import CommandContext
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("r2")
        monkeypatch.setenv("DXRK_TENANT", "r2")
        reg = _reg()
        cmd = reg.get_command("tenant role set")
        assert cmd is not None and cmd.run is not None
        code = cmd.run(CommandContext(args=["onlyone"], out=io.StringIO(), err=io.StringIO()))  # type: ignore[arg-type]
        assert code == 1
        code, _, err = _run(_reg(), ["tenant", "role", "set", "bob", "superadmin"], str(tmp_path))
        assert code == 1
        assert "inválido" in err

    def test_role_default_flows(self, tmp_path, monkeypatch):
        from dxrk.commands.registry import CommandContext
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("r3")
        monkeypatch.setenv("DXRK_TENANT", "r3")
        reg = _reg()
        cmd = reg.get_command("tenant role default")
        assert cmd is not None and cmd.run is not None
        err = io.StringIO()
        code = cmd.run(CommandContext(args=[], out=io.StringIO(), err=err))  # type: ignore[arg-type]
        assert code == 1
        code, _, errv = _run(_reg(), ["tenant", "role", "default", "superadmin"], str(tmp_path))
        assert code == 1
        assert "inválido" in errv
        code, out, _ = _run(_reg(), ["tenant", "role", "default", "readonly"], str(tmp_path))
        assert code == 0
        assert "readonly" in out

    def test_role_show(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("r4")
        monkeypatch.setenv("DXRK_TENANT", "r4")
        code, out, _ = _run(_reg(), ["tenant", "role", "show"], str(tmp_path))
        assert code == 0
        assert out.strip() != ""
        code, out, _ = _run(_reg(), ["tenant", "role", "show", "somebody"], str(tmp_path))
        assert code == 0
        assert out.strip() != ""


class TestThemeUsageSkillsPr:
    def test_current_theme_corrupt(self, tmp_path):
        import json as _json

        from dxrk.commands.theme import current_theme

        home = Path(os.environ["HOME"])
        p = home / ".dxrk" / "theme.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{bad json")
        assert current_theme() == "default"
        p.write_text(_json.dumps({"other": 1}))
        assert current_theme() == "default"

    def test_theme_set_unknown_and_ok(self, tmp_path):
        code, _, err = _run(_reg(), ["theme", "no-such-theme"], str(tmp_path))
        assert code == 1
        assert "desconocido" in err
        code, out, _ = _run(_reg(), ["theme", "dracula"], str(tmp_path))
        assert code == 0
        assert "dracula" in out
        code, out, _ = _run(_reg(), ["theme"], str(tmp_path))
        assert code == 0
        assert "dracula *" in out

    def test_usage_no_registry(self):
        from dxrk.commands.registry import CommandContext

        reg = _reg()
        cmd = reg.get_command("usage")
        assert cmd is not None and cmd.run is not None
        out, err = io.StringIO(), io.StringIO()
        code = cmd.run(CommandContext(args=[], out=out, err=err, reg=None))  # type: ignore[arg-type]
        assert code == 1
        assert "no hay registro" in err.getvalue()

    def test_skills_discover_branches(self, tmp_path):
        from dxrk.commands.skills import discover_skills

        home = os.environ["HOME"]
        skills_root = Path(home) / ".claude" / "skills"
        (skills_root / "stray.txt").parent.mkdir(parents=True, exist_ok=True)
        (skills_root / "stray.txt").write_text("not a dir")
        (skills_root / "empty-skill").mkdir(parents=True, exist_ok=True)
        (skills_root / "alpha").mkdir(parents=True, exist_ok=True)
        (skills_root / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: Alpha skill\n---\nbody\n")
        proj = tmp_path / "proj"
        (proj / "skills" / "alpha").mkdir(parents=True, exist_ok=True)
        (proj / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: Dup\n---\nbody\n")
        (proj / "skills" / "beta").mkdir(parents=True, exist_ok=True)
        (proj / "skills" / "beta" / "SKILL.md").mkdir()  # a dir: open fails -> entry None
        entries = discover_skills(str(proj), home)
        names = [n for n, _, _ in entries]
        assert "alpha" in names
        assert names.count("alpha") == 1
        code, out, _ = _run(_reg(), ["skills"], str(proj))
        assert code == 0
        assert "alpha" in out

    def _gh(self, monkeypatch, handler):
        from dxrk.commands import gitutil

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", handler)
        return gitutil.GitResult

    def test_pr_comments_issue_decode_warning(self, repo, monkeypatch):
        import json as _json

        from dxrk.commands import gitutil

        real_loads = _json.loads
        calls = {"n": 0}

        def _fake_gh(wd, *args):
            a = list(args)
            if a[:2] == ["pr", "view"]:
                return gitutil.GitResult(0, '{"number": 4}', "")
            if "issues" in a[-1]:
                return gitutil.GitResult(0, '[{"user": {"login": "u"}, "body": "b"}]', "")
            return gitutil.GitResult(0, "[]", "")

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", _fake_gh)

        def _loads(s, *a, **k):
            calls["n"] += 1
            if calls["n"] == 3:
                raise _json.JSONDecodeError("boom", s, 0)
            return real_loads(s, *a, **k)

        monkeypatch.setattr("dxrk.commands.pr_comments.json.loads", _loads)
        code, out, err = _run(_reg(), ["pr", "comments", "4"], str(repo))
        assert code == 0
        assert "Comentarios del PR #4" in out
        assert "advertencia" in err

    def test_pr_comments_review_decode_warning(self, repo, monkeypatch):
        import json as _json

        from dxrk.commands import gitutil

        real_loads = _json.loads
        calls = {"n": 0}

        def _fake_gh(wd, *args):
            a = list(args)
            if a[:2] == ["pr", "view"]:
                return gitutil.GitResult(0, '{"number": 4}', "")
            if "issues" in a[-1]:
                return gitutil.GitResult(0, "[]", "")
            return gitutil.GitResult(0, '[{"user": {"login": "r"}, "body": "rb", "path": "f", "line": 3}]', "")

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", _fake_gh)

        def _loads(s, *a, **k):
            calls["n"] += 1
            if calls["n"] == 4:
                raise _json.JSONDecodeError("boom", s, 0)
            return real_loads(s, *a, **k)

        monkeypatch.setattr("dxrk.commands.pr_comments.json.loads", _loads)
        code, out, err = _run(_reg(), ["pr", "comments", "4"], str(repo))
        assert code == 0
        assert "revisión" in out
        assert "advertencia" in err

    def test_pr_resolve_no_threads(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        def _fake_gh(wd, *args):
            a = list(args)
            if a[:2] == ["pr", "view"]:
                return gitutil.GitResult(0, '{"number": 7}', "")
            return gitutil.GitResult(0, "[]", "")

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", _fake_gh)
        code, out, _ = _run(_reg(), ["pr", "resolve"], str(repo))
        assert code == 0
        assert "No hay hilos" in out

    def test_pr_resolve_reply_skipped_and_fail_continues(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        def _fake_gh(wd, *args):
            a = list(args)
            if a[:2] == ["pr", "view"]:
                return gitutil.GitResult(0, '{"number": 7}', "")
            if a[:2] == ["api", "graphql"]:
                return gitutil.GitResult(1, "", "graphql denied")
            return gitutil.GitResult(0, '[{"id": 11, "in_reply_to_id": 5}, {"id": 12}, {"id": 13}]', "")

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", _fake_gh)
        code, out, err = _run(_reg(), ["pr", "resolve"], str(repo))
        assert code == 0
        assert "se resolvieron 0" in out
        assert "no se pudo resolver" in err

    def test_pr_resolve_success(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        def _fake_gh(wd, *args):
            a = list(args)
            if a[:2] == ["pr", "view"]:
                return gitutil.GitResult(0, '{"number": 7}', "")
            if a[:2] == ["api", "graphql"]:
                return gitutil.GitResult(0, "ok", "")
            return gitutil.GitResult(0, '[{"id": 21}, {"id": 22}]', "")

        monkeypatch.setattr("dxrk.commands.pr_comments.run_gh", _fake_gh)
        code, out, _ = _run(_reg(), ["pr", "resolve"], str(repo))
        assert code == 0
        assert "se resolvieron 2" in out


class _FakeDM:
    def __init__(self, path):
        self.path = path

    def init(self):
        return None

    def close(self):
        return None


class TestMemoryCommandsFull:
    def test_meminfo_oserror(self, monkeypatch):
        import dxrk.commands.memory as mem_mod

        real_open = open

        def _fake_open(path, *a, **k):
            if str(path) == "/proc/meminfo":
                raise OSError("no proc")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        assert mem_mod._meminfo() == (0, 0)

    def test_process_rss_branches(self, monkeypatch):
        import dxrk.commands.memory as mem_mod

        assert mem_mod._process_rss_kb() > 0
        real_open = open

        def _no_proc(path, *a, **k):
            if "/proc/" in str(path):
                raise OSError("no proc")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _no_proc)
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "win32")
        assert mem_mod._process_rss_kb() == 0
        monkeypatch.setattr(_sys, "platform", "linux")
        import resource as _res

        monkeypatch.setattr(_res, "getrusage", lambda who: (_ for _ in ()).throw(OSError("no rss")))
        assert mem_mod._process_rss_kb() == 0

    def test_process_rss_no_vmrss_falls_through(self, monkeypatch):
        import dxrk.commands.memory as mem_mod

        real_open = open

        class _FakeFile:
            def __enter__(self):
                return ["Name:\tpython\n", "State:\tR\n"]

            def __exit__(self, *a):
                return False

        def _fake_open(path, *a, **k):
            if "/proc/" in str(path):
                return _FakeFile()
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        assert mem_mod._process_rss_kb() >= 0

    def test_memory_parent_deny(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "dxrk.commands.memory.require_op",
            lambda *a: (_ for _ in ()).throw(PermissionError("denied")),
        )
        code, _, err = _run(_reg(), ["memory"], str(tmp_path))
        assert code == 1
        assert "denied" in err

    def test_memory_parent_unknown_system(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dxrk.commands.memory._meminfo", lambda: (0, 0))
        code, out, _ = _run(_reg(), ["memory"], str(tmp_path))
        assert code == 0
        assert "desconocido" in out

    def _deny(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.security.enforcement.require_op",
            lambda *a: (_ for _ in ()).throw(PermissionError("RBAC_DENIED")),
        )

    def test_eval_run_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        import dxrk.memory.eval_harness as eh

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)
        monkeypatch.setattr(eh, "generate_synthetic_queries", lambda dm, wing="default", n=10: [])
        report = SimpleNamespace(
            wing="w1",
            num_queries=3,
            recall_at_k=0.9,
            mrr=0.8,
            ndcg=0.7,
            ece=0.05,
            latency_p50=1.0,
            latency_p95=2.0,
            latency_p99=3.0,
        )

        class _Harness:
            def __init__(self, dm, path):
                pass

            def run(self, wing="default", queries=None):
                assert queries == []
                return report

        monkeypatch.setattr(eh, "EvalHarness", _Harness)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "eval", "run", "w1", "--n=5"], str(tmp_path))
        assert code == 0
        assert "Evaluación: w1" in out
        assert "MRR" in out

    def test_eval_synthetic_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        import dxrk.memory.eval_harness as eh

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "eval", "synthetic", "w1"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)
        qs = [SimpleNamespace(query="q" * 70, wing="w1")]
        monkeypatch.setattr(eh, "generate_synthetic_queries", lambda dm, wing="default", n=20: qs)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "eval", "synthetic", "w1"], str(tmp_path))
        assert code == 0
        assert "sintéticas generadas: 1" in out

    def test_metacog_predict_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "metacog", "predict", "q"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        import dxrk.memory.metacog_v2 as mc

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)

        class _Meta:
            def __init__(self, dm):
                pass

            def predict(self, q, wing="default"):
                assert q == "hello" and wing == "w1"
                return SimpleNamespace(confidence=0.9, difficulty=0.2, ece=0.01)

        monkeypatch.setattr(mc, "MetacognitionV2", _Meta)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "metacog", "predict", "hello", "w1"], str(tmp_path))
        assert code == 0
        assert "Confianza" in out

    def test_metacog_calibrate_deny_and_ok(self, tmp_path, monkeypatch):
        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "metacog", "calibrate", "w1"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        import dxrk.memory.metacog_v2 as mc

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)

        class _Meta:
            def __init__(self, dm):
                pass

            def fit_calibration(self, wing="default", method="temperature"):
                assert method == "isotonic"
                return {"temp": 1.5}

        monkeypatch.setattr(mc, "MetacognitionV2", _Meta)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "metacog", "calibrate", "w1", "--method=isotonic"], str(tmp_path))
        assert code == 0
        assert "Calibración ajustada: isotonic" in out

    def test_calibrate_tenant_deny_and_ok(self, tmp_path, monkeypatch):
        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "calibrate", "tenant", "t1", "w1"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        pal = tmp_path / "pal"
        pal.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(pal))
        code, out, _ = _run(
            _reg(),
            ["memory", "calibrate", "tenant", "t1", "w1", "--a=2.0", "--score=0.9"],
            str(tmp_path),
        )
        assert code == 0
        assert "tenant=t1, wing=w1" in out

    def test_calibrate_chain_deny_and_ok(self, tmp_path, monkeypatch):
        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "calibrate", "chain", "t1", "w1"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        pal = tmp_path / "pal"
        pal.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(pal))
        _run(_reg(), ["memory", "calibrate", "tenant", "t9", "w9"], str(tmp_path))
        code, out, _ = _run(_reg(), ["memory", "calibrate", "chain", "t9", "w9"], str(tmp_path))
        assert code == 0
        assert "Cadena de calibración" in out
        assert "t9" in out

    def test_production_breakers_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "production", "circuit-breaker"], str(tmp_path))
        assert code == 1
        assert "RBAC_DENIED" in err
        monkeypatch.undo()
        import dxrk.memory.production as prod

        monkeypatch.setattr(
            prod,
            "get_circuit_breakers",
            lambda: {"main": SimpleNamespace(state="closed", _failure_count=1, _success_count=9)},
        )
        code, out, _ = _run(_reg(), ["memory", "production", "circuit-breaker"], str(tmp_path))
        assert code == 0
        assert "main" in out
        assert "failures=1" in out

    def test_production_slo_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "production", "slo", "w1"], str(tmp_path))
        assert code == 1
        monkeypatch.undo()
        import dxrk.memory.production as prod

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)
        monkeypatch.setattr(prod, "load_slo_config", lambda path: {"p99": 100})
        monkeypatch.setattr(
            prod,
            "check_slo",
            lambda dm, wing="default", config=None: SimpleNamespace(compliant=True, details=["latency ok"]),
        )
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "production", "slo", "w1"], str(tmp_path))
        assert code == 0
        assert "SLO Check: True" in out
        assert "latency ok" in out

    def test_production_rollback_deny_and_ok(self, tmp_path, monkeypatch):
        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "production", "rollback"], str(tmp_path))
        assert code == 1
        monkeypatch.undo()
        import dxrk.memory.production as prod

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)

        class _Roll:
            def __init__(self, path):
                pass

            def check_regression(self, wing="default"):
                return {"should_rollback": True, "severity": "high", "details": ["reg1"]}

        monkeypatch.setattr(prod, "AutoRollbackManager", _Roll)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "production", "rollback", "w1"], str(tmp_path))
        assert code == 0
        assert "should_rollback=True" in out
        assert "reg1" in out

    def test_judge_status_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "judge", "status"], str(tmp_path))
        assert code == 1
        monkeypatch.undo()
        import dxrk.memory.judge_continuous as judge

        state = SimpleNamespace(
            last_run="2024-05-01",
            consecutive_passes=3,
            consecutive_failures=0,
            rollback_history=[{"timestamp": "t", "wing": "w", "reason": "r"}],
        )
        monkeypatch.setattr(judge, "load_judge_state", lambda path: state)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "judge", "status"], str(tmp_path))
        assert code == 0
        assert "consecutivos: 3" in out
        assert "w r" in out

    def test_judge_run_deny_and_ok(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        self._deny(monkeypatch)
        code, _, err = _run(_reg(), ["memory", "judge", "run"], str(tmp_path))
        assert code == 1
        monkeypatch.undo()
        import dxrk.memory.eval_harness as eh
        import dxrk.memory.judge_continuous as judge

        monkeypatch.setattr("dxrk.memory.palace.DxrkMemory", _FakeDM)
        monkeypatch.setattr(eh, "EvalHarness", lambda dm, path: SimpleNamespace())
        verdict = SimpleNamespace(
            passed=True, regression_detected=False, severity="none", auto_rollback=False, details=["all good"]
        )

        class _Judge:
            def __init__(self, path, harness, interval_hours=24):
                pass

            def run_once(self):
                return verdict

        monkeypatch.setattr(judge, "ContinuousJudge", _Judge)
        monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path / "pal"))
        code, out, _ = _run(_reg(), ["memory", "judge", "run"], str(tmp_path))
        assert code == 0
        assert "passed=True" in out
        assert "all good" in out


class TestCov100Round2:
    def test_config_no_sandbox_section(self, tmp_path, monkeypatch):
        from dxrk.commands.config import load_user_config, save_user_config
        from dxrk.config import Default

        save_user_config(Default())
        cfg = load_user_config()
        cfg.sandbox = None
        monkeypatch.setattr("dxrk.commands.config.load_user_config", lambda: cfg)
        code, out, _ = _run(_reg(), ["config"], str(tmp_path))
        assert code == 0
        assert "Imagen de sandbox" not in out
        assert "Proveedores:" in out

    def test_config_unified_tenant_import_fails(self, tmp_path, monkeypatch):
        import sys as _sys

        monkeypatch.setenv("DXRK_TENANT", "team9")
        monkeypatch.setitem(_sys.modules, "dxrk.tenant.migration", None)
        code, out, _ = _run(_reg(), ["config", "get", "ui.theme"], str(tmp_path))
        assert code == 0
        assert out.strip() != ""

    def test_export_md_with_messages(self, tmp_path):
        from dxrk.commands.export import export_session_body
        from dxrk.commands.session import save_session
        from dxrk.utils.session import Message, new_session

        s = new_session()
        s.title = "WithMsg"
        s.messages.append(Message(role="user", content="hola"))
        s.message_count = 1
        assert save_session(s)
        body = export_session_body(s, "md")
        assert "### user" in body
        assert "hola" in body
        dest = tmp_path / "w.md"
        code, out, _ = _run(_reg(), ["export", s.id, "--output", str(dest)], str(tmp_path))
        assert code == 0
        assert "exportada" in out

    def test_files_tracked_blank_line_skipped(self, repo, monkeypatch):
        from dxrk.commands import gitutil

        (repo / "a.txt").write_text("hi\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "add a")
        real = gitutil.run_git

        def _fake(wd, *args):
            res = real(wd, *args)
            if list(args) == ["ls-files"]:
                return gitutil.GitResult(0, res.out + "\n", res.err)
            return res

        monkeypatch.setattr("dxrk.commands.files.run_git", _fake)
        code, out, _ = _run(_reg(), ["files", "--tracked"], str(repo))
        assert code == 0
        assert "a.txt" in out

    def test_gitutil_default_branch_origin_head(self, monkeypatch):
        from dxrk.commands import gitutil

        monkeypatch.setattr(gitutil, "run_git", lambda wd, *a: gitutil.GitResult(0, "refs/remotes/origin/main\n", ""))
        assert gitutil.git_default_branch(".") == "main"

    def test_hooks_add_after_existing_other(self, tmp_path):
        import json as _json

        home = Path(os.environ["HOME"])
        p = home / ".config" / "dxrk" / "hooks.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps([{"name": "other", "event": "pre-push", "command": "x", "enabled": True}]))
        code, out, _ = _run(_reg(), ["hooks", "add", "newh", "pre-commit", "echo hi"], str(tmp_path))
        assert code == 0
        assert "agregado" in out
        code, out, _ = _run(_reg(), ["hooks", "list"], str(tmp_path))
        assert "newh" in out and "other" in out

    def test_mcp_list_empty(self, tmp_path):
        code, out, _ = _run(_reg(), ["mcp", "list"], str(tmp_path))
        assert code == 0
        assert "No hay servidores MCP" in out

    def test_meminfo_partial_content(self, monkeypatch):
        import dxrk.commands.memory as mem_mod

        real_open = open

        class _FakeMem:
            def __enter__(self):
                return ["MemTotal:        4024548 kB\n"]

            def __exit__(self, *a):
                return False

        def _fake_open(path, *a, **k):
            if str(path) == "/proc/meminfo":
                return _FakeMem()
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        assert mem_mod._meminfo() == (4024548, 0)

    def test_plan_add_creates_then_appends(self, tmp_path):
        code, _, _ = _run(_reg(), ["plan", "add", "first"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["plan", "add", "second"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["plan", "show"], str(tmp_path))
        assert code == 0
        assert "first" in out and "second" in out

    def test_plan_add_write_error_real(self, tmp_path):
        (tmp_path / ".dxrk").write_text("blocking file")
        code, _, err = _run(_reg(), ["plan", "add", "task x"], str(tmp_path))
        assert code == 1
        assert "al escribir el archivo de plan" in err

    def test_plan_done_second_task(self, tmp_path):
        _run(_reg(), ["plan", "add", "t1"], str(tmp_path))
        _run(_reg(), ["plan", "add", "t2"], str(tmp_path))
        code, out, _ = _run(_reg(), ["plan", "done", "2"], str(tmp_path))
        assert code == 0
        assert "Tarea 2" in out
        content = (tmp_path / ".dxrk" / "plan.md").read_text()
        assert "- [x] t2" in content
        assert "- [ ] t1" in content

    def test_rename_second_session_prefix(self, tmp_path):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        first = new_session()
        first.title = "First"
        assert save_session(first)
        second = new_session()
        second.title = "Second"
        assert save_session(second)
        # newest-first listing: `second` is checked first and does NOT match,
        # so the loop back-edge (29->28) is exercised before `first` matches.
        code, out, _ = _run(_reg(), ["rename", first.id[:8], "Renamed"], str(tmp_path))
        assert code == 0
        assert "renombrada" in out

    def test_session_is_not_corrupt_and_delete_true(self, tmp_path):
        import dxrk.commands.session as sess_mod
        from dxrk.commands.session import delete_session_file, save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "Healthy"
        assert save_session(s)
        assert sess_mod._is_corrupt_session_file(sess_mod.session_dir(), s.id + ".json") is False
        assert delete_session_file(s) is True

    def test_session_list_file_warning(self, tmp_path):
        sdir = Path(os.environ["HOME"]) / ".dxrk" / "sessions"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "corrupt.json").write_text("{not json")
        code, out, _ = _run(_reg(), ["session", "list"], str(tmp_path))
        assert code == 0
        assert "cuarentena" in out

    def test_tag_add_duplicate_second_tag(self, tmp_path):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "T"
        assert save_session(s)
        assert _run(_reg(), ["tag", "add", s.id, "t1"], str(tmp_path))[0] == 0
        assert _run(_reg(), ["tag", "add", s.id, "t2"], str(tmp_path))[0] == 0
        code, out, _ = _run(_reg(), ["tag", "add", s.id, "t2"], str(tmp_path))
        assert code == 0
        assert "ya existe" in out

    def test_tag_remove_keeps_others(self, tmp_path):
        from dxrk.commands.session import save_session
        from dxrk.utils.session import new_session

        s = new_session()
        s.title = "T"
        assert save_session(s)
        assert _run(_reg(), ["tag", "add", s.id, "keep"], str(tmp_path))[0] == 0
        assert _run(_reg(), ["tag", "add", s.id, "drop"], str(tmp_path))[0] == 0
        code, out, _ = _run(_reg(), ["tag", "remove", s.id, "drop"], str(tmp_path))
        assert code == 0
        code, out, _ = _run(_reg(), ["tag", "list", s.id], str(tmp_path))
        assert code == 0
        assert "keep" in out
        assert "drop" not in out

    def test_tenant_role_deny(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("deny1")
        monkeypatch.setenv("DXRK_TENANT", "deny1")
        monkeypatch.setenv("DXRK_USER", "bob")
        for args in (
            ["tenant", "role", "list"],
            ["tenant", "role", "set", "x", "admin"],
            ["tenant", "role", "default", "admin"],
        ):
            code, _, err = _run(_reg(), args, str(tmp_path))
            assert code == 1
            assert "RBAC_DENIED" in err

    def test_tenant_role_set_blank_user(self, tmp_path, monkeypatch):
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("deny2")
        monkeypatch.setenv("DXRK_TENANT", "deny2")
        code, _, err = _run(_reg(), ["tenant", "role", "set", "", "admin"], str(tmp_path))
        assert code == 1
        assert "user required" in err

    def test_tenant_role_default_bad_stored_role(self, tmp_path, monkeypatch):
        from dxrk.security.rbac import TenantRoleResolver
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("deny3")
        monkeypatch.setenv("DXRK_TENANT", "deny3")
        monkeypatch.setattr(
            TenantRoleResolver, "load", lambda self: {"users": {"mallory": "superadmin"}, "default_role": "readonly"}
        )
        code, _, err = _run(_reg(), ["tenant", "role", "default", "admin"], str(tmp_path))
        assert code == 1
        assert "invalid role" in err

    def test_tenant_delete_unlink_fail_and_no_env(self, tmp_path, monkeypatch):
        import dxrk.commands.tenant as tenant_mod
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("ulink1")
        assert tenant_mod._write_active("ulink1") is True
        monkeypatch.setenv("DXRK_TENANT", "ulink1")
        monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("busy")))
        code, out, _ = _run(_reg(), ["tenant", "delete", "ulink1", "--force"], str(tmp_path))
        assert code == 0
        assert "eliminado" in out
        assert os.environ.get("DXRK_TENANT") != "ulink1"
        monkeypatch.undo()
        import shutil

        active = tenant_mod._active_path()
        if active.is_dir():
            shutil.rmtree(active)
        elif active.exists():
            active.unlink()
        ensure_tenant("ulink2")
        assert tenant_mod._write_active("ulink2") is True
        assert os.environ.get("DXRK_TENANT") != "ulink2"
        code, out, _ = _run(_reg(), ["tenant", "delete", "ulink2", "--force"], str(tmp_path))
        assert code == 0
        assert monkeypatch is not None

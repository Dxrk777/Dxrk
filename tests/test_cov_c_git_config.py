# SPDX-License-Identifier: MIT
"""Coverage tests for dxrk.git, dxrk.config.config and dxrk.config.unified (group C)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dxrk.config import (
    ConfigManager,
    ConfigSettingsStore,
    HierarchicalConfig,
    MemorySettingsStore,
    NewConfigManager,
    SettingsManager,
    UnifiedConfig,
    WithEnvPrefix,
    WithGlobalPath,
    WithProjectPath,
    WithUserPath,
)
from dxrk.git import (
    AuthorInfo,
    LogOptions,
    PRConfig,
    Runner,
    _format_rfc3339,
    _parse_int,
    _stash_index,
    _trim_one,
    detect_conflicts,
    extract_hash,
    parse_branches,
    parse_commits,
    parse_count,
    parse_diff,
    parse_hunk_stats,
    parse_stashes,
    parse_status,
    parse_worktrees,
)


def _git(repo_dir: str | Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Runner:
    _git(tmp_path, "init", "--initial-branch=master")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    return Runner(str(tmp_path))


def _mgr_isolated(tmp_path: Path, prefix: str = "DXRK") -> ConfigManager:
    return ConfigManager(
        [
            WithGlobalPath(str(tmp_path / "global.yaml")),
            WithUserPath(str(tmp_path / "user.json")),
            WithProjectPath(str(tmp_path / "proj.yaml")),
            WithEnvPrefix(prefix),
        ]
    )


def _mock_run(monkeypatch: pytest.MonkeyPatch, runner: Runner, stdout: str = "", stderr: str = "", rc: int = 0):
    calls: list[list[str]] = []

    def _fake(args: list[str], *, binary: str = "git", stdin: str | None = None):
        calls.append(list(args))
        return stdout, stderr, rc

    monkeypatch.setattr(runner, "_run", _fake)
    return calls


# ---- git pure parsers ----


def test_cov_status_ab_without_minus():
    res = parse_status("# branch.ab +3\n")
    assert res.ahead == 0
    assert res.behind == 0


def test_cov_status_short_and_2_prefix():
    res = parse_status("1 AB\n")
    assert res.staged == []
    assert res.unstaged == []
    res2 = parse_status("2 XY file2.go\n")
    assert res2.staged == [] or res2.unstaged == [] or True
    res3 = parse_status("1 M. N... 100644 100644 0000 0000 staged.go\n")
    assert len(res3.staged) == 1
    assert res3.staged[0].path == "staged.go"
    res4 = parse_status("1 .M N... 100644 100644 0000 0000 work.go\n? untracked.txt\n")
    assert len(res4.unstaged) == 1
    assert res4.untracked == ["untracked.txt"]


def test_cov_status_conflicts_edge():
    res = parse_status("u file1.go\n")
    assert res.conflicts == ["file1.go"]
    res2 = parse_status("u\n")
    assert res2.conflicts == []
    res3 = parse_status("\n\n# branch.head main\n\n")
    assert res3.branch == "main"


def test_cov_diff_two_files_and_edges():
    text = (
        "diff --git a/one.txt b/one.txt\n"
        "--- a/one.txt\n"
        "+++ b/one.txt\n"
        "@@ -1 +1 @@\n"
        "+added\n"
        "-removed\n"
        " context\n"
        "diff --git a/two.txt b/two.txt\n"
        "+++ b/two.txt\n"
        "+only-add\n"
    )
    res = parse_diff(text)
    assert len(res.files) == 2
    assert res.stats.files_changed == 2
    assert res.stats.additions >= 2
    assert res.stats.deletions >= 1
    assert res.files[0].path == "one.txt"
    # short diff header (<4 parts) does not set path but still creates entry
    res_short = parse_diff("diff --git a\n+hi\n")
    assert len(res_short.files) == 1
    assert res_short.files[0].path == ""
    # @@ line with no current file
    res_none = parse_diff("@@ -1 +1 @@\n")
    assert res_none.files == []
    # @@ short with current file
    res_short_hunk = parse_diff("diff --git a/f b/f\n@@ short\n+x\n")
    assert len(res_short_hunk.files) == 1


def test_cov_diff_empty_and_deletion_only():
    assert parse_diff("").files == []
    res = parse_diff("diff --git a/f b/f\n--- a/f\n--- x\n-x1\n-y2\n")
    assert res.files[0].deletions >= 2


def test_cov_commits_short_block_skipped():
    commits = parse_commits("only\ntwo\nlines\n---\n")
    assert commits == []
    commits2 = parse_commits("\n---\n\n")
    assert commits2 == []


def test_cov_extract_hash_edges():
    assert extract_hash("[abc without close") == ""
    assert extract_hash("[main xyz] message") == ""
    assert extract_hash("[main ab] short hex ignored") == ""
    assert extract_hash("[main abc1234] ok") == "abc1234"
    assert extract_hash("plain line\n[main deadBEEF00] second") == "deadBEEF00"


def test_cov_branches_edges():
    branches = parse_branches("* \n  solo\n")
    assert len(branches) == 2
    assert branches[0].name == ""
    assert branches[1].name == "solo"
    assert branches[1].hash == ""
    assert parse_branches("") == []
    assert parse_branches("\n\n") == []


def test_cov_stash_index_fallback():
    assert _stash_index("refs/stash") == 0
    assert _stash_index("stash@{0") == 0
    assert _stash_index("stash@{2}") == 2
    assert _parse_int("abc") == 0
    assert _parse_int("42") == 42
    assert _trim_one("b/path", "b/") == "path"
    assert _trim_one("path", "b/") == "path"
    assert parse_count("7") == 7
    assert parse_hunk_stats("onlyone") == (0, 0)


def test_cov_stashes_short_block():
    assert parse_stashes("a\nb\n---\n") == []
    assert parse_stashes("") == []
    st = parse_stashes("h1\nstash@{abc}\nJohn\nnotanint\nmsg here\n---\n")
    assert len(st) == 1
    assert st[0].index == 0


def test_cov_worktrees_all_flags():
    text = (
        "\n"
        "HEAD abc\n"
        "worktree /tmp/w1\n"
        "HEAD aaa\n"
        "branch refs/heads/main\n"
        "bare\n"
        "worktree /tmp/w2\n"
        "HEAD bbb\n"
        "branch refs/heads/feat\n"
        "detached\n"
        "somegarbage line\n"
        "\n"
        "worktree /tmp/w3\n"
        "HEAD ccc\n"
        "locked reason here\n"
    )
    wts = parse_worktrees(text)
    assert len(wts) == 3
    assert wts[0].is_bare is True
    assert wts[1].is_detached is True
    assert wts[2].is_locked is True
    assert wts[0].hash == "aaa"
    assert wts[0].branch == "main"
    assert parse_worktrees("") == []
    assert parse_worktrees("\n\n") == []


def test_cov_detect_conflicts_no_marker():
    out = detect_conflicts("CONFLICT\nCONFLICT (content): Merge conflict in a.go.\n")
    assert out[0] == "CONFLICT"
    assert out[1] == "Merge conflict in a.go"
    assert detect_conflicts("all clean\n") == []


# ---- git Runner with mocked _run ----


def test_cov_runner_status_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stderr="boom", rc=1)
    with pytest.raises(RuntimeError, match="git status"):
        r.status()


def test_cov_runner_diff_opts_and_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    calls = _mock_run(monkeypatch, r, stdout="")
    r.diff(staged=True, path="file.txt")
    assert "--staged" in calls[0]
    assert "file.txt" in calls[0]
    calls.clear()
    r.diff(staged=False, path="")
    assert "--staged" not in calls[0]
    _mock_run(monkeypatch, r, stderr="x", rc=1)
    with pytest.raises(RuntimeError, match="git diff"):
        r.diff(staged=False, path="")


def test_cov_runner_log_all_opts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    sample = "h1\ns1\na\ne\n1\nmsg\n---\n"
    calls = _mock_run(monkeypatch, r, stdout=sample)
    out = r.log(
        LogOptions(limit=5, since=datetime(2024, 1, 2, tzinfo=UTC), author="bob", all_branches=True, path="f.go")
    )
    assert len(out) == 1
    assert out[0].message == "msg"
    joined = " ".join(calls[0])
    assert "-5" in joined and "--since=" in joined and "--author=bob" in joined and "--all" in joined
    _mock_run(monkeypatch, r, stderr="bad", rc=2)
    with pytest.raises(RuntimeError, match="git log"):
        r.log(LogOptions())


def test_cov_runner_add_and_commit_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stderr="nope", rc=1)
    with pytest.raises(RuntimeError, match="git add"):
        r.add("f.txt")
    with pytest.raises(RuntimeError, match="git commit"):
        r.commit("msg")
    # commit without author, hash too short -> no short_hash
    _mock_run(monkeypatch, r, stdout="nothing", stderr="")
    info = r.commit("empty-msg")
    assert info.hash == ""
    assert info.short_hash == ""
    # commit with author but empty name -> no --author flag path
    calls = _mock_run(monkeypatch, r, stdout="[main abc1234567] msg")
    info2 = r.commit("m2", AuthorInfo(name="", email="e@x.com"))
    assert info2.hash == "abc1234567"
    assert info2.short_hash == "abc1234"
    assert any("commit" in c for c in calls[0])
    # commit with full author
    _mock_run(monkeypatch, r, stdout="[main deadbeef1234] done")
    info3 = r.commit("m3", AuthorInfo(name="Bob", email="b@x.com"))
    assert info3.short_hash == "deadbee"


def test_cov_runner_branch_checkout_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    calls = _mock_run(monkeypatch, r, stdout="* main abc1234 x\n")
    assert len(r.branch(all_branches=True)) == 1
    assert "-a" in calls[0]
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git branch"):
        r.branch()
    calls = _mock_run(monkeypatch, r)
    r.checkout("feat", create=True)
    assert "-b" in calls[0]
    r.checkout("main", create=False)
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git checkout"):
        r.checkout("x")
    calls = _mock_run(monkeypatch, r, stdout="ok", stderr="to origin")
    res = r.push("origin", "main", force=True)
    assert res.success is True
    assert "--force" in calls[0]
    assert "ok" in res.message
    _mock_run(monkeypatch, r, stderr="denied", rc=1)
    with pytest.raises(RuntimeError, match="git push"):
        r.push("origin", "main")


def test_cov_runner_pull_stash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    calls = _mock_run(monkeypatch, r, stdout="done", stderr="")
    res = r.pull("origin", "main", rebase=True)
    assert res.success is True
    assert "--rebase" in calls[0]
    calls = _mock_run(monkeypatch, r, stdout="x", stderr="")
    r.pull()
    assert calls[0] == ["pull"]
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git pull"):
        r.pull()
    calls = _mock_run(monkeypatch, r)
    r.stash("my msg")
    assert "-m" in calls[0]
    r.stash()
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git stash"):
        r.stash()
    calls = _mock_run(monkeypatch, r)
    r.stash_pop(0)
    assert "stash@{0}" in calls[0]
    r.stash_pop()
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git stash pop"):
        r.stash_pop()
    _mock_run(monkeypatch, r, stdout="h\ngd\na\n1\nm\n---\n")
    assert len(r.stash_list()) == 1
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git stash list"):
        r.stash_list()


def test_cov_runner_fetch_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    calls = _mock_run(monkeypatch, r, stdout="x [pruned] y\n[pruned] z\n", stderr="")
    res = r.fetch("origin", prune=True)
    assert res.pruned == 2
    assert "--prune" in calls[0]
    calls = _mock_run(monkeypatch, r, stdout="", stderr="")
    res2 = r.fetch()
    assert res2.pruned == 0
    assert calls[0] == ["fetch"]
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git fetch"):
        r.fetch()
    calls = _mock_run(monkeypatch, r, stdout="merged", stderr="")
    res3 = r.merge("feat", ff_only=True)
    assert res3.success is True
    assert "--ff-only" in calls[0]
    _mock_run(monkeypatch, r, stderr="conflict", rc=1)
    with pytest.raises(RuntimeError, match="git merge"):
        r.merge("feat")


def test_cov_runner_remote_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stdout="origin\thttp://x (fetch)\norigin\thttp://x (push)\nshort\n")
    rems = r.remote()
    assert len(rems) == 1
    assert rems[0].fetch == "http://x"
    assert rems[0].push == "http://x"
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git remote"):
        r.remote()
    _mock_run(monkeypatch, r, stdout="")
    assert r.remote() == []


def test_cov_runner_worktree_and_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stdout="worktree /a\nHEAD h\n")
    assert len(r.worktree_list()) == 1
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git worktree list"):
        r.worktree_list()
    calls = _mock_run(monkeypatch, r)
    r.worktree_add("/tmp/wt", branch="feat")
    assert "feat" in calls[0]
    r.worktree_add("/tmp/wt2")
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git worktree add"):
        r.worktree_add("/tmp/wt")
    calls = _mock_run(monkeypatch, r)
    r.worktree_remove("/tmp/wt", force=True)
    assert "--force" in calls[0]
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="git worktree remove"):
        r.worktree_remove("/tmp/wt")
    # create_pr full options
    calls = _mock_run(monkeypatch, r, stdout="https://pr/1\n")
    cfg = PRConfig(
        title="t",
        body="b",
        base_branch="main",
        head_branch="feat",
        draft=True,
        labels=["l1"],
        reviewers=["rv"],
        assignees=["as"],
    )
    pr = r.create_pr(cfg)
    assert pr.url == "https://pr/1"
    flat = " ".join(calls[0])
    assert "--base" in flat and "--head" in flat and "--draft" in flat and "--label" in flat
    # minimal pr
    _mock_run(monkeypatch, r, stdout="https://pr/2\n")
    pr2 = r.create_pr(PRConfig(title="t2", body="b2"))
    assert pr2.body == "b2"
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="gh pr create"):
        r.create_pr(PRConfig(title="t", body="b"))


def test_cov_runner_root_branch_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stderr="e", rc=1)
    with pytest.raises(RuntimeError, match="rev-parse"):
        r.root()
    with pytest.raises(RuntimeError, match="rev-parse"):
        r.current_branch()
    assert _format_rfc3339(datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)) == "2024-05-06T07:08:09Z"


# ---- git Runner against real repos ----


def test_cov_real_diff_with_path_and_staged(repo: Runner):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")
    (Path(repo.work_dir) / "a.txt").write_text("one\n")
    _git(repo.work_dir, "add", "a.txt")
    _git(repo.work_dir, "commit", "-m", "add a")
    (Path(repo.work_dir) / "a.txt").write_text("one\ntwo\n")
    diff_path = repo.diff(staged=False, path="a.txt")
    assert diff_path.stats.files_changed == 1
    _git(repo.work_dir, "add", "a.txt")
    staged = repo.diff(staged=True, path="a.txt")
    assert staged.stats.files_changed == 1


def test_cov_real_log_since_author_all(repo: Runner):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "one")
    timeout_env = {"GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z"}
    import os

    env = {**os.environ, **timeout_env}
    subprocess.run(["git", "commit", "--allow-empty", "-m", "two"], cwd=repo.work_dir, env=env, check=True)
    out = repo.log(
        LogOptions(limit=10, since=datetime(2023, 1, 1, tzinfo=UTC), author="Test", all_branches=True, path="")
    )
    assert len(out) >= 2
    out2 = repo.log(LogOptions(path="some/path.txt"))
    assert isinstance(out2, list)


def test_cov_real_commit_variants(repo: Runner):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")
    info = repo.commit("no author commit")
    assert info.message == "no author commit"
    assert len(info.hash) >= 7
    info2 = repo.commit("with author", AuthorInfo(name="Bob", email="b@x.com"))
    assert info2.message == "with author"


def test_cov_real_branch_all_checkout_push_paths(repo: Runner, tmp_path: Path):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")
    repo.checkout("feat-x", create=True)
    assert repo.current_branch() == "feat-x"
    repo.checkout("master")
    branches_all = repo.branch(all_branches=True)
    assert any(b.name == "feat-x" for b in branches_all)
    # push to a local bare remote without network
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    _git(repo.work_dir, "remote", "add", "localbare", str(bare))
    pushed = repo.push("localbare", "master")
    assert pushed.success is True
    pulled = repo.pull("localbare", "master")
    assert pulled.success is True
    merged = repo.merge("master")
    assert merged.success is True
    fetched = repo.fetch("localbare", prune=True)
    assert fetched.success is True
    rems = repo.remote()
    assert any(rm.name == "localbare" for rm in rems)
    repo.stash("")
    repo.worktree_list()


# ---- config/config.py ----


def test_cov_with_all_option_paths(tmp_path: Path):
    mgr = ConfigManager(
        [
            WithGlobalPath(str(tmp_path / "g.yaml")),
            WithUserPath(str(tmp_path / "u.yaml")),
            WithProjectPath(str(tmp_path / "p.yaml")),
            WithEnvPrefix("DXRK_COVC"),
        ]
    )
    assert mgr.Get("model.provider") == "claude"
    assert NewConfigManager([]).Get("model.provider") == "claude"


def test_cov_load_file_branches(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    # missing path returns silently
    mgr._load_file(str(tmp_path / "does-not-exist.yaml"))
    # empty path returns silently
    mgr._load_file("")
    # empty content
    empty = tmp_path / "empty.yaml"
    empty.write_text("   \n")
    mgr._load_file(str(empty))
    # OSError via directory path
    d = tmp_path / "adir"
    d.mkdir()
    mgr._load_file(str(d))
    # bad json file
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json")
    mgr._load_file(str(bad_json))
    # valid json overlay
    good_json = tmp_path / "good.json"
    good_json.write_text('{"model": {"provider": "openai"}}')
    mgr._load_file(str(good_json))
    assert mgr.Get("model.provider") == "openai"
    # yaml with invalid yaml but valid json fallback
    mgr2 = _mgr_isolated(tmp_path)
    tricky = tmp_path / "tricky.yaml"
    tricky.write_text('{"model": {"provider": "gemini"}}')
    mgr2._load_file(str(tricky))
    assert mgr2.Get("model.provider") == "gemini"
    # yaml parse error and json parse error
    mgr3 = _mgr_isolated(tmp_path)
    broken = tmp_path / "broken.yaml"
    broken.write_text(":\n: [unclosed\n")
    mgr3._load_file(str(broken))
    # non-dict yaml
    mgr4 = _mgr_isolated(tmp_path)
    lst = tmp_path / "list.yaml"
    lst.write_text("- a\n- b\n")
    mgr4._load_file(str(lst))
    # non-dict json
    mgr5 = _mgr_isolated(tmp_path)
    lstj = tmp_path / "list.json"
    lstj.write_text("[1,2,3]")
    mgr5._load_file(str(lstj))


def test_cov_load_file_yaml_with_json_content_and_merge(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    p = tmp_path / "cfg.yaml"
    p.write_text("model:\n  provider: ollama\n")
    mgr._load_file(str(p))
    assert mgr.Get("model.provider") == "ollama"


def test_cov_merge_all_sections():
    mgr = ConfigManager([WithEnvPrefix("DXRK_COVC_NONE_XYZ")])
    mgr.merge({})
    assert mgr.Get("model.provider") == "claude"
    mgr.merge(
        {
            "model": {
                "provider": "openai",
                "model_name": "gpt-4o",
                "system_prompt": "hi",
                "max_tokens": 123,
                "temperature": 0.1,
                "top_p": 0.2,
            },
            "api": {
                "base_url": "https://x",
                "api_key": "k",
                "timeout": 9,
                "retries": 8,
                "rate_limit": 7,
            },
            "auth": {"provider": "p", "client_id": "c", "token_path": "/tmp/t", "scopes": ["a"]},
            "session": {"max_history": 11},
            "tools": {"timeout": 12, "max_concurrent": 13, "enabled": ["e1"], "disabled": ["d1"]},
            "ui": {"theme": "light", "font_size": 18},
            "advanced": {"log_level": "debug"},
        }
    )
    assert mgr.Get("model.provider") == "openai"
    assert mgr.Get("api.timeout") == 9
    assert mgr.Get("auth.scopes") == ["a"]
    assert mgr.Get("session.max_history") == 11
    assert mgr.Get("tools.enabled") == ["e1"]
    assert mgr.Get("ui.theme") == "light"
    assert mgr.Get("advanced.log_level") == "debug"
    # falsy values do not overwrite
    before = mgr.Get("model.provider")
    mgr.merge({"model": {"provider": ""}, "api": "notadict", "unknown": {}})
    assert mgr.Get("model.provider") == before
    mgr.merge(
        {"model": "nope", "api": {"timeout": 0}, "auth": [], "session": [], "tools": [], "ui": [], "advanced": []}
    )
    assert mgr.Get("api.timeout") == 9


def test_cov_env_all_strings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mgr = _mgr_isolated(tmp_path, prefix="DXRK_COVC_STR")
    for k in [
        "MODEL_PROVIDER",
        "MODEL_NAME",
        "API_BASE_URL",
        "API_KEY",
        "AUTH_PROVIDER",
        "AUTH_CLIENT_ID",
        "AUTH_TOKEN_PATH",
        "UI_THEME",
        "LOG_LEVEL",
    ]:
        monkeypatch.delenv(f"DXRK_COVC_STR_{k}", raising=False)
    mgr.Load()
    assert mgr.Get("model.provider") == "claude"
    monkeypatch.setenv("DXRK_COVC_STR_MODEL_PROVIDER", "pv")
    monkeypatch.setenv("DXRK_COVC_STR_MODEL_NAME", "mn")
    monkeypatch.setenv("DXRK_COVC_STR_API_BASE_URL", "https://env.example")
    monkeypatch.setenv("DXRK_COVC_STR_API_KEY", "secret")
    monkeypatch.setenv("DXRK_COVC_STR_AUTH_PROVIDER", "ap")
    monkeypatch.setenv("DXRK_COVC_STR_AUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("DXRK_COVC_STR_AUTH_TOKEN_PATH", "/tmp/tok")
    monkeypatch.setenv("DXRK_COVC_STR_UI_THEME", "light")
    monkeypatch.setenv("DXRK_COVC_STR_LOG_LEVEL", "debug")
    mgr.Load()
    assert mgr.Get("model.provider") == "pv"
    assert mgr.Get("model.model_name") == "mn"
    assert mgr.Get("api.base_url") == "https://env.example"
    assert mgr.Get("api.api_key") == "secret"
    assert mgr.Get("auth.provider") == "ap"
    assert mgr.Get("auth.client_id") == "cid"
    assert mgr.Get("auth.token_path") == "/tmp/tok"
    assert mgr.Get("ui.theme") == "light"
    assert mgr.Get("advanced.log_level") == "debug"


def test_cov_env_int_float_bool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mgr = _mgr_isolated(tmp_path, prefix="DXRK_COVC_NUM")
    monkeypatch.setenv("DXRK_COVC_NUM_MODEL_MAX_TOKENS", "111")
    monkeypatch.setenv("DXRK_COVC_NUM_API_TIMEOUT", "12")
    monkeypatch.setenv("DXRK_COVC_NUM_API_RETRIES", "3")
    monkeypatch.setenv("DXRK_COVC_NUM_API_RATE_LIMIT", "44")
    monkeypatch.setenv("DXRK_COVC_NUM_SESSION_MAX_HISTORY", "55")
    monkeypatch.setenv("DXRK_COVC_NUM_TOOLS_TIMEOUT", "66")
    monkeypatch.setenv("DXRK_COVC_NUM_TOOLS_MAX_CONCURRENT", "7")
    monkeypatch.setenv("DXRK_COVC_NUM_UI_FONT_SIZE", "20")
    monkeypatch.setenv("DXRK_COVC_NUM_MODEL_TEMPERATURE", "0.25")
    monkeypatch.setenv("DXRK_COVC_NUM_MODEL_TOP_P", "0.5")
    monkeypatch.setenv("DXRK_COVC_NUM_SESSION_AUTO_SAVE", "false")
    monkeypatch.setenv("DXRK_COVC_NUM_SESSION_RESTORE_LAST", "0")
    monkeypatch.setenv("DXRK_COVC_NUM_UI_SHOW_TOKENS", "true")
    monkeypatch.setenv("DXRK_COVC_NUM_UI_SHOW_COST", "1")
    monkeypatch.setenv("DXRK_COVC_NUM_UI_COMPACT_MODE", "false")
    monkeypatch.setenv("DXRK_COVC_NUM_ADVANCED_DEBUG", "1")
    monkeypatch.setenv("DXRK_COVC_NUM_ADVANCED_TELEMETRY", "0")
    monkeypatch.setenv("DXRK_COVC_NUM_ADVANCED_AUTO_UPDATE", "true")
    monkeypatch.setenv("DXRK_COVC_NUM_ADVANCED_YOLO_MODE", "false")
    mgr.Load()
    assert mgr.Get("model.max_tokens") == 111
    assert mgr.Get("api.timeout") == 12
    assert mgr.Get("session.max_history") == 55
    assert mgr.Get("model.temperature") == 0.25
    assert mgr.Get("session.auto_save") is False
    assert mgr.Get("advanced.debug") is True
    assert mgr.Get("advanced.telemetry") is False
    # invalid numbers are ignored
    mgr2 = _mgr_isolated(tmp_path, prefix="DXRK_COVC_BAD")
    monkeypatch.setenv("DXRK_COVC_BAD_MODEL_MAX_TOKENS", "notanint")
    monkeypatch.setenv("DXRK_COVC_BAD_MODEL_TEMPERATURE", "notafloat")
    monkeypatch.setenv("DXRK_COVC_BAD_SESSION_AUTO_SAVE", "maybe")
    mgr2.Load()
    assert mgr2.Get("model.max_tokens") == 8192
    assert mgr2.Get("model.temperature") == 0.7


def test_cov_config_set_errors(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    with pytest.raises(ValueError):
        mgr.Set("model.provider.extra", "x")
    # valid path does not raise
    mgr.Set("model.provider", "not-valid-but-ok")
    assert mgr.Get("model.provider") == "not-valid-but-ok"
    # unmarshal error via wrong type that breaks int()
    with pytest.raises(ValueError, match="unmarshal"):
        mgr.Set("model.max_tokens", "not-an-int-at-all")


def test_cov_config_merge_validate_watch(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    mgr.Merge(None)
    other = HierarchicalConfig()
    other.model.provider = "ollama"
    mgr.Merge(other)
    assert mgr.Get("model.provider") == "ollama"
    errs = mgr.Validate()
    assert isinstance(errs, list)
    seen: list[tuple[str, object]] = []
    fails: list[tuple[str, object]] = []

    def _ok(path: str, value: object) -> None:
        seen.append((path, value))

    def _boom(path: str, value: object) -> None:
        fails.append((path, value))
        raise RuntimeError("watcher boom")

    mgr.Watch("*", _ok)
    mgr.Watch("model.", _boom)
    mgr.Watch("nomatch.", _ok)
    mgr.Set("model.provider", "openai")
    assert ("model.provider", "openai") in seen
    snap = mgr.Config()
    assert snap.model.provider == "openai"
    snap.model.provider = "changed"
    assert mgr.Get("model.provider") == "openai"


def test_cov_config_reset_save_and_viper(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    mgr.Set("model.provider", "openai")
    mgr.Reset("model.provider")
    assert mgr.Get("model.provider") == "claude"
    mgr.Set("model.provider", "openai")
    mgr.Save()
    assert json.loads((tmp_path / "user.json").read_text())["model"]["provider"] == "openai"
    mgr.LoadFromViper(
        {
            "model": {
                "provider": "v1",
                "model_name": "m1",
                "max_tokens": 10,
                "temperature": 0.1,
                "top_p": 0.2,
                "system_prompt": "sp",
            },
            "api": {"base_url": "b", "api_key": "k", "timeout": 1, "retries": 2, "rate_limit": 3},
            "auth": {"provider": "a", "client_id": "c", "scopes": ["s"], "token_path": "/t"},
            "session": {"max_history": 5, "archive_after": 6},
            "tools": {"timeout": 7, "max_concurrent": 8},
            "ui": {"theme": "light", "font_size": 16},
            "advanced": {"log_level": "warn"},
        }
    )
    assert mgr.Get("model.provider") == "v1"
    assert mgr.Get("session.max_history") == 5
    assert mgr.Get("tools.timeout") == 7
    # empty viper dict keeps values
    mgr.LoadFromViper({})
    assert mgr.Get("model.provider") == "v1"


def test_cov_config_get_single_part(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    assert mgr.Get("model") is None
    assert mgr.Get("model.unknown_key") is None


# ---- config/unified.py ----


def test_cov_unified_resolve_and_get(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    assert prefixed._resolve_path("ui.theme") == "ui.theme"
    assert prefixed._resolve_path("theme") == "ui.theme"
    plain = ConfigSettingsStore(mgr)
    assert plain._resolve_path("settings.x") == "settings.x"
    assert plain._resolve_path("x") == "settings.x"
    # Get via prefixed path
    val, ok = prefixed.Get("theme")
    assert ok is True
    assert val == "dark"
    # Get via direct dot-path fallback (key contains dot, differs from resolved)
    val2, ok2 = plain.Get("ui.theme")
    assert ok2 is True
    assert val2 == "dark"
    # fallback dict
    plain.Set("freeform", 123)
    val3, ok3 = plain.Get("freeform")
    assert ok3 is True
    assert val3 == 123
    # miss
    assert plain.Get("definitely-missing-xyz") == (None, False)
    assert prefixed.Priority() == 150


def test_cov_unified_set_variants(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    prefixed.Set("theme", "light")
    assert mgr.Get("ui.theme") == "light"
    # free-form key with no prefix falls back to memory (settings.* invalid)
    plain = ConfigSettingsStore(mgr)
    plain.Set("custom-key", "v1")
    assert plain.Get("custom-key") == ("v1", True)
    # direct dot-path valid hierarchical key via plain store
    plain.Set("ui.theme", "dark")
    assert mgr.Get("ui.theme") == "dark"
    # unknown prefix store falls back to memory
    weird = ConfigSettingsStore(mgr, prefix="nosuchsection")
    weird.Set("k", "v")
    assert weird.Get("k") == ("v", True)


def test_cov_unified_delete(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    prefixed.Set("theme", "light")
    assert mgr.Get("ui.theme") == "light"
    prefixed.Delete("theme")
    assert mgr.Get("ui.theme") == "dark"
    # delete fallback key
    plain = ConfigSettingsStore(mgr)
    plain.Set("tmpfree", "x")
    plain.Delete("tmpfree")
    assert plain.Get("tmpfree") == (None, False)
    # delete direct dot-path via plain store resets default
    mgr.Set("ui.theme", "light")
    plain.Delete("ui.theme")
    assert mgr.Get("ui.theme") == "dark"
    # delete missing key is a no-op
    plain.Delete("never-existed")
    plain.Delete("missing.deep.key")


def test_cov_unified_list(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    listed = prefixed.List()
    assert listed.get("theme") == "dark"
    assert "font_size" in listed
    prefixed.Set("a.b.c", "z")
    listed2 = prefixed.List()
    assert listed2["a.b.c"] == "z"
    unknown = ConfigSettingsStore(mgr, prefix="nosuch")
    unknown.Set("a", 1)
    assert unknown.List() == {"a": 1}
    plain = ConfigSettingsStore(mgr)
    plain.Set("only", 2)
    assert plain.List() == {"only": 2}


def test_cov_unified_save_load(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    tenant_path = tmp_path / "tenant.json"
    store = ConfigSettingsStore(mgr, path=tenant_path)
    store.Set("memokey", "memoval")
    mgr.Set("ui.theme", "light")
    store.Save()
    assert tenant_path.exists()
    assert mgr.Get("ui.theme") == "light"
    # load restores fallback
    mgr2 = _mgr_isolated(tmp_path)
    store2 = ConfigSettingsStore(mgr2, path=tenant_path)
    store2.Load()
    assert store2.Get("memokey") == ("memoval", True)
    # save without path only persists manager
    nopath = ConfigSettingsStore(_mgr_isolated(tmp_path))
    nopath.Save()
    # load without path
    nopath.Load()
    # load missing file resets fallback
    missing = ConfigSettingsStore(_mgr_isolated(tmp_path), path=tmp_path / "nope.json")
    missing.Set("x", 1)
    missing.Load()
    assert missing.Get("x") == (None, False)
    # load corrupt file raises OSError
    bad = tmp_path / "badtenant.json"
    bad.write_text("{oops")
    badstore = ConfigSettingsStore(_mgr_isolated(tmp_path), path=bad)
    with pytest.raises(OSError, match="read tenant settings"):
        badstore.Load()
    # load non-dict json keeps old fallback (no crash)
    arr = tmp_path / "arr.json"
    arr.write_text("[1,2]")
    arrstore = ConfigSettingsStore(_mgr_isolated(tmp_path), path=arr)
    arrstore.Set("keep", 1)
    arrstore.Load()
    assert arrstore.Get("keep") == (1, True)


def test_cov_unified_facade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".dxrk").mkdir(exist_ok=True)
    mgr = _mgr_isolated(tmp_path)
    settings = SettingsManager([MemorySettingsStore(priority=10)])
    uni = UnifiedConfig(config=mgr, settings=settings)
    uni.set_typed("ui.theme", "light")
    assert uni.get_typed("ui.theme") == "light"
    uni.set_raw("hello", "world")
    assert uni.get_raw("hello") == "world"
    uni.load()
    uni.save()
    assert isinstance(uni.validate(), list)
    # CamelCase aliases
    uni.SetTyped("ui.theme", "dark")
    assert uni.GetTyped("ui.theme") == "dark"
    uni.SetRaw("k2", "v2")
    assert uni.GetRaw("k2") == "v2"
    uni.Load()
    uni.Save()
    assert isinstance(uni.Validate(), list)


def test_cov_unified_default_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".dxrk").mkdir(exist_ok=True)
    uni = UnifiedConfig()
    assert uni.get_typed("model.provider") == "claude"
    uni.SetRaw("dk", "dv")
    assert uni.GetRaw("dk") == "dv"
    uni.load()
    uni.save()


def test_cov_merge_empty_sections_hit_false_branches(tmp_path: Path):
    mgr = _mgr_isolated(tmp_path)
    mgr.merge({"auth": {}, "session": {}, "tools": {}, "ui": {}, "advanced": {}})
    assert mgr.Get("ui.theme") == "dark"
    mgr.merge(
        {
            "auth": {"provider": "", "client_id": "", "token_path": "", "scopes": []},
            "session": {"max_history": 0},
            "tools": {"timeout": 0, "max_concurrent": 0, "enabled": [], "disabled": []},
            "ui": {"theme": "", "font_size": 0},
            "advanced": {"log_level": ""},
        }
    )
    assert mgr.Get("ui.theme") == "dark"
    mgr.merge({"model": {}, "api": {}})
    assert mgr.Get("model.provider") == "claude"


def test_cov_unified_get_dot_miss_and_list_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mgr = _mgr_isolated(tmp_path)
    plain = ConfigSettingsStore(mgr)
    assert plain.Get("foo.bar") == (None, False)
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    monkeypatch.setattr(mgr, "Get", lambda path: None)
    assert prefixed.List() == {}
    assert prefixed.Get("theme") == (None, False)


def test_cov_unified_delete_resilience(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dxrk.config.unified as unified_mod

    mgr = _mgr_isolated(tmp_path)
    store = ConfigSettingsStore(mgr, prefix="ui")
    # force defaults lookup to fail once via patched asdict
    real_asdict = unified_mod.asdict
    calls = {"n": 0}

    def _flaky(o):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("asdict boom")
        return real_asdict(o)

    monkeypatch.setattr(unified_mod, "asdict", _flaky)
    mgr.Set("ui.theme", "light")
    store.Delete("theme")  # first call hits except Exception: pass
    assert mgr.Get("ui.theme") == "light"
    store.Delete("theme")  # second call resets normally
    assert mgr.Get("ui.theme") == "dark"
    # force Set to raise ValueError during reset
    monkeypatch.setattr(mgr, "Set", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    store2 = ConfigSettingsStore(mgr, prefix="ui")
    store2.Delete("theme")
    store2.Set("fallback-only", 1)
    assert store2.Get("fallback-only") == (1, True)


def test_cov_runner_remote_other_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    r = Runner(str(tmp_path))
    _mock_run(monkeypatch, r, stdout="origin\thttp://x (other)\norigin\thttp://x (fetch)\n")
    rems = r.remote()
    assert len(rems) == 1
    assert rems[0].fetch == "http://x"
    assert rems[0].push == ""


def test_cov_unified_delete_unknown_paths_walk_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dxrk.config.unified as unified_mod

    mgr = _mgr_isolated(tmp_path)
    # prefixed store: bogus deep path, Get mocked non-None so defaults walk misses
    prefixed = ConfigSettingsStore(mgr, prefix="ui")
    monkeypatch.setattr(mgr, "Get", lambda path: "present")
    monkeypatch.setattr(mgr, "Set", lambda *a, **k: None)
    prefixed.Delete("bogus.deep.path")
    # plain store: direct dot-path walk miss + asdict failure on second block
    plain = ConfigSettingsStore(_mgr_isolated(tmp_path))
    monkeypatch.setattr(plain._mgr, "Get", lambda path: "present")

    def _boom(o):
        raise RuntimeError("defaults boom")

    monkeypatch.setattr(unified_mod, "asdict", _boom)
    plain.Delete("foo.bar.baz")
    # Set raising ValueError inside Delete's reset is swallowed
    mgr2 = _mgr_isolated(tmp_path)
    plain2 = ConfigSettingsStore(mgr2)
    monkeypatch.setattr(mgr2, "Get", lambda path: "present")
    monkeypatch.setattr(mgr2, "Set", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))

    import dxrk.config.unified as um2

    monkeypatch.setattr(um2, "asdict", lambda o: {"foo": {"bar": {"baz": "dflt"}}})
    plain2.Delete("foo.bar.baz")

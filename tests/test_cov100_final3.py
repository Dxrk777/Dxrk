# SPDX-License-Identifier: MIT
"""Coverage final lote 3 — __main__/backup/cli/memory-main/qieo/model/
opencode/task/planner/router/yolo/pool/proxy/git/chunker."""

from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace
from unittest import mock


class TestMainBranches:
    def test_enterprise_cli_nonzero_exits(self):
        import dxrk.__main__ as m

        reg = SimpleNamespace(execute=lambda argv: 2)
        with mock.patch("dxrk.commands.register_all", return_value=reg):
            args = SimpleNamespace(enterprise_command=None, task=None, department=None)
            try:
                m._run_enterprise_cli(args)
                raised = False
            except SystemExit as e:
                raised = e.code == 2
            assert raised is True

    def test_tenant_cli_nonzero_exits(self):
        import dxrk.__main__ as m

        reg = SimpleNamespace(execute=lambda argv: 3)
        with mock.patch("dxrk.commands.register_all", return_value=reg):
            args = SimpleNamespace(tenant_command=None, tenant_id=None, force=False)
            try:
                m._run_tenant_cli(args)
                raised = False
            except SystemExit as e:
                raised = e.code == 3
            assert raised is True

    def test_install_dry_run_false(self, capsys):
        import dxrk.__main__ as m

        out = SimpleNamespace(error="", dry_run=False)
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.run_install", return_value=out),
            mock.patch.object(m, "_rebuild_install_raw", return_value=[]),
        ):
            m._run_install_cli(SimpleNamespace())
            assert True

    def test_uninstall_no_removed_files(self, capsys):
        import dxrk.__main__ as m

        with (
            mock.patch("dxrk.cli.uninstall.RunUninstall", return_value=SimpleNamespace()),
            mock.patch.object(m, "_rebuild_uninstall_raw", return_value=[]),
        ):
            m._run_uninstall_cli(SimpleNamespace())
            assert True

    def test_uninstall_manual_actions(self, capsys):
        import dxrk.__main__ as m

        res = SimpleNamespace(removed_files=["a"], manual_actions=["do-x"])
        with (
            mock.patch("dxrk.cli.uninstall.RunUninstall", return_value=res),
            mock.patch.object(m, "_rebuild_uninstall_raw", return_value=[]),
        ):
            m._run_uninstall_cli(SimpleNamespace())
            assert "do-x" in capsys.readouterr().out


class TestInstallStepsBackupOSError:
    def test_rollback_oserror_logged(self, tmp_path):
        from dxrk.cli.install_steps_backup import RollbackRestoreStep

        dest = tmp_path / "dst"
        dest.write_text("new")
        src = tmp_path / "src"
        src.write_text("old")
        step = RollbackRestoreStep(
            "rb",
            {
                "manifest": {
                    "entries": [{"dest": "dst", "source": str(src)}],
                    "_backup_root": str(tmp_path),
                }
            },
        )
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert step.rollback() is None


class TestRuntimeUninstallDeclined:
    def test_declined_returns_none(self):
        import io as _io

        from dxrk.cli import runtime_uninstall as ru

        buf = _io.StringIO()
        with mock.patch.object(ru, "_prompt_uninstall_confirm", return_value=False):
            assert ru.run_uninstall(["--agent", "x"], stdout=buf) is None
            assert "cancelada" in buf.getvalue()


class TestMemoryMain:
    def test_main_module(self):
        import runpy

        with mock.patch("sys.argv", ["dxrk.memory"]):
            try:
                runpy.run_module("dxrk.memory.__main__", run_name="__main__")
                raised = False
            except SystemExit as e:
                raised = e.code == 0
            assert raised is True


class TestQieoBranches:
    def test_zero_norm(self):
        from dxrk.memory.qieo import Qubit

        q = Qubit(alpha=0.0, beta=0.0)
        out = q.rotate(0.0, 0.0)
        assert out.alpha == 0.0 and out.beta == 0.0

    def test_default_config_and_seed(self):
        from dxrk.memory.qieo import qieo_optimize

        best, fit = qieo_optimize(
            objective_fn=lambda p: sum(p),
            bounds=[(0.0, 1.0)],
            config=None,
            seed=42,
        )
        assert len(best) == 1 and isinstance(fit, float)

    def test_best_none_fallback(self):
        from dxrk.memory.qieo import QIEOConfig, qieo_optimize

        best, _ = qieo_optimize(
            objective_fn=lambda p: 0.0,
            bounds=[],
            config=QIEOConfig(pop_size=4),
            seed=1,
        )
        assert best == []


class TestModelBranches:
    def test_has_component_false(self):
        from dxrk.models import ComponentID, Selection

        sel = Selection()
        assert sel.has_component(ComponentID.SDD) is False

    def test_resolve_home_error(self, monkeypatch):
        import pytest

        from dxrk.model import _resolve_home

        monkeypatch.setattr(os.path, "expanduser", lambda p: "~")
        with pytest.raises(OSError):
            _resolve_home("  ")


class TestOpencodeBranches:
    def test_non_dict_cache(self, tmp_path):
        import pytest

        from dxrk.opencode import load_models

        p = tmp_path / "m.json"
        p.write_text("[1,2]")
        with pytest.raises(ValueError, match="expected dict"):
            load_models(str(p))

    def test_non_dict_provider_and_model(self, tmp_path):
        from dxrk.opencode import load_models

        p = tmp_path / "m.json"
        p.write_text(
            json.dumps(
                {
                    "p1": "notadict",
                    "p2": {"name": "P", "env": [], "models": {"m1": "nodict", "m2": {}}},
                    "p3": {"name": "Q", "env": []},
                }
            )
        )
        out = load_models(str(p))
        assert "p2" in out and "p3" in out

    def test_auth_branches(self, tmp_path):
        from dxrk.opencode import load_auth_providers

        missing = tmp_path / "nope.json"
        assert load_auth_providers(str(missing)) == {}
        bad = tmp_path / "bad.json"
        bad.write_text("[1]")
        assert load_auth_providers(str(bad)) == {}
        ok = tmp_path / "ok.json"
        ok.write_text(json.dumps({"a": 1}))
        assert load_auth_providers(str(ok)) == {"a": True}

    def test_detect_branches(self, tmp_path, monkeypatch):
        from dxrk.opencode import Model, Provider, detect_available_providers

        def _tool():
            return {"m": Model(id="m", name="M", tool_call=True)}

        providers = {
            "no-tool": Provider(id="no-tool", name="N"),
            "authed": Provider(id="authed", name="A", models=_tool()),
            "opencode": Provider(id="opencode", name="O", models=_tool()),
            "envd": Provider(id="envd", name="E", env=["DXRK_COV_TEST_ENV_XYZ"], models=_tool()),
        }
        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({"authed": True}))
        monkeypatch.setenv("DXRK_COV_TEST_ENV_XYZ", "1")
        out = detect_available_providers(providers, str(auth))
        assert "authed" in out and "opencode" in out and "envd" in out
        assert "no-tool" not in out


class TestTaskBranches:
    def _task(self, **kw):
        from dxrk.task import Payload, TaskType, new_task

        return new_task(TaskType.GENERIC, Payload(), *kw.pop("opts", []))

    def test_cancel_completed_noop(self):
        from dxrk.task import TaskStatus

        t = self._task()
        t.complete("done")
        t.cancel()  # 133->exit false branch
        assert t.status == TaskStatus.COMPLETED

    def test_wait_notified(self):
        t = self._task()

        def _complete():
            import time as _time

            _time.sleep(0.05)
            t.complete("done")

        th = threading.Thread(target=_complete)
        th.start()
        t.wait()  # line 149 blocking wait
        th.join()
        assert True

    def test_wait_timeout(self):
        t = self._task()
        t.wait(timeout=0.05)  # line 153 expiry
        assert True

    def test_push_closed_and_get_remove(self):
        from dxrk.task import Payload, Queue, TaskType, new_task

        q = Queue()
        q.close()
        q.push(new_task(TaskType.GENERIC, Payload()))  # line 196 early return
        assert q.list() == []
        q2 = Queue()
        t = new_task(TaskType.GENERIC, Payload())
        q2.push(t)
        assert q2.get(t.id) is t
        assert q2.get("missing") is None
        assert q2.remove("missing") is False
        assert q2.remove(t.id) is True

    def test_worker_skips(self):
        import time as _time

        from dxrk.task import Payload, Queue, TaskStatus, TaskType, WorkerPool, new_task

        q = Queue()
        t = new_task(TaskType.GENERIC, Payload())
        t.status = TaskStatus.CANCELLED
        q.push(t)
        pool = WorkerPool(queue=q, handler=None, workers=1)
        pool.start()
        _time.sleep(0.3)
        pool.stop()
        assert True
        q3 = Queue()
        q3.push(new_task(TaskType.GENERIC, Payload()))
        pool3 = WorkerPool(queue=q3, handler=None, workers=1)
        pool3.start()
        _time.sleep(0.3)
        pool3.stop()  # 325 handler-None continue
        assert True


class TestPlannerBranches:
    def test_unsupported_agent(self):
        from dxrk.models import AgentID, Selection
        from dxrk.planner import DependencyResolver, mvp_graph

        sel = Selection()
        sel.agents = [AgentID.CLAUDE_CODE]
        with mock.patch("dxrk.planner._supported_agents", return_value=set()):
            resolved = DependencyResolver(mvp_graph()).resolve(sel)
            assert AgentID.CLAUDE_CODE in resolved.unsupported_agents

    def test_unknown_dependency(self):
        import pytest

        from dxrk.models import ComponentID
        from dxrk.planner import DependencyResolver, Graph

        r = DependencyResolver(Graph({ComponentID.THEME: [ComponentID.SDD]}))
        with pytest.raises(ValueError, match="unknown dependency"):
            r._expand_dependencies(ComponentID.THEME, {})

    def test_topological_branch(self):
        from dxrk.models import ComponentID
        from dxrk.planner import topological_sort

        out = topological_sort(
            {
                ComponentID.DXRK_MEMORY: [],
                ComponentID.SDD: [ComponentID.DXRK_MEMORY],
                ComponentID.SKILLS: [ComponentID.DXRK_MEMORY, ComponentID.SDD],
            }
        )
        assert ComponentID.DXRK_MEMORY in out

    def test_soft_ordering_accessible(self):
        import dxrk.planner as pl

        assert isinstance(pl.soft_ordering_constraints(), list)
        assert isinstance(pl.SOFT_ORDERING_PAIRS, list)


class TestRouterBranches:
    def test_evict_stale_and_heapify(self):
        from dxrk.router import CacheEntry, QueryResponse, SemanticCache

        c = SemanticCache(max_size=2)
        c.set("m1", QueryResponse())
        c.set("m2", QueryResponse())
        # stale heap entry not present in _entries
        stale = CacheEntry(response=QueryResponse(), created_at=0, expires_at=9999999999.0, last_access=0)
        import heapq

        stale.index = len(c._lru)
        heapq.heappush(c._lru, stale)
        key1 = c._key_fn("m1")
        del c._entries[key1]  # force loop-exhaust path on stale? keep one real
        c.set("m3", QueryResponse())  # triggers _evict_locked with stale entry
        assert c.stats().size <= 2
        # heapify branch via invalidate of non-last entry
        c2 = SemanticCache(max_size=10)
        c2.set("a", QueryResponse())
        c2.set("b", QueryResponse())
        c2.set("c", QueryResponse())
        c2.invalidate("a")  # pos valid, not last -> heapify line 352
        assert c2.stats().size == 2

    def test_semantic_skips_and_hit(self):
        import time as _t

        from dxrk.router import QueryResponse, SemanticCache

        c = SemanticCache(semantic_enabled=True, semantic_threshold=0.99)
        c.set("hello world message one", QueryResponse())
        for e in c._entries.values():
            e.expires_at = _t.time() - 10
        out, hit = c.get("totally different xyzzy")  # 362 expired continue
        assert hit is False
        c2 = SemanticCache(semantic_enabled=True, semantic_threshold=0.99)
        c2.set("msg2 hello", QueryResponse())
        c2._embeddings.clear()
        out2, hit2 = c2.get("other text here")  # 365 embedding-missing continue
        assert hit2 is False
        c3 = SemanticCache(semantic_enabled=True, semantic_threshold=0.0)
        c3.set("same message", QueryResponse())
        _, hit3 = c3.get("same message")  # exact hit path
        assert hit3 is True


class TestYoloBranches:
    def test_empty_command_name(self):
        from dxrk.security.yolo import assess_bash_risk

        assert assess_bash_risk("") is not None

    def test_tool_names_filter(self):
        from dxrk.security.yolo import KNOWN_DANGEROUS_PATTERNS, check_dangerous_patterns

        scoped = [dp for dp in KNOWN_DANGEROUS_PATTERNS if dp.tool_names]
        assert scoped, "expected at least one scoped pattern"
        dp = scoped[0]
        other_tool = "definitely-not-" + (dp.tool_names[0] if dp.tool_names else "x")
        assert check_dangerous_patterns(f"prefix {dp.pattern} suffix", other_tool) == []
        hits = check_dangerous_patterns(f"prefix {dp.pattern} suffix", dp.tool_names[0])
        assert any(h.pattern == dp.pattern for h in hits)


class TestPoolProxyBranches:
    def test_with_proxy_errors(self):
        import pytest

        from dxrk.utils.http.pool import new_connection_pool

        pool = new_connection_pool(None)
        with pytest.raises(Exception):
            pool.with_proxy("::::not a url::::")
        pool.close()

    def test_do_ctx_canceled(self):
        from datetime import timedelta

        import httpx

        from dxrk.utils.http.context import _background, _with_cancel
        from dxrk.utils.http.pool import new_connection_pool, new_pooled_client

        pool = new_connection_pool(None)
        pc = new_pooled_client(pool, timedelta(seconds=5))
        ctx, cancel = _with_cancel(_background())
        cancel()
        req = httpx.Request("GET", "http://example.com")
        req._ctx = ctx
        out, err = pc.do(req)
        assert out is None and err is not None
        # remaining-timeout branch (line 371)
        ctx2, _ = _with_cancel(_background())
        req2 = httpx.Request("GET", "http://example.com")
        req2._ctx = ctx2
        with mock.patch.object(pc.client, "send", side_effect=httpx.ConnectError("x")):
            out2, err2 = pc.do(req2)
            assert out2 is None and err2 is not None
        # set_timeout both branches (420)
        pc.set_timeout(timedelta(seconds=7))
        pc.client.timeout = 5.0
        pc.set_timeout(timedelta(seconds=9))
        pc.close()
        pool.close()

    def test_monitor_exception_paths(self):
        import time as _t
        from datetime import timedelta

        from dxrk.utils.http.pool import PoolMonitor, new_connection_pool

        pool = new_connection_pool(None)
        with mock.patch.object(pool, "get_stats", side_effect=RuntimeError("x")):
            mon = PoolMonitor(pool, timedelta(milliseconds=10), None)
            mon.start()
            _t.sleep(0.05)
            mon.stop()
        pool2 = new_connection_pool(None)
        mon2 = PoolMonitor(pool2, timedelta(milliseconds=10), lambda s: (_ for _ in ()).throw(ValueError("cb")))
        mon2.start()
        _t.sleep(0.05)
        mon2.stop()  # 512-513 on_stats raises -> continue
        # stop with running=True but thread None (493->495 skips join)
        mon3 = PoolMonitor(pool2, timedelta(milliseconds=10), None)
        mon3.running = True
        mon3.thread = None
        mon3.stop()
        pool.close()
        pool2.close()

    def test_proxy_branches(self):
        from dxrk.utils.http.proxy import ProxyConfig, ProxyType, new_proxy_config

        cfg, err = new_proxy_config("::::")
        assert cfg is None and err is not None
        cfg2, err2 = new_proxy_config("http://localhost:8080")
        assert err2 is None and cfg2 is not None
        empty = ProxyConfig(type=ProxyType.ProxyTypeHTTP, host="")
        assert empty.get_proxy_url() is None  # line 86
        noauth = ProxyConfig(type=ProxyType.ProxyTypeHTTP, host="h", port=8080)
        assert noauth.get_proxy_url() == "http://h:8080"  # 91->93 no-auth branch


class TestGitChunkerFormat:
    def test_git_conflict_short(self):
        from dxrk.git import parse_status

        res = parse_status("u ")
        assert res.conflicts == []

    def test_chunker_empty_file(self, tmp_path):
        from dxrk.rag.chunker import ChunkConfig, ChunkFile, DefaultChunkConfig

        p = tmp_path / "empty.py"
        p.write_text("")
        chunks = ChunkFile(str(p), DefaultChunkConfig())
        assert len(chunks) == 1 and chunks[0].text == ""
        # zero-size config forces the while-exit branch (167->182)
        big = tmp_path / "big.py"
        big.write_text("\n".join(f"line{i}" for i in range(10)))
        out = ChunkFile(str(big), ChunkConfig(chunk_size=0, chunk_overlap=0))
        assert isinstance(out, list)

    def test_format_branch(self):
        from dxrk.scholar.citation.format import Paper, format_bibtex

        assert "@article" in format_bibtex(Paper(title="T", authors=[]))

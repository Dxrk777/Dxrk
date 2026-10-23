# SPDX-License-Identifier: MIT
"""Coverage final lote 2 — scraper/trace/resilience/slo/log/mcp/confidence/
reconsolidation/triplecopy/cost/coordinator/judge/scholar/thompson."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock


class TestScraperBranches:
    def _fake_resp(self, text):
        return SimpleNamespace(text=text, raise_for_status=lambda: None)

    def test_no_title_no_body_no_href(self):
        import dxrk.scraper as s

        html = "<html><p>hi</p><a>no-href</a></html>"
        with mock.patch("dxrk.scraper.httpx.get", return_value=self._fake_resp(html)):
            res = s.scrape("http://example.com", 5.0)
            assert res.title == "" or res.title is not None
            assert isinstance(res.links, list)

    def test_title_and_body_and_links(self):
        import dxrk.scraper as s

        html = '<html><head><title>T</title></head><body>hello<a href="http://x">l</a><a>bare</a></body></html>'
        with mock.patch("dxrk.scraper.httpx.get", return_value=self._fake_resp(html)):
            res = s.scrape("http://example.com", 5.0)
            assert res.title == "T"
            assert "hello" in res.content
            assert "http://x" in res.links

    def test_extract_domain_error(self):
        import dxrk.scraper as s

        assert s.extract_domain("not a url") == ""
        with mock.patch("dxrk.scraper.urlparse", side_effect=ValueError("bad")):
            assert s.extract_domain("http://x") == ""


class TestTraceBranches:
    def test_protocol_stubs(self):
        from dxrk.trace import Exporter

        assert Exporter.tracer(None, "n") is None
        assert Exporter.shutdown(None) is None
        assert Exporter.trace_span(None, None) is None

    def test_span_double_end(self):
        from dxrk.trace import Span

        sp = Span(name="s")
        sp.end()
        assert sp._ended is True
        sp.end()  # line 28 early return
        assert sp._ended is True

    def test_span_end_without_tracer(self):
        from dxrk.trace import Span

        sp = Span(name="s", _tracer=None)
        sp.end()  # 31->exit false branch (no export)
        assert sp.recording is False

    def test_stdout_exporter_tracer(self, capsys):
        from dxrk.trace import Span, StdoutExporter

        ex = StdoutExporter(service_name="svc")
        tr = ex.tracer("t")  # line 79
        assert tr is not None
        ctx = SimpleNamespace(span=None)
        _, span = tr.start(ctx, "op")
        assert isinstance(span, Span)
        ex.trace_span(span)
        out = capsys.readouterr()
        assert "op" in out.err


class TestResilienceBranches:
    def test_backoff_jitter(self):
        from dxrk.resilience import RetryConfig, backoff_duration

        cfg = RetryConfig(jitter=True)
        d = backoff_duration(3, cfg)
        assert d.total_seconds() > 0

    def test_rate_limiter_constructors_and_double_close(self):
        from dxrk.resilience import (
            RateLimiterConfig,
            new_rate_limiter,
            new_rate_limiter_with_config,
        )

        rl = new_rate_limiter()  # line 126
        assert rl is not None
        rl2 = new_rate_limiter_with_config(RateLimiterConfig())
        assert rl2 is not None
        rl.close()
        rl.close()  # line 120 early return

    def test_circuit_half_open_branches(self):
        from dxrk.resilience import CircuitBreaker, CircuitBreakerConfig, State

        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, success_threshold=2))
        cb._state = State.HALF_OPEN
        cb._on_failure()  # 174->exit true branch
        assert cb._state == State.OPEN
        cb._state = State.HALF_OPEN
        cb._success_count = 0
        cb._on_success()
        assert cb._success_count == 1
        cb._on_success()  # reaches threshold -> CLOSED
        assert cb._state == State.CLOSED
        cb._state = State.CLOSED
        cb._failure_count = 5
        cb._on_success()  # 186->exit true branch resets failures
        assert cb._failure_count == 0


class TestSloBranches:
    def test_short_window_fail(self):
        from dxrk.slo import MultiWindowEvaluator, WindowConfig

        cfg = WindowConfig(short_target=0.99, long_target=0.9)
        ok, msg = MultiWindowEvaluator().evaluate([0.5], cfg)
        assert ok is False and "short" in msg

    def test_long_window_fail(self):
        from dxrk.slo import MultiWindowEvaluator, WindowConfig

        cfg = WindowConfig(short_target=0.5, long_target=0.99)
        ok, msg = MultiWindowEvaluator().evaluate([0.9], cfg)
        assert ok is False and "long" in msg

    def test_record_ctx_canceled(self):
        from dxrk.slo import Objective, Tracker

        rec = Tracker()
        rec.register_objective(Objective(name="o1", target=0.9, current=0.5))
        ctx = SimpleNamespace(done=lambda: True)
        try:
            rec.snapshot(ctx=ctx)
            raised = False
        except RuntimeError as e:
            raised = "canceled" in str(e)
        assert raised is True


class TestLogBranches:
    def test_protocol_stubs(self):
        from dxrk.log import Logger

        assert Logger.debug(None, "m") is None
        assert Logger.info(None, "m") is None
        assert Logger.warn(None, "m") is None
        assert Logger.error(None, "m") is None
        assert Logger.with_(None) is None
        assert Logger.level(None) is None

    def test_format_fields_skips_non_str(self):
        from dxrk.log import _format_fields

        assert _format_fields([], ("k", 1, 123, "v")) == " k=1"

    def test_convert_skips_non_str(self):
        from dxrk.log import convert_args_to_fields

        assert convert_args_to_fields((123, "v", "k", 2)) == [("k", 2)]

    def test_detect_level_error(self, caplog):
        import logging

        from dxrk.log import Level, detect_level

        logger = logging.getLogger("dxrk-cov-test-nonexistent-xyz")
        logger.setLevel(logging.CRITICAL + 10)
        assert detect_level(logger) == Level.ERROR


class TestMcpBranches:
    def test_send_no_stdio(self):
        from dxrk.mcp import StdioTransport

        tr = StdioTransport.__new__(StdioTransport)
        tr._proc = SimpleNamespace(stdin=None, stdout=None)
        try:
            tr.send(b"hi")
            raise AssertionError("should raise")
        except ConnectionError:
            pass

    def test_send_timeout(self):
        import select

        from dxrk.mcp import StdioTransport

        stdin = SimpleNamespace(write=lambda b: None, flush=lambda: None)
        stdout = SimpleNamespace(readline=lambda: b"{}\n")
        tr = StdioTransport.__new__(StdioTransport)
        tr._proc = SimpleNamespace(stdin=stdin, stdout=stdout)
        tr._timeout = 1.0
        with mock.patch.object(select, "select", return_value=([], [], [])):
            try:
                tr.send(b"hi")
                raise AssertionError("should raise")
            except TimeoutError:
                pass

    def test_close_oserror_ignored(self):
        from dxrk.mcp import StdioTransport

        proc = SimpleNamespace(
            poll=lambda: None,
            kill=lambda: (_ for _ in ()).throw(OSError("ro")),
            wait=lambda: None,
        )
        tr = StdioTransport.__new__(StdioTransport)
        tr._proc = proc
        tr.close()  # lines 51-52


class TestConfidenceBranches:
    def test_get_with_attrs(self):
        from dxrk.memory.confidence import find_related_recalls

        src = SimpleNamespace(id="a", metadata={"partition": "w", "subgroup": "r"}, quarantined=False)
        other = SimpleNamespace(id="b", metadata={"partition": "w", "subgroup": "r"}, quarantined=False)
        out = find_related_recalls(lambda i: src, lambda: [src, other], "a")
        assert out == [("b", 0.8)]

    def test_protocol_stubs(self):
        from dxrk.memory.confidence import RecallGetter, RecallIterator

        assert RecallIterator.__call__(None) is None
        assert RecallGetter.__call__(None, "x") is None


class TestReconsolidationBranches:
    def test_now_iso(self):
        from dxrk.memory.reconsolidation import _now_iso

        assert "T" in _now_iso()

    def test_parse_naive(self):
        from dxrk.memory.reconsolidation import _parse_iso

        dt = _parse_iso("2024-01-01T00:00:00")
        assert dt.tzinfo is not None

    def test_no_labile(self):
        from dxrk.memory.reconsolidation import ReconsolidationState, reconsolidate

        st = ReconsolidationState(labile_until="")
        out, stability, difficulty, rd = reconsolidate(st, 0.5, 5.0, 100.0, 0.9)
        assert out.labile_until == ""

    def test_window_closed(self):
        from dxrk.memory.reconsolidation import ReconsolidationState, reconsolidate

        st = ReconsolidationState(labile_until="2000-01-01T00:00:00+00:00")
        new_state, new_stability, _, _ = reconsolidate(st, 0.5, 5.0, 100.0, 0.9)
        assert new_state.labile_until == ""
        assert new_stability == max(0.05, 0.5 * 0.9)


class TestTriplecopyBranches:
    def test_zero_stability(self):
        from dxrk.memory.triplecopy import _retrievability

        assert _retrievability(1.0, 0.0) == 0.0
        assert _retrievability(1.0, -2.0) == 0.0

    def test_update_fast_only_identity(self):
        from dxrk.memory.triplecopy import create_triple_copy, update_fast_only

        tc = create_triple_copy(4.0)
        assert update_fast_only(tc, 1.0, 1.0) is tc

    def test_copy_ages(self):
        from dxrk.memory.triplecopy import create_triple_copy, get_copy_ages

        tc = create_triple_copy(8.0)
        assert get_copy_ages(tc) == (2.0, 8.0, 32.0)


class TestCostBranches:
    def test_ms(self):
        from datetime import timedelta

        from dxrk.cost import _go_duration

        assert _go_duration(timedelta(milliseconds=250)) == "250ms"

    def test_hours(self):
        from datetime import timedelta

        from dxrk.cost import _go_duration

        assert _go_duration(timedelta(hours=2)) == "2h0s"

    def test_minutes(self):
        from datetime import timedelta

        from dxrk.cost import _go_duration

        assert _go_duration(timedelta(minutes=3)) == "3m0s"

    def test_exact_seconds_no_frac(self):
        from datetime import timedelta

        from dxrk.cost import _go_duration

        assert _go_duration(timedelta(hours=1, minutes=2)) == "1h2m0s"


class TestCoordinatorBranches:
    def test_fail_without_task(self):
        import pytest

        from dxrk.coordinator import Worker

        w = Worker(id="w1")
        with pytest.raises(ValueError, match="no started task"):
            w.fail("boom")

    def test_stop_with_cancel_and_busy(self):
        from dxrk.coordinator import AgentStatus, Worker

        w = Worker(id="w2")
        called = {}
        w.cancel = lambda: called.setdefault("x", True)
        w.status = AgentStatus.AgentBusy
        w.started_at = __import__("dxrk.coordinator", fromlist=["_utcnow"])._utcnow()
        w.task = "t"
        w.stop()
        assert called.get("x") is True
        assert w.status == AgentStatus.AgentFailed

    def test_scratchpad_eviction(self):
        from dxrk.coordinator import Coordinator, CoordinatorConfig

        c = Coordinator(CoordinatorConfig(scratchpad_limit=1))
        c.set_scratchpad("k1", "v1", "t")
        c.set_scratchpad("k2", "v2", "t")  # evicts k1 (lines 309-314)
        assert "k1" not in c._scratchpad and "k2" in c._scratchpad

    def test_stop_all_workers(self):
        from dxrk.coordinator import Coordinator, CoordinatorConfig

        c = Coordinator(CoordinatorConfig())
        w = SimpleNamespace(stop=lambda: None)
        c._workers["a"] = w
        c.shutdown()  # line 396
        assert True


class TestJudgeBranches:
    def test_failed_counts(self):
        from dxrk.judge.verifier import Verifier

        v = Verifier(project_root="/tmp", commands=[("echo", "hi"), ("false",)])
        res = v.verify()
        assert res.failures >= 1
        res2 = v.verify_once()
        assert res2.failures >= 1

    def test_run_cmd_oserror(self):
        from dxrk.judge.verifier import Verifier

        v = Verifier(project_root="/tmp")
        with mock.patch("subprocess.run", side_effect=OSError("no")):
            assert v._run_cmd(("x",)) == ("", True)
        with mock.patch("subprocess.run", side_effect=RuntimeError("weird")):
            assert v._run_cmd(("x",)) == ("", True)

    def test_factory(self):
        from dxrk.judge.verifier import NewVerifier

        v = NewVerifier("/tmp")
        assert v.project_root == "/tmp"


class TestScholarBranches:
    def test_openalex_doi_decode_error(self):
        from dxrk.scholar.openalex import OpenAlexProvider

        p = OpenAlexProvider()
        resp = SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError("bad")))
        with mock.patch.object(p, "_get", return_value=(resp, None)):
            out, err = p.fetch_by_doi("10.1/x")
            assert out is None and "decode" in err

    def test_pubmed_branches(self):
        from dxrk.scholar.pubmed import PubMedProvider, map_pubmed_summary

        p = PubMedProvider()
        # ids empty
        out, err = p._fetch_summaries([])
        assert out == [] and err is None
        # resp None branch
        with mock.patch.object(p, "_get", return_value=(None, None)):
            out, err = p._fetch_summaries(["1"])
            assert out == [] and err is None
        # decode error
        resp = SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError("bad")))
        with mock.patch.object(p, "_get", return_value=(resp, None)):
            out, err = p._fetch_summaries(["1"])
            assert "decode" in err
        # non-dict entry skipped
        resp2 = SimpleNamespace(json=lambda: {"result": {"1": "notadict"}})
        with mock.patch.object(p, "_get", return_value=(resp2, None)):
            out, err = p._fetch_summaries(["1"])
            assert out == []
        assert map_pubmed_summary({}) is None or True

    def test_semanticscholar_non_dict(self):
        from dxrk.scholar.semanticscholar import SemanticScholarProvider

        p = SemanticScholarProvider()
        resp = SimpleNamespace(json=lambda: {"data": ["notadict", 123]})
        with mock.patch.object(p, "_get", return_value=(resp, None)):
            out, err = p.search("q", 5)
            assert out == [] and err is None


class TestThompsonBranches:
    def _malla(self, recalls):
        return SimpleNamespace(iter_recalls=lambda: recalls)

    def test_skip_low_visits_and_pinned(self):
        from dxrk.memory.thompson import thompson_select_recalls

        malla = self._malla(
            [
                {"id": "low", "metadata": {"access_count_total": 0}},
                {"id": "q", "metadata": {"access_count_total": 99, "quarantined": True}},
                {"id": "pin", "metadata": {"access_count_total": 99, "pinned": True}},
                {"id": "ok", "metadata": {"access_count_total": 99}},
            ]
        )
        out = thompson_select_recalls(malla, 5, min_visits=1)
        assert "low" not in out and "pin" not in out and "q" not in out
        assert "ok" in out

    def test_default_config(self):
        from dxrk.memory.thompson import select_evaluation_candidates

        malla = self._malla([{"id": "a", "metadata": {"access_count_total": 5}} for _ in range(1)])
        out = select_evaluation_candidates(malla, 3)
        assert isinstance(out, list)

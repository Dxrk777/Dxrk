# SPDX-License-Identifier: MIT
"""Pytest smoke for benchmarks — stdlib fallback if pytest-benchmark missing.

- Without pytest-benchmark: runs quick stdlib benches and asserts thresholds.
- With pytest-benchmark: also runs micro-benchmarks via `benchmark` fixture
  (select with `pytest --benchmark-only`).

Collection always succeeds (no hard dep). Ensures
`uv run python -m pytest benchmarks/ -q` passes in CI without bench group.
"""

from __future__ import annotations

import sys
import time

import pytest


def _has_benchmark_fixture(request: pytest.FixtureRequest) -> bool:
    return "benchmark" in request.fixturenames


# ---------------------------------------------------------------------------
# Stdlib smoke — always runs (quick, ~2s total)
# ---------------------------------------------------------------------------


def test_bench_memory_quick_smoke() -> None:
    """Quick smoke: bench_memory suite with tiny corpus runs and sane p50."""
    from benchmarks.bench_memory import run_suite

    cases = run_suite(quick=True, runs=10, corpus_sizes=[100])
    assert cases, "bench_memory quick produced no cases"
    # find search case
    search_cases = [c for c in cases if c.name.startswith("search")]
    assert search_cases, "no search case"
    for c in search_cases:
        # p50 should be finite and < 500 ms even on slow CI
        assert 0 < c.stats["p50_ms"] < 500, f"search p50 out of range: {c.stats}"
        assert c.throughput is None or c.throughput > 0


def test_bench_http_quick_smoke() -> None:
    """Quick smoke: bench_http suite runs and throughputs > 0."""
    from benchmarks.bench_http import run_suite

    cases = run_suite(quick=True, runs=200)
    assert cases, "bench_http quick produced no cases"
    for c in cases:
        assert c.runs > 0
        assert c.stats["p50_ms"] >= 0
        assert c.throughput > 0, f"{c.name} throughput 0"


def test_bench_memory_dialect_and_graph_smoke() -> None:
    """Dialect + graph traverse benches in quick mode."""
    from benchmarks.bench_memory import _bench_dialect_compress, _bench_graph_traverse

    d_times = _bench_dialect_compress(n_docs=50)
    assert len(d_times) == 50
    assert all(t >= 0 for t in d_times)

    g_times = _bench_graph_traverse(n_triples=20)
    assert len(g_times) == 50
    assert all(t >= 0 for t in g_times)


def test_bench_memory_layers_smoke() -> None:
    """Layers wake_up smoke."""
    from benchmarks.bench_memory import _bench_layers_wake_up

    times = _bench_layers_wake_up(n_drawers=10)
    assert len(times) == 20
    assert all(t >= 0 for t in times)


# ---------------------------------------------------------------------------
# Optional pytest-benchmark micro-benchmarks (only when plugin present)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.version_info < (3, 13), reason="requires python 3.13")
def test_bench_search_with_pytest_benchmark(request: pytest.FixtureRequest) -> None:
    """If pytest-benchmark installed, exercise `benchmark` fixture on a tiny search."""
    if not _has_benchmark_fixture(request):
        pytest.skip("pytest-benchmark not installed — stdlib fallback active")
    benchmark = request.getfixturevalue("benchmark")  # type: ignore[no-untyped-call]

    import tempfile

    from benchmarks.bench_memory import QUERY_SET, _build_corpus

    with tempfile.TemporaryDirectory() as td:
        pal = _build_corpus(td, 100)
        # benchmark pedantic: run search 5×, each is one benchmark iteration
        result = benchmark(lambda: pal.search(QUERY_SET[0], n_results=5))
        assert result is not None
        pal.close()


@pytest.mark.skipif(sys.version_info < (3, 13), reason="requires python 3.13")
def test_bench_proxy_parse_with_pytest_benchmark(request: pytest.FixtureRequest) -> None:
    if not _has_benchmark_fixture(request):
        pytest.skip("pytest-benchmark not installed — stdlib fallback active")
    benchmark = request.getfixturevalue("benchmark")  # type: ignore[no-untyped-call]

    from dxrk.utils.http import NewProxyConfig

    def _parse() -> None:
        cfg, _ = NewProxyConfig("http://proxy.example.com:8080")
        _ = cfg

    benchmark(_parse)


def test_bench_fallback_timeit_equivalent() -> None:
    """Stdlib timeit fallback path — assert it measures >0 without benchmark fixture."""
    import timeit

    stmt = "SanitizeBody(b'password=secret&token=abc')"
    setup = "from dxrk.utils.http import SanitizeBody"
    t = timeit.timeit(stmt, setup=setup, number=100)
    assert t > 0
    # sanity: perf_counter based fallback similar magnitude
    t0 = time.perf_counter()
    from dxrk.utils.http import SanitizeBody as _SB

    for _ in range(100):
        _SB(b"password=secret&token=abc")
    elapsed = time.perf_counter() - t0
    assert elapsed > 0

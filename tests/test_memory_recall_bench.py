# SPDX-License-Identifier: MIT
"""Smoke + regression net for the public recall benchmark.

Pins ``benchmarks/bench_recall.py``: the corpus builds intact (60 drawers,
no dedupe collapse), every metric lands in [0, 1], and the published
ordering holds (hybrid P@1 >= each ablation — the numbers in
docs/benchmarks.md are measured from this code path).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from benchmarks.bench_recall import CORPUS, QUERIES, build_palace, measure


def test_recall_corpus_builds_intact() -> None:
    expected = sum(len(v) for v in CORPUS.values())
    assert expected >= 50
    with tempfile.TemporaryDirectory() as td:
        dm = build_palace(str(Path(td) / "palace"))
        try:
            assert dm.count() == expected
        finally:
            dm.close()


def test_recall_metrics_measured_and_ordered() -> None:
    rows, _ = measure(reps=1)
    assert [r.method for r in rows] == ["hybrid", "bm25-only", "vector-only"]
    for r in rows:
        assert r.n_queries == len(QUERIES) == 24
        for v in (r.p_at_1, r.p_at_3, r.p_at_5, r.recall_at_5):
            assert 0.0 <= v <= 1.0
        assert r.mean_latency_ms > 0
    by = {r.method: r for r in rows}
    assert by["hybrid"].p_at_1 >= by["bm25-only"].p_at_1
    assert by["hybrid"].p_at_1 >= by["vector-only"].p_at_1
    assert by["hybrid"].recall_at_5 >= by["bm25-only"].recall_at_5

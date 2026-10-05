# SPDX-License-Identifier: MIT
"""Eval Harness tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
import uuid

from dxrk.memory.eval_harness import (
    EvalQuery,
    EvalResult,
    EvalReport,
    load_eval_dataset,
    save_eval_dataset,
    generate_synthetic_queries,
    recall_at_k,
    mrr_score,
    ndcg_score,
    evaluate_query,
    evaluate_dataset,
    aggregate_results,
    compute_ece,
    EvalHarness,
)


class TestEvalHarness:
    def test_recall_at_k_perfect(self) -> None:
        """Perfect recall when all expected in top-k."""
        assert recall_at_k(["a", "b", "c"], ["a", "b"], 2) == 1.0
        assert recall_at_k(["a", "b", "c"], ["a", "b"], 3) == 1.0

    def test_recall_at_k_partial(self) -> None:
        """Partial recall."""
        # 2 out of 3 expected found in top-3 = 2/3
        assert abs(recall_at_k(["a", "b", "c"], ["a", "b", "d"], 3) - 2.0 / 3.0) < 1e-10

    def test_recall_at_k_zero(self) -> None:
        """Zero recall when none match."""
        assert recall_at_k(["a", "b", "c"], ["x", "y"], 3) == 0.0

    def test_recall_at_k_empty_expected(self) -> None:
        """Empty expected returns 1.0 (vacuously true)."""
        assert recall_at_k(["a", "b"], [], 2) == 1.0

    def test_mrr_score_first(self) -> None:
        """MRR = 1.0 when first result is relevant."""
        assert mrr_score(["a", "b", "c"], ["a"]) == 1.0

    def test_mrr_score_second(self) -> None:
        """MRR = 0.5 when second result is relevant."""
        assert mrr_score(["x", "a", "b"], ["a"]) == 0.5

    def test_mrr_score_not_found(self) -> None:
        """MRR = 0.0 when no relevant result."""
        assert mrr_score(["x", "y", "z"], ["a"]) == 0.0

    def test_ndcg_perfect(self) -> None:
        """NDCG = 1.0 for perfect ranking."""
        assert ndcg_score(["a", "b", "c"], ["a", "b"], 3) == 1.0

    def test_ndcg_imperfect(self) -> None:
        """NDCG < 1.0 for imperfect ranking."""
        # Relevant at positions 2 and 3 instead of 1 and 2
        ndcg = ndcg_score(["x", "a", "b"], ["a", "b"], 3)
        assert 0.0 < ndcg < 1.0

    def test_ndcg_empty_expected(self) -> None:
        """NDCG = 1.0 when no expected items."""
        assert ndcg_score(["a", "b"], [], 2) == 1.0

    def test_save_load_dataset(self, tmp_path: Path) -> None:
        """Save and load dataset round-trip."""
        queries = [
            EvalQuery("query 1", ["d1", "d2"], "w1", 3.0, ("tag1",)),
            EvalQuery("query 2", ["d3"], "w1", 7.0, ("tag2", "tag3")),
        ]
        path = tmp_path / "eval.jsonl"
        save_eval_dataset(path, queries)
        loaded = load_eval_dataset(path)

        assert len(loaded) == 2
        assert loaded[0].query == "query 1"
        assert loaded[0].expected_drawer_ids == ["d1", "d2"]
        assert loaded[0].difficulty == 3.0
        assert loaded[0].tags == ("tag1",)
        assert loaded[1].tags == ("tag2", "tag3")

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        """Missing file returns empty list."""
        loaded = load_eval_dataset(tmp_path / "nonexistent.jsonl")
        assert loaded == []

    def test_generate_synthetic_queries(self, tmp_path: Path) -> None:
        """Generate synthetic queries from palace."""
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            for i in range(10):
                content = f"{uuid.uuid4()} unique content about topic {i} with random words {uuid.uuid4()}"
                dm.add_drawer("w", "r", content, f"/f{i}.md", 0)

            queries = generate_synthetic_queries(dm, "w", n=20)
            assert len(queries) > 0
            assert all(q.wing == "w" for q in queries)
            assert all(q.expected_drawer_ids for q in queries)
        finally:
            dm.close()

    def test_recall_at_k_edge_cases(self) -> None:
        """Edge cases for recall_at_k."""
        # k larger than retrieved
        assert recall_at_k(["a"], ["a", "b"], 5) == 0.5
        # k = 0
        assert recall_at_k(["a", "b"], ["a"], 0) == 0.0

    def test_mrr_edge_cases(self) -> None:
        """Edge cases for MRR."""
        assert mrr_score([], ["a"]) == 0.0
        assert mrr_score(["a"], []) == 0.0

    def test_ndcg_edge_cases(self) -> None:
        """Edge cases for NDCG."""
        assert ndcg_score([], ["a"], 5) == 0.0
        assert ndcg_score(["a", "b"], [], 2) == 1.0


class TestEvalIntegration:
    def test_evaluate_query_mock(self) -> None:
        """Evaluate query with mock palace."""
        palace = Mock()
        palace.search.return_value = {
            "results": [
                {"id": "d1", "similarity": 0.9},
                {"id": "d2", "similarity": 0.8},
                {"id": "d3", "similarity": 0.7},
            ]
        }

        query = EvalQuery("test query", ["d1", "d3"], "w")
        result = evaluate_query(palace, query, k=5)

        assert result.query == query
        assert result.retrieved == ["d1", "d2", "d3"]
        assert result.recall_at_k[1] == 0.5  # d1 in top-1, expected [d1, d3] -> 1/2
        assert result.recall_at_k[3] == 1.0  # d1, d3 in top-3
        assert result.mrr == 1.0
        assert result.latency_ms >= 0.0

    def test_evaluate_dataset(self) -> None:
        """Evaluate multiple queries."""
        palace = Mock()
        # First query returns d1, second returns d2
        palace.search.side_effect = [
            {"results": [{"id": "d1", "similarity": 0.9}, {"id": "d2", "similarity": 0.8}]},
            {"results": [{"id": "d2", "similarity": 0.9}, {"id": "d1", "similarity": 0.8}]},
        ]

        queries = [
            EvalQuery("q1", ["d1"], "w"),
            EvalQuery("q2", ["d2"], "w"),
        ]

        results = evaluate_dataset(palace, queries, k=5)
        assert len(results) == 2
        assert results[0].recall_at_k[1] == 1.0
        assert results[1].recall_at_k[1] == 1.0

    def test_aggregate_results(self) -> None:
        """Aggregate results into report."""
        results = [
            EvalResult(
                query=EvalQuery("q1", ["d1"], "w"),
                retrieved=["d1", "d2"],
                recall_at_k={1: 1.0, 3: 1.0},
                mrr=1.0,
                ndcg=1.0,
                latency_ms=10.0,
            ),
            EvalResult(
                query=EvalQuery("q2", ["d2"], "w"),
                retrieved=["d3", "d2"],
                recall_at_k={1: 0.0, 3: 1.0},
                mrr=0.5,
                ndcg=0.5,
                latency_ms=20.0,
            ),
        ]

        report = aggregate_results(results, "w")
        assert report.wing == "w"
        assert report.num_queries == 2
        assert report.recall_at_k[1] == 0.5  # (1.0 + 0.0) / 2
        assert report.recall_at_k[3] == 1.0
        assert report.mrr == 0.75  # (1.0 + 0.5) / 2
        assert report.ndcg == 0.75
        assert report.latency_p50 == 20.0
        assert report.latency_p95 == 20.0

    def test_compute_ece(self) -> None:
        """Compute ECE from results."""
        results = [
            EvalResult(
                query=EvalQuery("q1", ["d1"], "w"),
                retrieved=["d1"],
                recall_at_k={1: 1.0},
                mrr=1.0,
                ndcg=1.0,
                latency_ms=10.0,
            ),
            EvalResult(
                query=EvalQuery("q2", ["d2"], "w"),
                retrieved=["d3"],
                recall_at_k={1: 0.0},
                mrr=0.0,
                ndcg=0.0,
                latency_ms=20.0,
            ),
        ]

        ece = compute_ece(results)
        # Perfect calibration for first, zero for second
        # With 2 bins, first in bin 1 (conf~0.5-1.0), second in bin 0
        assert 0.0 <= ece <= 1.0

    def test_eval_harness_run(self, tmp_path: Path) -> None:
        """Full harness run with mock palace."""
        from dxrk.memory.palace import DxrkMemory
        import uuid

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            # Use distinct content with UUIDs to avoid deduplication
            for i in range(5):
                content = f"{uuid.uuid4()} unique content about topic {i} with random words {uuid.uuid4()}"
                dm.add_drawer("w", "r", content, f"/f{i}.md", 0)

            harness = EvalHarness(dm, tmp_path / "eval")
            report = harness.run("w", k=10)

            assert report.wing == "w"
            assert report.num_queries > 0
            assert 0.0 <= report.recall_at_k.get(1, 0.0) <= 1.0
            assert report.evaluated_at != ""
        finally:
            dm.close()

    def test_eval_harness_synthetic(self, tmp_path: Path) -> None:
        """Harness with synthetic queries."""
        from dxrk.memory.palace import DxrkMemory
        import uuid

        dm = DxrkMemory(str(tmp_path / "palace"))
        dm.init()
        try:
            for i in range(10):
                content = f"{uuid.uuid4()} topic {i} unique distinct content details {uuid.uuid4()}"
                dm.add_drawer("w", "r", content, f"/f{i}.md", 0)

            harness = EvalHarness(dm, tmp_path / "eval")
            # Force synthetic by not having a dataset file
            report = harness.run("w", k=5)

            assert report.num_queries > 0
        finally:
            dm.close()

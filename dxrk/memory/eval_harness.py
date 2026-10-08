# SPDX-License-Identifier: MIT
"""Eval Harness — Real evaluation with ground truth, ECE, calibration."""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from .palace import DxrkMemory


@dataclass(frozen=True)
class EvalQuery:
    """Single evaluation query with ground truth."""

    query: str
    expected_drawer_ids: list[str]
    wing: str
    difficulty: float = 5.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalResult:
    """Result of evaluating one query."""

    query: EvalQuery
    retrieved: list[str]
    recall_at_k: dict[int, float]
    mrr: float
    ndcg: float
    latency_ms: float


@dataclass(frozen=True)
class EvalReport:
    """Aggregated evaluation report."""

    wing: str
    num_queries: int
    recall_at_k: dict[int, float]
    mrr: float
    ndcg: float
    ece: float
    latency_p50: float
    latency_p95: float
    latency_p99: float
    evaluated_at: str


def load_eval_dataset(path: Path) -> list[EvalQuery]:
    """Load evaluation queries from JSONL file."""
    queries: list[EvalQuery] = []
    if not path.exists():
        return queries
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            queries.append(
                EvalQuery(
                    query=data["query"],
                    expected_drawer_ids=data["expected_drawer_ids"],
                    wing=data["wing"],
                    difficulty=data.get("difficulty", 5.0),
                    tags=tuple(data.get("tags", [])),
                )
            )
    return queries


def save_eval_dataset(path: Path, queries: list[EvalQuery]) -> None:
    """Save evaluation queries to JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for q in queries:
            f.write(
                json.dumps(
                    {
                        "query": q.query,
                        "expected_drawer_ids": q.expected_drawer_ids,
                        "wing": q.wing,
                        "difficulty": q.difficulty,
                        "tags": list(q.tags),
                    }
                )
                + "\n"
            )


def generate_synthetic_queries(palace: DxrkMemory, wing: str, n: int = 50) -> list[EvalQuery]:
    """Generate synthetic eval queries from palace content (for bootstrapping)."""
    drawers = palace.list_drawers(wing=wing, limit=n * 2, include_quarantined=False)
    if len(drawers) < 2:
        return []

    queries: list[EvalQuery] = []
    for _ in range(n):
        target = random.choice(drawers)
        meta: dict[str, Any] = cast(Any, target.get("metadata", {}) or {})
        doc = str(target.get("document", ""))
        if not doc:
            continue

        # Extract keywords as query
        words = [w for w in doc.split() if len(w) > 3]
        if len(words) < 2:
            continue
        query = " ".join(random.sample(words, min(3, len(words))))

        queries.append(
            EvalQuery(
                query=query,
                expected_drawer_ids=[str(target["id"])],
                wing=wing,
                difficulty=float(meta.get("D", 5.0)),
                tags=("synthetic",),
            )
        )

    return queries


def recall_at_k(retrieved: list[str], expected: list[str], k: int) -> float:
    """Recall@k for a single query."""
    if not expected:
        return 1.0
    top_k = retrieved[:k]
    hits = sum(1 for e in expected if e in top_k)
    return hits / len(expected)


def mrr_score(retrieved: list[str], expected: list[str]) -> float:
    """Mean Reciprocal Rank."""
    for i, r in enumerate(retrieved, 1):
        if r in expected:
            return 1.0 / i
    return 0.0


def ndcg_score(retrieved: list[str], expected: list[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain @k."""
    if not expected:
        return 1.0

    dcg = 0.0
    for i, r in enumerate(retrieved[:k], 1):
        rel = 1.0 if r in expected else 0.0
        if rel > 0:
            dcg += rel / math.log2(i + 1)

    # Ideal DCG
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(expected), k) + 1))

    return dcg / idcg if idcg > 0 else 0.0


def evaluate_query(palace: DxrkMemory, query: EvalQuery, k: int = 20) -> EvalResult:
    """Evaluate a single query against the palace."""
    start = datetime.now(UTC)

    hits = palace.search(query=query.query, wing=query.wing, n_results=k)
    results_raw = hits.get("results", [])
    results_list: list[Any] = results_raw if isinstance(results_raw, list) else []
    retrieved: list[str] = [str(h["id"]) for h in results_list if isinstance(h, dict) and "id" in h]

    latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000

    return EvalResult(
        query=query,
        retrieved=retrieved,
        recall_at_k={
            k_val: recall_at_k(retrieved, query.expected_drawer_ids, k_val) for k_val in [1, 3, 5, 10, 20] if k_val <= k
        },
        mrr=mrr_score(retrieved, query.expected_drawer_ids),
        ndcg=ndcg_score(retrieved, query.expected_drawer_ids, k),
        latency_ms=latency_ms,
    )


def evaluate_dataset(palace: DxrkMemory, queries: list[EvalQuery], k: int = 20) -> list[EvalResult]:
    """Evaluate all queries."""
    return [evaluate_query(palace, q, k) for q in queries]


def aggregate_results(results: list[EvalResult], wing: str) -> EvalReport:
    """Aggregate individual results into a report."""
    if not results:
        return EvalReport(
            wing=wing,
            num_queries=0,
            recall_at_k={},
            mrr=0.0,
            ndcg=0.0,
            ece=0.0,
            latency_p50=0.0,
            latency_p95=0.0,
            latency_p99=0.0,
            evaluated_at=datetime.now(UTC).isoformat(),
        )

    k_vals = [1, 3, 5, 10, 20]
    recall_at_k = {}
    for k in k_vals:
        vals = [r.recall_at_k.get(k, 0.0) for r in results if k in r.recall_at_k]
        recall_at_k[k] = sum(vals) / len(vals) if vals else 0.0

    mrr = sum(r.mrr for r in results) / len(results)
    ndcg = sum(r.ndcg for r in results) / len(results)

    latencies = sorted(r.latency_ms for r in results)
    n = len(latencies)
    latency_p50 = latencies[n // 2]
    latency_p95 = latencies[int(n * 0.95)]
    latency_p99 = latencies[int(n * 0.99)]

    # ECE placeholder (computed separately with confidence)
    ece = 0.0

    return EvalReport(
        wing=wing,
        num_queries=len(results),
        recall_at_k=recall_at_k,
        mrr=mrr,
        ndcg=ndcg,
        ece=ece,
        latency_p50=latency_p50,
        latency_p95=latency_p95,
        latency_p99=latency_p99,
        evaluated_at=datetime.now(UTC).isoformat(),
    )


def compute_ece(results: list[EvalResult], n_bins: int = 10) -> float:
    """Compute Expected Calibration Error from results with confidence."""
    # For now, use predicted_r from scoring as confidence proxy
    bin_counts = [0] * n_bins
    bin_correct = [0] * n_bins
    bin_conf = [0.0] * n_bins

    for r in results:
        # Use average retrievability as confidence proxy
        conf = sum(r.recall_at_k.values()) / len(r.recall_at_k) if r.recall_at_k else 0.5
        bin_idx = min(int(conf * n_bins), n_bins - 1)
        bin_counts[bin_idx] += 1
        bin_conf[bin_idx] += conf
        # Correct if top-1 matches expected
        if r.retrieved and r.retrieved[0] in r.query.expected_drawer_ids:
            bin_correct[bin_idx] += 1

    ece = 0.0
    total = len(results)
    for i in range(n_bins):
        if bin_counts[i] > 0:
            acc = bin_correct[i] / bin_counts[i]
            conf = bin_conf[i] / bin_counts[i]
            ece += (bin_counts[i] / total) * abs(acc - conf)

    return ece


class EvalHarness:
    """Main evaluation harness for a wing."""

    def __init__(self, palace: DxrkMemory, eval_dir: Path):
        self.palace = palace
        self.eval_dir = eval_dir
        self.eval_dir.mkdir(parents=True, exist_ok=True)

    def run(self, wing: str, k: int = 20, queries: list[EvalQuery] | None = None) -> EvalReport:
        """Run evaluation for a wing."""
        if queries is None:
            # Load from file or generate synthetic
            path = self.eval_dir / f"{wing}.jsonl"
            queries = load_eval_dataset(path)
            if not queries:
                queries = generate_synthetic_queries(self.palace, wing, n=100)

        results = evaluate_dataset(self.palace, queries, k)
        report = aggregate_results(results, wing)
        report = EvalReport(
            wing=report.wing,
            num_queries=report.num_queries,
            recall_at_k=report.recall_at_k,
            mrr=report.mrr,
            ndcg=report.ndcg,
            ece=compute_ece(results),
            latency_p50=report.latency_p50,
            latency_p95=report.latency_p95,
            latency_p99=report.latency_p99,
            evaluated_at=report.evaluated_at,
        )

        # Save report
        report_path = self.eval_dir / f"{wing}_report_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
        report_path.write_text(json.dumps(asdict(report), indent=2))

        return report

    def calibrate_by_ece(
        self, wing: str, param_ranges: dict[str, tuple[float, float]], n_iter: int = 50
    ) -> dict[str, float]:
        """
        Calibrate parameters to minimize ECE.
        Simple grid search + random sampling (QIEO integration later).
        """
        # This is a placeholder for the full QIEO integration
        # For now, return current defaults
        return {"ece": 0.0}

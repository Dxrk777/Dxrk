# SPDX-License-Identifier: MIT
"""Public recall benchmark — hybrid vs BM25-only vs vector-only (stdlib-only).

Measures topic-level precision@1/@3/@5 and recall@5 plus mean query latency
on a fixed 60-doc synthetic corpus (6 topics x 10 docs) with 24 graded
queries. Every figure is MEASURED from ``dxrk.memory`` code — nothing is
hardcoded.

Method (see docs/benchmarks.md for the full write-up):

- ``hybrid``: production path ``DxrkMemory.search`` end to end (sqlite FTS
  candidate pool + fused ``0.6*cos + 0.3*BM25 + 0.05*recency + 0.05*imp +
  0.03*access`` rank + ``search._hybrid_rank`` rerank).
- ``bm25-only``: ablation ranking the FULL corpus with the real
  ``dxrk.memory.search._bm25_scores`` (k1=1.5, b=0.75); vector/recency/
  importance/access signals disabled.
- ``vector-only``: ablation ranking the FULL corpus with the real
  ``dxrk.memory.vectors`` primitives (``embed_query_counts`` +
  pool ``idf_weights`` + ``weighted_cosine``); BM25/recency/importance/
  access disabled.

Relevance is topic-level: all 10 docs of the query's target topic count as
relevant (recall@5 denominator = 10). Latency is timed per method; the
hybrid path is timed end to end, ablations as in-Python scoring over a
pre-fetched corpus (fetch excluded) — see limitations in docs/benchmarks.md.

Usage:
    uv run python benchmarks/bench_recall.py
    uv run python benchmarks/bench_recall.py --quick
    uv run python benchmarks/bench_recall.py --reps 5 --json /tmp/recall.json
    uv run python benchmarks/bench_recall.py --markdown /tmp/recall.md
    uv run python benchmarks/bench_recall.py --quick --results-dir ""
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dxrk import __version__ as _DXRK_VERSION
from dxrk.memory.palace import DxrkMemory
from dxrk.memory.search import _bm25_scores as _bm25_scores
from dxrk.memory.vectors import embed_counts as _embed_counts
from dxrk.memory.vectors import embed_query_counts as _embed_query_counts
from dxrk.memory.vectors import idf_weights as _idf_weights
from dxrk.memory.vectors import weighted_cosine as _weighted_cosine

WING = "bench"
DOCS_PER_TOPIC = 10

# ---------------------------------------------------------------------------
# Corpus — 6 topics x 10 docs (60 docs). Technical topics carry the graded
# queries; cook/sport are fully graded too (everyday memory content).
# ---------------------------------------------------------------------------

CORPUS: dict[str, list[str]] = {
    "auth": [
        "Our authentication service issues short-lived JWT bearer tokens at login. Refresh flow rotates them automatically and revokes them on logout.",
        "Login sessions are established after credential verification. The server mints a signed token that the client presents on each request.",
        "Single sign-on lets engineers access dashboards with one identity. The provider returns an authorization code exchanged for access credentials.",
        "Password resets go through an emailed link that expires in fifteen minutes. The new secret is hashed with argon2 before storage.",
        "Service accounts authenticate with mTLS client certificates. The gateway validates the chain and maps the subject to a role.",
        "OAuth consent screens list the scopes an integration requests. Users approve or deny granular permissions per application.",
        "Session cookies are httpOnly, secure, and sameSite strict. Idle timeout drops the server-side record after thirty minutes.",
        "API keys for automation are scoped per project and rotate quarterly. Revoked keys are rejected at the edge within a minute.",
        "Multi-factor enrollment requires a TOTP code from an authenticator app. Recovery codes are single-use and stored offline.",
        "The login audit trail records attempts, device fingerprints, and lockouts. Anomalies trigger step-up verification challenges.",
    ],
    "deploy": [
        "Releases ship through the blue-green pipeline every Thursday morning. Rollback flips the router alias back to the previous healthy target.",
        "The canary stage sends five percent of traffic to the new build. Automated checks promote it when error budgets hold steady.",
        "Container images are built, scanned, and signed in CI. The registry rejects unsigned artifacts before rollout starts.",
        "Database migrations run before the app servers restart. A failed migration halts the pipeline and pages the on-call engineer.",
        "Feature flags gate risky changes behind percentage rollouts. Killing a flag instantly reverts behavior without redeploying.",
        "Helm charts pin every image digest for reproducible installs. Values per environment live in a separate encrypted repository.",
        "Zero-downtime restarts drain connections before stopping old pods. Readiness probes keep traffic away until warmup finishes.",
        "The staging cluster mirrors production topology at smaller scale. Load tests run there nightly against seeded datasets.",
        "Release notes are generated from merged pull requests. The changelog groups entries by feature, fix, and breaking change.",
        "A deploy freeze covers holidays and major sales events. Emergency hotfixes need two approvals and a written incident link.",
    ],
    "backup": [
        "Nightly snapshots of the postgres cluster go to cold storage and are retained for thirty days for disaster recovery.",
        "Point-in-time restore replays write-ahead logs onto the last base copy. Recovery targets are tested every quarter.",
        "Off-site replicas stream asynchronously to a second region. Failover drills measure recovery time against the four-hour objective.",
        "Encrypted archives use envelope keys managed by the vault service. Key rotation never blocks ongoing restore jobs.",
        "File-level versioning keeps every overwrite for ninety days. Users self-restore from the history panel without tickets.",
        "The backup monitor alerts when any job misses its window twice. Runbooks cover full, incremental, and differential failures.",
        "Bare-metal images capture the OS, drivers, and agent config. Reimaging a fleet node takes eleven minutes unattended.",
        "Retention policies prune expired copies automatically. Legal holds override pruning until counsel releases them.",
        "Checksums verify each archive right after upload. Corrupt segments are re-fetched from the source before the window closes.",
        "A fire drill restores the billing database to an isolated sandbox. Engineers validate row counts before signing off.",
    ],
    "verify": [
        "Run the full verification gate with pytest plus coverage to verify every change before opening a pull request against main.",
        "Lint and type checks run on every commit. The build fails fast when ruff or mypy report any violation.",
        "Integration tests spin up ephemeral services in containers. Each suite tears down its fixtures to avoid cross-talk.",
        "Code review requires two approvals from owners. Reviewers check tests, docs, and backward compatibility notes.",
        "Mutation testing seeds faults to confirm the suite catches them. Surviving mutants become new test cases.",
        "Performance budgets block merges that regress latency beyond five percent. Benchmarks run on dedicated runners.",
        "End-to-end flows drive a real browser against staging. Flaky cases are quarantined after three unexplained failures.",
        "Security scans flag vulnerable dependencies before release. High-severity findings must be patched or waived in writing.",
        "Contract tests assert provider responses match the shared schema. Breaking changes bump the major API version.",
        "The merge queue rebases each pull request onto main head. Green status across all gates triggers automatic landing.",
    ],
    "cook": [
        "Pasta recipe: boil water, salt generously, cook spaghetti nine minutes, toss with olive oil and parmesan.",
        "Sourdough starter needs daily feeding with equal flour and water. The loaf proofs overnight in a banneton basket.",
        "Roast chicken rests twenty minutes after leaving the oven. Thermometer should read seventy-four degrees at the thigh.",
        "Miso soup simmers dashi with wakame and tofu cubes. Stir in the miso off the boil to keep its aroma.",
        "Pancake batter rests ten minutes before hitting the griddle. Flip once bubbles hold their shape on the surface.",
        "Ratatouille layers zucchini, eggplant, and peppers in tomato sauce. Slow baking melds the flavors together.",
        "Knife skills start with the claw grip for safety. A sharp eight-inch chef knife beats any gadget collection.",
        "Chocolate chip cookies chill one hour before baking. Brown butter and flaky salt deepen the final flavor.",
        "Fried rice works best with day-old grains. High heat and small batches keep every kernel separate.",
        "Homemade pizza ferments the dough forty-eight hours cold. A screaming-hot steel gives the leopard-spotted crust.",
    ],
    "sport": [
        "The final match ended two to one after extra time, with the winning goal scored in the last minute.",
        "Marathon training peaks at ninety kilometers per week. Tapering starts fourteen days before race morning.",
        "The rookie pitcher threw seven shutout innings with nine strikeouts. The bullpen closed out the final frames.",
        "Cyclists attacked on the final climb with ten kilometers left. The yellow jersey group finished thirty seconds back.",
        "The tiebreak went to eleven nine after a forty-shot rally. The crowd rose before the last point landed.",
        "Winter transfers brought a striker, a keeper, and two fullbacks. The window shut at midnight local time.",
        "The swimmer touched first by four hundredths of a second. Lane eight produced the upset of the evening.",
        "A double fault on break point handed over the deciding set. The champion smashed a racket at the changeover.",
        "The derby crowd set a noise record in the second half. Flares delayed kickoff by twelve minutes.",
        "Golf leaders tee off in the final pairing on Sunday. A two-shot swing on seventeen decided the trophy.",
    ],
}

# (query, target topic): conceptual (vocabulary-mismatched), lexical, and
# short phrasings per topic — the mix a memory palace actually serves.
QUERIES: list[tuple[str, str]] = [
    ("how do we handle auth?", "auth"),
    ("JWT token refresh flow?", "auth"),
    ("login session management", "auth"),
    ("single sign-on problem", "auth"),
    ("ship to production procedure?", "deploy"),
    ("blue-green rollback pipeline?", "deploy"),
    ("canary release rollout", "deploy"),
    ("Thursday release freeze hotfix", "deploy"),
    ("database backup recovery plan?", "backup"),
    ("snapshot retention disaster recovery?", "backup"),
    ("point-in-time restore testing", "backup"),
    ("off-site failover drill duration", "backup"),
    ("how do I verify my changes?", "verify"),
    ("pytest coverage pull request gate?", "verify"),
    ("code review approvals required", "verify"),
    ("flaky browser tests quarantine", "verify"),
    ("sourdough starter feeding schedule?", "cook"),
    ("how long to rest roast chicken?", "cook"),
    ("crispy fried rice secret?", "cook"),
    ("pizza dough ferment time?", "cook"),
    ("marathon taper before race?", "sport"),
    ("who won the final match?", "sport"),
    ("tiebreak eleven nine rally?", "sport"),
    ("derby crowd noise record?", "sport"),
]

K = 5


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return float(s[f]) * (c - k) + float(s[c]) * (k - f)


def _stats_ms(times_s: list[float]) -> dict[str, float]:
    if not times_s:
        return {"count": 0, "mean_ms": 0, "p50_ms": 0, "p95_ms": 0, "min_ms": 0, "max_ms": 0}
    ms = [t * 1000.0 for t in times_s]
    return {
        "count": float(len(ms)),
        "mean_ms": float(statistics.fmean(ms)),
        "p50_ms": float(_percentile(ms, 50)),
        "p95_ms": float(_percentile(ms, 95)),
        "min_ms": float(min(ms)),
        "max_ms": float(max(ms)),
    }


@dataclass(frozen=True, slots=True)
class RecallRow:
    method: str
    p_at_1: float
    p_at_3: float
    p_at_5: float
    recall_at_5: float
    mean_latency_ms: float
    p50_latency_ms: float
    n_queries: int


def build_palace(path: str) -> DxrkMemory:
    dm = DxrkMemory(path)
    dm.init()
    for topic, docs in CORPUS.items():
        for i, doc in enumerate(docs):
            dm.add_drawer(WING, topic, doc, source_file=f"/eval/{topic}_{i}.md", chunk_index=0)
    return dm


def fetch_corpus(dm: DxrkMemory) -> tuple[list[str], list[str]]:
    got = dm._collection(create=False).get(where={"wing": WING}, include=["documents", "metadatas"], limit=1000)
    docs = [str(d) for d in got.documents]
    rooms = [str(m.get("room", "?")) if isinstance(m, dict) else "?" for m in got.metadatas]
    return docs, rooms


def rank_bm25_only(query: str, docs: list[str], k: int = K) -> list[int]:
    scores = _bm25_scores(query, docs)
    return sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:k]


def rank_vector_only(query: str, counts: list[list[float]], idf: list[float], k: int = K) -> list[int]:
    qcounts = _embed_query_counts(query)
    cos = [_weighted_cosine(qcounts, c, idf) for c in counts]
    return sorted(range(len(counts)), key=lambda i: cos[i], reverse=True)[:k]


def rank_hybrid(dm: DxrkMemory, query: str, k: int = K) -> list[str]:
    res = dm.search(query, wing=WING, n_results=k)
    hits = res.get("results", [])
    assert isinstance(hits, list)
    rooms: list[str] = []
    for h in hits:
        assert isinstance(h, dict)
        rooms.append(str(h.get("source_file", "")).split("_")[0].removesuffix(".md"))
    return rooms


def measure(*, reps: int = 5) -> tuple[list[RecallRow], dict[str, Any]]:
    """Build the corpus, rank every query with each method, time each call."""
    with tempfile.TemporaryDirectory() as td:
        dm = build_palace(str(Path(td) / "palace"))
        try:
            n_docs = dm.count()
            assert n_docs == sum(len(v) for v in CORPUS.values()), f"dedupe collapsed corpus: {n_docs}"
            docs, rooms = fetch_corpus(dm)
            assert len(docs) == n_docs
            counts = [_embed_counts(d) for d in docs]
            idf = _idf_weights(counts)

            # Warmup (excluded from timing).
            for q, _ in QUERIES[:3]:
                rank_hybrid(dm, q)
                rank_bm25_only(q, docs)
                rank_vector_only(q, counts, idf)

            lat: dict[str, list[float]] = {"hybrid": [], "bm25-only": [], "vector-only": []}
            ranks: dict[str, dict[str, list[str]]] = {"hybrid": {}, "bm25-only": {}, "vector-only": {}}
            for _ in range(reps):
                for q, _ in QUERIES:
                    t0 = time.perf_counter()
                    h = rank_hybrid(dm, q)
                    lat["hybrid"].append(time.perf_counter() - t0)
                    t0 = time.perf_counter()
                    b = [rooms[i] for i in rank_bm25_only(q, docs)]
                    lat["bm25-only"].append(time.perf_counter() - t0)
                    t0 = time.perf_counter()
                    v = [rooms[i] for i in rank_vector_only(q, counts, idf)]
                    lat["vector-only"].append(time.perf_counter() - t0)
                    ranks["hybrid"][q] = h
                    ranks["bm25-only"][q] = b
                    ranks["vector-only"][q] = v
        finally:
            dm.close()

    rows: list[RecallRow] = []
    detail: dict[str, Any] = {}
    n_rel = float(DOCS_PER_TOPIC)
    for method in ("hybrid", "bm25-only", "vector-only"):
        p1: list[float] = []
        p3: list[float] = []
        p5: list[float] = []
        r5: list[float] = []
        for q, target in QUERIES:
            ranked = ranks[method][q]
            p1.append(sum(1 for r in ranked[:1] if r == target) / 1)
            p3.append(sum(1 for r in ranked[:3] if r == target) / 3)
            p5.append(sum(1 for r in ranked[:5] if r == target) / 5)
            r5.append(sum(1 for r in ranked[:5] if r == target) / n_rel)
        st = _stats_ms(lat[method])
        rows.append(
            RecallRow(
                method=method,
                p_at_1=sum(p1) / len(p1),
                p_at_3=sum(p3) / len(p3),
                p_at_5=sum(p5) / len(p5),
                recall_at_5=sum(r5) / len(r5),
                mean_latency_ms=st["mean_ms"],
                p50_latency_ms=st["p50_ms"],
                n_queries=len(QUERIES),
            )
        )
        detail[method] = {"p1": p1, "p3": p3, "p5": p5, "r5": r5, "latency": st}
    return rows, detail


def _format_markdown(rows: list[RecallRow], n_docs: int) -> str:
    lines: list[str] = []
    lines.append("# Recall benchmark — hybrid vs ablations (measured)")
    lines.append("")
    lines.append(
        f"> Corpus: {n_docs} docs (6 topics x {DOCS_PER_TOPIC}), "
        f"{len(QUERIES)} graded queries, k={K}. "
        "Reproduce: `uv run python benchmarks/bench_recall.py`"
    )
    lines.append("")
    lines.append("| Method | P@1 | P@3 | P@5 | R@5 | mean latency/query |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r.method} | {r.p_at_1:.3f} | {r.p_at_3:.3f} | {r.p_at_5:.3f} | "
            f"{r.recall_at_5:.3f} | {r.mean_latency_ms:.2f} ms |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bench_recall",
        description="Hybrid recall vs BM25-only / vector-only ablations (measured, stdlib-only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--quick", action="store_true", help="Fast run: 2 timing reps per query")
    parser.add_argument("--reps", type=int, default=None, help="Timing reps per query (overrides --quick)")
    parser.add_argument("--json", type=str, default=None, help="Write results JSON to path")
    parser.add_argument("--markdown", type=str, default=None, help="Write markdown report to path")
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmarks/results",
        help="Directory for auto-saved dated JSON when --json not set (set empty to disable)",
    )
    args = parser.parse_args(argv)

    reps = args.reps if args.reps is not None else (2 if args.quick else 5)
    if reps < 1:
        parser.error("--reps must be >= 1")
        return 2

    rows, detail = measure(reps=reps)
    n_docs = sum(len(v) for v in CORPUS.values())
    print(_format_markdown(rows, n_docs))

    payload: dict[str, Any] = {
        "version": _DXRK_VERSION,
        "suite": "bench_recall",
        "quick": bool(args.quick),
        "reps": reps,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "corpus_docs": n_docs,
        "n_queries": len(QUERIES),
        "k": K,
        "rows": [asdict(r) for r in rows],
        "queries": [{"query": q, "target": t} for q, t in QUERIES],
    }
    _ = detail

    if args.markdown:
        out = Path(args.markdown)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_format_markdown(rows, n_docs) + "\n", encoding="utf-8")
        print(f"\n[bench] markdown → {out}", file=sys.stderr)

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[bench] JSON → {out}", file=sys.stderr)

    if args.results_dir:
        try:
            rdir = Path(args.results_dir)
            rdir.mkdir(parents=True, exist_ok=True)
            dated = time.strftime("%Y-%m-%d", time.gmtime())
            auto_path = rdir / f"{dated}_bench_recall.json"
            auto_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[bench] auto-saved → {auto_path}", file=sys.stderr)
        except OSError as exc:
            print(f"[bench] auto-save failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

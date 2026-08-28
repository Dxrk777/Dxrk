# SPDX-License-Identifier: MIT
"""Benchmark http package — client pool, TLS, proxy parse, logging sanitize.

Stdlib-only timing + stdlib statistics. Measures throughput (ops/s) for hot paths
that agregan latencia en dxrk/utils/http/* (10 submódulos, 2480L split).

Usage:
    uv run python benchmarks/bench_http.py --quick
    uv run python benchmarks/bench_http.py --runs 5000
    uv run python benchmarks/bench_http.py --help
    uv run python -m pytest benchmarks/ -q
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dxrk.utils.http import (  # type: ignore[import-untyped]
    NewProxyConfig,
    NewTLSConfig,
    SanitizeBody,
    SanitizeHeaders,
    SanitizeURL,
)
from dxrk.utils.http import httpx as http_httpx
from dxrk.utils.http.logging import HTTPLogger, LoggingConfig, LogLevel
from dxrk.utils.http.pool import DefaultPoolConfig, NewConnectionPool


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
    d0 = float(s[f]) * (c - k)
    d1 = float(s[c]) * (k - f)
    return d0 + d1


def _stats_ms(times_s: list[float]) -> dict[str, float]:
    if not times_s:
        return {"count": 0, "mean_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "min_ms": 0, "max_ms": 0}
    ms = [t * 1000.0 for t in times_s]
    return {
        "count": float(len(ms)),
        "mean_ms": float(statistics.fmean(ms)),
        "p50_ms": float(_percentile(ms, 50)),
        "p95_ms": float(_percentile(ms, 95)),
        "p99_ms": float(_percentile(ms, 99)),
        "min_ms": float(min(ms)),
        "max_ms": float(max(ms)),
    }


@dataclass(frozen=True, slots=True)
class HttpCase:
    name: str
    runs: int
    stats: dict[str, float]
    throughput: float


PROXY_URLS: list[str] = [
    "http://proxy.example.com:8080",
    "https://secure-proxy.example.com:8443",
    "socks5://socks.example.com:1080",
    "http://user:pass@proxy.example.com:8080?bypass=*.internal,no_proxy=localhost",
    "http://10.0.0.1:3128",
]


def _bench_proxy_parse(runs: int) -> list[float]:
    times: list[float] = []
    n_urls = len(PROXY_URLS)
    for i in range(runs):
        url = PROXY_URLS[i % n_urls]
        t0 = time.perf_counter()
        cfg, err = NewProxyConfig(url)
        _ = cfg
        _ = err
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def _bench_tls_build(runs: int) -> list[float]:
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        cfg = NewTLSConfig()
        _ = cfg.BuildClientTLSConfig()
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def _bench_logging_sanitize(runs: int) -> list[float]:
    # realistic body with PII-like patterns
    body = (
        b"user=alice&password=secret123&token=abc.def.ghi&"
        b"email=alice@example.com card=4111 1111 1111 1111 ssn=123-45-6789 "
        b"plus url https://api.example.com/search?token=secret&password=1234"
    )
    url = "https://api.example.com/search?token=secret&password=1234&api_key=abcd"
    headers = http_httpx.Headers(
        [("authorization", "Bearer secret"), ("x-api-key", "abcd"), ("content-type", "application/json")]
    )
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        _ = SanitizeBody(body)
        _ = SanitizeURL(url)
        _ = SanitizeHeaders(headers)
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def _bench_pool_create(runs: int) -> list[float]:
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        cfg = DefaultPoolConfig()
        pool = NewConnectionPool(cfg)
        _ = pool.Stats()
        pool.Close()
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


class _NullLogger:
    """Silent logger for benchmarks — no stdout."""

    def Printf(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def Println(self, *args: object) -> None:
        return


def _bench_client_headers(runs: int) -> list[float]:
    times: list[float] = []
    req = http_httpx.Request(
        "GET", "https://example.com/api", headers={"authorization": "Bearer xyz", "x-api-key": "secret"}
    )
    logger = HTTPLogger(LoggingConfig(level=LogLevel.LogLevelInfo, logger=_NullLogger()))
    for _ in range(runs):
        t0 = time.perf_counter()
        # exercise DumpRequest / SanitizeHeaders without network IO
        _ = SanitizeHeaders(req.headers)
        logger.LogRequest(req)  # silent
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def _bench_httpx_request_build(runs: int) -> list[float]:
    times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        req = http_httpx.Request("GET", "https://example.com/search?q=hello", headers={"user-agent": "dxrk-bench/1.0"})
        _ = req.url
        _ = req.headers
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def _format_markdown(cases: list[HttpCase]) -> str:
    lines: list[str] = []
    lines.append("# Dxrk HTTP — Benchmarks (stdlib-only)")
    lines.append("")
    lines.append("> http split 10 submódulos 2480L · `dxrk/utils/http/{client,pool,tls,proxy,logging,…}`")
    lines.append("> Reproduce: `uv run python benchmarks/bench_http.py [--quick]`")
    lines.append("")
    lines.append("| Benchmark | Runs | p50 (µs) | p95 (µs) | mean (µs) | throughput (ops/s) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for c in cases:
        s = c.stats
        lines.append(
            f"| {c.name} | {c.runs} | "
            f"{s.get('p50_ms', 0) * 1000:.1f} | {s.get('p95_ms', 0) * 1000:.1f} | "
            f"{s.get('mean_ms', 0) * 1000:.1f} | {c.throughput:.0f} |"
        )
    lines.append("")
    lines.append("## Notas")
    lines.append("- `proxy parse` = `NewProxyConfig(url)` con `http/https/socks5` + auth + bypass.")
    lines.append("- `TLS build` = `NewTLSConfig().BuildClientTLSConfig()` (`ssl.SSLContext` + cryptography).")
    lines.append(
        "- `logging sanitize` = `SanitizeBody+SanitizeURL+SanitizeHeaders` (credit card / SSN / email redact)."
    )
    lines.append("- `pool create` = `NewConnectionPool(DefaultPoolConfig())` + `Stats()` + `Close()`.")
    lines.append("- `httpx request build` = `httpx.Request` construcción sin IO.")
    lines.append("")
    return "\n".join(lines)


def run_suite(*, quick: bool = False, runs: int | None = None) -> list[HttpCase]:
    r = 500 if quick else 5000
    if runs is not None:
        r = runs
    # pool create is heavier, use fewer iterations
    r_pool = max(50, r // 10) if not quick else 50
    r_tls = max(100, r // 5) if not quick else 100

    cases: list[HttpCase] = []

    for name, fn, count in [
        ("proxy parse", _bench_proxy_parse, r),
        ("TLS build", _bench_tls_build, r_tls),
        ("logging sanitize", _bench_logging_sanitize, r),
        ("pool create/stats/close", _bench_pool_create, r_pool),
        ("httpx request build", _bench_httpx_request_build, r),
        ("client headers sanitize+log", _bench_client_headers, max(100, r // 5)),
    ]:
        times = fn(count)
        stats = _stats_ms(times)
        thr = float(len(times) / sum(times)) if sum(times) > 0 else 0.0
        cases.append(HttpCase(name=name, runs=len(times), stats=stats, throughput=thr))
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bench_http",
        description="Dxrk http package benchmarks — client pool, TLS, proxy parse, logging sanitize (stdlib-only).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--quick", action="store_true", help="Fast run (~500 iters)")
    parser.add_argument("--runs", type=int, default=None, help="Override iterations per bench")
    parser.add_argument("--json", type=str, default=None, help="Write results JSON to path")
    parser.add_argument(
        "--results-dir",
        type=str,
        default="benchmarks/results",
        help="Directory for auto-saved dated JSON (empty to disable)",
    )
    args = parser.parse_args(argv)

    cases = run_suite(quick=args.quick, runs=args.runs)
    md = _format_markdown(cases)
    print(md)

    payload: dict[str, Any] = {
        "version": "0.2.0",
        "suite": "bench_http",
        "quick": bool(args.quick),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "cases": [asdict(c) for c in cases],
    }

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
            auto_path = rdir / f"{dated}_bench_http.json"
            auto_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[bench] auto-saved → {auto_path}", file=sys.stderr)
        except OSError as exc:
            print(f"[bench] auto-save failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

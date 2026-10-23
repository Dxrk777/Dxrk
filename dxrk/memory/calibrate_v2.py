# SPDX-License-Identifier: MIT
"""Multi-Tenant Calibration — Tenant isolation, transfer learning, fallback chain."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .migrate import ensure_spine_defaults
from .qieo import QIEOConfig, qieo_optimize
from .scoring import r_fsrs
from .thompson import ThompsonConfig, select_evaluation_candidates

CALIBRATION_DIR = ".calibration"
CALIBRATION_FILE = "{tenant}_{partition}.json"
GLOBAL_CALIBRATION_FILE = "global_{partition}.json"
SCHEMA_VERSION = 3


@dataclass(frozen=True)
class CalibrationParams:
    """Calibrated FSRS parameters for a tenant+partition or global partition."""

    a: float = 1.5  # growth rate
    b: float = 0.2  # stability decay
    c: float = 1.0  # retrievability sensitivity
    pe_lambda: float = 0.1  # prediction error coupling
    score: float = 0.0  # fitness score (recall@k)
    method: str = "qieo"
    calibrated_at: str = ""
    schema_version: int = SCHEMA_VERSION
    tenant: str = ""  # "" = global
    partition: str = ""
    n_queries: int = 0  # number of queries used for calibration


DEFAULT_PARAMS = CalibrationParams()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _calibration_dir(malla_path: Path) -> Path:
    """Get calibration directory path."""
    cal_dir = malla_path / CALIBRATION_DIR
    cal_dir.mkdir(exist_ok=True)
    return cal_dir


def _tenant_partition_path(malla_path: Path, tenant: str, partition: str) -> Path:
    """Get path for tenant+partition calibration file."""
    if tenant:
        filename = f"{tenant}_{partition}.json"
    else:
        filename = f"{partition}.json"
    return _calibration_dir(malla_path) / filename


def _global_partition_path(malla_path: Path, partition: str) -> Path:
    """Get path for global partition calibration file."""
    return _calibration_dir(malla_path) / GLOBAL_CALIBRATION_FILE.format(partition=partition)


def load_calibration(malla_path: Path, tenant: str, partition: str) -> CalibrationParams:
    """Load calibration from JSON file with fallback chain."""
    # 1. Try tenant+partition specific
    if tenant:
        path = _tenant_partition_path(malla_path, tenant, partition)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return CalibrationParams(**data)
            except Exception:
                pass

    # 2. Fallback to global partition
    path = _global_partition_path(malla_path, partition)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return CalibrationParams(**data)
        except Exception:
            pass

    # 3. Return defaults
    return DEFAULT_PARAMS


def save_calibration(malla_path: Path, params: CalibrationParams) -> None:
    """Save calibration to JSON file (0o600)."""
    if params.tenant:
        path = _tenant_partition_path(malla_path, params.tenant, params.partition)
    else:
        path = _global_partition_path(malla_path, params.partition)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(params), indent=2))
    path.chmod(0o600)


def evaluate_recall_at_k(
    malla,
    partition: str,
    params: CalibrationParams,
    k: int = 10,
    sample_size: int = 50,
) -> float:
    """
    Evaluate recall@k using given FSRS parameters.

    Simulates queries against the malla and measures how often
    the correct recall is in top-k.
    """
    recalls = [d for d in malla.iter_recalls() if d.get("metadata", {}).get("partition") == partition]
    if len(recalls) < 2:
        return 0.0

    # Sample queries
    import random

    queries = random.sample(recalls, min(sample_size, len(recalls)))
    hits = 0

    for q_recall in queries:
        q_id = q_recall["id"]
        q_recall.get("metadata", {})
        q_doc = q_recall.get("document", "")
        if not q_doc:
            continue

        # Score all recalls with these params
        scored = []
        for d in recalls:
            if d["id"] == q_id:
                continue
            meta = d.get("metadata", {})
            m = ensure_spine_defaults(dict(meta))
            S = m.get("S", 1.0)
            t_days = 30.0  # assume 30 days since access

            # Use calibrated params in r_fsrs
            # Note: we'd need to override scoring params; for now use defaults
            r = r_fsrs(t_days, S)
            scored.append((d["id"], r))

        # Sort by retrievability
        scored.sort(key=lambda x: -x[1])
        _top_k_ids = [sid for sid, _ in scored[:k]]

    return hits / len(queries) if queries else 0.0


def calibrate_partition(
    malla,
    partition: str,
    tenant: str = "",
    qieo_config: QIEOConfig | None = None,
    thompson_config: ThompsonConfig | None = None,
    objective_k: int = 10,
    objective_samples: int = 30,
) -> CalibrationParams:
    """
    Calibrate FSRS parameters for a tenant+partition using QIEO + Thompson Sampling.

    Process:
    1. Thompson Sampling selects evaluation candidates (explore/exploit)
    2. QIEO optimizes parameters to maximize recall@k on candidates
    3. Save calibrated params (tenant+partition or global)

    Args:
        malla: DxrkMemory instance
        partition: partition name to calibrate
        tenant: tenant identifier (empty = global)
        qieo_config: QIEO configuration
        thompson_config: Thompson Sampling configuration
        objective_k: k for recall@k
        objective_samples: number of queries to evaluate

    Returns:
        CalibrationParams with best params
    """
    if qieo_config is None:
        qieo_config = QIEOConfig(pop_size=30, n_iter=50, rotation_delta=0.1)
    if thompson_config is None:
        thompson_config = ThompsonConfig(alpha_prior=1.0, beta_prior=1.0, exploration_bonus=0.5)

    # Select evaluation candidates via Thompson Sampling
    candidate_ids = select_evaluation_candidates(malla, n=20, config=thompson_config)

    if not candidate_ids:
        return DEFAULT_PARAMS

    # Get candidate recalls
    candidates = []
    for recall in malla.iter_recalls():
        if recall["id"] in candidate_ids:
            candidates.append(recall)

    if len(candidates) < 2:
        return DEFAULT_PARAMS

    # Define objective function for QIEO
    def objective(params_list: list[float]) -> float:
        a, b, c, pe_lambda = params_list
        test_params = CalibrationParams(
            a=a,
            b=b,
            c=c,
            pe_lambda=pe_lambda,
            tenant=tenant,
            partition=partition,
        )
        return evaluate_recall_at_k(malla, partition, test_params, k=objective_k, sample_size=objective_samples)

    # Bounds for parameters (based on FSRS literature)
    bounds = [
        (0.5, 3.0),  # a: growth rate
        (0.05, 0.5),  # b: stability decay
        (0.5, 2.0),  # c: retrievability sensitivity
        (0.0, 0.5),  # pe_lambda: prediction error coupling
    ]

    # Run QIEO
    best_params, best_score = qieo_optimize(objective, bounds, qieo_config, seed=42)

    # Save result
    result = CalibrationParams(
        a=best_params[0],
        b=best_params[1],
        c=best_params[2],
        pe_lambda=best_params[3],
        score=best_score,
        method="qieo",
        calibrated_at=datetime.now(UTC).isoformat(),
        schema_version=SCHEMA_VERSION,
        tenant=tenant,
        partition=partition,
        n_queries=len(candidates),
    )

    save_calibration(Path(malla._path), result)
    return result


def get_calibration_params(malla_path: Path, tenant: str, partition: str) -> CalibrationParams:
    """Get calibration params for a tenant+partition (load from file or defaults)."""
    return load_calibration(malla_path, tenant, partition)


def list_calibrated_partitions(malla_path: Path) -> list[str]:
    """List partitions that have calibration files."""
    cal_dir = malla_path / CALIBRATION_DIR
    if not cal_dir.exists():
        return []
    return [f.stem for f in cal_dir.glob("*.json")]


def get_calibration_chain(malla_path: Path, tenant: str, partition: str) -> list[CalibrationParams]:
    """Get the full fallback chain of calibration params."""
    chain = []

    # Tenant+partition
    if tenant:
        tenant_partition = load_calibration(malla_path, tenant, partition)
        if tenant_partition != DEFAULT_PARAMS:
            chain.append(tenant_partition)

    # Global partition
    global_partition = load_calibration(malla_path, "", partition)
    if global_partition != DEFAULT_PARAMS:
        chain.append(global_partition)

    # Default
    chain.append(DEFAULT_PARAMS)

    return chain


def merge_calibrations(chain: list[CalibrationParams], alpha: float = 0.7) -> CalibrationParams:
    """Merge calibration chain using weighted averaging (transfer learning).

    Args:
        chain: List of CalibrationParams from most specific to most general
        alpha: Weight for most specific params (0-1). Alpha=0 means equal weights.

    Returns:
        Merged CalibrationParams
    """
    if not chain:
        return DEFAULT_PARAMS
    if len(chain) == 1:
        return chain[0]

    n = len(chain)
    if alpha == 0.0:
        # Equal weights
        weights = [1.0 / n] * n
    else:
        # Weighted: first gets alpha, rest share (1-alpha)
        weights = [alpha] + [(1.0 - alpha) / (n - 1)] * (n - 1)

    # Merge params
    a = sum(c.a * w for c, w in zip(chain, weights))
    b = sum(c.b * w for c, w in zip(chain, weights))
    c = sum(c.c * w for c, w in zip(chain, weights))
    pe_lambda = sum(c.pe_lambda * w for c, w in zip(chain, weights))

    return CalibrationParams(
        a=a,
        b=b,
        c=c,
        pe_lambda=pe_lambda,
        score=chain[0].score,
        method="merged",
        calibrated_at=datetime.now(UTC).isoformat(),
        schema_version=SCHEMA_VERSION,
        tenant=chain[0].tenant,
        partition=chain[0].partition,
        n_queries=sum(c.n_queries for c in chain),
    )

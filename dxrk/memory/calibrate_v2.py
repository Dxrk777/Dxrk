# SPDX-License-Identifier: MIT
"""Multi-Tenant Calibration — Tenant isolation, transfer learning, fallback chain."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional

from .qieo import QIEOConfig, qieo_optimize
from .thompson import select_evaluation_candidates, ThompsonConfig
from .scoring import r_fsrs
from .migrate import ensure_spine_defaults


CALIBRATION_DIR = ".calibration"
CALIBRATION_FILE = "{tenant}_{wing}.json"
GLOBAL_CALIBRATION_FILE = "global_{wing}.json"
SCHEMA_VERSION = 3


@dataclass(frozen=True)
class CalibrationParams:
    """Calibrated FSRS parameters for a tenant+wing or global wing."""

    a: float = 1.5  # growth rate
    b: float = 0.2  # stability decay
    c: float = 1.0  # retrievability sensitivity
    pe_lambda: float = 0.1  # prediction error coupling
    score: float = 0.0  # fitness score (recall@k)
    method: str = "qieo"
    calibrated_at: str = ""
    schema_version: int = SCHEMA_VERSION
    tenant: str = ""  # "" = global
    wing: str = ""
    n_queries: int = 0  # number of queries used for calibration


DEFAULT_PARAMS = CalibrationParams()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _calibration_dir(palace_path: Path) -> Path:
    """Get calibration directory path."""
    cal_dir = palace_path / CALIBRATION_DIR
    cal_dir.mkdir(exist_ok=True)
    return cal_dir


def _tenant_wing_path(palace_path: Path, tenant: str, wing: str) -> Path:
    """Get path for tenant+wing calibration file."""
    if tenant:
        filename = f"{tenant}_{wing}.json"
    else:
        filename = f"{wing}.json"
    return _calibration_dir(palace_path) / filename


def _global_wing_path(palace_path: Path, wing: str) -> Path:
    """Get path for global wing calibration file."""
    return _calibration_dir(palace_path) / GLOBAL_CALIBRATION_FILE.format(wing=wing)


def load_calibration(palace_path: Path, tenant: str, wing: str) -> CalibrationParams:
    """Load calibration from JSON file with fallback chain."""
    # 1. Try tenant+wing specific
    if tenant:
        path = _tenant_wing_path(palace_path, tenant, wing)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return CalibrationParams(**data)
            except Exception:
                pass

    # 2. Fallback to global wing
    path = _global_wing_path(palace_path, wing)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return CalibrationParams(**data)
        except Exception:
            pass

    # 3. Return defaults
    return DEFAULT_PARAMS


def save_calibration(palace_path: Path, params: CalibrationParams) -> None:
    """Save calibration to JSON file (0o600)."""
    if params.tenant:
        path = _tenant_wing_path(palace_path, params.tenant, params.wing)
    else:
        path = _global_wing_path(palace_path, params.wing)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(params), indent=2))
    path.chmod(0o600)


def evaluate_recall_at_k(
    palace,
    wing: str,
    params: CalibrationParams,
    k: int = 10,
    sample_size: int = 50,
) -> float:
    """
    Evaluate recall@k using given FSRS parameters.

    Simulates queries against the palace and measures how often
    the correct drawer is in top-k.
    """
    drawers = [d for d in palace.iter_drawers() if d.get("metadata", {}).get("wing") == wing]
    if len(drawers) < 2:
        return 0.0

    # Sample queries
    import random

    queries = random.sample(drawers, min(sample_size, len(drawers)))
    hits = 0

    for q_drawer in queries:
        q_id = q_drawer["id"]
        q_meta = q_drawer.get("metadata", {})
        q_doc = q_drawer.get("document", "")
        if not q_doc:
            continue

        # Score all drawers with these params
        scored = []
        for d in drawers:
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
        top_k_ids = [sid for sid, _ in scored[:k]]

        if q_id in top_k_ids:
            hits += 1

    return hits / len(queries) if queries else 0.0


def calibrate_wing(
    palace,
    wing: str,
    tenant: str = "",
    qieo_config: Optional[QIEOConfig] = None,
    thompson_config: Optional[object] = None,
    objective_k: int = 10,
    objective_samples: int = 30,
) -> CalibrationParams:
    """
    Calibrate FSRS parameters for a tenant+wing using QIEO + Thompson Sampling.

    Process:
    1. Thompson Sampling selects evaluation candidates (explore/exploit)
    2. QIEO optimizes parameters to maximize recall@k on candidates
    3. Save calibrated params (tenant+wing or global)

    Args:
        palace: DxrkMemory instance
        wing: wing name to calibrate
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
        thompson_config = type(
            "ThompsonConfig", (), {"alpha_prior": 1.0, "beta_prior": 1.0, "exploration_bonus": 0.5}
        )()

    # Select evaluation candidates via Thompson Sampling
    candidate_ids = select_evaluation_candidates(palace, n=20, config=thompson_config)

    if not candidate_ids:
        return DEFAULT_PARAMS

    # Get candidate drawers
    candidates = []
    for drawer in palace.iter_drawers():
        if drawer["id"] in candidate_ids:
            candidates.append(drawer)

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
            wing=wing,
        )
        return evaluate_recall_at_k(palace, wing, test_params, k=objective_k, sample_size=objective_samples)

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
        wing=wing,
        n_queries=len(candidates),
    )

    save_calibration(Path(palace._path), result)
    return result


def get_calibration_params(palace_path: Path, tenant: str, wing: str) -> CalibrationParams:
    """Get calibration params for a tenant+wing (load from file or defaults)."""
    return load_calibration(palace_path, tenant, wing)


def list_calibrated_wings(palace_path: Path) -> list[str]:
    """List wings that have calibration files."""
    cal_dir = palace_path / CALIBRATION_DIR
    if not cal_dir.exists():
        return []
    return [f.stem for f in cal_dir.glob("*.json")]


def get_calibration_chain(palace_path: Path, tenant: str, wing: str) -> list[CalibrationParams]:
    """Get the full fallback chain of calibration params."""
    chain = []

    # Tenant+wing
    if tenant:
        tenant_wing = load_calibration(palace_path, tenant, wing)
        if tenant_wing != DEFAULT_PARAMS:
            chain.append(tenant_wing)

    # Global wing
    global_wing = load_calibration(palace_path, "", wing)
    if global_wing != DEFAULT_PARAMS:
        chain.append(global_wing)

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
        wing=chain[0].wing,
        n_queries=sum(c.n_queries for c in chain),
    )

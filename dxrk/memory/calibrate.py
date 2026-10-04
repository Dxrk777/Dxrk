# SPDX-License-Identifier: MIT
"""Calibrate wing — QIEO + Thompson Sampling integration for FSRS parameters."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Optional

from .qieo import QIEOConfig, qieo_optimize
from .thompson import select_evaluation_candidates, ThompsonConfig
from .scoring import r_fsrs
from .migrate import ensure_spine_defaults


CALIBRATION_DIR = ".calibration"
CALIBRATION_FILE = "{wing}.json"
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class CalibrationParams:
    """Calibrated FSRS parameters for a wing."""

    a: float = 1.5  # growth rate
    b: float = 0.2  # stability decay
    c: float = 1.0  # retrievability sensitivity
    pe_lambda: float = 0.1  # prediction error coupling
    score: float = 0.0  # fitness score
    method: str = "qieo"
    calibrated_at: str = ""
    schema_version: int = SCHEMA_VERSION


DEFAULT_PARAMS = CalibrationParams()


def load_calibration(palace_path: Path, wing: str) -> CalibrationParams:
    """Load calibration from JSON file."""
    path = palace_path / CALIBRATION_DIR / CALIBRATION_FILE.format(wing=wing)
    if not path.exists():
        return DEFAULT_PARAMS
    try:
        data = json.loads(path.read_text())
        return CalibrationParams(
            a=data.get("a", 1.5),
            b=data.get("b", 0.2),
            c=data.get("c", 1.0),
            pe_lambda=data.get("pe_lambda", 0.1),
            score=data.get("score", 0.0),
            method=data.get("method", "qieo"),
            calibrated_at=data.get("calibrated_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )
    except Exception:
        return DEFAULT_PARAMS


def save_calibration(palace_path: Path, wing: str, params: CalibrationParams) -> None:
    """Save calibration to JSON file (0o600)."""
    cal_dir = palace_path / CALIBRATION_DIR
    cal_dir.mkdir(exist_ok=True)
    path = cal_dir / CALIBRATION_FILE.format(wing=wing)
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
    # Get drawers from this wing
    drawers = [d for d in palace.iter_drawers() if d.get("metadata", {}).get("wing") == wing]
    if len(drawers) < 2:
        return 0.0

    # Sample queries
    queries = random.sample(drawers, min(sample_size, len(drawers)))
    hits = 0

    for q_drawer in queries:
        q_id = q_drawer["id"]
        q_meta = q_drawer.get("metadata", {})

        # Get true content for similarity
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
    qieo_config: Optional[QIEOConfig] = None,
    thompson_config: Optional[ThompsonConfig] = None,
    objective_k: int = 10,
    objective_samples: int = 30,
) -> CalibrationParams:
    """
    Calibrate FSRS parameters for a wing using QIEO + Thompson Sampling.

    Process:
    1. Thompson Sampling selects evaluation candidates (explore/exploit)
    2. QIEO optimizes parameters to maximize recall@k on candidates
    3. Save calibrated params

    Args:
        palace: DxrkMemory instance
        wing: wing name to calibrate
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
        thompson_config = ThompsonConfig()

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
        test_params = CalibrationParams(a=a, b=b, c=c, pe_lambda=pe_lambda)
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
    )

    save_calibration(Path(palace._path), wing, result)
    return result


def get_calibration_params(palace_path: Path, wing: str) -> CalibrationParams:
    """Get calibration params for a wing (load from file or defaults)."""
    return load_calibration(palace_path, wing)


def list_calibrated_wings(palace_path: Path) -> list[str]:
    """List wings that have calibration files."""
    cal_dir = palace_path / CALIBRATION_DIR
    if not cal_dir.exists():
        return []
    return [f.stem for f in cal_dir.glob("*.json")]

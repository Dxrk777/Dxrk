# SPDX-License-Identifier: MIT
"""Metacognición Avanzada — Temperature Scaling, Isotonic Regression, Bias Detection (Fleming & Dolan 2012)."""

from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class MetacogState:
    """Metacognitive state with calibration and bias tracking."""

    calibration_error: float = 0.0  # ECE actual
    bias_direction: float = 0.0  # >0 overconfident, <0 underconfident
    temperature: float = 1.0  # temperature scaling factor
    isotonic_map: dict[str, float] | None = None  # {bin_center: calibrated_prob}
    confidence_bins: dict[str, dict] = field(default_factory=dict)  # bin -> {count, correct, conf_sum}
    bias_history: list[float] = field(default_factory=list)
    introspection_log: list[dict] = field(default_factory=list)
    n_judgments: int = 0
    last_calibration: str = ""
    n_bins: int = 10


METACOG_SIDECAR = ".metacog_state.json"
MAX_INTROSPECTION = 1000
BIAS_EMA_ALPHA = 0.05
EMA_ALPHA = 0.05
MIN_JUDGMENTS_FOR_ECE = 30
MAX_INTROSPECTION_LOG = 1000


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_metacog_state(palace_path: Path) -> MetacogState:
    """Load metacognitive state from sidecar JSON."""
    path = palace_path / METACOG_SIDECAR
    if not path.exists():
        return MetacogState()
    try:
        data = json.loads(path.read_text())
        return MetacogState(
            calibration_error=data.get("calibration_error", 0.0),
            bias_direction=data.get("bias_direction", 0.0),
            temperature=data.get("temperature", 1.0),
            isotonic_map=data.get("isotonic_map"),
            confidence_bins=data.get("confidence_bins", {}),
            bias_history=data.get("bias_history", []),
            introspection_log=data.get("introspection_log", []),
            n_judgments=data.get("n_judgments", 0),
            last_calibration=data.get("last_calibration", ""),
            n_bins=data.get("n_bins", 10),
        )
    except Exception:
        return MetacogState()


def save_metacog_state(palace_path: Path, state: MetacogState) -> None:
    """Persist metacognitive state to sidecar JSON (0o600)."""
    path = palace_path / METACOG_SIDECAR
    data = {
        "calibration_error": state.calibration_error,
        "bias_direction": state.bias_direction,
        "temperature": state.temperature,
        "isotonic_map": state.isotonic_map,
        "confidence_bins": state.confidence_bins,
        "bias_history": state.bias_history,
        "introspection_log": state.introspection_log[-MAX_INTROSPECTION_LOG:],
        "n_judgments": state.n_judgments,
        "last_calibration": state.last_calibration,
        "n_bins": state.n_bins,
    }
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def compute_ece_from_bins(bins: dict[str, dict], total: int) -> float:
    """Expected Calibration Error from bin statistics."""
    ece = 0.0
    for bin_idx, stats in bins.items():
        count = stats.get("count", 0)
        if count == 0:
            continue
        acc = stats.get("correct", 0) / count
        conf = stats.get("conf_sum", 0) / count
        ece += (count / total) * abs(acc - conf)
    return ece


def compute_ece_history(introspection: list[dict], n_bins: int = 10) -> float:
    """Compute ECE from full introspection history."""
    if len(introspection) < MIN_JUDGMENTS_FOR_ECE:
        return 0.0

    bin_counts = [0] * n_bins
    bin_correct = [0] * n_bins
    bin_conf = [0.0] * n_bins

    for entry in introspection:
        pred = entry.get("predicted", 0.5)
        actual = entry.get("actual", 0)
        bin_idx = min(int(pred * n_bins), n_bins - 1)
        bin_counts[bin_idx] += 1
        bin_conf[bin_idx] += pred
        bin_correct[bin_idx] += actual

    ece = 0.0
    total = len(introspection)
    for i in range(n_bins):
        if bin_counts[i] > 0:
            acc = bin_correct[i] / bin_counts[i]
            conf = bin_conf[i] / bin_counts[i]
            ece += (bin_counts[i] / total) * abs(acc - conf)
    return ece


def record_judgment(
    state: MetacogState,
    predicted: float,
    actual: float,
    context: dict | None = None,
) -> MetacogState:
    """
    Record a judgment (prediction vs outcome) and update metacognitive state.

    Args:
        state: current MetacogState
        predicted: confidence prediction [0, 1]
        actual: binary outcome (0 or 1)
        context: optional context (wing, query_type, etc.)

    Returns:
        Updated MetacogState
    """
    predicted = clamp(predicted)
    actual = 1.0 if actual else 0.0

    # Update bias (EMA)
    error = predicted - actual
    new_bias = state.bias_direction * (1 - BIAS_EMA_ALPHA) + error * BIAS_EMA_ALPHA

    # Update confidence bins
    n_bins = state.n_bins
    bins = dict(state.confidence_bins)
    bin_idx = min(int(predicted * n_bins), n_bins - 1)
    bin_key = str(bin_idx)

    if bin_key not in bins:
        bins[bin_key] = {"count": 0, "correct": 0, "conf_sum": 0.0}
    bins[bin_key]["count"] += 1
    bins[bin_key]["correct"] += actual
    bins[bin_key]["conf_sum"] += predicted

    # Introspection log
    log_entry = {
        "ts": _now_iso(),
        "predicted": predicted,
        "actual": actual,
        "error": error,
        "context": context or {},
    }
    new_log = state.introspection_log + [log_entry]
    if len(new_log) > MAX_INTROSPECTION_LOG:
        new_log = new_log[-MAX_INTROSPECTION_LOG:]

    # Recompute ECE
    total = sum(b.get("count", 0) for b in bins.values())
    ece = compute_ece_from_bins(bins, total) if total > 0 else 0.0

    return MetacogState(
        calibration_error=ece,
        bias_direction=new_bias,
        temperature=state.temperature,
        isotonic_map=state.isotonic_map,
        confidence_bins=bins,
        bias_history=state.bias_history + [new_bias],
        introspection_log=new_log,
        n_judgments=state.n_judgments + 1,
        last_calibration=state.last_calibration,
        n_bins=state.n_bins,
    )


def temperature_scaling(predicted: float, temperature: float) -> float:
    """Apply temperature scaling to confidence.

    Standard convention:
    - T > 1: softens predictions (pushes toward 0.5) - for overconfident models
    - T < 1: sharpens predictions (pushes toward 0/1) - for underconfident models
    """
    if predicted <= 0:
        return 0.0
    if predicted >= 1:
        return 1.0
    logit = math.log(predicted / (1 - predicted))
    # Standard temperature scaling: scaled = sigmoid(logit / T)
    # T > 1 softens (toward 0.5), T < 1 sharpens (toward 0/1)
    scaled = 1.0 / (1.0 + math.exp(-logit / temperature))
    return clamp(scaled)


def fit_temperature(introspection: list[dict], max_iter: int = 100, lr: float = 0.01) -> float:
    """
    Fit temperature scaling parameter using gradient descent on NLL.

    Standard convention:
    - T > 1: softens predictions (for overconfident models)
    - T < 1: sharpens predictions (for underconfident models)
    """
    if len(introspection) < MIN_JUDGMENTS_FOR_ECE:
        return 1.0

    T = 1.0
    for _ in range(max_iter):
        grad = 0.0
        for entry in introspection:
            p = entry.get("predicted", 0.5)
            y = entry.get("actual", 0)
            if p <= 0 or p >= 1:
                continue
            logit = math.log(p / (1 - p))
            p_scaled = 1.0 / (1.0 + math.exp(-logit / T))
            p_scaled = clamp(p_scaled, 1e-6, 1 - 1e-6)
            # Gradient of NLL w.r.t T: d(NLL)/dT = (y - p_scaled) * logit / T^2
            # For overconfident (y=0, p_scaled high): grad negative -> T increases (softens)
            # For underconfident (y=1, p_scaled low): grad positive -> T decreases (sharpens)
            grad += (y - p_scaled) * logit / (T * T)
        T = max(0.1, T - lr * grad)
        if abs(grad) < 1e-6:
            break
    return clamp(T, 0.1, 10.0)


def fit_isotonic(introspection: list[dict], n_bins: int = 10) -> dict[str, float]:
    """
    Fit isotonic regression (PAVA) for confidence calibration.
    Returns map from bin_center -> calibrated_probability.
    """
    if len(introspection) < MIN_JUDGMENTS_FOR_ECE:
        return {}

    # Bin predictions
    bin_data: dict[float, dict[str, list[float]]] = defaultdict(lambda: {"preds": [], "actuals": []})
    for entry in introspection:
        p = entry.get("predicted", 0.5)
        y = entry.get("actual", 0)
        bin_idx = min(int(p * n_bins), n_bins - 1)
        center = (bin_idx + 0.5) / n_bins
        bin_data[center]["preds"].append(p)
        bin_data[center]["actuals"].append(y)

    # Compute mean prediction and accuracy per bin
    points = []
    for center, data in bin_data.items():
        if not data["preds"]:
            continue
        mean_pred = sum(data["preds"]) / len(data["preds"])
        mean_actual = sum(data["actuals"]) / len(data["actuals"])
        weight = len(data["preds"])
        points.append((mean_pred, mean_actual, weight))

    if len(points) < 2:
        return {}

    # PAVA (Pool Adjacent Violators Algorithm)
    points.sort(key=lambda x: x[0])  # sort by mean_pred

    # Initialize blocks
    blocks = []
    for pred, actual, weight in points:
        blocks.append({"pred": pred, "actual": actual, "weight": weight})

    # Merge adjacent violators
    i = 0
    while i < len(blocks) - 1:
        if blocks[i]["actual"] > blocks[i + 1]["actual"]:
            # Merge blocks i and i+1
            w1, w2 = blocks[i]["weight"], blocks[i + 1]["weight"]
            new_pred = (blocks[i]["pred"] * w1 + blocks[i + 1]["pred"] * w2) / (w1 + w2)
            new_actual = (blocks[i]["actual"] * w1 + blocks[i + 1]["actual"] * w2) / (w1 + w2)
            blocks[i] = {"pred": new_pred, "actual": new_actual, "weight": w1 + w2}
            blocks.pop(i + 1)
            # Check if need to merge backwards
            if i > 0:
                i -= 1
        else:
            i += 1

    # Build map
    result = {}
    for block in blocks:
        result[str(block["pred"])] = block["actual"]
    return result


def apply_isotonic(predicted: float, isotonic_map: dict[str, float]) -> float:
    """Apply isotonic calibration map to prediction."""
    if not isotonic_map:
        return predicted
    # Find closest key
    keys = sorted(float(k) for k in isotonic_map.keys())
    if not keys:
        return predicted
    idx = bisect.bisect_left(keys, predicted)
    if idx == 0:
        return isotonic_map[str(keys[0])]
    if idx == len(keys):
        return isotonic_map[str(keys[-1])]
    # Interpolate between neighbors
    lo, hi = keys[idx - 1], keys[idx]
    lo_val = isotonic_map[str(lo)]
    hi_val = isotonic_map[str(hi)]
    if hi == lo:
        return lo_val
    alpha = (predicted - lo) / (hi - lo)
    return clamp(lo_val + alpha * (hi_val - lo_val))


def detect_bias(state: MetacogState, window: int = 100) -> dict:
    """Detect bias patterns in recent history."""
    log = state.introspection_log[-window:]
    if len(log) < 10:
        return {"overall_bias": state.bias_direction, "recent_bias": 0.0, "category_bias": {}}

    recent_bias = sum(e["error"] for e in log) / len(log)

    # Category bias (by context)
    cat_bias = defaultdict(list)
    for e in log:
        ctx = e.get("context", {})
        for k, v in ctx.items():
            cat_bias[f"{k}={v}"].append(e["error"])

    category_bias = {}
    for cat, errors in cat_bias.items():
        if len(errors) >= 5:
            category_bias[cat] = sum(errors) / len(errors)

    return {
        "overall_bias": state.bias_direction,
        "recent_bias": recent_bias,
        "category_bias": category_bias,
    }


def calibrate_confidence(
    state: MetacogState,
    raw_confidence: float,
    method: str = "auto",
) -> float:
    """
    Apply full calibration pipeline to raw confidence.

    Methods:
    - "temperature": only temperature scaling
    - "isotonic": only isotonic regression
    - "auto": both (isotonic if available, else temperature)
    - "none": no calibration
    """
    raw_confidence = clamp(raw_confidence)

    if method == "none":
        return raw_confidence

    if method == "temperature":
        return temperature_scaling(raw_confidence, state.temperature)

    if method == "isotonic":
        return apply_isotonic(raw_confidence, state.isotonic_map or {})

    # Auto: prefer isotonic if available and enough data
    if state.isotonic_map and state.n_judgments >= MIN_JUDGMENTS_FOR_ECE:
        return apply_isotonic(raw_confidence, state.isotonic_map)
    elif state.temperature != 1.0:
        return temperature_scaling(raw_confidence, state.temperature)
    else:
        return raw_confidence


def run_calibration(palace_path: Path) -> MetacogState:
    """Run full calibration: fit temperature + isotonic, save state."""
    state = load_metacog_state(palace_path)

    if state.n_judgments < MIN_JUDGMENTS_FOR_ECE:
        return state

    # Fit temperature
    T = fit_temperature(state.introspection_log)

    # Fit isotonic
    iso_map = fit_isotonic(state.introspection_log, state.n_bins)

    # Update state
    new_state = MetacogState(
        calibration_error=state.calibration_error,
        bias_direction=state.bias_direction,
        temperature=T,
        isotonic_map=iso_map,
        confidence_bins=state.confidence_bins,
        bias_history=state.bias_history,
        introspection_log=state.introspection_log,
        n_judgments=state.n_judgments,
        last_calibration=_now_iso(),
        n_bins=state.n_bins,
    )

    save_metacog_state(palace_path, new_state)
    return new_state


def get_metacog_summary(state: MetacogState) -> dict:
    """Get human-readable summary of metacognitive state."""
    return {
        "calibration_error": round(state.calibration_error, 4),
        "bias_direction": round(state.bias_direction, 4),
        "temperature": round(state.temperature, 4),
        "has_isotonic": state.isotonic_map is not None and len(state.isotonic_map) > 0,
        "n_judgments": state.n_judgments,
        "last_calibration": state.last_calibration,
        "bias_stats": {
            "overall": round(state.bias_direction, 4),
            "history_len": len(state.bias_history),
        },
    }


@dataclass(frozen=True)
class MetacognitionPrediction:
    """Result of metacognitive prediction."""

    confidence: float
    difficulty: float
    ece: float
    calibrated_confidence: float | None = None
    bias_info: dict | None = None


from dxrk.memory.palace import DxrkMemory


class MetacognitionV2:
    """Wrapper class for metacognitive operations (MCP/CLI compatible)."""

    def __init__(self, palace: DxrkMemory):
        self.palace = palace
        from pathlib import Path

        self._palace_path = Path(palace._path) if hasattr(palace, "_path") else Path(".")
        self._state = load_metacog_state(self._palace_path)

    def predict(self, query: str, wing: str = "default") -> MetacognitionPrediction:
        """Get metacognitive prediction for a query."""
        # Use palace search to estimate difficulty
        results = self.palace.search(query, wing=wing, n_results=5)
        hits_raw = results.get("results", []) if isinstance(results, dict) else []
        hits: list = hits_raw if isinstance(hits_raw, list) else []

        # Estimate difficulty from result count and scores
        difficulty = 1.0 - min(len(hits) / 10.0, 1.0)

        # Get calibrated confidence
        raw_confidence = 0.5 + (1.0 - difficulty) * 0.5  # heuristic
        calibrated = calibrate_confidence(self._state, raw_confidence, method="auto")

        # Get bias info
        bias_info = detect_bias(self._state)

        return MetacognitionPrediction(
            confidence=calibrated,
            difficulty=difficulty,
            ece=self._state.calibration_error,
            calibrated_confidence=calibrated,
            bias_info=bias_info,
        )

    def fit_calibration(self, wing: str = "default", method: str = "temperature") -> dict:
        """Fit calibration and return parameters."""
        # Run full calibration
        new_state = run_calibration(self._palace_path)
        self._state = new_state
        return {
            "temperature": new_state.temperature,
            "has_isotonic": new_state.isotonic_map is not None,
            "ece": new_state.calibration_error,
            "bias": new_state.bias_direction,
            "n_judgments": new_state.n_judgments,
        }

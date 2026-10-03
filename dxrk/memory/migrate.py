# SPDX-License-Identifier: MIT
"""Lazy spine migration + score ledger for the RDU ranking model (Fase 0).

Schema v2 spine keys carried on every drawer metadata dict:

- ``S`` (stability, days), ``D`` (difficulty 1..10), ``rd`` (rating
  deviation), ``s_updates`` — the FSRS-style memory state.
- ``content_sha256`` — integrity checksum (``""`` means needs rehash).
- ``quarantined`` / ``quarantine_reason`` / ``quarantined_at``.
- ``score_ledger`` (hash-chained, capped) + ``score_ledger_dropped``.
- ``access_history`` (ISO timestamps, capped) + ``access_count_total``.

stdlib only, no imports from the palace (palace imports this module).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

SCHEMA_VERSION = 2
LEDGER_CAP = 20
ACCESS_HISTORY_CAP = 20

SPINE_S_DEFAULT = 1.0
SPINE_D_DEFAULT = 5.0
SPINE_RD_DEFAULT = 350.0


def content_sha256_of(content: str) -> str:
    """Hex sha256 of drawer content (integrity checksum)."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def needs_rehash(meta: dict[str, object]) -> bool:
    """True when the drawer has no usable checksum (implicit rehash flag)."""
    sha = meta.get("content_sha256")
    return not (isinstance(sha, str) and sha.strip() != "")


def _to_float(value: object, default: float) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _to_int(value: object, default: int = 0) -> int:
    try:
        result = int(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return int(max(0, result))


def _to_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str) and v]
    return []


def ensure_spine_defaults(meta: dict[str, object]) -> dict[str, object]:
    """Fill missing RDU spine keys in place; idempotent, never raises.

    Legacy rows (``schema_version < 2``) get migrated priors derived from
    the existing access signal ``n = access_count``:

    - ``S = 1 + log1p(n)``, ``D = 5.0``, ``rd = 350 / (1 + n)``,
    - ``access_history = [accessed_at]`` when present,
    - ``access_count_total`` mirrors ``access_count``,
    - ``content_sha256 = ""`` (marks the row for rehash on next read).

    Rows already at schema >= 2 only get plain defaults for keys that are
    absent or mistyped. Always stamps ``schema_version = 2``.
    """
    schema = meta.get("schema_version")
    legacy = not (isinstance(schema, (int, float)) and schema >= 2)
    n = _to_int(meta.get("access_count", 0))

    if legacy:
        if not isinstance(meta.get("S"), (int, float)):
            meta["S"] = 1.0 + math.log1p(n)
        if not isinstance(meta.get("D"), (int, float)):
            meta["D"] = SPINE_D_DEFAULT
        if not isinstance(meta.get("rd"), (int, float)):
            meta["rd"] = SPINE_RD_DEFAULT / (1 + n)
        if not isinstance(meta.get("s_updates"), int) or isinstance(meta.get("s_updates"), bool):
            meta["s_updates"] = 0
        if not isinstance(meta.get("content_sha256"), str) or not str(meta.get("content_sha256")).strip():
            meta["content_sha256"] = ""
        if not isinstance(meta.get("access_history"), list):
            accessed = meta.get("accessed_at")
            meta["access_history"] = [accessed] if isinstance(accessed, str) and accessed else []
        else:
            meta["access_history"] = _to_str_list(meta.get("access_history"))
        if not isinstance(meta.get("access_count_total"), int) or isinstance(meta.get("access_count_total"), bool):
            meta["access_count_total"] = n
        if not isinstance(meta.get("score_ledger"), list):
            meta["score_ledger"] = []
        if not isinstance(meta.get("score_ledger_dropped"), int) or isinstance(meta.get("score_ledger_dropped"), bool):
            meta["score_ledger_dropped"] = 0
        if not isinstance(meta.get("quarantined"), bool):
            meta["quarantined"] = False
        if not isinstance(meta.get("quarantine_reason"), str):
            meta["quarantine_reason"] = ""
        if not isinstance(meta.get("quarantined_at"), str):
            meta["quarantined_at"] = ""
    else:
        meta.setdefault("S", SPINE_S_DEFAULT)
        meta.setdefault("D", SPINE_D_DEFAULT)
        meta.setdefault("rd", SPINE_RD_DEFAULT)
        meta.setdefault("s_updates", 0)
        meta.setdefault("content_sha256", "")
        meta.setdefault("access_history", [])
        if not isinstance(meta.get("access_count_total"), int) or isinstance(meta.get("access_count_total"), bool):
            meta["access_count_total"] = _to_int(meta.get("access_count", 0))
        meta.setdefault("score_ledger", [])
        meta.setdefault("score_ledger_dropped", 0)
        meta.setdefault("quarantined", False)
        meta.setdefault("quarantine_reason", "")
        meta.setdefault("quarantined_at", "")

    # Normalize numeric/bool shapes (sqlite round-trips ints as ints, but
    # hand-written rows may carry strings or bools-as-ints).
    meta["S"] = _to_float(meta.get("S"), SPINE_S_DEFAULT)
    meta["D"] = _to_float(meta.get("D"), SPINE_D_DEFAULT)
    meta["rd"] = _to_float(meta.get("rd"), SPINE_RD_DEFAULT)
    if not isinstance(meta.get("s_updates"), int) or isinstance(meta.get("s_updates"), bool):
        meta["s_updates"] = _to_int(meta.get("s_updates"), 0)
    if not isinstance(meta.get("score_ledger_dropped"), int) or isinstance(meta.get("score_ledger_dropped"), bool):
        meta["score_ledger_dropped"] = 0
    if not isinstance(meta.get("quarantined"), bool):
        meta["quarantined"] = bool(meta.get("quarantined"))
    meta["schema_version"] = SCHEMA_VERSION
    return meta


def _ledger_hash(prev_hash: str, ts: str, score: float, stability: float, difficulty: float, reason: str) -> str:
    payload = {"ts": ts, "score": score, "S": stability, "D": difficulty, "reason": reason}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def ledger_append(
    meta: dict[str, object],
    *,
    score: object,
    S: object,
    D: object,
    reason: str,
    ts: str | None = None,
    cap: int = LEDGER_CAP,
) -> dict[str, object]:
    """Append a score event to the hash-chained ledger (in place).

    ``hash = sha256(prev_hash + canonical-payload)`` where the payload is
    ``{ts, score, S, D, reason}``. When the ledger exceeds ``cap`` the
    oldest entry is dropped and ``score_ledger_dropped`` increments (the
    chain then verifies from the oldest *present* entry — see
    :func:`verify_chain`). Returns the appended entry.
    """
    ledger = meta.get("score_ledger")
    if not isinstance(ledger, list):
        ledger = []
        meta["score_ledger"] = ledger
    prev = ""
    for prior in ledger:
        if isinstance(prior, dict) and isinstance(prior.get("hash"), str):
            prev = str(prior["hash"])
    stamp = ts or datetime.now(UTC).isoformat()
    entry: dict[str, object] = {
        "ts": stamp,
        "score": round(_to_float(score, 0.0), 6),
        "S": _to_float(S, SPINE_S_DEFAULT),
        "D": _to_float(D, SPINE_D_DEFAULT),
        "reason": str(reason or ""),
        "prev_hash": prev,
        "hash": "",
    }
    entry["hash"] = _ledger_hash(
        prev,
        str(entry["ts"]),
        float(entry["score"]),  # type: ignore[arg-type]
        float(entry["S"]),  # type: ignore[arg-type]
        float(entry["D"]),  # type: ignore[arg-type]
        str(entry["reason"]),
    )
    ledger.append(entry)
    if len(ledger) > cap:
        overflow = len(ledger) - cap
        del ledger[0:overflow]
        meta["score_ledger_dropped"] = _to_int(meta.get("score_ledger_dropped"), 0) + overflow
    return entry


def verify_chain(meta: dict[str, object]) -> tuple[bool, int]:
    """Verify the score ledger hash chain.

    Returns ``(ok, break_index)`` with ``break_index == -1`` when the
    chain is intact. A non-empty ``score_ledger_dropped`` counter means the
    oldest *present* entry's ``prev_hash`` points at a pruned entry, so its
    linkage is trusted but its own hash is still recomputed. Tampered
    fields, broken links, or malformed entries report their index.
    """
    ledger = meta.get("score_ledger")
    if not ledger:
        return True, -1
    if not isinstance(ledger, list):
        return False, 0
    try:
        dropped = _to_int(meta.get("score_ledger_dropped", 0), 0)
    except (TypeError, ValueError):
        dropped = 0
    prev = ""
    for i, raw in enumerate(ledger):
        if not isinstance(raw, dict):
            return False, i
        entry = raw
        for key in ("ts", "score", "S", "D", "reason", "prev_hash", "hash"):
            if key not in entry:
                return False, i
        if i == 0:
            if dropped <= 0 and str(entry.get("prev_hash") or "") != "":
                return False, i
        elif str(entry.get("prev_hash") or "") != prev:
            return False, i
        try:
            recomputed = _ledger_hash(
                prev if i > 0 else str(entry.get("prev_hash") or ""),
                str(entry.get("ts")),
                round(float(entry.get("score")), 6),  # type: ignore[arg-type]
                float(entry.get("S")),  # type: ignore[arg-type]
                float(entry.get("D")),  # type: ignore[arg-type]
                str(entry.get("reason")),
            )
        except (TypeError, ValueError):
            return False, i
        if recomputed != str(entry.get("hash")):
            return False, i
        prev = str(entry.get("hash"))
    return True, -1


def merkle_root(metas: Iterable[dict[str, object]]) -> str:
    """Palace integrity root: sha256 over sorted non-empty content checksums.

    Returns ``""`` when no drawer carries a checksum yet (nothing to commit
    to). Any checksum change, add, or removal changes the root.
    """
    hashes = sorted(
        str(m.get("content_sha256"))
        for m in metas
        if isinstance(m, dict) and isinstance(m.get("content_sha256"), str) and str(m.get("content_sha256")).strip()
    )
    if not hashes:
        return ""
    return hashlib.sha256("".join(hashes).encode("utf-8")).hexdigest()

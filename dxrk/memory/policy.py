# SPDX-License-Identifier: MIT
"""Palace policy engine — RBAC-gated background triggers (Fase 0 tanda 2).

``PolicyEngine(palace).maybe_run(trigger)`` runs hygiene triggers that
write paths cannot afford inline:

- ``write``    -> ``over_budget`` only (wing.count > cap -> enforce_wing_cap).
- ``periodic`` -> ``rescore_stale`` + ``checksum_sweep`` + ``quarantine_sweep``,
  each at most once per ``min_interval_seconds`` (default 15 min), tracked
  in the ``<palace>/.policy_state.json`` sidecar (``last_run`` per trigger
  plus the sweep rotation ``cursor``).

Every trigger runs as the effective tenant under the palace lock and
requires the ``memory.maintain`` cap via
``require_op(tenant, "system:policy", "memory.maintain")`` — without an
explicit grant it aborts with ``PermissionError("RBAC_DENIED: ...")``.
The RBAC check is never bypassed (local trusted mode — no tenant
configured — follows the same ``require_op`` semantics as every caller).

stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("dxrk.memory.policy")

TRIGGER_WRITE = "write"
TRIGGER_PERIODIC = "periodic"

TRIGGER_OVER_BUDGET = "over_budget"
TRIGGER_RESCORE_STALE = "rescore_stale"
TRIGGER_CHECKSUM_SWEEP = "checksum_sweep"
TRIGGER_QUARANTINE_SWEEP = "quarantine_sweep"

PERIODIC_TRIGGERS: tuple[str, ...] = (
    TRIGGER_RESCORE_STALE,
    TRIGGER_CHECKSUM_SWEEP,
    TRIGGER_QUARANTINE_SWEEP,
)

POLICY_STATE_FILE = ".policy_state.json"
POLICY_MIN_INTERVAL_SECONDS = 900.0  # 15 min
RESCORE_STALE_DAYS = 30.0
CHECKSUM_SWEEP_WINDOW = 200
POLICY_SCAN_LIMIT = 5000


def _is_dead(meta: object) -> bool:
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("valid_to") or meta.get("forgotten") or meta.get("quarantined"))


class PolicyEngine:
    """Hygiene triggers for one palace; see module docstring."""

    def __init__(
        self,
        palace: Any,
        *,
        sweep_window: int = CHECKSUM_SWEEP_WINDOW,
        stale_days: float = RESCORE_STALE_DAYS,
        min_interval_seconds: float = POLICY_MIN_INTERVAL_SECONDS,
        scan_limit: int = POLICY_SCAN_LIMIT,
    ) -> None:
        self._palace = palace
        try:
            self._sweep_window = max(1, int(sweep_window))
        except (TypeError, ValueError):
            self._sweep_window = CHECKSUM_SWEEP_WINDOW
        try:
            self._stale_days = max(0.0, float(stale_days))
        except (TypeError, ValueError):
            self._stale_days = RESCORE_STALE_DAYS
        try:
            self._min_interval = max(0.0, float(min_interval_seconds))
        except (TypeError, ValueError):
            self._min_interval = POLICY_MIN_INTERVAL_SECONDS
        try:
            self._scan_limit = max(1, int(scan_limit))
        except (TypeError, ValueError):
            self._scan_limit = POLICY_SCAN_LIMIT

    # -- entry point ----------------------------------------------------

    def maybe_run(self, trigger: str = TRIGGER_PERIODIC) -> dict[str, object]:
        """Run ``trigger`` (``"write"`` | ``"periodic"``) and return a report.

        Raises ``ValueError`` on unknown triggers and ``PermissionError``
        (``RBAC_DENIED``) when the effective tenant holds no
        ``memory.maintain`` grant for the ``system:policy`` actor.
        """
        from dxrk.security.enforcement import require_op

        from .palace import mine_palace_lock

        if trigger not in (TRIGGER_WRITE, TRIGGER_PERIODIC):
            raise ValueError(f"invalid policy trigger {trigger!r} (expected 'write' | 'periodic')")
        tenant = (getattr(self._palace, "tenant_id", "") or os.environ.get("DXRK_TENANT", "") or "").strip()
        require_op(tenant, "system:policy", "memory.maintain")
        palace_path = str(getattr(self._palace, "palace_path", "") or "")
        with mine_palace_lock(palace_path, tenant_id=tenant or None):
            if trigger == TRIGGER_WRITE:
                return {
                    "ok": True,
                    "trigger": TRIGGER_WRITE,
                    "results": {TRIGGER_OVER_BUDGET: self._run_over_budget()},
                }
            state = self._read_state()
            now = datetime.now(UTC)
            results: dict[str, object] = {}
            for name in PERIODIC_TRIGGERS:
                if not self._due(state, name, now):
                    results[name] = {"skipped": True, "reason": "throttled"}
                    continue
                results[name] = self._run_named(name)
                state = self._read_state()
                self._stamp(state, name, now)
                self._write_state(state)
            return {"ok": True, "trigger": TRIGGER_PERIODIC, "results": results}

    def _run_named(self, name: str) -> dict[str, object]:
        if name == TRIGGER_RESCORE_STALE:
            return self._run_rescore_stale()
        if name == TRIGGER_CHECKSUM_SWEEP:
            return self._run_checksum_sweep()
        if name == TRIGGER_QUARANTINE_SWEEP:
            return self._run_quarantine_sweep()
        raise ValueError(f"invalid policy trigger {name!r}")

    # -- triggers -------------------------------------------------------

    def _run_over_budget(self) -> dict[str, object]:
        wings_over: list[str] = []
        evicted = 0
        try:
            wings = self._palace.list_wings()
        except Exception:
            logger.debug("Policy over_budget list_wings failed", exc_info=True)
            return {"wings_over": wings_over, "evicted": evicted}
        for wing in wings:
            try:
                usage = self._palace.wing_usage(str(wing))
            except Exception:
                logger.debug("Policy over_budget wing_usage failed for %s", wing, exc_info=True)
                continue
            if isinstance(usage, dict) and usage.get("over"):
                wings_over.append(str(wing))
                try:
                    evicted += int(self._palace.enforce_wing_cap(str(wing)))
                except Exception:
                    logger.debug("Policy over_budget eviction failed for %s", wing, exc_info=True)
        return {"wings_over": sorted(wings_over), "evicted": evicted}

    def _run_rescore_stale(self) -> dict[str, object]:
        from .migrate import ensure_spine_defaults, ledger_append
        from .scoring import parse_dt, score_meta

        col = self._palace._collection(create=False)
        try:
            got = col.get(include=["metadatas"], limit=self._scan_limit)
        except Exception:
            logger.debug("Policy rescore_stale scan failed", exc_info=True)
            return {"scanned": 0, "rescored": 0}
        now = datetime.now(UTC)
        scanned = 0
        rescored = 0
        for rid, raw in zip(got.ids, got.metadatas):
            scanned += 1
            if not isinstance(raw, dict) or _is_dead(raw):
                continue
            meta = ensure_spine_defaults(dict(raw))
            filed_dt = parse_dt(meta.get("filed_at"))
            if filed_dt is None:
                continue
            if filed_dt.tzinfo is None:
                filed_dt = filed_dt.replace(tzinfo=UTC)
            if (now - filed_dt).total_seconds() / 86400.0 <= self._stale_days:
                continue
            ledger = meta.get("score_ledger")
            entries = [e for e in ledger if isinstance(e, dict)] if isinstance(ledger, list) else []
            if entries:
                last_ts = parse_dt(entries[-1].get("ts"))
                if last_ts is not None:
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=UTC)
                    if (now - last_ts).total_seconds() / 86400.0 <= self._stale_days:
                        continue
            try:
                s_val = float(cast(Any, meta.get("S", 1.0)))
            except (TypeError, ValueError):
                s_val = 1.0
            try:
                d_val = float(cast(Any, meta.get("D", 5.0)))
            except (TypeError, ValueError):
                d_val = 5.0
            try:
                ledger_append(meta, score=score_meta(meta), S=s_val, D=d_val, reason="rescore_stale")
                col.update(ids=[rid], metadatas=[meta])
                rescored += 1
            except Exception:
                logger.debug("Policy rescore_stale persist failed for %s", rid, exc_info=True)
        return {"scanned": scanned, "rescored": rescored}

    def _run_checksum_sweep(self) -> dict[str, object]:
        from .migrate import content_sha256_of

        col = self._palace._collection(create=False)
        try:
            all_got = col.get(include=["metadatas"], limit=self._scan_limit)
        except Exception:
            logger.debug("Policy checksum_sweep scan failed", exc_info=True)
            return {"checked": 0, "ok": 0, "rehashed": 0, "mismatches": []}
        ids = list(all_got.ids)
        total = len(ids)
        if total == 0:
            return {"checked": 0, "ok": 0, "rehashed": 0, "mismatches": []}
        state = self._read_state()
        try:
            cursor = int(cast(Any, state.get("cursor", 0))) % total
        except (TypeError, ValueError):
            cursor = 0
        window_ids = [ids[(cursor + i) % total] for i in range(min(self._sweep_window, total))]
        try:
            got = col.get(ids=window_ids, include=["documents", "metadatas"])
        except Exception:
            logger.debug("Policy checksum_sweep window fetch failed", exc_info=True)
            return {"checked": 0, "ok": 0, "rehashed": 0, "mismatches": []}
        by_id = {rid: (doc, meta) for rid, doc, meta in zip(got.ids, got.documents, got.metadatas)}
        checked = 0
        ok = 0
        rehashed = 0
        mismatches: list[str] = []
        for rid in window_ids:
            doc, raw = by_id.get(rid, ("", {}))
            checked += 1
            meta = dict(raw) if isinstance(raw, dict) else {}
            text = doc if isinstance(doc, str) else ""
            stored = meta.get("content_sha256")
            if not (isinstance(stored, str) and stored.strip()):
                meta["content_sha256"] = content_sha256_of(text)
                try:
                    col.update(ids=[rid], metadatas=[meta])
                    rehashed += 1
                except Exception:
                    logger.debug("Policy checksum_sweep rehash failed for %s", rid, exc_info=True)
                continue
            if stored == content_sha256_of(text):
                ok += 1
            else:
                mismatches.append(rid)
        state["cursor"] = (cursor + len(window_ids)) % total
        self._write_state(state)
        return {"checked": checked, "ok": ok, "rehashed": rehashed, "mismatches": sorted(mismatches)}

    def _run_quarantine_sweep(self) -> dict[str, object]:
        from .migrate import content_sha256_of

        col = self._palace._collection(create=False)
        try:
            got = col.get(include=["documents", "metadatas"], limit=self._scan_limit)
        except Exception:
            logger.debug("Policy quarantine_sweep scan failed", exc_info=True)
            return {"scanned": 0, "quarantined": [], "reasons": {}}
        scanned = 0
        quarantined: list[str] = []
        reasons: dict[str, str] = {}
        for rid, doc, raw in zip(got.ids, got.documents, got.metadatas):
            scanned += 1
            if isinstance(raw, dict) and raw.get("quarantined"):
                continue
            text = doc if isinstance(doc, str) else ""
            reason = ""
            if not isinstance(raw, dict):
                reason = "invalid_metadata"
            elif not text.strip():
                reason = "empty_document"
            else:
                stored = raw.get("content_sha256")
                if isinstance(stored, str) and stored.strip() and stored != content_sha256_of(text):
                    reason = "checksum_mismatch"
            if not reason:
                continue
            try:
                if self._palace.quarantine_drawer(rid, reason=reason):
                    quarantined.append(rid)
                    reasons[rid] = reason
            except Exception:
                logger.debug("Policy quarantine_sweep failed for %s", rid, exc_info=True)
        return {"scanned": scanned, "quarantined": sorted(quarantined), "reasons": reasons}

    # -- sidecar state --------------------------------------------------

    def _state_path(self) -> Path | None:
        palace_path = str(getattr(self._palace, "palace_path", "") or "")
        if not palace_path or palace_path in ("memory-only",):
            return None
        try:
            return Path(palace_path) / POLICY_STATE_FILE
        except Exception:
            return None

    def _read_state(self) -> dict[str, object]:
        path = self._state_path()
        if path is None or not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, object]) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            logger.debug("Policy state write failed", exc_info=True)

    def _stamp(self, state: dict[str, object], name: str, now: datetime) -> dict[str, object]:
        last_run = state.get("last_run")
        if not isinstance(last_run, dict):
            last_run = {}
            state["last_run"] = last_run
        last_run[name] = now.isoformat()
        return state

    def _due(self, state: dict[str, object], name: str, now: datetime) -> bool:
        from .scoring import parse_dt

        last_run = state.get("last_run")
        if not isinstance(last_run, dict):
            return True
        last_ts = parse_dt(last_run.get(name))
        if last_ts is None:
            return True
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)
        return (now - last_ts).total_seconds() >= self._min_interval

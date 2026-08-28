# SPDX-License-Identifier: MIT
"""Shared date-window parsing for read-path filters.

DxrkMemory date windowing — stdlib only, wall-clock inclusive/exclusive.
``since``/``before`` bounds are compared against drawer ``filed_at`` metadata.
Semantics: ``since`` inclusive, ``before`` exclusive: ``[since, before)``.
Comparison is wall-clock and timezone-naive. ``filed_at`` values are written
as naive local ISO strings (``datetime.now().isoformat()``) or aware UTC;
the offset is dropped for wall-clock comparison.
A drawer whose ``filed_at`` is missing or unparseable is EXCLUDED whenever
a bound is active.
"""

from __future__ import annotations

from datetime import datetime


def parse_date_bound(value: str | None = None, field_name: str = "date") -> datetime | None:
    """Parse an optional ISO-8601 date/datetime filter bound.

    Accepts a date (``"2026-04-01"``), a naive timestamp
    (``"2026-04-01T09:30:00"``), or one carrying a ``Z``/``+HH:MM`` offset.
    Returns a naive ``datetime`` for wall-clock comparison against drawer
    ``filed_at`` values. Any timezone offset on the input is dropped so an
    aware bound never raises ``TypeError`` against a naive ``filed_at``.
    Blank / whitespace-only means "no filter" (``None``).
    Raises ``ValueError`` on unparseable value.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string")
    value = value.strip()
    if not value:
        return None
    iso = value[:-1] if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be an ISO date string "
            f"(e.g. '2026-04-01' or '2026-04-01T09:30:00'), got {value!r}"
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed


def parse_window(since: str | None = None, before: str | None = None) -> tuple[datetime | None, datetime | None]:
    """Parse a ``[since, before)`` pair, rejecting an inverted window.

    Returns ``(since_dt, before_dt)`` — either side ``None`` when absent.
    Raises ``ValueError`` naming the offending field or the inversion.
    """
    since_dt = parse_date_bound(since, "since")
    before_dt = parse_date_bound(before, "before")
    if since_dt is not None and before_dt is not None and since_dt >= before_dt:
        raise ValueError(f"since ({since!r}) must be earlier than before ({before!r})")
    return since_dt, before_dt


def filed_at_in_window(
    filed_at: object, since_dt: datetime | None, before_dt: datetime | None
) -> bool:
    """True if a drawer's ``filed_at`` falls in ``[since, before)``.

    ``since`` is inclusive and ``before`` is exclusive.
    A drawer whose ``filed_at`` is missing or unparseable is EXCLUDED
    whenever a bound is active — a date-filtered result must never
    silently include rows of unknown age.
    """
    if since_dt is None and before_dt is None:
        return True
    try:
        # filed_at may be non-str (None, missing, etc.)
        if not isinstance(filed_at, str):
            return False
        filed_dt = parse_date_bound(filed_at, "filed_at")
    except ValueError:
        return False
    if filed_dt is None:
        return False
    if since_dt is not None and filed_dt < since_dt:
        return False
    if before_dt is not None and filed_dt >= before_dt:
        return False
    return True

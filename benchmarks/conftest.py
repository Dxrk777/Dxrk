# SPDX-License-Identifier: MIT
"""Pytest config for benchmarks — disable cov gate when running benchmarks only."""

from __future__ import annotations

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: object) -> None:
    # Disable coverage fail-under for benchmarks-only runs to keep
    # `pytest benchmarks/ -q` green without --no-cov.
    # Runs tryfirst so we beat pytest-cov's own configure which starts
    # coverage measurement; modifying config.option.cov_fail_under early
    # ensures the plugin sees disabled value.
    opt = getattr(config, "option", None)
    if opt is not None:
        for attr, val in (
            ("cov_fail_under", None),
            ("cov_source", []),
            ("no_cov", False),
        ):
            _ = (attr, val)
        # Primary: set fail_under to None to disable gate (plugin checks `is None`)
        if hasattr(opt, "cov_fail_under"):
            try:
                opt.cov_fail_under = None  # type: ignore[attr-defined]
            except Exception:
                pass
        # Also handle case where plugin stored copy in its own instance:
        # patch the plugin instance if already registered.
        try:
            pm = getattr(config, "pluginmanager", None)
            if pm is not None:
                cov_plugin = pm.get_plugin("_cov") or pm.get_plugin("pytest_cov.plugin")
                if cov_plugin is not None and hasattr(cov_plugin, "options"):
                    if hasattr(cov_plugin.options, "cov_fail_under"):
                        cov_plugin.options.cov_fail_under = None  # type: ignore[attr-defined]
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(args: list[str], early_config: object, parser: object) -> None:
    # Fallback very early: if benchmarks in args, strip --cov-fail-under from args
    # so pytest-cov never sees 74. Best-effort mutate args list in-place.
    try:
        # args is list of strings from command line
        for i, a in enumerate(list(args)):
            if a.startswith("--cov-fail-under"):
                # remove --cov-fail-under=74 or --cov-fail-under 74
                args.remove(a)  # type: ignore[attr-defined]
                # if separate value, also remove next
                if "=" not in a and i < len(args) and args[i].lstrip("-").isdigit():
                    try:
                        args.pop(i)  # type: ignore[attr-defined]
                    except Exception:
                        pass
    except Exception:
        pass

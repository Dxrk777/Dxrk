# SPDX-License-Identifier: MIT
"""Tests para dxrk.enterprise.cli — CLI legacy (no usado por dxrk.__main__).

Determinista: sin red ni sleeps. DxrkEnterprise real escribe en
~/.dxrk/enterprise al instanciarse, por eso se sustituye por un doble
via monkeypatch sobre dxrk.enterprise.company.DxrkEnterprise (cli.py lo
importa dentro de cada rama con `from .company import DxrkEnterprise`,
asi el parche se recoge en tiempo de llamada).
"""

from __future__ import annotations

import runpy

import pytest


class FakeCompany:
    last: FakeCompany | None = None

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.executed: list[tuple[str, str | None]] = []
        type(self).last = self

    def start_company(self) -> None:
        self.started = True

    def stop_company(self) -> None:
        self.stopped = True

    def generate_company_report(self) -> str:
        return "FAKE-REPORT"

    def execute_task(self, task: str, dept: str | None = None) -> dict[str, str]:
        self.executed.append((task, dept))
        return {"ok": task, "dept": dept or "auto"}

    def list_all_skills(self) -> dict[str, list[dict[str, object]]]:
        return {
            "developers": [
                {"name": "debug_master", "installed": True},
                {"name": "code_review", "installed": False},
            ],
        }


@pytest.fixture(autouse=True)
def _patch_company(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCompany.last = None
    monkeypatch.setattr("dxrk.enterprise.company.DxrkEnterprise", FakeCompany)


def test_empty_args_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli([])
    assert "DXRK ENTERPRISE CLI" in capsys.readouterr().out


def test_start(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["start"])
    out = capsys.readouterr().out
    assert "Dxrk Enterprise started!" in out
    assert "FAKE-REPORT" in out
    assert FakeCompany.last is not None and FakeCompany.last.started is True


def test_stop(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["stop"])
    assert "Dxrk Enterprise stopped." in capsys.readouterr().out
    assert FakeCompany.last is not None and FakeCompany.last.stopped is True


def test_status(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["status"])
    assert "FAKE-REPORT" in capsys.readouterr().out


def test_execute_without_task_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["execute"])
    assert "Usage: dxrk-py enterprise execute" in capsys.readouterr().out
    assert FakeCompany.last is None


def test_execute_with_task_defaults_dept_none(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["execute", "debug python code"])
    out = capsys.readouterr().out
    assert "Result:" in out
    assert FakeCompany.last is not None
    assert FakeCompany.last.started is True
    assert FakeCompany.last.executed == [("debug python code", None)]


def test_execute_with_explicit_dept(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["execute", "debug python code", "developers"])
    assert "Result:" in capsys.readouterr().out
    assert FakeCompany.last is not None
    assert FakeCompany.last.executed == [("debug python code", "developers")]


def test_skills_lists_yes_no(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["skills"])
    out = capsys.readouterr().out
    assert "DEVELOPERS:" in out
    assert "[yes] debug_master" in out
    assert "[no] code_review" in out


def test_report(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["report"])
    assert "FAKE-REPORT" in capsys.readouterr().out


def test_unknown_command_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import enterprise_cli

    enterprise_cli(["fantasma"])
    out = capsys.readouterr().out
    assert "Unknown command: fantasma" in out
    assert "DXRK ENTERPRISE CLI" in out


def test_print_usage_direct(capsys: pytest.CaptureFixture[str]) -> None:
    from dxrk.enterprise.cli import print_usage

    print_usage()
    out = capsys.readouterr().out
    assert "dxrk-py enterprise start" in out
    assert "dxrk-py enterprise skills" in out


def test_main_guard_runs_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["cli.py", "status"])
    runpy.run_module("dxrk.enterprise.cli", run_name="__main__")
    assert "FAKE-REPORT" in capsys.readouterr().out

# SPDX-License-Identifier: MIT
"""Updater: self-update via git fetch + pull + rebuild"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass

from .permissions import CapFSWrite, CapGit, PermissionStore

UNKNOWN = "unknown"


@dataclass
class CmdResult:
    out: str = ""
    err: bool = False


@dataclass
class UpdateResult:
    updated: bool = False
    before: str = ""
    after: str = ""
    changes: int = 0
    error: str | None = None


class Updater:
    """Checks for upstream commits and pulls + rebuilds the project."""

    def __init__(
        self, project_root: str, interval_sec: int, perms: PermissionStore
    ) -> None:
        self.project_root = project_root
        self.mu = threading.Lock()
        self._last_check: float | None = None
        self.interval = max(interval_sec, 30)
        self.perms = perms

    def check(self, force: bool) -> UpdateResult:
        with self.mu:
            now = time.time()
            if (
                not force
                and self._last_check is not None
                and now - self._last_check < self.interval
            ):
                return UpdateResult(updated=False)
            self._last_check = now

            err = self.perms.check(CapGit, "self-update: git fetch + pull")
            if err:
                return UpdateResult(updated=False, error=err)

            before = self._current_commit()

            fetch = self._git(["fetch", "--all"])
            if fetch.err:
                return UpdateResult(updated=False, error=f"fetch: {fetch.out}")

            log_out = self._git(["log", "HEAD..origin/HEAD", "--oneline"])
            if log_out.err:
                return UpdateResult(updated=False, error=f"log: {log_out.out}")

            changes = log_out.out.count("\n")
            if changes == 0 and not force:
                return UpdateResult(updated=False)

            pull = self._git(["pull", "--rebase"])
            if pull.err:
                return UpdateResult(updated=False, error=f"pull: {pull.out}")

            after = self._current_commit()

            build = self._run_build()
            if build.err:
                return UpdateResult(
                    updated=False,
                    before=before,
                    after=after,
                    changes=changes,
                    error=f"build failed: {build.out}",
                )
            return UpdateResult(
                updated=True, before=before, after=after, changes=changes
            )

    def _current_commit(self) -> str:
        res = self._git(["rev-parse", "--short", "HEAD"])
        if res.err:
            return UNKNOWN
        return res.out.strip()

    def _git(self, args: list[str]) -> CmdResult:
        return _run_cmd_raw(self.project_root, "git", args)

    def _run_build(self) -> CmdResult:
        return _run_cmd_raw(self.project_root, "go", ["build", "./..."])

    def last_check(self) -> float | None:
        with self.mu:
            return self._last_check

    def write_file(self, path: str, content: str) -> str | None:
        err = self.perms.check(CapFSWrite, f"write {path}")
        if err:
            return err
        directory = os.path.dirname(path)
        try:
            os.makedirs(directory, mode=0o750, exist_ok=True)
        except OSError as exc:
            return f"mkdir: {exc}"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as exc:
            return f"write: {exc}"
        return None


def _run_cmd_raw(project_root: str, name: str, args: list[str]) -> CmdResult:
    try:
        proc = subprocess.run(
            [name, *args],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as exc:
        return CmdResult(out=str(exc), err=True)
    return CmdResult(out=proc.stdout or "", err=proc.returncode != 0)


def NewUpdater(project_root: str, interval_sec: int, perms: PermissionStore) -> Updater:
    return Updater(project_root, interval_sec, perms)

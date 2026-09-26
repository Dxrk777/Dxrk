# SPDX-License-Identifier: MIT
"""Permanent parity guard for the modules-plus-facade refactors.

Each facade below (``dxrk.utils.messages``, ``dxrk.cli.install``, ...) is a
thin re-export layer over focused split files. The contract under test:

* every API name *defined* in a submodule is reachable from its facade;
* bound to the very same object (``facade.X is submodule.X``), so imports
  and monkeypatch targets keep working no matter which path callers use.

Two things are deliberately NOT part of the contract:

* names a submodule merely *imports* for its own use (``Any``,
  ``dataclass``, ``datetime``, ``Step``, ``AgentID``, ...). Only real
  definitions count: top-level ``def``/``class``/assignments plus explicit
  ``X as X`` re-exports, mirroring the facade convention;
* module objects (``os``, ``sys``, ...) and module-level loggers, which are
  shared infrastructure rather than API. Every ``log`` binding here is the
  same ``getLogger("dxrk.cli.install")`` singleton, still reachable via the
  sibling facades that re-export it, and no caller references the one
  binding a facade drops (``dxrk.cli.runtime_run.log``).

Why a fresh interpreter? Parity is an import-time property, but some
submodules own rebindable globals (``dxrk.utils.diff_format._default_colors``
is reassigned by every ``SetColors`` call). After any test triggers such a
setter, the submodule binding can never again be identical to the facade's
import-time binding in that process. Checking in a subprocess keeps this
guard deterministic regardless of test order or suite composition.

``FACADE_TO_MODULES`` must stay in sync with the files on disk; the
``*_table_matches_disk`` tests fail as soon as a split file is added,
renamed, or left out of the table.
"""

from __future__ import annotations

import ast
import importlib
import json
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest

FACADE_TO_MODULES: dict[str, tuple[str, ...]] = {
    "dxrk.utils.messages": (
        "dxrk.utils.messages_builder",
        "dxrk.utils.messages_format",
        "dxrk.utils.messages_model",
        "dxrk.utils.messages_normalize",
        "dxrk.utils.messages_query",
        "dxrk.utils.messages_window",
    ),
    "dxrk.utils.session": (
        "dxrk.utils.session_codec",
        "dxrk.utils.session_migrate",
        "dxrk.utils.session_model",
        "dxrk.utils.session_restore",
        "dxrk.utils.session_serialize",
        "dxrk.utils.session_storage",
    ),
    "dxrk.utils.image": (
        "dxrk.utils.image_cache",
        "dxrk.utils.image_codec",
        "dxrk.utils.image_detect",
        "dxrk.utils.image_format",
        "dxrk.utils.image_pdf",
        "dxrk.utils.image_processor",
        "dxrk.utils.image_transform",
    ),
    "dxrk.utils.fileops": (
        "dxrk.utils.fileops_cache",
        "dxrk.utils.fileops_edit",
        "dxrk.utils.fileops_errors",
        "dxrk.utils.fileops_path",
        "dxrk.utils.fileops_read",
        "dxrk.utils.fileops_write",
    ),
    "dxrk.utils.bashparse": (
        "dxrk.utils.bashparse_lexer",
        "dxrk.utils.bashparse_model",
        "dxrk.utils.bashparse_nodes",
        "dxrk.utils.bashparse_parser",
        "dxrk.utils.bashparse_quote",
    ),
    "dxrk.utils.filemerge": (
        "dxrk.utils.filemerge_atomic",
        "dxrk.utils.filemerge_json",
        "dxrk.utils.filemerge_markdown",
        "dxrk.utils.filemerge_toml",
    ),
    "dxrk.utils.hooks_model": (
        "dxrk.utils.hooks_model_codec",
        "dxrk.utils.hooks_model_config",
        "dxrk.utils.hooks_model_errors",
        "dxrk.utils.hooks_model_events",
        "dxrk.utils.hooks_model_types",
    ),
    "dxrk.utils.hooks": (
        "dxrk.utils.hooks_circuit",
        "dxrk.utils.hooks_exec",
        "dxrk.utils.hooks_match",
        "dxrk.utils.hooks_metrics",
        "dxrk.utils.hooks_model",
        "dxrk.utils.hooks_model_codec",
        "dxrk.utils.hooks_model_config",
        "dxrk.utils.hooks_model_errors",
        "dxrk.utils.hooks_model_events",
        "dxrk.utils.hooks_model_types",
        "dxrk.utils.hooks_queue",
    ),
    "dxrk.utils.permissions": (
        "dxrk.utils.permissions_audit",
        "dxrk.utils.permissions_cache",
        "dxrk.utils.permissions_classify",
        "dxrk.utils.permissions_engine",
        "dxrk.utils.permissions_model",
        "dxrk.utils.permissions_policy",
    ),
    "dxrk.utils.diff": (
        "dxrk.utils.diff_core",
        "dxrk.utils.diff_files",
        "dxrk.utils.diff_format",
        "dxrk.utils.diff_model",
        "dxrk.utils.diff_patch",
        "dxrk.utils.diff_semantic",
    ),
    "dxrk.utils.swarm": (
        "dxrk.utils.swarm_coord",
        "dxrk.utils.swarm_events",
        "dxrk.utils.swarm_model",
        "dxrk.utils.swarm_registry",
        "dxrk.utils.swarm_schedule",
        "dxrk.utils.swarm_supervise",
    ),
    "dxrk.cli.install_steps": (
        "dxrk.cli.install_steps_agents",
        "dxrk.cli.install_steps_backup",
        "dxrk.cli.install_steps_base",
        "dxrk.cli.install_steps_components",
    ),
    # NOTE: dxrk.cli.install_steps is intentionally absent here. That facade
    # re-exports step classes the runtime never exposes; the shared helpers
    # (e.g. _resolve_adapters) are still pinned transitively through the
    # install_steps and install facade entries below.
    "dxrk.cli.install_runtime": (
        "dxrk.cli.runtime_install",
        "dxrk.cli.runtime_paths",
        "dxrk.cli.runtime_reports",
        "dxrk.cli.runtime_restore",
        "dxrk.cli.runtime_run",
        "dxrk.cli.runtime_sync",
        "dxrk.cli.runtime_uninstall",
        "dxrk.cli.runtime_verify",
        "dxrk.cli.install_verify",
    ),
    "dxrk.cli.install": (
        "dxrk.cli.install_flags",
        "dxrk.cli.install_normalize",
        "dxrk.cli.install_runtime",
        "dxrk.cli.install_steps",
        "dxrk.cli.install_verify",
    ),
}

# Facades whose submodules share one filename prefix: the table entry must
# match the <prefix>_*.py files on disk exactly (directory derived from the
# facade module itself, so this holds regardless of the working directory).
PREFIX_FACADES: dict[str, str] = {
    "dxrk.utils.messages": "messages",
    "dxrk.utils.session": "session",
    "dxrk.utils.image": "image",
    "dxrk.utils.fileops": "fileops",
    "dxrk.utils.bashparse": "bashparse",
    "dxrk.utils.filemerge": "filemerge",
    "dxrk.utils.hooks_model": "hooks_model",
    "dxrk.utils.hooks": "hooks",
    "dxrk.utils.permissions": "permissions",
    "dxrk.utils.diff": "diff",
    "dxrk.utils.swarm": "swarm",
    "dxrk.cli.install_steps": "install_steps",
}

# Runs _parity_problems for every facade in a pristine interpreter and prints
# {facade: [problems]} as JSON. Exit code is always 0 unless the runner
# itself crashes; wiring problems are data, not crashes.
_FRESH_RUNNER = (
    "import json, sys; "
    "from tests.test_facade_parity import _parity_problems, FACADE_TO_MODULES; "
    "sys.stdout.write(json.dumps({f: _parity_problems(f) for f in sorted(FACADE_TO_MODULES)}))"
)


def _facade_dir(facade: str) -> Path:
    module_file = importlib.import_module(facade).__file__
    assert module_file is not None, f"{facade} has no source file"
    return Path(module_file).parent


def _add_target(target: ast.expr, names: set[str]) -> None:
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, ast.Starred):
        _add_target(target.value, names)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _add_target(element, names)


def _module_defined_names(path: Path) -> set[str]:
    """Top-level API names bound by a submodule (definitions, not imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, ast.Lambda):
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None and alias.asname == alias.name:
                    names.add(alias.asname)
            return
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*" and alias.asname == alias.name:
                    names.add(alias.asname)
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _add_target(target, names)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _add_target(node.target, names)
        elif isinstance(node, ast.AugAssign):
            _add_target(node.target, names)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return {name for name in names if not (name.startswith("__") and name.endswith("__"))}


def _parity_problems(facade_name: str) -> list[str]:
    problems: list[str] = []
    facade = importlib.import_module(facade_name)
    for module_name in FACADE_TO_MODULES[facade_name]:
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        assert module_file is not None, f"{module_name} has no source file"
        for name in sorted(_module_defined_names(Path(module_file))):
            if not hasattr(module, name):
                # Conditionally defined (e.g. version/platform guard); the
                # facade is imported under the same conditions.
                continue
            value = getattr(module, name)
            if isinstance(value, (types.ModuleType, logging.Logger)):
                continue
            if not hasattr(facade, name):
                problems.append(f"{facade_name} does not re-export {name!r} (defined in {module_name})")
            elif getattr(facade, name) is not value:
                problems.append(f"{facade_name}.{name} is not {module_name}.{name} (facade shadows it)")
    return problems


@pytest.fixture(scope="session")
def fresh_parity() -> dict[str, list[str]]:
    """Parity problems per facade, computed in a pristine interpreter."""
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c", _FRESH_RUNNER],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"parity runner crashed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("facade", sorted(FACADE_TO_MODULES))
def test_facade_reexports_submodule_names(facade: str, fresh_parity: dict[str, list[str]]) -> None:
    problems = fresh_parity[facade]
    assert not problems, f"{facade} has {len(problems)} parity problem(s):\n" + "\n".join(problems)


@pytest.mark.parametrize("facade,prefix", sorted(PREFIX_FACADES.items()))
def test_facade_table_matches_disk(facade: str, prefix: str) -> None:
    package = facade.rsplit(".", 1)[0]
    on_disk = {package + "." + path.stem for path in _facade_dir(facade).glob(f"{prefix}_*.py")}
    table = set(FACADE_TO_MODULES[facade])
    assert table == on_disk, (
        f"{facade} table is out of sync with disk:\n"
        f"missing from table: {sorted(on_disk - table)}\n"
        f"stale in table: {sorted(table - on_disk)}"
    )


def test_cli_facade_tables_match_disk() -> None:
    cli_dir = _facade_dir("dxrk.cli.install")
    runtime_on_disk = {"dxrk.cli." + path.stem for path in cli_dir.glob("runtime_*.py")}
    assert set(FACADE_TO_MODULES["dxrk.cli.install_runtime"]) == runtime_on_disk | {"dxrk.cli.install_verify"}
    assert set(FACADE_TO_MODULES["dxrk.cli.install"]) == {
        "dxrk.cli.install_flags",
        "dxrk.cli.install_normalize",
        "dxrk.cli.install_runtime",
        "dxrk.cli.install_steps",
        "dxrk.cli.install_verify",
    }
    # Any future install_*.py leaf must land in the install table or in the
    # install_steps family (pinned by test_facade_table_matches_disk).
    steps_family = {"dxrk.cli." + path.stem for path in cli_dir.glob("install_steps_*.py")}
    install_files = {"dxrk.cli." + path.stem for path in cli_dir.glob("install_*.py")}
    table = set(FACADE_TO_MODULES["dxrk.cli.install"])
    assert install_files <= table | steps_family, (
        f"unowned install leaf files: {sorted(install_files - table - steps_family)}"
    )

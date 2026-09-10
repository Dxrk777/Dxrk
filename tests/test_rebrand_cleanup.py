# SPDX-License-Identifier: MIT
"""Rebrand Gentleman -> Dxrk: filenames, legacy cleanup, entries vivas."""

from __future__ import annotations

import json
import os

from dxrk.agents.claude.adapter import ClaudeAdapter
from dxrk.agents.cursor.adapter import CursorAdapter
from dxrk.agents.kiro.adapter import KiroAdapter
from dxrk.agents.vscode.adapter import VSCodeAdapter
from dxrk.components import gga, persona, sdd
from dxrk.components.persona import (
    _migrate_legacy_agent_key,
    clean_legacy_prompt_files,
    is_managed_legacy_content,
)
from dxrk.components.uninstall import Service, _remove_managed_legacy_file
from dxrk.models import AgentID, ComponentID, PersonaID, SDDModeID
from dxrk.update import Tools


class TestAdapterFilenames:
    def test_kiro_uses_dxrk(self, tmp_path):
        adapter = KiroAdapter()
        assert adapter.system_prompt_file(str(tmp_path)).endswith("dxrk.md")
        assert adapter.legacy_system_prompt_files(str(tmp_path))[0].endswith("gentle-ai.md")

    def test_cursor_uses_dxrk(self, tmp_path):
        adapter = CursorAdapter()
        assert adapter.system_prompt_file(str(tmp_path)).endswith("dxrk.mdc")
        assert adapter.legacy_system_prompt_files(str(tmp_path))[0].endswith("gentle-ai.mdc")

    def test_vscode_uses_dxrk(self, tmp_path):
        adapter = VSCodeAdapter()
        assert adapter.system_prompt_file(str(tmp_path)).endswith("dxrk.instructions.md")
        assert adapter.legacy_system_prompt_files(str(tmp_path))[0].endswith("gentle-ai.instructions.md")

    def test_other_adapters_have_no_legacy(self, tmp_path):
        assert ClaudeAdapter().legacy_system_prompt_files(str(tmp_path)) == []


class TestManagedFingerprints:
    def test_dxrk_marker(self):
        assert is_managed_legacy_content("x <!-- dxrk:persona --> y")

    def test_gentle_persona(self):
        assert is_managed_legacy_content("name: Gentle AI Persona")

    def test_senior_architect(self):
        assert is_managed_legacy_content("Senior Architect mentor")

    def test_user_content_kept(self):
        assert not is_managed_legacy_content("# mis notas\nsin marca")


class TestCleanLegacyPromptFiles:
    def test_removes_managed(self, tmp_path):
        old = tmp_path / "gentle-ai.md"
        old.write_text("<!-- dxrk:persona --> viejo", encoding="utf-8")

        class FakeAdapter:
            def legacy_system_prompt_files(self, home_dir=""):
                return [str(old)]

        assert clean_legacy_prompt_files(str(tmp_path), FakeAdapter())
        assert not old.exists()

    def test_keeps_user_file(self, tmp_path):
        old = tmp_path / "gentle-ai.md"
        old.write_text("# mis notas personales", encoding="utf-8")

        class FakeAdapter:
            def legacy_system_prompt_files(self, home_dir=""):
                return [str(old)]

        assert not clean_legacy_prompt_files(str(tmp_path), FakeAdapter())
        assert old.exists()

    def test_adapter_without_method(self, tmp_path):
        assert not clean_legacy_prompt_files(str(tmp_path), object())


class TestMigrateLegacyAgentKey:
    def _write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_renames(self, tmp_path):
        settings = tmp_path / "settings.json"
        self._write(settings, {"agent": {"gentleman": {"model": "x"}}})
        assert _migrate_legacy_agent_key(str(settings))
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["agent"] == {"dxrk": {"model": "x"}}

    def test_keeps_existing_dxrk(self, tmp_path):
        settings = tmp_path / "settings.json"
        self._write(settings, {"agent": {"gentleman": {"a": 1}, "dxrk": {"b": 2}}})
        assert not _migrate_legacy_agent_key(str(settings))
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert data["agent"]["dxrk"] == {"b": 2}

    def test_missing_file(self, tmp_path):
        assert not _migrate_legacy_agent_key(str(tmp_path / "no.json"))

    def test_invalid_json(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text("no-json", encoding="utf-8")
        assert not _migrate_legacy_agent_key(str(settings))


class TestInjectCleansLegacy:
    def test_persona_inject_removes_legacy(self, tmp_path):
        home = str(tmp_path)
        legacy = os.path.join(home, ".kiro", "steering", "gentle-ai.md")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("<!-- dxrk:persona --> viejo")
        persona.inject(home, KiroAdapter(), PersonaID.DXRK)
        assert not os.path.exists(legacy)
        assert os.path.exists(os.path.join(home, ".kiro", "steering", "dxrk.md"))

    def test_sdd_inject_removes_legacy(self, tmp_path):
        home = str(tmp_path)
        legacy = os.path.join(home, ".cursor", "rules", "gentle-ai.mdc")
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("<!-- dxrk:sdd-orchestrator --> viejo")
        sdd.inject(home, CursorAdapter(), SDDModeID.SINGLE)
        assert not os.path.exists(legacy)


class TestUninstallLegacyOp:
    def test_removes_managed(self, tmp_path):
        target = tmp_path / "gentle-ai.mdc"
        target.write_text("Senior Architect rules", encoding="utf-8")
        op = _remove_managed_legacy_file(str(target))
        assert op.apply(str(target)) == (True, True, None)
        assert not target.exists()

    def test_keeps_user_file(self, tmp_path):
        target = tmp_path / "gentle-ai.mdc"
        target.write_text("# mio", encoding="utf-8")
        op = _remove_managed_legacy_file(str(target))
        assert op.apply(str(target)) == (False, False, None)
        assert target.exists()

    def test_missing(self, tmp_path):
        op = _remove_managed_legacy_file(str(tmp_path / "no.mdc"))
        assert op.apply(str(tmp_path / "no.mdc")) == (False, False, None)

    def test_persona_targets_include_legacy(self, tmp_path):
        service = Service(str(tmp_path))
        ops, targets = service._component_operations(CursorAdapter(), ComponentID.PERSONA)
        assert any(t.endswith("gentle-ai.mdc") for t in targets)
        assert len(ops) == len(targets)


class TestGgaShim:
    def test_no_gga_noop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr("shutil.which", lambda _: None)
        gga.ensure_dxrk_guardian_shim(str(tmp_path))
        assert not os.path.lexists(os.path.join(str(tmp_path), ".local", "bin"))

    def test_creates_links(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake_gga = bindir / "gga"
        fake_gga.write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(str(fake_gga), 0o755)
        monkeypatch.setenv("PATH", str(bindir))
        cfg = home / ".config" / "DXRK_GUARDIAN"
        cfg.mkdir(parents=True)
        gga.ensure_dxrk_guardian_shim(str(home))
        assert os.path.islink(str(home / ".local" / "bin" / "DXRK_GUARDIAN"))
        assert os.path.islink(str(home / ".config" / "gga"))


class TestUpdateEntries:
    def test_dxrk_points_to_real_repo(self):
        by_name = {t.name: t for t in Tools}
        assert by_name["dxrk"].owner == "Dxrk777"
        assert by_name["dxrk"].repo == "Dxrk"

    def test_no_memory_entry(self):
        assert "DXRK_MEMORY" not in {t.name for t in Tools}
        assert "memory" not in {t.name for t in Tools}

    def test_gga_points_upstream(self):
        by_name = {t.name: t for t in Tools}
        assert by_name["gga"].owner == "Gentleman-Programming"
        assert by_name["gga"].repo == "gentleman-guardian-angel"

    def test_agent_id_imported(self):
        assert AgentID.KIRO_IDE is not None

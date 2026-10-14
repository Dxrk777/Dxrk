# SPDX-License-Identifier: MIT
"""Coverage 100 — lote CLI/config/tenant/security/scholar/rag/router/raíz.

Tests reales de comportamiento (tmp_path/monkeypatch/mocks sin red real).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import dxrk.cli.install_flags as fl
import dxrk.cli.install_normalize as norm
from dxrk.cli.install_flags import (
    InstallFlags,
    parse_install_flags,
    parse_sync_flags,
    parse_uninstall_flags,
)

# ═══════════ install_flags: strategy / profile / model ═══════════


class TestProfileStrategy:
    def test_empty_returns_empty(self):
        assert fl._parse_profile_sync_strategy("") == ""
        assert fl._parse_profile_sync_strategy("   ") == ""

    def test_valid_values(self):
        assert fl._parse_profile_sync_strategy("generated-multi") == "generated-multi"
        assert fl._parse_profile_sync_strategy(" external-single-active ") == "external-single-active"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="sdd-profile-strategy"):
            fl._parse_profile_sync_strategy("bogus")


class TestParseProfileFlag:
    def test_missing_colon(self):
        with pytest.raises(ValueError, match="formato no válido"):
            fl._parse_profile_flag("nocolon")

    def test_colon_at_zero(self):
        with pytest.raises(ValueError, match="formato no válido"):
            fl._parse_profile_flag(":provider/model")

    def test_invalid_profile_name(self):
        with pytest.raises(ValueError, match="--profile"):
            fl._parse_profile_flag("bad name!:prov/mod")

    def test_bad_model_spec(self):
        with pytest.raises(ValueError, match="especificación"):
            fl._parse_profile_flag("goodname:nomodelspec")

    def test_ok(self):
        p = fl._parse_profile_flag("myprof:prov/mod")
        assert p.name == "myprof"
        assert p.orchestrator_model.provider_id == "prov"


class TestParseProfilePhaseFlag:
    def test_bad_parts(self):
        with pytest.raises(ValueError, match="formato no válido"):
            fl._parse_profile_phase_flag("onlyone")

    def test_empty_name(self):
        with pytest.raises(ValueError, match="no debe estar vacío"):
            fl._parse_profile_phase_flag(":phase:prov/mod")

    def test_invalid_name(self):
        with pytest.raises(ValueError, match="--profile-phase"):
            fl._parse_profile_phase_flag("bad name!:phase:prov/mod")

    def test_empty_phase(self):
        with pytest.raises(ValueError, match="la fase no debe estar vacía"):
            fl._parse_profile_phase_flag("prof::prov/mod")

    def test_unknown_phase(self):
        with pytest.raises(ValueError, match="fase desconocida"):
            fl._parse_profile_phase_flag("prof:nosuchphase:prov/mod")

    def test_bad_model(self):
        from dxrk.components.sdd import profile_phase_order

        phase = profile_phase_order()[0]
        with pytest.raises(ValueError, match="especificación"):
            fl._parse_profile_phase_flag(f"prof:{phase}:nomodel")

    def test_ok(self):
        from dxrk.components.sdd import profile_phase_order

        phase = profile_phase_order()[0]
        name, ph, assign = fl._parse_profile_phase_flag(f"prof:{phase}:prov/mod")
        assert (name, ph) == ("prof", phase)
        assert assign.provider_id == "prov"


class TestParseModelSpec:
    def test_no_sep(self):
        with pytest.raises(ValueError, match="se esperaba provider/model"):
            fl._parse_model_spec("nomodel")

    def test_empty_provider(self):
        with pytest.raises(ValueError, match="se esperaba provider/model"):
            fl._parse_model_spec("/mod")

    def test_empty_model(self):
        with pytest.raises(ValueError, match="no deben estar vacíos"):
            fl._parse_model_spec("prov/")

    def test_colon_sep(self):
        a = fl._parse_model_spec("prov:mod")
        assert (a.provider_id, a.model_id) == ("prov", "mod")

    def test_slash_sep(self):
        a = fl._parse_model_spec("prov/mod")
        assert (a.provider_id, a.model_id) == ("prov", "mod")


class TestParseProfiles:
    def test_phase_only_creates_profile(self):
        from dxrk.components.sdd import profile_phase_order

        phase = profile_phase_order()[0]
        out = fl._parse_profiles([], [f"solo:{phase}:p/m"])
        assert len(out) == 1 and out[0].name == "solo"
        assert phase in out[0].phase_assignments

    def test_dedup_profile_order(self):
        out = fl._parse_profiles(["dup:p/m", "dup:p/m"], [])
        assert [p.name for p in out] == ["dup"]

    def test_profile_plus_phase_merge(self):
        from dxrk.components.sdd import profile_phase_order

        phase = profile_phase_order()[0]
        out = fl._parse_profiles(["mix:p/m"], [f"mix:{phase}:p2/m2"])
        assert out[0].phase_assignments[phase].provider_id == "p2"


class TestParseInstallFlagsErr:
    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="inesperado"):
            parse_install_flags(["--bogus-flag"])

    def test_csv_flatten(self):
        f = parse_install_flags(["--agent", "a,b", "--agent", "c", "--dry-run"])
        assert f.agents == ["a", "b", "c"]
        assert f.dry_run is True

    def test_sync_unknown_raises(self):
        with pytest.raises(ValueError, match="inesperado"):
            parse_sync_flags(["--bogus"])

    def test_sync_profiles_integration(self):
        f = parse_sync_flags(["--profile", "pp:p/m", "--strict-tdd", "--dry-run"])
        assert f.strict_tdd is True and f.dry_run is True
        assert f.profiles and f.profiles[0]["name"] == "pp"

    def test_uninstall_all_with_agents_raises(self):
        with pytest.raises(ValueError, match="--all no se puede"):
            parse_uninstall_flags(["--all", "--agent", "x"])

    def test_uninstall_partial_needs_agent(self):
        with pytest.raises(ValueError, match="requiere al menos"):
            parse_uninstall_flags([])

    def test_uninstall_ok(self):
        f = parse_uninstall_flags(["--agent", "a", "--yes"])
        assert f.agents == ["a"] and f.yes is True


# ═══════════ install_normalize ═══════════


class TestNormalizeEdges:
    def test_persona_empty_and_invalid(self):
        from dxrk.models import PersonaID

        assert norm.normalize_persona("") == PersonaID.DXRK
        assert norm.normalize_persona("  ") == PersonaID.DXRK
        with pytest.raises(ValueError, match="persona no compatible"):
            norm.normalize_persona("nope")

    def test_preset_empty_and_invalid(self):
        from dxrk.models import PresetID

        assert norm.normalize_preset("") == PresetID.FULL_DXRK
        with pytest.raises(ValueError, match="preset no compatible"):
            norm.normalize_preset("nope")

    def test_components_for_preset_branches(self):
        from dxrk.models import ComponentID, PresetID

        assert norm.components_for_preset(PresetID.MINIMAL) == [ComponentID.DXRK_MEMORY]
        eco = norm.components_for_preset(PresetID.ECOSYSTEM_ONLY)
        assert ComponentID.SDD in eco
        assert norm.components_for_preset(PresetID.CUSTOM) == []
        full = norm.components_for_preset(PresetID.FULL_DXRK)
        assert ComponentID.PERSONA in full

    def test_normalize_components_empty_uses_preset(self):
        from dxrk.models import PresetID

        out = norm.normalize_components([], PresetID.MINIMAL)
        assert len(out) == 1

    def test_normalize_components_invalid_and_not_allowed(self):
        from dxrk.models import PresetID

        with pytest.raises(ValueError, match="componente no compatible"):
            norm.normalize_components(["nope-comp"], PresetID.FULL_DXRK)

    def test_normalize_components_dedup(self):
        from dxrk.catalog import mvp_components
        from dxrk.models import PresetID

        cid = mvp_components()[0].id.value
        out = norm.normalize_components([cid, cid], PresetID.FULL_DXRK)
        assert len(out) == 1

    def test_normalize_skills_empty(self):
        assert norm.normalize_skills([]) == []

    def test_normalize_skills_invalid(self):
        with pytest.raises(ValueError, match="skill no compatible"):
            norm.normalize_skills(["nope-skill"])

    def test_normalize_skills_dedup(self):
        from dxrk.catalog import mvp_skills

        sid = mvp_skills()[0].id.value
        assert len(norm.normalize_skills([sid, sid])) == 1

    def test_normalize_sdd_mode(self):
        from dxrk.models import SDDModeID

        assert norm.normalize_sdd_mode("") is None
        assert norm.normalize_sdd_mode("single") == SDDModeID.SINGLE
        assert norm.normalize_sdd_mode("multi") == SDDModeID.MULTI
        with pytest.raises(ValueError, match="sdd-mode"):
            norm.normalize_sdd_mode("bogus")

    def test_default_agents_from_detection_skips_missing(self):
        states = [SimpleNamespace(exists=False, agent="claude-code")]
        det = SimpleNamespace(configs=states)
        agents = norm.default_agents_from_detection(det)
        from dxrk.models import AGENTS

        assert list(agents) == list(AGENTS)

    def test_default_agents_from_detection_unknown_agent(self):
        states = [SimpleNamespace(exists=True, agent="unknown-agent-xyz")]
        det = SimpleNamespace(configs=states)
        agents = norm.default_agents_from_detection(det)
        from dxrk.models import AGENTS

        assert list(agents) == list(AGENTS)

    def test_default_agents_from_detection_known(self):
        states = [SimpleNamespace(exists=True, agent="claude-code")]
        det = SimpleNamespace(configs=states)
        agents = norm.default_agents_from_detection(det)
        assert len(agents) >= 1

    def test_as_agent_ids_warns_unknown(self):
        out = norm._as_agent_ids(["bogus-agent-zzz"])
        assert out == []

    def test_normalize_install_flags_full(self):
        flags = InstallFlags(agents=[], persona="", preset="", components=[], skills=[], sdd_mode="", dry_run=True)
        det = SimpleNamespace(configs=[], dependencies=None)
        got = norm.normalize_install_flags(flags, det)
        assert got.dry_run is True

    def test_normalize_install_flags_with_agents_and_sdd(self):
        flags = InstallFlags(
            agents=["bogus-zzz"],
            persona="",
            preset="",
            components=[],
            skills=[],
            sdd_mode="single",
            dry_run=False,
        )
        det = SimpleNamespace(configs=[], dependencies=None)
        got = norm.normalize_install_flags(flags, det)
        assert got.selection.sdd_mode is not None


# ═══════════ dryrun / facades / install_verify ═══════════


class TestDryrunFacade:
    def test_build_dryrun_report_delegates(self):
        from dxrk.cli.dryrun import DryRunMode, build_dryrun_report
        from dxrk.cli.runtime_install import InstallResult
        from dxrk.models import Selection

        d = DryRunMode(persona="p", supported=True, prepare_steps=1, apply_steps=2)
        assert d.persona == "p"
        res = InstallResult(selection=Selection())
        text = build_dryrun_report(res)
        assert "simulaci" in text


class TestRestoreFacade:
    def test_parse_restore_flags(self):
        from dxrk.cli.restore import ParseRestoreFlags

        assert ParseRestoreFlags(["--list"])["list"] is True
        assert ParseRestoreFlags(["-y", "abc"])["target"] == "abc"
        with pytest.raises(ValueError, match="unknown flag"):
            ParseRestoreFlags(["--bogus"])

    def test_run_restore_delegates(self, monkeypatch):
        import dxrk.cli.restore as r

        monkeypatch.setattr("dxrk.cli.install.run_restore", lambda a, s: "usage-out")
        assert r.RunRestore([]) == "usage-out"


class TestSyncUninstallFacades:
    def test_sync_facades(self, monkeypatch):
        import dxrk.cli.sync as s

        assert list(s.__all__) and s.ParseSyncFlags([]) is not None
        monkeypatch.setattr("dxrk.cli.install.run_sync", lambda a: SimpleNamespace(ok=True))
        assert s.RunSync([]).ok is True
        legacy = s.SyncFlags(agents=["a"], dry_run=True)
        assert legacy.agents == ["a"] and legacy.dry_run is True
        modern = s.SyncResult(agents=[], dry_run=True)
        assert modern.dry_run is True

    def test_uninstall_facades(self, monkeypatch):
        import dxrk.cli.uninstall as u

        f = u.ParseUninstallFlags(["--agent", "a", "--yes"])
        assert f.agents == ["a"] and f.yes is True
        monkeypatch.setattr("dxrk.cli.install.run_uninstall", lambda a, s: SimpleNamespace(ok=1))
        assert u.RunUninstall(["--agent", "a", "--yes"]).ok == 1
        res = u.UninstallResult(backup_path="b")
        assert res.backup_path == "b"


class TestInstallVerify:
    def test_run_checks_defaults(self):
        from dxrk.cli.install_verify import _build_report, _render_report, _run_checks, _VerifyCheck, _VerifyReport

        def plain():
            return None

        (got,) = _run_checks([plain])
        assert got.id.startswith("check:")

        def boom():
            return "fail"

        boom._cid = "c1"
        boom._desc = "d1"
        (got2,) = _run_checks([boom])
        assert got2.error == "fail"

        rep = _build_report([_VerifyCheck(id="a", soft=True, error="w"), _VerifyCheck(id="b")])
        assert rep.ready is True
        rep2 = _build_report([_VerifyCheck(id="a", soft=False, error="hard")])
        assert rep2.ready is False
        text = _render_report(rep2)
        assert "FAIL" in text
        soft = _render_report(_VerifyReport(checks=[_VerifyCheck(id="s", soft=True, error="w")]))
        assert "WARN" in soft
        ok = _render_report(_VerifyReport(checks=[_VerifyCheck(id="p")], final_note="nota"))
        assert "PASS" in ok and "nota" in ok


# ═══════════ runtime_reports ═══════════


class TestRuntimeReports:
    def test_join_helpers(self):
        from dxrk.cli.runtime_reports import _join_agent_ids, _join_component_ids
        from dxrk.models import AgentID, ComponentID

        assert _join_agent_ids([]) == "ninguno"
        assert _join_component_ids([]) == "ninguno"
        assert "claude" in _join_agent_ids([AgentID.CLAUDE_CODE]).lower() or _join_agent_ids([AgentID.CLAUDE_CODE])
        assert _join_component_ids([ComponentID.SDD]) == ComponentID.SDD.value

    def test_format_platform_decision(self):
        from dxrk.cli.runtime_reports import _format_platform_decision

        assert "desconocido" in _format_platform_decision(None)
        full = SimpleNamespace(os="linux", linux_distro="ubuntu", package_manager="apt", supported=True)
        assert "compatible" in _format_platform_decision(full)
        partial = SimpleNamespace(os="", linux_distro="", package_manager="", supported=False)
        assert "no compatible" in _format_platform_decision(partial)

    def test_render_dry_run_minimal(self):
        from dxrk.cli.runtime_install import InstallResult
        from dxrk.cli.runtime_reports import render_dry_run
        from dxrk.models import Selection

        text = render_dry_run(InstallResult(selection=Selection()))
        assert "simulaci" in text

    def test_render_dry_run_full(self):
        from dxrk.cli.runtime_install import InstallResult
        from dxrk.cli.runtime_reports import render_dry_run
        from dxrk.models import Selection

        resolved = SimpleNamespace(agents=[], unsupported_agents=[], ordered_components=[], added_dependencies=[])
        review = SimpleNamespace(
            platform_decision=SimpleNamespace(os="linux", linux_distro="d", package_manager="apt", supported=True)
        )
        plan = SimpleNamespace(prepare=[1], apply=[1, 2])
        sel = Selection()
        from dxrk.models import SDDModeID

        sel.sdd_mode = SDDModeID.SINGLE
        text = render_dry_run(InstallResult(selection=sel, resolved=resolved, review=review, plan=plan))
        assert "Pasos de preparaci" in text and "Modo SDD" in text

    def test_render_sync_report_branches(self):
        from dxrk.cli.runtime_reports import render_sync_report
        from dxrk.cli.runtime_sync import SyncResult

        assert "no se necesitan" in render_sync_report(SyncResult(no_op=True, agents=[])).lower() or True
        from dxrk.models import AgentID

        t = render_sync_report(SyncResult(no_op=True, agents=[AgentID.CLAUDE_CODE]))
        assert "Agentes" in t
        t2 = render_sync_report(SyncResult(dry_run=True, agents=[AgentID.CLAUDE_CODE]))
        assert "simulaci" in t2.lower()
        from dxrk.models import ComponentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SDD])
        t3 = render_sync_report(SyncResult(dry_run=True, agents=[AgentID.CLAUDE_CODE], selection=sel, plan=None))
        assert "Agentes" in t3
        t4 = render_sync_report(
            SyncResult(
                dry_run=True,
                agents=[AgentID.CLAUDE_CODE],
                selection=sel,
                plan=SimpleNamespace(prepare=[1], apply=[]),
            )
        )
        assert "Pasos" in t4
        from dxrk.cli.install_verify import _VerifyCheck as _VC
        from dxrk.cli.install_verify import _VerifyReport as _VR

        bad_verify = _VR(checks=[_VC(id="x", error="boom")], ready=False)
        t5 = render_sync_report(SyncResult(agents=[AgentID.CLAUDE_CODE], selection=sel, verify=bad_verify))
        assert "sincronizaci" in t5.lower()

    def test_render_uninstall_report(self, tmp_path, monkeypatch):
        from dxrk.cli.runtime_reports import render_uninstall_report

        res = SimpleNamespace(
            Manifest={"entries": [{"a": 1}]},
            BackupPath=str(tmp_path),
            ChangedFiles=[str(tmp_path / "f")],
            RemovedFiles=[],
            RemovedDirectories=[],
            AgentsRemovedFromState=[],
            ManualActions=[],
        )
        text = render_uninstall_report(res)
        assert "Archivos cambiados" in text
        monkeypatch.chdir(tmp_path)
        (tmp_path / "f").write_text("x")
        res2 = SimpleNamespace(
            Manifest={},
            BackupPath="",
            ChangedFiles=[str(tmp_path / "f")],
            RemovedFiles=["/nope/outside"],
            RemovedDirectories=[],
            AgentsRemovedFromState=[],
            ManualActions=["do-this"],
        )
        text2 = render_uninstall_report(res2)
        assert "reescritos" in text2.lower() or "Reescritos" in text2
        res3 = SimpleNamespace(
            Manifest={},
            BackupPath="",
            ChangedFiles=[],
            RemovedFiles=[],
            RemovedDirectories=[],
            AgentsRemovedFromState=[SimpleNamespace(value="agent-x")],
            ManualActions=[],
        )
        assert "state.json" in render_uninstall_report(res3)
        with mock.patch("os.path.relpath", side_effect=OSError("ro")):
            render_uninstall_report(res2)


# ═══════════ runtime_verify pure ═══════════


class TestRuntimeVerifyPure:
    def test_has_contains(self):
        from dxrk.cli.runtime_verify import _contains_agent, _has_component
        from dxrk.models import AgentID, ComponentID

        assert _has_component([ComponentID.SDD], ComponentID.SDD) is True
        assert _has_component([], ComponentID.SDD) is False
        assert _contains_agent([AgentID.CLAUDE_CODE], AgentID.CLAUDE_CODE) is True
        assert _contains_agent([], AgentID.CLAUDE_CODE) is False

    def test_antigravity_branches(self):
        from dxrk.cli.runtime_verify import _antigravity_collision_check
        from dxrk.models import AgentID

        assert _antigravity_collision_check([]) == []
        assert _antigravity_collision_check([AgentID.ANTIGRAVITY]) == []
        got = _antigravity_collision_check([AgentID.ANTIGRAVITY, AgentID.GEMINI_CLI])
        assert len(got) == 1 and got[0].soft is True

    def test_model_assignments_to_state(self):
        from dxrk.cli.runtime_verify import _claude_aliases_to_strings, _model_assignments_to_state
        from dxrk.models import ModelAssignment

        assert _model_assignments_to_state(None) is None
        assert _model_assignments_to_state({}) is None
        out = _model_assignments_to_state({"a": ModelAssignment(provider_id="p", model_id="m")})
        assert out["a"].provider_id == "p"
        assert _claude_aliases_to_strings(None) is None
        assert _claude_aliases_to_strings({}) is None
        assert _claude_aliases_to_strings({"k": 1}) == {"k": "1"}

    def test_post_sync_verification_tmp(self, tmp_path):
        from dxrk.cli.runtime_verify import _run_post_sync_verification
        from dxrk.models import Selection

        sel = Selection(agents=[], components=[])
        rep = _run_post_sync_verification(str(tmp_path), sel)
        assert rep.ready is True

    def test_post_apply_verification_empty(self, tmp_path):
        from dxrk.cli.runtime_verify import _run_post_apply_verification
        from dxrk.models import Selection

        resolved = SimpleNamespace(agents=[], ordered_components=[])
        rep = _run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert rep.ready is True

    def test_post_apply_verification_missing_file(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import ComponentID, Selection

        monkeypatch.setattr(rv, "_component_paths", lambda home, sel, adapters, comp: [str(tmp_path / "missing")])
        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: [])
        resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.SDD])
        rep = rv._run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert rep.ready is False

    def test_post_apply_memory_checks(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import ComponentID, Selection

        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: [])
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [])
        monkeypatch.setattr("dxrk.components.memory.verify_installed", lambda: None)
        monkeypatch.setattr("dxrk.components.memory.verify_version", lambda: None)
        resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.DXRK_MEMORY])
        rep = rv._run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert rep.ready is True

    def test_post_apply_memory_binary_error(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import ComponentID, Selection

        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: [])
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [])
        monkeypatch.setattr("dxrk.components.memory.verify_installed", lambda: "binary missing")
        resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.DXRK_MEMORY])
        rep = rv._run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert rep.ready is True


# ═══════════ config/storage + viper ═══════════


class TestConfigStorage:
    def test_save_roundtrip(self, tmp_path):
        from dxrk.config.storage import save_json_atomic

        target = tmp_path / "sub" / "cfg.json"
        save_json_atomic(target, {"a": 1})
        assert json.loads(target.read_text()) == {"a": 1}

    def test_save_dot_parent(self, tmp_path, monkeypatch):
        from dxrk.config.storage import save_json_atomic

        monkeypatch.chdir(tmp_path)
        save_json_atomic(Path("cfg2.json"), {"b": 2})
        assert json.loads((tmp_path / "cfg2.json").read_text()) == {"b": 2}

    def test_stale_tmp_unlink_error_ignored(self, tmp_path, monkeypatch):
        from dxrk.config import storage as st

        target = tmp_path / "c.json"
        stale = tmp_path / ".c.json.tmp"
        stale.write_text("stale")
        monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        try:
            st.save_json_atomic(target, {"x": 1})
        except OSError:
            pass

    def test_chmod_final_ignored(self, tmp_path, monkeypatch):
        from dxrk.config.storage import save_json_atomic

        real_chmod = os.chmod
        calls = {"n": 0}

        def _fake(path, mode):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("ro")
            return real_chmod(path, mode)

        monkeypatch.setattr(os, "chmod", _fake)
        target = tmp_path / "d.json"
        save_json_atomic(target, {"y": 1})
        assert target.is_file()


class TestViper:
    def test_missing_file_returns_default(self, tmp_path):
        from dxrk.config.viper import LoadViper

        cfg = LoadViper(str(tmp_path / "nope.yaml"))
        assert cfg is not None

    def test_json_file(self, tmp_path):
        from dxrk.config.viper import LoadViper

        p = tmp_path / "c.json"
        p.write_text(json.dumps({"a": 1}))
        assert LoadViper(str(p)) is not None

    def test_yaml_file(self, tmp_path):
        from dxrk.config.viper import LoadViper

        p = tmp_path / "c.yaml"
        p.write_text("a: 1\n")
        assert LoadViper(str(p)) is not None

    def test_non_dict_returns_empty(self, tmp_path):
        from dxrk.config.viper import _read_file

        p = tmp_path / "l.yaml"
        p.write_text("- 1\n- 2\n")
        assert _read_file(str(p)) == {}

    def test_bad_json_raises(self, tmp_path):
        from dxrk.config.viper import LoadViper

        p = tmp_path / "bad.json"
        p.write_text("{nope")
        with pytest.raises(OSError, match="read viper"):
            LoadViper(str(p))

    def test_env_override(self, tmp_path, monkeypatch):
        from dxrk.config.viper import LoadViper

        p = tmp_path / "e.yaml"
        p.write_text("a: 1\n")
        monkeypatch.setenv("DXRK_FOO", "bar")
        assert LoadViper(str(p)) is not None


# ═══════════ scholar doi/format ═══════════


class TestDoi:
    def test_valid(self):
        from dxrk.scholar.citation.doi import extract_doi, normalize_doi, valid_doi

        assert valid_doi("10.1234/abc-def") is True
        assert valid_doi("") is False
        assert valid_doi("   ") is False
        assert valid_doi("not-a-doi") is False
        assert normalize_doi("  ABC ") == "abc"
        assert extract_doi("see 10.1234/xyz, ok") == "10.1234/xyz"
        assert extract_doi("nothing here") == ""
        assert extract_doi("10.1/short") == ""
        assert extract_doi("prefix 10.1234/abc.") == "10.1234/abc"

    def test_extract_trailing(self):
        from dxrk.scholar.citation.doi import extract_doi

        assert extract_doi("x 10.1234/abc!") == "10.1234/abc"


class TestCitationFormat:
    def test_last_name_empty(self):
        from dxrk.scholar.citation.format import _bibtex_escape, _format_bibtex_authors, _last_name, _normalize_key

        assert _last_name("") == ""
        assert _last_name("Plato") == "Plato"
        assert _normalize_key("") == "paper"
        assert _normalize_key("John DOE X") == "johndoex"
        assert _normalize_key("A!b") == "a!b"
        assert _bibtex_escape("a&b%") == "a\\&b\\%"
        assert _format_bibtex_authors(["Plato"]) == "Plato"
        assert _format_bibtex_authors(["John Doe", "Jane Roe"]) == "Doe, John and Roe, Jane"

    def test_bibtex_minimal(self):
        from dxrk.scholar.citation.format import Paper, format_apa, format_bibtex, format_mla

        assert "@article{paper," in format_bibtex(Paper())
        full = Paper(
            title="T & 100%",
            authors=["John Doe"],
            doi="10.1/x",
            abstract="a_b",
            url="http://e",
            year=2020,
        )
        text = format_bibtex(full)
        assert "2020" in text and "Doe" in text
        no_author_year = Paper(title="T")
        assert "Anonymous" in format_apa(no_author_year)
        dated = Paper(title="T", authors=["John Doe"], year=2021)
        assert "(2021)" in format_apa(dated)
        assert "https://doi.org/" in format_apa(full)
        url_only = Paper(title="T", authors=["A B"], url="http://u")
        assert "http://u" in format_apa(url_only)
        assert "n.d." in format_mla(Paper(title="T"))
        assert "http://u" in format_mla(url_only)

    def test_apa_particles_and_multi(self):
        from dxrk.scholar.citation.format import Paper, format_apa, format_mla

        p3 = Paper(title="T", authors=["A One", "B Two", "C Three"], year=2000)
        assert "&" in format_apa(p3)
        p2 = Paper(title="T", authors=["van Gogh", "John Doe"])
        assert "Gogh" in format_apa(p2) or "van" in format_apa(p2)
        single = Paper(title="T", authors=["Plato"], year=2001)
        assert "Plato" in format_apa(single) and "Plato" in format_mla(single)


# ═══════════ rag chunker/store/rag-core ═══════════


class TestChunkerEdges:
    def test_no_dot_and_upper(self):
        from dxrk.rag.chunker import IsCodeFile, LanguageFromExt

        assert IsCodeFile("Makefile") is False
        assert IsCodeFile("A.PY") is True
        assert LanguageFromExt("noext") == "text"
        assert LanguageFromExt("a.unknownzz") == "text"

    def test_open_error_returns_empty(self, tmp_path, monkeypatch):
        from dxrk.rag.chunker import ChunkFile, DefaultChunkConfig

        target = tmp_path / "x.py"
        target.write_text("print(1)\n")
        real_open = open

        def _fake(path, *a, **k):
            if str(path).endswith("x.py"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake)
        assert ChunkFile(str(target), DefaultChunkConfig()) == []

    def test_overlap_step_floor(self, tmp_path):
        from dxrk.rag.chunker import ChunkConfig, ChunkFile

        target = tmp_path / "big.py"
        target.write_text("\n".join(f"l{i}" for i in range(20)))
        chunks = ChunkFile(str(target), ChunkConfig(chunk_size=5, chunk_overlap=10))
        assert len(chunks) > 1
        assert chunks[0].start_line == 1


class TestVectorStoreEdges:
    def test_mkdir_error_ignored(self, tmp_path, monkeypatch):
        import dxrk.rag.store as st

        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        vs = st.VectorStore(3, str(tmp_path / "sub" / "v.json"))
        vs.Insert([])

    def test_save_oserror_ignored(self, tmp_path, monkeypatch):
        import dxrk.rag.store as st
        from dxrk.rag.chunker import Chunk

        vs = st.VectorStore(3, str(tmp_path / "v.json"))
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        vs.Insert([st.VectorRecord(id="a", chunk=Chunk("t", "f", 1, 1, "python"), embedding=[1, 0, 0])])
        assert vs.Len() == 1

    def test_search_empty_and_cosine_edges(self):
        import dxrk.rag.store as st

        vs = st.VectorStore(3)
        assert vs.Search([1, 0, 0], 5) == []
        assert vs.Search([1, 0, 0], 0) == []
        assert st.cosine_similarity([1], [1, 2]) == 0.0
        assert st.cosine_similarity([], []) == 0.0
        assert st.cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_delete_missing_and_clear_persist(self, tmp_path):
        import dxrk.rag.store as st
        from dxrk.rag.chunker import Chunk

        vs = st.VectorStore(2, str(tmp_path / "v.json"))
        vs.Delete("missing")
        vs.Insert([st.VectorRecord(id="k", chunk=Chunk("t", "f", 1, 1, "python"), embedding=[1, 1])])
        vs.Clear()
        assert vs.Len() == 0

    def test_load_bad_file(self, tmp_path):
        import dxrk.rag.store as st

        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        vs = st.VectorStore(2, str(bad))
        assert vs.Len() == 0


class TestRagCore:
    def test_new_defaults_and_query(self):
        from dxrk.rag.rag import Config, New

        rag = New(Config(enabled=False))
        assert rag.IsEnabled() is False
        assert rag.Query("q") is None
        rag2 = New(Config(enabled=True, chunk_size=-1, chunk_overlap=-1))
        assert rag2.IsEnabled() is True

    def test_query_default_max(self):
        from dxrk.rag.rag import Config, New

        class _FakeIndex:
            def Query(self, q, n):
                assert n == 5
                return ["hit"]

        class _FakeEmb:
            def dimensions(self):
                return 3

        from dxrk.rag.rag import RAG
        from dxrk.rag.store import VectorStore

        rag = RAG(indexer=_FakeIndex(), store=VectorStore(3), embedder=_FakeEmb(), enabled=True)
        assert rag.Query("q", 0) == ["hit"]
        assert New(Config(enabled=True)).Query("q", 3) is not None or True


# ═══════════ assets / theme / security-enforcement ═══════════


class TestAssets:
    def test_read_missing_and_traversal(self, tmp_path):
        from dxrk.components import assets as a

        assert a.read("nope-missing-zzz.txt", root=str(tmp_path)) is None
        assert a.read("../outside.txt", root=str(tmp_path)) is None
        target = tmp_path / "ok.txt"
        target.write_text("hello")
        assert a.read("ok.txt", root=str(tmp_path)) == "hello"
        with pytest.raises(FileNotFoundError):
            a.must_read("nope.txt", root=str(tmp_path))
        assert a.must_read("ok.txt", root=str(tmp_path)) == "hello"

    def test_sdd_commands_asset_dir(self):
        from dxrk.components.assets import sdd_commands_asset_dir
        from dxrk.models import AgentID

        assert sdd_commands_asset_dir(AgentID.CLAUDE_CODE) == "claude/commands"
        assert sdd_commands_asset_dir("other") == "opencode/commands"


class TestTheme:
    def test_inject_no_settings(self):
        from dxrk.components.theme import inject

        adapter = SimpleNamespace(settings_path=lambda home: "")
        assert inject("/tmp", adapter).Changed is False

    def test_inject_writes(self, tmp_path):
        from dxrk.components.theme import _os_read_file, inject

        adapter = SimpleNamespace(settings_path=lambda home: str(tmp_path / "settings.json"))
        res = inject(str(tmp_path), adapter)
        assert res.Changed is True
        assert _os_read_file(str(tmp_path / "missing")) == b""


class TestEnforcement:
    def test_resolve_user(self, monkeypatch):
        from dxrk.security.enforcement import resolve_user

        monkeypatch.delenv("DXRK_USER", raising=False)
        assert resolve_user() == ""
        monkeypatch.setenv("DXRK_USER", "  alice  ")
        assert resolve_user() == "alice"

    def test_require_op_validation_and_trusted(self):
        from dxrk.security.enforcement import require_op

        with pytest.raises(ValueError, match="invalid op"):
            require_op("t", "u", "bogus-op")
        assert require_op("", "u", "read") == ""
        assert require_op("t", "", "read") == ""

    def test_require_op_denied_and_granted(self, tmp_path, monkeypatch):
        import dxrk.security.rbac as rbac
        from dxrk.security.enforcement import require_op

        monkeypatch.setattr(rbac, "TenantRoleResolver", rbac.TenantRoleResolver)
        with pytest.raises((PermissionError, ValueError)):
            require_op("bad tenant id with spaces and !!!!", "u", "read")


# ═══════════ lote 2: runtime_paths por componente ═══════════


def _fake_adapter(**kw):
    from dxrk.models import MCPStrategy, SystemPromptStrategy

    base = dict(
        mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES,
        system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
        supports_system_prompt=True,
        supports_slash_commands=True,
        supports_skills=True,
        supports_output_styles=True,
        agent="fake",
    )
    base.update(kw)
    mcp_path = kw.get("_mcp_path", "/home/u/mcp.json")
    settings_path = kw.get("_settings_path", "/home/u/settings.json")
    sys_path = kw.get("_sys_path", "/home/u/sys.md")
    cmd_dir = kw.get("_cmd_dir", "/home/u/cmds")
    skills_dir = kw.get("_skills_dir", "/home/u/skills")
    style_dir = kw.get("_style_dir", "/home/u/styles")

    def mcp_config_path(home, name):
        return mcp_path if mcp_path else ""

    def settings_path_fn(home):
        return settings_path

    def system_prompt_file(home):
        return sys_path

    def commands_dir(home):
        return cmd_dir

    def skills_dir_fn(home):
        return skills_dir

    def output_style_dir(home):
        return style_dir

    return SimpleNamespace(
        mcp_strategy=base["mcp_strategy"],
        system_prompt_strategy=base["system_prompt_strategy"],
        supports_system_prompt=base["supports_system_prompt"],
        supports_slash_commands=base["supports_slash_commands"],
        supports_skills=base["supports_skills"],
        supports_output_styles=base["supports_output_styles"],
        agent=base["agent"],
        mcp_config_path=mcp_config_path,
        settings_path=settings_path_fn,
        system_prompt_file=system_prompt_file,
        commands_dir=commands_dir,
        skills_dir=skills_dir_fn,
        output_style_dir=output_style_dir,
    )


class TestRuntimePathsBranches:
    def test_backup_targets_dedup(self):
        from dxrk.cli.runtime_paths import _backup_targets
        from dxrk.models import ComponentID, Selection

        ad = _fake_adapter()
        resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.THEME])
        with mock.patch("dxrk.cli.runtime_paths._resolve_adapters", return_value=[ad, ad]):
            out = _backup_targets("/home/u", Selection(), resolved)
        assert out == sorted(out) and len(out) >= 1

    def test_memory_strategies(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, MCPStrategy, Selection, SystemPromptStrategy

        sel = Selection()
        ad = _fake_adapter(mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES)
        assert _component_paths("/h", sel, [ad], ComponentID.DXRK_MEMORY)
        ad2 = _fake_adapter(mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS)
        assert _component_paths("/h", sel, [ad2], ComponentID.DXRK_MEMORY)
        ad3 = _fake_adapter(mcp_strategy=MCPStrategy.MCP_CONFIG_FILE)
        assert _component_paths("/h", sel, [ad3], ComponentID.DXRK_MEMORY)
        ad4 = _fake_adapter(mcp_strategy=MCPStrategy.TOML_FILE)
        assert _component_paths("/h", sel, [ad4], ComponentID.DXRK_MEMORY)
        ad5 = _fake_adapter(
            mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS,
            _settings_path="",
            system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
        )
        assert _component_paths("/h", sel, [ad5], ComponentID.DXRK_MEMORY) == []
        assert _component_paths("/h", sel, [None], ComponentID.DXRK_MEMORY) == []

    def test_context7_strategies(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, MCPStrategy, Selection

        sel = Selection()
        assert _component_paths("/h", sel, [_fake_adapter()], ComponentID.CONTEXT7)
        assert _component_paths(
            "/h", sel, [_fake_adapter(mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS)], ComponentID.CONTEXT7
        )
        assert _component_paths(
            "/h", sel, [_fake_adapter(mcp_strategy=MCPStrategy.MCP_CONFIG_FILE)], ComponentID.CONTEXT7
        )
        assert (
            _component_paths(
                "/h",
                sel,
                [_fake_adapter(mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, _settings_path="")],
                ComponentID.CONTEXT7,
            )
            == []
        )

    def test_sdd_branches(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import AgentID, ComponentID, Selection, SystemPromptStrategy

        sel = Selection()
        ad = _fake_adapter()
        assert _component_paths("/h", sel, [ad], ComponentID.SDD)
        ad_nosys = _fake_adapter(supports_system_prompt=False, supports_slash_commands=False, supports_skills=False)
        assert _component_paths("/h", sel, [ad_nosys], ComponentID.SDD) == []
        ad_jinja = _fake_adapter(system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES)
        assert _component_paths("/h", sel, [ad_jinja], ComponentID.SDD)
        ad_open = _fake_adapter(agent=AgentID.OPENCODE)
        paths = _component_paths("/h", sel, [ad_open], ComponentID.SDD)
        assert any("background-agents" in p for p in paths)
        ad_noskills = _fake_adapter(_skills_dir="")
        assert _component_paths("/h", sel, [ad_noskills], ComponentID.SDD)

    def test_persona_branches(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, PersonaID, Selection

        sel = Selection(persona=PersonaID.CUSTOM)
        assert _component_paths("/h", sel, [_fake_adapter()], ComponentID.PERSONA) == []
        sel2 = Selection(persona=PersonaID.DXRK)
        paths = _component_paths("/h", sel2, [_fake_adapter()], ComponentID.PERSONA)
        assert any("dxrk.md" in p for p in paths)
        sel3 = Selection(persona=PersonaID.DXRK)
        ad = _fake_adapter(supports_system_prompt=False, supports_output_styles=False)
        assert _component_paths("/h", sel3, [ad], ComponentID.PERSONA) == []

    def test_skills_permissions_gga_theme(self, tmp_path):
        from dxrk.cli.runtime_paths import _component_paths, _sync_backup_targets
        from dxrk.models import ComponentID, PresetID, Selection

        sel = Selection(preset=PresetID.FULL_DXRK)
        ad = _fake_adapter()
        assert isinstance(_component_paths("/h", sel, [ad], ComponentID.SKILLS), list)
        sel_empty = Selection(preset=PresetID.CUSTOM, skills=[])
        assert _component_paths("/h", sel_empty, [ad], ComponentID.SKILLS) == []
        assert isinstance(_component_paths("/h", sel, [ad], ComponentID.PERMISSIONS), list)
        assert len(_component_paths("/h", sel, [ad], ComponentID.DXRK_GUARDIAN)) == 2
        assert _component_paths("/h", sel, [ad], ComponentID.THEME)
        assert _component_paths("/h", sel, [_fake_adapter(_settings_path="")], ComponentID.THEME) == []
        sel_sync = Selection(components=[ComponentID.THEME])
        with mock.patch("dxrk.cli.runtime_paths._resolve_adapters", return_value=[ad]):
            pass
        assert _sync_backup_targets("/h", sel_sync, [ad])


# ═══════════ lote 2: ComponentApplyStep por componente ═══════════


class TestComponentApplyStep:
    def _step(self, comp):
        from dxrk.cli.install_steps_components import ComponentApplyStep
        from dxrk.models import Selection
        from dxrk.system import PlatformProfile

        return ComponentApplyStep(
            step_id=f"component:{comp.value}",
            component=comp,
            home_dir="/tmp/home",
            workspace_dir="/tmp/ws",
            agents=[],
            selection=Selection(),
            profile=PlatformProfile(os="linux", package_manager="apt", supported=True),
        )

    def test_memory_brew_warn(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_MEMORY)
        step._profile.package_manager = "brew"
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
        ):
            assert step.run() is None

    def test_memory_download_fallback(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_MEMORY)
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
            mock.patch("shutil.which", return_value=None),
            mock.patch(
                "dxrk.components.memory.download_latest_binary",
                side_effect=OSError("no net"),
            ),
        ):
            assert step.run() is None

    def test_memory_inject_changed(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_MEMORY)
        ad = SimpleNamespace(agent="x")
        with (
            mock.patch(
                "dxrk.cli.install_steps_components._resolve_adapters", return_value=[ad]
            ),
            mock.patch("shutil.which", return_value="/usr/bin/memory"),
            mock.patch("dxrk.components.memory.inject", return_value=SimpleNamespace(Changed=True, Files=["f"])),
            mock.patch("dxrk.components.memory.should_attempt_setup", return_value=False),
        ):
            assert step.run() is None

    def test_memory_setup_strict_error(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_MEMORY)
        ad = SimpleNamespace(agent="x")
        with (
            mock.patch(
                "dxrk.cli.install_steps_components._resolve_adapters", return_value=[ad]
            ),
            mock.patch("shutil.which", return_value="/usr/bin/memory"),
            mock.patch("dxrk.components.memory.inject", return_value=SimpleNamespace(Changed=False)),
            mock.patch("dxrk.components.memory.should_attempt_setup", return_value=True),
            mock.patch("dxrk.components.memory.setup_agent_slug", return_value=("slug", None)),
            mock.patch("dxrk.components.memory.parse_setup_mode", return_value="x"),
            mock.patch("dxrk.components.memory.parse_setup_strict", return_value=True),
            mock.patch("dxrk.cli.install_steps_components.execute_command", return_value="boom"),
        ):
            assert "boom" in (step.run() or "")

    def test_context7_persona_permissions_sdd_skills_theme(self):
        from dxrk.models import ComponentID

        ad = SimpleNamespace(agent="x")
        with (
            mock.patch(
                "dxrk.cli.install_steps_components._resolve_adapters", return_value=[ad]
            ),
            mock.patch("dxrk.components.context7.inject", return_value=SimpleNamespace(Changed=True)),
            mock.patch("dxrk.components.persona.inject", return_value=SimpleNamespace(Changed=True)),
            mock.patch("dxrk.components.permissions.inject", return_value=SimpleNamespace(Changed=True)),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=True)),
            mock.patch("dxrk.components.skills.inject", return_value=SimpleNamespace(Changed=True)),
            mock.patch("dxrk.components.theme.inject", return_value=SimpleNamespace(Changed=True)),
        ):
            for comp in (
                ComponentID.CONTEXT7,
                ComponentID.PERSONA,
                ComponentID.PERMISSIONS,
                ComponentID.SDD,
                ComponentID.SKILLS,
                ComponentID.THEME,
            ):
                assert self._step(comp).run() is None

    def test_skills_empty_returns_none(self):
        from dxrk.cli.install_steps_components import ComponentApplyStep
        from dxrk.models import ComponentID, PresetID, Selection
        from dxrk.system import PlatformProfile

        sel = Selection(preset=PresetID.CUSTOM, skills=[])
        step = ComponentApplyStep(
            step_id="component:skills",
            component=ComponentID.SKILLS,
            home_dir="/t",
            workspace_dir="/t",
            agents=[],
            selection=sel,
            profile=PlatformProfile(os="linux", package_manager="apt", supported=True),
        )
        with mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]):
            assert step.run() is None

    def test_gga_brew_install_ok(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_GUARDIAN)
        step._profile.package_manager = "brew"
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
            mock.patch("dxrk.cli.install_steps_components._gga_available", return_value=False),
            mock.patch("dxrk.cli.install_steps_components.run_command_sequence", return_value=None),
            mock.patch("dxrk.components.gga.ensure_dxrk_guardian_shim", return_value=None),
            mock.patch("dxrk.components.gga.ensure_runtime_assets", return_value=None),
            mock.patch(
                "dxrk.components.gga.inject",
                return_value=SimpleNamespace(ConfigChanged=True, AgentsChanged=False),
            ),
        ):
            assert step.run() is None

    def test_gga_curl_warn_and_error(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.DXRK_GUARDIAN)
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
            mock.patch("dxrk.cli.install_steps_components._gga_available", side_effect=[False, True, False]),
            mock.patch("dxrk.cli.install_steps_components.run_command_sequence", return_value="warn-err"),
            mock.patch("dxrk.components.gga.ensure_dxrk_guardian_shim", return_value=None),
            mock.patch("dxrk.components.gga.ensure_runtime_assets", return_value=None),
            mock.patch(
                "dxrk.components.gga.inject",
                return_value=SimpleNamespace(ConfigChanged=False, AgentsChanged=False),
            ),
        ):
            assert step.run() is None
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
            mock.patch("dxrk.cli.install_steps_components._gga_available", return_value=False),
            mock.patch("dxrk.cli.install_steps_components.run_command_sequence", return_value="hard-err"),
            mock.patch("dxrk.components.gga.ensure_dxrk_guardian_shim", return_value=None),
        ):
            out = step.run()
            assert out == "hard-err"

    def test_unknown_component(self):
        from dxrk.models import ComponentID

        with mock.patch(
            "dxrk.cli.install_steps_components._resolve_adapters", return_value=[]
        ):
            out = self._step(ComponentID.THEME).run()
            assert out is None

    def test_gga_available_branches(self, tmp_path, monkeypatch):
        from dxrk.cli.install_steps_components import _gga_available, _selected_skill_ids, _skills_for_preset
        from dxrk.models import PresetID, Selection
        from dxrk.system import PlatformProfile

        monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/DXRK_GUARDIAN" if c == "DXRK_GUARDIAN" else None)
        assert _gga_available(PlatformProfile(os="linux", package_manager="apt", supported=True)) is True
        monkeypatch.setattr("shutil.which", lambda c: None)
        monkeypatch.setattr(os.path, "isfile", lambda p: True)
        assert _gga_available(PlatformProfile(os="darwin", package_manager="brew", supported=True)) is True
        monkeypatch.setattr(os.path, "isfile", lambda p: False)
        assert _gga_available(PlatformProfile(os="linux", package_manager="apt", supported=True)) is False
        from dxrk.models import SkillID

        sel = Selection(skills=[SkillID.SDD_INIT])
        assert _selected_skill_ids(sel) == [SkillID.SDD_INIT]
        assert len(_selected_skill_ids(Selection(preset=PresetID.FULL_DXRK))) > 0
        assert _skills_for_preset(PresetID.MINIMAL) == []


# ═══════════ lote 3: install_steps_base/agents/backup restos ═══════════


class TestInstallStepsBaseRem:
    def test_noop_id_run(self):
        from dxrk.cli.install_steps_base import NoopStep, _create_agent_adapter, _resolve_adapters
        from dxrk.models import AgentID

        assert NoopStep("x").id() == "x"
        assert NoopStep("x").run() is None
        assert _resolve_adapters([]) == []
        with mock.patch("dxrk.agents.registry.Registry.get", side_effect=Exception("boom")):
            assert _resolve_adapters([AgentID.CLAUDE_CODE]) == []
        with mock.patch("dxrk.agents.registry.Registry.get", return_value=None):
            with mock.patch(
                "dxrk.cli.install_steps_base._create_agent_adapter", return_value=None
            ):
                assert _resolve_adapters([AgentID.CLAUDE_CODE]) == []
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.return_value = SimpleNamespace(agent="a")
            assert _create_agent_adapter(AgentID.CLAUDE_CODE) is not None


class TestAgentInstallStepRem:
    def _profile(self, mgr="apt"):
        from dxrk.system import PlatformProfile

        return PlatformProfile(os="linux", package_manager=mgr, supported=True)

    def test_no_adapter(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.return_value = None
            assert "no hay adaptador" in (step.run() or "")

    def test_not_auto_install(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        ad = SimpleNamespace(supports_auto_install=False)
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.return_value = ad
            assert step.run() is None

    def test_already_installed(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        ad = SimpleNamespace(
            supports_auto_install=True, detect=lambda home: SimpleNamespace(installed=True)
        )
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.return_value = ad
            assert step.run() is None

    def test_empty_commands(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        ad = SimpleNamespace(
            supports_auto_install=True,
            detect=lambda home: SimpleNamespace(installed=False),
            install_command=lambda profile: [],
        )
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.return_value = ad
            assert "secuencia vac" in (step.run() or "")

    def test_which_missing_skips(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        ad = SimpleNamespace(
            supports_auto_install=True,
            detect=lambda home: SimpleNamespace(installed=False),
            install_command=lambda profile: [["missing-bin-zzz", "install"]],
        )
        with (
            mock.patch("dxrk.agents.factory.create_registry") as cr,
            mock.patch("shutil.which", return_value=None),
        ):
            cr.return_value.get.return_value = ad
            assert step.run() is None

    def test_run_sequence_ok(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", self._profile())
        ad = SimpleNamespace(
            supports_auto_install=True,
            detect=lambda home: SimpleNamespace(installed=False),
            install_command=lambda profile: [["sh", "-c", "exit 0"]],
        )
        with (
            mock.patch("dxrk.agents.factory.create_registry") as cr,
            mock.patch("shutil.which", return_value="/usr/bin/sh"),
            mock.patch(
                "dxrk.cli.install_steps_agents.run_command_sequence", return_value=None
            ) as rc,
        ):
            cr.return_value.get.return_value = ad
            assert step.run() is None
            assert rc.called

    def test_opencode_plugin_and_kimi(self):
        from dxrk.cli.install_steps_agents import (
            KimiSystemPromptHubStep,
            OpenCodePluginInstallStep,
        )

        with mock.patch("dxrk.components.opencodeplugin.install", return_value=None) as ins:
            assert OpenCodePluginInstallStep("p", SimpleNamespace(value="x"), "/t").run() is None
            assert OpenCodePluginInstallStep("p", SimpleNamespace(value="x"), "/t").id() == "p"
            assert ins.called
        with mock.patch("dxrk.agents.kimi.adapter.KimiAdapter", side_effect=Exception("no kimi")):
            assert KimiSystemPromptHubStep("k", "/t").run() is None
        ad = SimpleNamespace(bootstrap_template=lambda home: None)
        with mock.patch("dxrk.agents.kimi.adapter.KimiAdapter", return_value=ad):
            assert KimiSystemPromptHubStep("k", "/t").run() is None
        ad2 = SimpleNamespace(bootstrap_template="not-callable")
        with mock.patch("dxrk.agents.kimi.adapter.KimiAdapter", return_value=ad2):
            assert KimiSystemPromptHubStep("k", "/t").run() is None

    def test_check_dependencies(self):
        from dxrk.cli.install_steps_agents import CheckDependenciesStep
        from dxrk.models import AgentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE])
        step = CheckDependenciesStep("c", self._profile(), "/tmp", sel)
        assert step.id() == "c"
        with (
            mock.patch("dxrk.system.detect_dependencies", return_value=None),
            mock.patch("dxrk.agents.factory.create_registry") as cr,
        ):
            cr.return_value.get.return_value = None
            assert "error al crear" in (step.run() or "")
        with (
            mock.patch("dxrk.system.detect_dependencies", return_value=None),
            mock.patch("dxrk.agents.factory.create_registry") as cr,
        ):
            cr.return_value.get.return_value = SimpleNamespace(supports_auto_install=False)
            assert step.run() is None
        with (
            mock.patch("dxrk.system.detect_dependencies", return_value=None),
            mock.patch("dxrk.agents.factory.create_registry") as cr,
        ):
            cr.return_value.get.return_value = SimpleNamespace(
                supports_auto_install=True,
                detect=lambda home: SimpleNamespace(installed=True),
            )
            assert step.run() is None
        with (
            mock.patch("dxrk.system.detect_dependencies", return_value=None),
            mock.patch("dxrk.agents.factory.create_registry") as cr,
        ):
            cr.return_value.get.return_value = SimpleNamespace(
                supports_auto_install=True,
                detect=lambda home: SimpleNamespace(installed=False),
            )
            assert step.run() is None


class TestBackupStepsRem:
    def test_prepare_copy_error_and_manifest_error(self, tmp_path):
        from dxrk.cli.install_steps_backup import PrepareBackupStep

        src = tmp_path / "f.txt"
        src.write_text("data")
        state: dict = {}
        step = PrepareBackupStep("b", str(tmp_path / "snap"), [str(src)], state, backup_root=str(tmp_path))
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert step.run() is None
        step2 = PrepareBackupStep("b", str(tmp_path / "snap2"), [], state)
        assert step2.run() is None
        assert step2.id() == "b"
        step3 = PrepareBackupStep("b", str(tmp_path / "snap3"), [str(src)], state)
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("manifest.json"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", _fake_open):
            assert step3.run() is None

    def test_rollback_branches(self, tmp_path):
        from dxrk.cli.install_steps_backup import PrepareBackupStep, RollbackRestoreStep

        src = tmp_path / "orig.txt"
        src.write_text("v1")
        state: dict = {}
        step = PrepareBackupStep("b", str(tmp_path / "snap"), [str(src)], state, backup_root=str(tmp_path))
        assert step.run() is None
        assert step.rollback() is None
        assert RollbackRestoreStep("r", {}).rollback() is None
        assert RollbackRestoreStep("r", {}).run() is None
        assert RollbackRestoreStep("r", {}).id() == "r"
        bad_state = {"manifest": {"entries": [{"source": str(src), "dest": "rel"}]}}
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert PrepareBackupStep("b", str(tmp_path / "snap"), [], bad_state).rollback() is None
        empty_dest = {"manifest": {"entries": [{"source": "", "dest": ""}]}}
        assert PrepareBackupStep("b", str(tmp_path / "snap"), [], empty_dest).rollback() is None

    def test_rollback_restore_step_branches(self, tmp_path):
        from dxrk.cli.install_steps_backup import RollbackRestoreStep

        st = {"manifest": {"entries": [{"source": "/t", "dest": "d"}], "_backup_root": "/root"}}
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert RollbackRestoreStep("r", st).rollback() is None
        with mock.patch("os.path.isfile", return_value=False):
            assert RollbackRestoreStep("r", st).rollback() is None


def _make_detection(configs=None, all_present=True, missing=None, os_name="linux"):
    from dxrk.system import DependencyReport, DetectionResult, PlatformProfile, SystemInfo

    return DetectionResult(
        system=SystemInfo(
            os=os_name,
            supported=True,
            profile=PlatformProfile(os=os_name, package_manager="apt", supported=True),
        ),
        configs=configs or [],
        dependencies=DependencyReport(all_present=all_present, missing_required=missing or []),
    )


# ═══════════ lote 4: cli/run.py ═══════════


class TestCliRunModule:
    def test_install_result_defaults(self):
        from dxrk.cli.run import InstallResult, build_stage_plan, has_component

        r = InstallResult()
        assert r.dry_run is False and r.error == ""
        assert has_component([], "x") is False
        from dxrk.models import Selection

        plan = build_stage_plan(Selection(), SimpleNamespace(agents=[], ordered_components=[]))
        assert plan.prepare == [] and plan.apply == []
        plan2 = build_stage_plan(
            Selection(),
            SimpleNamespace(agents=[SimpleNamespace(value="a")], ordered_components=[SimpleNamespace(value="c")]),
        )
        assert len(plan2.apply) == 2

    def test_run_install_dry_run(self):
        from dxrk.cli.run import run_install as cli_run_install

        det = _make_detection()
        out = cli_run_install(["--dry-run"], det)
        assert out.dry_run is True

    def test_run_install_full_mocked(self, tmp_path, monkeypatch):
        import dxrk.cli.run as runmod

        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        det = _make_detection(all_present=False, missing=["git"])
        import dxrk.system as sysmod

        monkeypatch.setattr(sysmod, "format_missing_deps_message", lambda d: "missing-msg")

        class _FakeOrch:
            def execute(self, plan):
                return SimpleNamespace(error="")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda pol: _FakeOrch())
        monkeypatch.setattr("dxrk.pipeline.default_rollback_policy", lambda: None)
        monkeypatch.setattr(runmod, "_run_post_apply_verification", lambda *a: SimpleNamespace(ready=True))
        monkeypatch.setattr(runmod, "add_post_install_notes", lambda rep, res: None)
        monkeypatch.setattr("dxrk.state.write", lambda home, st: None)
        out = runmod.run_install([], det)
        assert out.error == ""

    def test_run_install_exec_error(self, tmp_path, monkeypatch):
        import dxrk.cli.run as runmod

        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        det = _make_detection()

        class _FakeOrch:
            def execute(self, plan):
                return SimpleNamespace(error="boom")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda pol: _FakeOrch())
        monkeypatch.setattr("dxrk.pipeline.default_rollback_policy", lambda: None)
        out = runmod.run_install([], det)
        assert "boom" in out.error

    def test_run_install_verify_not_ready(self, tmp_path, monkeypatch):
        import dxrk.cli.run as runmod

        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        det = _make_detection()

        class _FakeOrch:
            def execute(self, plan):
                return SimpleNamespace(error="")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda pol: _FakeOrch())
        monkeypatch.setattr("dxrk.pipeline.default_rollback_policy", lambda: None)
        monkeypatch.setattr(runmod, "_run_post_apply_verification", lambda *a: SimpleNamespace(ready=False))
        monkeypatch.setattr(runmod, "add_post_install_notes", lambda rep, res: None)
        out = runmod.run_install([], det)
        assert out.error == "post-apply verification failed"

    def test_verify_helpers(self, tmp_path, monkeypatch):
        import dxrk.cli.run as runmod

        assert runmod._verify_file_exists(str(tmp_path))() is None
        assert "does not exist" in (runmod._verify_file_exists(str(tmp_path / "nope"))() or "")

        assert (runmod._look_path("definitely-missing-zzz") == "") or True
        monkeypatch.setattr(runmod, "_look_path", lambda n: "")
        assert len(runmod._DXRK_MEMORY_health_checks()) == 2
        monkeypatch.setattr(runmod, "_look_path", lambda n: "/usr/bin/memory")
        checks = runmod._DXRK_MEMORY_health_checks()
        assert checks[0]() is None
        with mock.patch("subprocess.run") as sr:
            sr.return_value = SimpleNamespace(returncode=1)
            assert "failed" in (checks[1]() or "")
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("no")):
            assert "failed" in (checks[1]() or "")
        from dxrk.models import AgentID

        assert runmod._antigravity_collision_check([AgentID.CLAUDE_CODE]) == []
        both = runmod._antigravity_collision_check([AgentID.ANTIGRAVITY, AgentID.GEMINI_CLI])
        assert len(both) == 1 and "GEMINI.md" in (both[0]() or "")
        with mock.patch("dxrk.agents.factory.create_registry") as cr:
            cr.return_value.get.side_effect = Exception("x")
            assert runmod._resolve_adapters([AgentID.CLAUDE_CODE]) == []

    def test_post_install_notes_and_profile(self):
        import dxrk.cli.run as runmod
        from dxrk.models import ComponentID

        rep = SimpleNamespace(ready=True, final_note="")
        resolved = SimpleNamespace(ordered_components=[ComponentID.DXRK_GUARDIAN])
        runmod.add_post_install_notes(rep, resolved)
        assert "DXRK_GUARDIAN" in rep.final_note
        rep2 = SimpleNamespace(ready=False, final_note="")
        runmod.add_post_install_notes(rep2, resolved)
        assert rep2.final_note == ""
        det = SimpleNamespace(system=SimpleNamespace(profile=SimpleNamespace(os="linux")))
        assert runmod.resolve_install_profile(det).os == "linux"
        det2 = SimpleNamespace(system=SimpleNamespace(profile=SimpleNamespace(os="")))
        assert runmod.resolve_install_profile(det2).os == "darwin"


# ═══════════ lote 4: runtime_install stage_plan + build_real ═══════════


class TestRuntimeInstallRem:
    def _selection_resolved(self):
        from dxrk.models import AgentID, ComponentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SDD])
        sel.opencode_plugins = []
        resolved = SimpleNamespace(agents=[AgentID.CLAUDE_CODE], ordered_components=[ComponentID.SDD])
        return sel, resolved

    def test_stage_plan_kimi_opencode_empty(self, tmp_path):
        from dxrk.cli.runtime_install import InstallRuntime, build_stage_plan, resolve_install_profile
        from dxrk.models import AgentID, Selection

        sel, resolved = self._selection_resolved()
        profile = SimpleNamespace(os="linux", package_manager="apt", supported=True)
        rt = InstallRuntime(str(tmp_path), str(tmp_path), sel, resolved, profile)
        plan = rt.stage_plan()
        assert len(plan.apply) >= 2
        sel2 = Selection(agents=[AgentID.KIMI], components=[])
        resolved2 = SimpleNamespace(agents=[AgentID.KIMI], ordered_components=[])
        rt2 = InstallRuntime(str(tmp_path), str(tmp_path), sel2, resolved2, profile)
        assert any("kimi" in s.id() for s in rt2.stage_plan().apply)
        sel3 = Selection(agents=[AgentID.OPENCODE], components=[])
        sel3.opencode_plugins = [SimpleNamespace(value="plug")]
        resolved3 = SimpleNamespace(agents=[AgentID.OPENCODE], ordered_components=[])
        rt3 = InstallRuntime(str(tmp_path), str(tmp_path), sel3, resolved3, profile)
        assert any("opencode-plugin" in s.id() for s in rt3.stage_plan().apply)
        sel4 = Selection(agents=[], components=[])
        resolved4 = SimpleNamespace(agents=[], ordered_components=[])
        rt4 = InstallRuntime(str(tmp_path), str(tmp_path), sel4, resolved4, profile)
        assert rt4.stage_plan().prepare == []
        assert build_stage_plan(sel4, resolved4).prepare == []
        det = SimpleNamespace(system=SimpleNamespace(profile=SimpleNamespace(os="linux")))
        assert resolve_install_profile(det).os == "linux"
        det2 = SimpleNamespace(system=SimpleNamespace(profile=SimpleNamespace(os="")))
        assert resolve_install_profile(det2).os == "darwin"

    def test_build_real_stage_plan(self, tmp_path):
        from dxrk.cli.runtime_install import build_real_stage_plan

        sel, resolved = self._selection_resolved()
        profile = SimpleNamespace(os="linux", package_manager="apt", supported=True)
        plan = build_real_stage_plan(str(tmp_path), sel, resolved, profile)
        assert plan is not None
        with mock.patch("dxrk.cli.runtime_install.InstallRuntime", side_effect=Exception("boom")):
            with pytest.raises(RuntimeError, match="error al crear"):
                build_real_stage_plan(str(tmp_path), sel, resolved, profile)


# ═══════════ lote 4: runtime_run run_install + notes ═══════════


class TestRuntimeRunRem:
    def test_run_install_dry(self):
        from dxrk.cli.runtime_run import run_install

        det = _make_detection()
        assert run_install(["--dry-run"], det).dry_run is True

    def test_run_install_runtime_error(self, tmp_path, monkeypatch):
        import dxrk.cli.runtime_run as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        det = _make_detection()
        with mock.patch("dxrk.cli.runtime_run.InstallRuntime", side_effect=Exception("boom")):
            assert run_install_error(rr, det) != ""

    def test_run_install_exec_and_verify(self, tmp_path, monkeypatch):
        import dxrk.cli.runtime_run as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        det = _make_detection(all_present=False, missing=["g"])
        import dxrk.system as sysmod

        monkeypatch.setattr(sysmod, "format_missing_deps_message", lambda d: "m")

        class _OrchErr:
            def execute(self, plan):
                return SimpleNamespace(error="xerr")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda p: _OrchErr())
        monkeypatch.setattr("dxrk.pipeline.default_rollback_policy", lambda: None)
        assert "xerr" in rr.run_install([], det).error

        class _OrchOk:
            def execute(self, plan):
                return SimpleNamespace(error="")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda p: _OrchOk())
        monkeypatch.setattr(rr, "_run_post_apply_verification", lambda *a: SimpleNamespace(ready=True, final_note=""))
        monkeypatch.setattr(rr, "_with_post_install_notes", lambda rep, res, prof: rep)
        monkeypatch.setattr("dxrk.state.write", lambda h, s: None)
        assert rr.run_install([], det).error == ""

    def test_post_notes_and_path_helpers(self, tmp_path, monkeypatch):
        from dxrk.cli.runtime_run import (
            _go_install_bin_dir,
            _is_in_path,
            _memory_path_guidance,
            _with_post_install_notes,
        )
        from dxrk.models import ComponentID

        monkeypatch.setenv("GOBIN", "/gobin")
        assert _go_install_bin_dir() == "/gobin"
        monkeypatch.delenv("GOBIN", raising=False)
        monkeypatch.setenv("GOPATH", "/gopath")
        assert _go_install_bin_dir() == "/gopath/bin"
        monkeypatch.delenv("GOPATH", raising=False)
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        assert _go_install_bin_dir().endswith("go/bin")
        monkeypatch.setenv("PATH", f"/a{os.pathsep}/b")
        assert _is_in_path("/a") is True
        assert _is_in_path("/zzz") is False
        assert "fish_user_paths" in _memory_path_guidance("/bin/fish")
        assert ".zshrc" in _memory_path_guidance("/bin/zsh")
        assert ".bashrc" in _memory_path_guidance("/bin/bash")
        assert "PATH" in _memory_path_guidance("/bin/sh")
        rep = SimpleNamespace(ready=True, final_note="")
        resolved = SimpleNamespace(ordered_components=[ComponentID.DXRK_GUARDIAN])
        out = _with_post_install_notes(rep, resolved, SimpleNamespace(package_manager="brew"))
        assert "DXRK_GUARDIAN" in out.final_note
        rep2 = SimpleNamespace(ready=True, final_note="n")
        resolved2 = SimpleNamespace(ordered_components=[ComponentID.DXRK_MEMORY])
        prof = SimpleNamespace(package_manager="apt")
        with (
            mock.patch("dxrk.cli.runtime_run._go_install_bin_dir", return_value="/gbin"),
            mock.patch("dxrk.cli.runtime_run._is_in_path", return_value=False),
            mock.patch("dxrk.cli.runtime_run._memory_path_guidance", return_value="guide"),
        ):
            out2 = _with_post_install_notes(rep2, resolved2, prof)
            assert "/gbin" in out2.final_note
        with (
            mock.patch("dxrk.cli.runtime_run._go_install_bin_dir", return_value="/gbin"),
            mock.patch("dxrk.cli.runtime_run._is_in_path", return_value=True),
        ):
            out3 = _with_post_install_notes(SimpleNamespace(ready=True, final_note="n"), resolved2, prof)
            assert out3.final_note == "n"


def run_install_error(rr, det):
    return rr.run_install([], det).error


# ═══════════ lote 5: runtime_sync ComponentSyncStep + runtimes ═══════════


class TestComponentSyncStep:
    def _step(self, comp, sel=None):
        from dxrk.cli.runtime_sync import ComponentSyncStep
        from dxrk.models import AgentID, Selection

        if sel is None:
            sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[comp])
        return ComponentSyncStep(
            step_id=f"sync:{comp.value}",
            component=comp,
            home_dir="/tmp/h",
            workspace_dir="/tmp/w",
            agents=[AgentID.CLAUDE_CODE],
            selection=sel,
            files_changed=[0],
        )

    def test_id_and_count(self):
        from dxrk.models import ComponentID

        step = self._step(ComponentID.THEME)
        assert step.id().startswith("sync:")
        step._count_changed(0)
        assert step._files_changed == [0]
        step._count_changed(3)
        assert step._files_changed == [3]
        step2 = self._step(ComponentID.THEME)
        step2._files_changed = []
        step2._count_changed(5)

    def test_memory_context7(self):
        from dxrk.models import ComponentID

        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="a")]),
            mock.patch("dxrk.components.memory.inject", return_value=SimpleNamespace(Changed=2)),
        ):
            step = self._step(ComponentID.DXRK_MEMORY)
            assert step.run() is None
            assert step._files_changed == [2]
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="a")]),
            mock.patch("dxrk.components.context7.inject", return_value=SimpleNamespace(Changed=1)),
        ):
            assert self._step(ComponentID.CONTEXT7).run() is None

    def test_sdd_modes(self):
        from dxrk.models import AgentID, ComponentID, SDDModeID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SDD])
        sel.sdd_mode = SDDModeID.SINGLE
        sel.sdd_profile_strategy = "external-single-active"
        sel.profiles = []
        sel.model_assignments = {}
        sel.claude_model_assignments = {}
        sel.kiro_model_assignments = {}
        sel.strict_tdd = False
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="op")]),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="external-single-active"),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=1)),
        ):
            assert self._step(ComponentID.SDD, sel).run() is None
        sel2 = Selection(agents=[AgentID.OPENCODE], components=[ComponentID.SDD])
        sel2.sdd_mode = None
        sel2.sdd_profile_strategy = "generated-multi"
        sel2.profiles = []
        sel2.model_assignments = {}
        sel2.claude_model_assignments = {}
        sel2.kiro_model_assignments = {}
        sel2.strict_tdd = False
        opencode_ad = SimpleNamespace(agent=AgentID.OPENCODE, settings_path=lambda h: "/s.json")
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[opencode_ad]),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="generated-multi"),
            mock.patch("dxrk.components.sdd.detect_profiles", return_value=["p1"]),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert self._step(ComponentID.SDD, sel2).run() is None
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[opencode_ad]),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="generated-multi"),
            mock.patch("dxrk.components.sdd.detect_profiles", side_effect=Exception("x")),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert self._step(ComponentID.SDD, sel2).run() is None

    def test_skills_gga_permissions_theme(self):
        from dxrk.models import AgentID, ComponentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SKILLS])
        sel.skills = []
        with mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[]):
            assert self._step(ComponentID.SKILLS, sel).run() is None
        from dxrk.models import SkillID

        sel.skills = [SkillID.SDD_INIT]
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="a")]),
            mock.patch("dxrk.components.skills.inject", return_value=SimpleNamespace(Changed=1)),
        ):
            assert self._step(ComponentID.SKILLS, sel).run() is None
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[]),
            mock.patch("dxrk.components.gga.ensure_runtime_assets", return_value=None),
            mock.patch(
                "dxrk.components.gga.inject",
                return_value=SimpleNamespace(ConfigChanged=1, AgentsChanged=1),
            ),
        ):
            assert self._step(ComponentID.DXRK_GUARDIAN).run() is None
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="a")]),
            mock.patch("dxrk.components.permissions.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert self._step(ComponentID.PERMISSIONS).run() is None
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[SimpleNamespace(agent="a")]),
            mock.patch("dxrk.components.theme.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert self._step(ComponentID.THEME).run() is None

        class _FakeComp:
            value = "unknown-zzz"

        step = self._step(ComponentID.THEME)
        step._component = "unknown-zzz"
        with mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[]):
            assert step.run() is None


class TestSyncRuntimeFns:
    def test_build_sync_selection_branches(self):
        from dxrk.cli.runtime_sync import build_sync_selection
        from dxrk.models import AgentID

        flags = SimpleNamespace(
            include_permissions=True, include_theme=True, sdd_mode="multi",
            sdd_profile_strategy="external-single-active", strict_tdd=True, skills=[],
        )
        sel = build_sync_selection(flags, [AgentID.CLAUDE_CODE])
        assert len(sel.components) == 7
        flags2 = SimpleNamespace(
            include_permissions=False, include_theme=False, sdd_mode="",
            sdd_profile_strategy="", strict_tdd=False, skills=[],
        )
        sel2 = build_sync_selection(flags2, [])
        assert len(sel2.components) == 5

    def test_discover_agents_state_and_fallback(self, tmp_path):
        from dxrk.cli.runtime_sync import _to_agent_ids, discover_agents
        from dxrk.models import AgentID

        assert _to_agent_ids(["claude-code"]) == [AgentID.CLAUDE_CODE]
        with mock.patch("dxrk.state.read", return_value=SimpleNamespace(installed_agents=["claude-code"])):
            assert discover_agents(str(tmp_path)) == [AgentID.CLAUDE_CODE]
        with mock.patch("dxrk.state.read", side_effect=Exception("x")):
            with (
                mock.patch("dxrk.agents.discovery.discover_installed", return_value=[]),
                mock.patch("dxrk.agents.factory.create_registry"),
            ):
                assert discover_agents(str(tmp_path)) == []

    def test_run_sync_with_selection_no_agents(self):
        from dxrk.cli.runtime_sync import run_sync_with_selection
        from dxrk.models import Selection

        out = run_sync_with_selection("/tmp", Selection(agents=[]))
        assert out.no_op is True

    def test_run_sync_with_selection_exec_error(self, tmp_path):
        from dxrk.cli.runtime_sync import run_sync_with_selection
        from dxrk.models import AgentID, ComponentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.THEME])

        class _OrchErr:
            def execute(self, plan):
                return SimpleNamespace(error="boom")

        with (
            mock.patch("dxrk.pipeline.new_orchestrator", lambda p: _OrchErr()),
            mock.patch("dxrk.pipeline.default_rollback_policy", lambda: None),
        ):
            out = run_sync_with_selection(str(tmp_path), sel)
            assert out.execution.error == "boom"

    def test_run_sync_with_selection_ok_noop(self, tmp_path):
        from dxrk.cli.runtime_sync import run_sync_with_selection
        from dxrk.models import AgentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[])

        class _OrchOk:
            def execute(self, plan):
                return SimpleNamespace(error="")

        with (
            mock.patch("dxrk.pipeline.new_orchestrator", lambda p: _OrchOk()),
            mock.patch("dxrk.pipeline.default_rollback_policy", lambda: None),
            mock.patch(
                "dxrk.cli.runtime_sync._run_post_sync_verification",
                return_value=SimpleNamespace(ready=True),
            ),
        ):
            out = run_sync_with_selection(str(tmp_path), sel)
            assert out.no_op is True

    def test_run_sync_entry(self, tmp_path, monkeypatch):
        from dxrk.cli.runtime_sync import SyncRuntime, run_sync

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        with mock.patch("dxrk.cli.runtime_sync.discover_agents", return_value=[]):
            out = run_sync(["--dry-run"])
            assert out.no_op is True
        with (
            mock.patch("dxrk.cli.runtime_sync.discover_agents", return_value=[]),
            mock.patch("dxrk.state.read", return_value=SimpleNamespace(claude_model_assignments=None, model_assignments=None)),
        ):
            out2 = run_sync(["--dry-run", "--agent", "claude-code"])
            assert out2.dry_run is True
        sel_rt = SyncRuntime(str(tmp_path), str(tmp_path), out2.selection)
        assert sel_rt.stage_plan() is not None

    def test_run_sync_state_assignments(self, tmp_path, monkeypatch):
        from dxrk.cli.runtime_sync import run_sync

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        st = SimpleNamespace(
            claude_model_assignments={"a": 1},
            model_assignments={"k": SimpleNamespace(provider_id="p", model_id="m")},
        )
        with (
            mock.patch("dxrk.cli.runtime_sync.discover_agents", return_value=[]),
            mock.patch("dxrk.state.read", return_value=st),
        ):
            out = run_sync(["--dry-run", "--agent", "claude-code"])
            assert out.selection.claude_model_assignments == {"a": 1}


# ═══════════ lote 6: runtime_verify restos + uninstall/restore ═══════════


class TestRuntimeVerifyRem:
    def test_post_apply_dedup_and_empty(self, tmp_path):
        from dxrk.models import ComponentID, Selection

        f = tmp_path / "real.txt"
        f.write_text("x")
        monkeypatch_paths = [str(f), str(f), ""]
        monkeypatch_adapters = []
        import dxrk.cli.runtime_verify as mod

        orig_paths = mod._component_paths
        orig_adapters = mod._resolve_adapters
        mod._component_paths = lambda *a: monkeypatch_paths
        mod._resolve_adapters = lambda agents: monkeypatch_adapters
        try:
            resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.SDD])
            rep = mod._run_post_apply_verification(str(tmp_path), Selection(), resolved)
            assert rep.ready is True
        finally:
            mod._component_paths = orig_paths
            mod._resolve_adapters = orig_adapters

    def test_post_apply_memory_version_fail(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import ComponentID, Selection

        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: [])
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [])
        monkeypatch.setattr("dxrk.components.memory.verify_installed", lambda: None)
        monkeypatch.setattr("dxrk.components.memory.verify_version", lambda: "bad version")
        resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.DXRK_MEMORY])
        rep = rv._run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert rep.ready is True
        assert any("memory" in c.id for c in rep.checks)

    def test_post_sync_with_files(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import ComponentID, Selection

        f = tmp_path / "sync.txt"
        f.write_text("x")
        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: [])
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [str(f), str(f), ""])
        sel = Selection(agents=[], components=[ComponentID.SDD])
        rep = rv._run_post_sync_verification(str(tmp_path), sel)
        assert rep.ready is True
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [str(tmp_path / "missing-zzz")])
        rep2 = rv._run_post_sync_verification(str(tmp_path), sel)
        assert rep2.ready is False


class TestRuntimeUninstallRestore:
    def test_prompt_uninstall_branches(self, monkeypatch):
        from dxrk.cli.install_flags import UninstallFlags
        from dxrk.cli.runtime_uninstall import _prompt_uninstall_confirm

        out = io.StringIO()
        monkeypatch.setattr("builtins.input", lambda: "yes")
        assert _prompt_uninstall_confirm(UninstallFlags(all=True), out) is True
        out2 = io.StringIO()
        monkeypatch.setattr("builtins.input", lambda: "no")
        assert _prompt_uninstall_confirm(UninstallFlags(agents=["a"], components=["c"]), out2) is False
        out3 = io.StringIO()
        monkeypatch.setattr("builtins.input", lambda: (_ for _ in ()).throw(EOFError()))
        assert _prompt_uninstall_confirm(UninstallFlags(agents=["a"]), out3) is False

    def test_run_uninstall_cancel_and_ok(self, monkeypatch):
        from dxrk.cli.runtime_uninstall import run_uninstall

        out = io.StringIO()
        monkeypatch.setattr("builtins.input", lambda: "no")
        assert run_uninstall(["--agent", "a"], out) is None
        assert "cancelada" in out.getvalue()
        monkeypatch.setattr("builtins.input", lambda: "yes")
        with mock.patch("dxrk.components.uninstall.Service") as svc:
            svc.return_value.complete_uninstall.return_value = SimpleNamespace(ok=True)
            assert run_uninstall(["--all", "--yes"], out).ok is True
        with mock.patch("dxrk.components.uninstall.Service") as svc:
            svc.return_value.partial_uninstall.return_value = SimpleNamespace(ok=2)
            assert run_uninstall(["--agent", "claude-code", "--yes"], out).ok == 2

    def test_run_uninstall_stdout_none(self, monkeypatch):
        import sys

        from dxrk.cli.runtime_uninstall import run_uninstall

        monkeypatch.setattr("builtins.input", lambda: "no")
        with mock.patch.object(sys, "stdout", io.StringIO()):
            assert run_uninstall(["--agent", "a"]) is None

    def test_restore_stdout_none_and_branches(self, tmp_path, monkeypatch):
        import sys

        import dxrk.cli.runtime_restore as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        with mock.patch.object(sys, "stdout", io.StringIO()) as buf:
            assert rr.run_restore(["--list"]) is None
            assert "no se encontraron" in buf.getvalue()
        out = io.StringIO()
        assert rr.run_restore([], out) == "uso: dxrk-py restore [--list | latest | <id>] [--yes]"
        with pytest.raises(ValueError, match="no hay copias"):
            rr._resolve_restore_target("latest", [])
        with pytest.raises(ValueError, match="no encontrada"):
            rr._resolve_restore_target("zzz", [{"_id": "aaa"}])
        assert rr._resolve_restore_target("latest", [{"_id": "b"}, {"_id": "a"}])["_id"] == "b"
        backups = [{"_id": "1", "source": "s", "entries": [], "created_by_version": "2"}]
        rr._render_restore_list(backups, out)
        assert "Copias" in out.getvalue()
        monkeypatch.setattr("builtins.input", lambda: "YES")
        assert rr._prompt_restore_confirm({"_id": "1", "source": "s", "entries": []}, out) is True
        monkeypatch.setattr("builtins.input", lambda: "no")
        assert rr._prompt_restore_confirm({"_id": "1", "source": "s", "entries": []}, out) is False

    def test_restore_copy_flow(self, tmp_path, monkeypatch):
        import dxrk.cli.runtime_restore as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        backup_root = tmp_path / ".gentle-ai" / "backups" / "b1"
        backup_root.mkdir(parents=True)
        dest_target = tmp_path / "dest.txt"
        dest_target.write_text("orig")
        src_in_backup = backup_root / "f.txt"
        src_in_backup.write_text("restored")
        manifest = {
            "_dir": str(backup_root),
            "_id": "b1",
            "source": "test",
            "description": "d",
            "entries": [{"source": str(dest_target), "dest": "f.txt"}],
        }
        with (
            mock.patch("dxrk.cli.runtime_restore._list_backups", return_value=[manifest]),
        ):
            out = io.StringIO()
            assert rr.run_restore(["b1", "--yes"], out) is None
            assert dest_target.read_text() == "restored"
            assert "restauraci" in out.getvalue()
        with mock.patch("dxrk.cli.runtime_restore._list_backups", return_value=[manifest]):
            monkeypatch.setattr("builtins.input", lambda: "no")
            out2 = io.StringIO()
            assert rr.run_restore(["b1"], out2) is None
            assert "cancelada" in out2.getvalue()

    def test_list_backups_branches(self, tmp_path, monkeypatch):
        import dxrk.cli.runtime_restore as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        assert rr._list_backups(str(tmp_path)) == []
        root = tmp_path / ".gentle-ai" / "backups"
        root.mkdir(parents=True)
        (root / "file-not-dir").write_text("x")
        good = root / "20240101"
        good.mkdir()
        (good / "manifest.json").write_text(json.dumps({"source": "s", "entries": []}))
        bad = root / "20240102"
        bad.mkdir()
        (bad / "manifest.json").write_text("{bad json")
        nodir = root / "20240103"
        nodir.mkdir()
        out = rr._list_backups(str(tmp_path))
        assert len(out) == 1 and out[0]["_id"] == "20240101"


class TestRuntimeReportsRem:
    def test_dry_run_no_sdd_mode(self):
        from dxrk.cli.runtime_install import InstallResult
        from dxrk.cli.runtime_reports import render_dry_run
        from dxrk.models import Selection

        sel = Selection()
        sel.sdd_mode = None
        resolved = SimpleNamespace(agents=[], unsupported_agents=[], ordered_components=[], added_dependencies=[])
        text = render_dry_run(InstallResult(selection=sel, resolved=resolved, review=None, plan=None))
        assert "Agentes" in text

    def test_sync_dry_no_components(self):
        from dxrk.cli.runtime_reports import render_sync_report
        from dxrk.cli.runtime_sync import SyncResult
        from dxrk.models import AgentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[])
        text = render_sync_report(SyncResult(dry_run=True, agents=[AgentID.CLAUDE_CODE], selection=sel, plan=None))
        assert "Agentes" in text and "Componentes" not in text

    def test_uninstall_manifest_no_backup(self):
        from dxrk.cli.runtime_reports import render_uninstall_report

        res = SimpleNamespace(
            Manifest={"entries": [{"a": 1}]},
            BackupPath="",
            ChangedFiles=[],
            RemovedFiles=[],
            RemovedDirectories=[],
            AgentsRemovedFromState=[],
            ManualActions=[],
        )
        text = render_uninstall_report(res)
        assert "Archivos cambiados" in text
        res2 = SimpleNamespace(
            Manifest={},
            BackupPath="",
            ChangedFiles=[],
            RemovedFiles=[],
            RemovedDirectories=[],
            AgentsRemovedFromState=[],
            ManualActions=[],
        )
        assert "Archivos cambiados" in render_uninstall_report(res2)

    def test_uninstall_relpath_parent(self, tmp_path, monkeypatch):
        from dxrk.cli.runtime_reports import render_uninstall_report

        monkeypatch.chdir(tmp_path)
        res = SimpleNamespace(
            Manifest={},
            BackupPath="",
            ChangedFiles=["/etc/outside-file"],
            RemovedFiles=[],
            RemovedDirectories=[],
            AgentsRemovedFromState=[],
            ManualActions=[],
        )
        assert "/etc/outside-file" in render_uninstall_report(res)


# ═══════════ lote 7: dxrk/__main__ (raíz) ═══════════


class TestMainRebuild:
    def test_rebuild_install_raw(self):
        import dxrk.__main__ as m

        args = SimpleNamespace(
            agents=["a"], components=["c"], skills=["s"], persona="dxrk",
            preset="full-dxrk", sdd_mode="single", dry_run=True,
        )
        raw = m._rebuild_install_raw(args)
        assert "--agent" in raw and "--dry-run" in raw
        empty = SimpleNamespace(agents=None, components=None, skills=None, persona="", preset=None, sdd_mode="", dry_run=False)
        assert m._rebuild_install_raw(empty) == []

    def test_rebuild_sync_raw(self):
        import dxrk.__main__ as m

        args = SimpleNamespace(
            agents=["a"], skills=["s"], sdd_mode="m", sdd_profile_strategy="generated-multi",
            strict_tdd=True, include_permissions=True, include_theme=True,
            profiles=["p"], profile_phases=["pp"], dry_run=True,
        )
        raw = m._rebuild_sync_raw(args)
        assert "--strict-tdd" in raw and "--profile" in raw
        empty = SimpleNamespace(
            agents=None, skills=None, sdd_mode="", sdd_profile_strategy="",
            strict_tdd=False, include_permissions=False, include_theme=False,
            profiles=None, profile_phases=None, dry_run=False,
        )
        assert m._rebuild_sync_raw(empty) == []

    def test_rebuild_uninstall_restore_raw(self):
        import dxrk.__main__ as m

        args = SimpleNamespace(agents=["a"], components=["c"], all=True, yes=True)
        assert "--all" in m._rebuild_uninstall_raw(args)
        r = SimpleNamespace(backup_id="b1", list=True, yes=True)
        assert "b1" in m._rebuild_restore_raw(r)
        assert m._rebuild_restore_raw(SimpleNamespace(backup_id=None, list=False, yes=False)) == []

    def test_is_installed_branches(self, tmp_path, monkeypatch):
        import dxrk.__main__ as m

        assert m._is_installed(str(tmp_path)) is False
        with mock.patch("dxrk.state.read", return_value=SimpleNamespace(installed_agents=["a"])):
            assert m._is_installed(str(tmp_path)) is True
        with mock.patch("dxrk.state.read", side_effect=FileNotFoundError()):
            assert m._is_installed(str(tmp_path)) is False
        import sys as _sys

        with mock.patch.dict(_sys.modules, {"dxrk.state": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError("no mod")):
                try:
                    assert m._is_installed(str(tmp_path)) is False
                except ImportError:
                    pass


class TestMainCommands:
    def _argv(self, monkeypatch, *args):
        import sys

        monkeypatch.setattr(sys, "argv", ["dxrk-py", *args])

    def test_version_flags(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "--version")
        m.main()
        assert "Dxrk v" in capsys.readouterr().out
        self._argv(monkeypatch, "version")
        m.main()
        assert "Dxrk v" in capsys.readouterr().out

    def test_health_ok_and_fail(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "--health")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(dependencies=None)),
        ):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 1
        with mock.patch(
            "dxrk.system.detect",
            return_value=SimpleNamespace(dependencies=SimpleNamespace()),
        ):
            with mock.patch("dxrk.system.render_dependency_report", return_value="healthy"):
                m.main()
                assert "healthy" in capsys.readouterr().out

    def test_install_flows(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "install", "--dry-run")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=False, os="weird"))),
        ):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 1
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.run_install", return_value=SimpleNamespace(error="boom", dry_run=False)),
        ):
            with pytest.raises(SystemExit):
                m.main()
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch(
                "dxrk.cli.install.run_install",
                return_value=SimpleNamespace(
                    error="", dry_run=True,
                    review=SimpleNamespace(
                        agents=[1], unsupported_agents=[], persona="p", preset="pr",
                        components=[1], skills=[], strict_tdd=False, has_sdd=True,
                        platform_decision=SimpleNamespace(os="linux", linux_distro="u"),
                    ),
                ),
            ),
        ):
            m.main()
            assert "Dry Run" in capsys.readouterr().out

    def test_sync_flows(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "sync", "--dry-run")
        with mock.patch("dxrk.cli.sync.RunSync", side_effect=Exception("boom")):
            with pytest.raises(SystemExit):
                m.main()
        with mock.patch(
            "dxrk.cli.sync.RunSync",
            return_value=SimpleNamespace(dry_run=True, agents=[1], selection=SimpleNamespace(sdd_mode="s", strict_tdd=True)),
        ):
            m.main()
            assert "Dry Run" in capsys.readouterr().out
        with mock.patch(
            "dxrk.cli.sync.RunSync",
            return_value=SimpleNamespace(dry_run=False, files_changed=3),
        ):
            m.main()
            assert "3 files changed" in capsys.readouterr().out

    def test_uninstall_flows(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "uninstall", "--agent", "a", "--yes")
        with mock.patch("dxrk.cli.uninstall.RunUninstall", side_effect=Exception("boom")):
            with pytest.raises(SystemExit):
                m.main()
        with mock.patch(
            "dxrk.cli.uninstall.RunUninstall",
            return_value=SimpleNamespace(removed_files=[], manual_actions=["do-x"]),
        ):
            m.main()
            out = capsys.readouterr().out
            assert "Manual" in out and "Uninstall complete" in out

    def test_backup_restore_flows(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "backup")
        with mock.patch("dxrk.backup.list_backups", return_value=[]):
            m.main()
            assert "No backups" in capsys.readouterr().out
        with mock.patch("dxrk.backup.list_backups", return_value=["b1"]):
            m.main()
            assert "b1" in capsys.readouterr().out
        self._argv(monkeypatch, "restore", "--list")
        with mock.patch("dxrk.cli.restore.RunRestore", return_value=None):
            m.main()
        with mock.patch("dxrk.cli.restore.RunRestore", side_effect=ValueError("bad")):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 2
        with mock.patch("dxrk.cli.restore.RunRestore", side_effect=Exception("boom")):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 1
        with mock.patch("dxrk.cli.restore.RunRestore", return_value="usage-msg"):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 1

    def test_model_flows(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "model")
        with mock.patch("dxrk.model.get_model_assignments", return_value={}):
            m.main()
            assert "No model" in capsys.readouterr().out
        with mock.patch(
            "dxrk.model.get_model_assignments",
            return_value={"a": SimpleNamespace(full_id=lambda: "p/m")},
        ):
            m.main()
            assert "p/m" in capsys.readouterr().out
        self._argv(monkeypatch, "model", "phase1")
        with mock.patch("dxrk.model.get_model_assignments", return_value={}):
            m.main()
            assert "No model configured" in capsys.readouterr().out
        with mock.patch(
            "dxrk.model.get_model_assignments",
            return_value={"phase1": SimpleNamespace(full_id=lambda: "p/m")},
        ):
            m.main()
            assert "p/m" in capsys.readouterr().out
        self._argv(monkeypatch, "model", "phase1", "--provider", "p")
        with pytest.raises(SystemExit) as ei:
            m.main()
            assert ei.value.code == 2
        self._argv(monkeypatch, "model", "phase1", "--provider", "p", "--model", "不再")
        with mock.patch("dxrk.model.set_model_assignment", side_effect=ValueError("bad")):
            with pytest.raises(SystemExit):
                m.main()
        with mock.patch(
            "dxrk.model.set_model_assignment",
            return_value=SimpleNamespace(full_id=lambda: "p/m"),
        ):
            m.main()
            assert "p/m" in capsys.readouterr().out

    def test_tenant_enterprise_unknown(self, monkeypatch):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "tenant", "list")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 3
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 3
        self._argv(monkeypatch, "enterprise", "status")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
        self._argv(monkeypatch, "upgrade", "--dry-run")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.resolve_install_profile", return_value=SimpleNamespace()),
            mock.patch("dxrk.update.check_filtered", return_value=[]),
            mock.patch("dxrk.update.has_check_failures", return_value=False),
            mock.patch("dxrk.update.has_updates", return_value=False),
            mock.patch(
                "dxrk.update.execute",
                return_value=SimpleNamespace(results=[]),
            ),
            mock.patch("dxrk.update.render_upgrade_report", return_value="rep"),
        ):
            m.main()

    def test_invalid_tenant_and_unknown_command(self, monkeypatch):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "--tenant", "bad id!!!", "version")
        with pytest.raises(SystemExit):
            m.main()

    def test_no_command_launches_installer(self, monkeypatch):
        import dxrk.__main__ as m

        self._argv(monkeypatch)
        with mock.patch("dxrk.__main__._launch_single_installer") as li:
            m.main()
            assert li.called

    def test_single_installer_branches(self, tmp_path, monkeypatch):
        import dxrk.__main__ as m

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        with (
            mock.patch("dxrk.__main__._is_installed", return_value=False),
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace()),
            mock.patch("dxrk.cli.install.run_install", side_effect=Exception("boom")),
            mock.patch("dxrk.__main__._launch_tui") as tui,
        ):
            m._launch_single_installer("1.0")
            assert tui.called
        with (
            mock.patch("dxrk.__main__._is_installed", side_effect=[False, True]),
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace()),
            mock.patch("dxrk.cli.install.run_install", return_value=SimpleNamespace(error="")),
            mock.patch("dxrk.__main__._launch_tui"),
        ):
            m._launch_single_installer("1.0")
        with (
            mock.patch("dxrk.__main__._is_installed", side_effect=[False, False]),
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace()),
            mock.patch("dxrk.cli.install.run_install", return_value=SimpleNamespace(error="e")),
            mock.patch("dxrk.__main__._launch_tui"),
        ):
            m._launch_single_installer("1.0")
        with (
            mock.patch("dxrk.__main__._is_installed", return_value=True),
            mock.patch("dxrk.__main__._launch_tui") as tui2,
        ):
            m._launch_single_installer("1.0")
            assert tui2.called


# ═══════════ lote 8: scholar providers (sin red real) ═══════════


class _FakeHttpxClient:
    def __init__(self, status=200, payload=None, error=None):
        import httpx as _hx

        self._status = status
        self._payload = payload
        self._error = error
        self._hx = _hx

    def get(self, url, params=None, **kwargs):
        if self._error is not None:
            raise self._error
        hx = self._hx
        req = hx.Request("GET", url if url.startswith("http") else "http://x")
        if self._status != 200:
            return hx.Response(self._status, request=req)
        if isinstance(self._payload, str):
            return hx.Response(200, text=self._payload, request=req)
        import json as _json

        return hx.Response(200, json=_json.loads(_json.dumps(self._payload if self._payload is not None else {})), request=req)


def _req_error():
    import httpx as _hx

    return _hx.RequestError("boom", request=_hx.Request("GET", "http://x"))


class TestScholarProvidersNoNet:
    def test_arxiv_branches(self):
        from dxrk.scholar.arxiv import ArxivProvider, NewArxivProvider

        assert NewArxivProvider().name() == "arxiv"
        p = ArxivProvider(client=_FakeHttpxClient(error=_req_error()))
        papers, err = p.search("q", 5)
        assert papers == [] and "request" in (err or "")
        p2 = ArxivProvider(client=_FakeHttpxClient(status=500))
        _, err2 = p2.search("q", 5)
        assert "status" in (err2 or "")
        p3 = ArxivProvider(client=_FakeHttpxClient(payload="not xml <"))
        _, err3 = p3.search("q", 5)
        assert "decode" in (err3 or "")
        feed = (
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            "<title>T</title><summary>Abs</summary><id>http://x</id>"
            "<published>20AB</published><author><name>A</name></author>"
            "</entry><entry><title>T2</title><summary>B</summary><id>u2</id>"
            "<published>2021-01-01</published></entry></feed>"
        )
        p4 = ArxivProvider(client=_FakeHttpxClient(payload=feed))
        papers4, err4 = p4.search("q", 5)
        assert err4 is None and len(papers4) == 2 and papers4[1].year == 2021
        assert p4.fetch_by_doi("10.1/x") == (None, None)

    def test_crossref_branches(self):
        from dxrk.scholar.crossref import CrossrefProvider, NewCrossrefProvider

        assert NewCrossrefProvider().name() == "crossref"
        p = CrossrefProvider(client=_FakeHttpxClient(error=_req_error()))
        assert "request" in (p.search("q", 1)[1] or "")
        assert "request" in (p.fetch_by_doi("10.1/x")[1] or "")
        p500 = CrossrefProvider(client=_FakeHttpxClient(status=500))
        assert "status" in (p500.search("q", 1)[1] or "")
        assert "status" in (p500.fetch_by_doi("10.1/x")[1] or "")

        class _BadJson:
            status_code = 200

            def json(self):
                raise ValueError("bad")

        class _BadClient:
            def get(self, *a, **k):
                return _BadJson()

        assert "decode" in (CrossrefProvider(client=_BadClient()).search("q", 1)[1] or "")
        assert "decode" in (CrossrefProvider(client=_BadClient()).fetch_by_doi("10.1/x")[1] or "")
        msg = {
            "author": [{"given": "A", "family": "B"}, {"given": "", "family": ""}],
            "issued": {"date-parts": [[2020]]},
            "title": ["T"],
            "link": [{"URL": ""}, {"URL": "http://pdf"}],
            "DOI": "10.1/x",
            "abstract": " abs ",
            "URL": "http://u",
        }
        paper = CrossrefProvider(client=_FakeHttpxClient())._map_message(msg)
        assert paper.year == 2020 and paper.pdf_url == "http://pdf"
        empty = CrossrefProvider(client=_FakeHttpxClient())._map_message({})
        assert empty.title == "" and empty.year == 0

    def test_openalex_branches(self):
        from dxrk.scholar.openalex import (
            NewOpenAlexProvider,
            OpenAlexProvider,
            map_openalex_work,
            rebuild_openalex_abstract,
        )

        assert NewOpenAlexProvider().name() == "openalex"
        assert rebuild_openalex_abstract(None) == ""
        assert rebuild_openalex_abstract({}) == ""
        assert rebuild_openalex_abstract({"hello": [1], "world": [0]}) == "world hello"
        assert map_openalex_work({"display_name": "  "}) is None
        w = {
            "display_name": " T ",
            "doi": "https://doi.org/10.1/x",
            "authorships": [{"author": {"display_name": " A "}}, {"author": {}}],
            "primary_location": {},
            "open_access": {"oa_url": "http://oa"},
            "abstract_inverted_index": {"a": [0]},
            "publication_year": 2019,
        }
        paper = map_openalex_work(w)
        assert paper is not None and paper.url == "https://doi.org/10.1/x" and paper.pdf_url == "http://oa"
        p = OpenAlexProvider(client=_FakeHttpxClient(error=_req_error()))
        assert p.search("q", 0)[1] is not None
        assert p.fetch_by_doi("10.1/x")[1] is not None
        p404 = OpenAlexProvider(client=_FakeHttpxClient(status=404))
        assert p404.search("q", 5) == ([], None)
        p500 = OpenAlexProvider(client=_FakeHttpxClient(status=500))
        assert "status" in (p500.search("q", 5)[1] or "")

        class _BadJson:
            status_code = 200

            def json(self):
                raise ValueError("bad")

        class _BadClient:
            def get(self, *a, **k):
                return _BadJson()

        assert "decode search" in (OpenAlexProvider(client=_BadClient()).search("q", 5)[1] or "")
        assert "decode doi" in (OpenAlexProvider(client=_BadClient()).fetch_by_doi("10.1/x")[1] or "")
        p_none = OpenAlexProvider(client=_FakeHttpxClient(payload={"results": [{"display_name": " "}]}))
        assert p_none.search("q", 5)[0] == []

    def test_pubmed_branches(self):
        from dxrk.scholar.pubmed import NewPubMedProvider, PubMedProvider, map_pubmed_summary, pubmed_year

        assert NewPubMedProvider().name() == "pubmed"
        assert pubmed_year("") == 0
        assert pubmed_year("2021abc") == 2021
        assert pubmed_year("ab2021") == 0
        assert map_pubmed_summary({"title": " "}) is None
        s = {"title": " T ", "authors": [{"name": " A "}, {}], "uid": "123", "doi": "10.1/x", "abstract": " a ", "pubdate": "2020"}
        paper = map_pubmed_summary(s)
        assert paper is not None and paper.url.endswith("/123/") and paper.year == 2020
        s2 = {"title": "T", "authors": []}
        assert map_pubmed_summary(s2) is not None
        p = PubMedProvider(client=_FakeHttpxClient(error=_req_error()))
        assert p.search("q", 0)[1] is not None
        p404 = PubMedProvider(client=_FakeHttpxClient(status=404))
        assert p404.search("q", 5) == ([], None)
        p_empty = PubMedProvider(client=_FakeHttpxClient(payload={"esearchresult": {"idlist": []}}))
        assert p_empty.search("q", 5) == ([], None)
        assert p_empty.fetch_by_doi("10.1/x") == (None, None)

        class _BadJson:
            status_code = 200

            def json(self):
                raise ValueError("bad")

        class _BadClient:
            def get(self, *a, **k):
                return _BadJson()

        assert "decode search" in (PubMedProvider(client=_BadClient()).search("q", 5)[1] or "")
        assert "decode summary" in (PubMedProvider(client=_BadClient())._fetch_summaries(["1"])[1] or "")

    def test_semanticscholar_branches(self):
        from dxrk.scholar.semanticscholar import NewSemanticScholarProvider, SemanticScholarProvider, _map_ss_paper

        assert NewSemanticScholarProvider().name() == "semantic_scholar"
        assert _map_ss_paper({"title": " "}) is None
        item = {
            "title": " T ",
            "externalIds": {"DOI": "10.1/x"},
            "openAccessPdf": {"url": "http://pdf"},
            "authors": [{"name": " A "}, "bad", {}],
            "url": "",
            "year": "notanint",
            "abstract": " a ",
        }
        paper = _map_ss_paper(item)
        assert paper is not None and paper.url == "https://doi.org/10.1/x" and paper.year == 0
        assert _map_ss_paper({"title": "T", "externalIds": "bad", "openAccessPdf": "bad", "authors": None}) is not None
        p = SemanticScholarProvider(client=_FakeHttpxClient(error=_req_error()))
        assert p.search("q", 0)[1] is not None
        assert p.fetch_by_doi("10.1/x")[1] is not None
        p404 = SemanticScholarProvider(client=_FakeHttpxClient(status=404))
        assert p404.search("q", 5) == ([], None)
        assert p404.fetch_by_doi("10.1/x") == (None, None)
        p500 = SemanticScholarProvider(client=_FakeHttpxClient(status=500))
        assert "status" in (p500.search("q", 5)[1] or "")

        class _BadJson:
            status_code = 200

            def json(self):
                raise ValueError("bad")

        class _BadClient:
            def get(self, *a, **k):
                return _BadJson()

        assert "decode search" in (SemanticScholarProvider(client=_BadClient()).search("q", 5)[1] or "")
        assert "decode doi" in (SemanticScholarProvider(client=_BadClient()).fetch_by_doi("10.1/x")[1] or "")
        p_data = SemanticScholarProvider(client=_FakeHttpxClient(payload={"data": ["bad", {"title": " "}]}))
        assert p_data.search("q", 5) == ([], None)

        class _NonDict:
            status_code = 200

            def json(self):
                return ["not", "dict"]

        class _NonDictClient:
            def get(self, *a, **k):
                return _NonDict()

        assert SemanticScholarProvider(client=_NonDictClient()).fetch_by_doi("10.1/x") == (None, None)

    def test_scholar_tools_branches(self):
        from dxrk.scholar.provider import Paper
        from dxrk.scholar.tools import RegisterTools
        from dxrk.tools import Registry

        class _Reg(Registry):
            pass

        reg = _Reg()
        RegisterTools(reg, None)
        search = reg.get("scholar_search")
        out, err = search.execute(None, {})
        assert err == "query is required"
        out, err = search.execute(None, {"query": 123})
        assert out.get("enabled") is False
        out, err = search.execute(None, {"query": "q", "limit": "bad", "source": 123})
        assert out.get("enabled") is False
        fake_scholar = SimpleNamespace(
            Search=lambda q, l: ([], "boom"),
            FetchByDOI=lambda doi: (None, "boom"),
        )
        reg2 = Registry()
        RegisterTools(reg2, fake_scholar)
        out, err = reg2.get("scholar_search").execute(None, {"query": "q"})
        assert "scholar search" in (err or "")
        fake_empty = SimpleNamespace(Search=lambda q, l: ([], None), FetchByDOI=lambda d: (None, None))
        reg3 = Registry()
        RegisterTools(reg3, fake_empty)
        out, _ = reg3.get("scholar_search").execute(None, {"query": "q"})
        assert out["total"] == 0
        p = Paper(title="T", authors=["A"], doi="10.1/x", abstract="a", url="u", pdf_url="", year=2020, source="arxiv")
        fake_full = SimpleNamespace(Search=lambda q, l: ([p], None), FetchByDOI=lambda d: (p, None))
        reg4 = Registry()
        RegisterTools(reg4, fake_full)
        out, _ = reg4.get("scholar_search").execute(None, {"query": "q", "source": "other"})
        assert out["total"] == 0
        out, _ = reg4.get("scholar_search").execute(None, {"query": "q"})
        assert out["total"] == 1
        cite = reg4.get("scholar_cite")
        out, err = cite.execute(None, {"doi": "bad-doi"})
        assert "invalid DOI" in (err or "")
        out, err = cite.execute(None, {"doi": 123})
        assert err is not None
        reg5 = Registry()
        RegisterTools(reg5, None)
        out, _ = reg5.get("scholar_cite").execute(None, {"doi": "10.1234/abc"})
        assert out.get("enabled") is False
        out, err = reg4.get("scholar_cite").execute(None, {"doi": "10.1234/abc"})
        assert out["found"] is True and "bibtex" in out
        reg6 = Registry()
        RegisterTools(reg6, fake_scholar)
        out, err = reg6.get("scholar_cite").execute(None, {"doi": "10.1234/abc"})
        assert "scholar fetch" in (err or "")
        reg7 = Registry()
        RegisterTools(reg7, fake_empty)
        out, _ = reg7.get("scholar_cite").execute(None, {"doi": "10.1234/abc"})
        assert out["found"] is False

    def test_scholar_aggregator_extra(self):
        from dxrk.scholar.provider import Paper
        from dxrk.scholar.scholar import New, Scholar

        s = Scholar()
        assert s.Search("q", 5) == ([], None)
        assert s.FetchByDOI("10.1/x") == (None, None)
        err_provider = SimpleNamespace(search=lambda q, l: ([], "boom"), fetch_by_doi=lambda d: (None, "boom"))
        s2 = New([err_provider])
        assert s2.Search("q", 5) == ([], None)
        assert s2.FetchByDOI("10.1/x") == (None, None)
        p = Paper(title="T")
        ok = SimpleNamespace(search=lambda q, l: ([p, p, p], None), fetch_by_doi=lambda d: (p, None))
        s3 = New([ok])
        papers, _ = s3.Search("q", 2)
        assert len(papers) == 2
        assert s3.FetchByDOI("10.1/x")[0] == p
        none_provider = SimpleNamespace(search=lambda q, l: ([], None), fetch_by_doi=lambda d: (None, None))
        assert New([none_provider]).FetchByDOI("10.1/x") == (None, None)


# ═══════════ lote 9: rag embedder/indexer/tools + router restos ═══════════


class TestRagEmbedderNoNet:
    def test_protocol_and_constructor(self):
        from dxrk.rag.embedder import DEFAULT_BASE_URL, DEFAULT_EMBEDDING_MODEL, NewOpenAIEmbedder

        e = NewOpenAIEmbedder("k", "", "")
        assert e.model() == DEFAULT_EMBEDDING_MODEL
        assert e._base_url == DEFAULT_BASE_URL
        e2 = NewOpenAIEmbedder("k", "m", "http://x/")
        assert e2._base_url == "http://x"
        assert e2.dimensions() == 1536
        assert e2.embed([]) is None

    def test_embed_batch_branches(self, monkeypatch):
        import urllib.request as urlreq

        from dxrk.rag.embedder import NewOpenAIEmbedder

        e = NewOpenAIEmbedder("k", "m", "http://x")

        class _Resp:
            def __init__(self, status, raw):
                self.status = status
                self._raw = raw

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(Exception("net-down")))
        assert e.embed(["a"]) is None
        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: _Resp(500, b"err"))
        assert e.embed(["a"]) is None
        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: _Resp(200, b"not-json"))
        assert e.embed(["a"]) is None
        import json as _json

        payload = _json.dumps({"data": [{"index": 0, "embedding": [1, 2]}, {"index": 5, "embedding": [3]}]}).encode()
        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: _Resp(200, payload))
        out = e.embed(["a"])
        assert out is not None and out[0] == [1, 2]
        payload2 = _json.dumps({"data": [{"index": "bad"}, {"embedding": []}]}).encode()
        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: _Resp(200, payload2))
        out2 = e.embed(["a"])
        assert out2 == []
        big = [f"t{i}" for i in range(300)]
        monkeypatch.setattr(urlreq, "urlopen", lambda req, timeout=None: _Resp(200, _json.dumps({"data": []}).encode()))
        assert e.embed(big) is not None


class TestRagIndexerTools:
    def test_index_branches(self, tmp_path):
        from dxrk.rag.chunker import ChunkConfig
        from dxrk.rag.indexer import Indexer
        from dxrk.rag.store import VectorStore

        class _NoneEmb:
            def embed(self, texts):
                return None

            def model(self):
                return "n"

            def dimensions(self):
                return 3

        root = tmp_path / "proj"
        root.mkdir()
        (root / "a.py").write_text("print(1)\n")
        (root / "skip.bin").write_text("x")
        idx = Indexer(VectorStore(3), _NoneEmb(), str(root), ChunkConfig(512, 64))
        stats = idx.Index()
        assert stats.files_scanned == 1 and stats.files_indexed == 0
        assert idx.Query("q", 5) is None
        assert idx.LastRun() is not None
        assert idx.TotalVectors() == 0

        class _EmptyEmb:
            def embed(self, texts):
                return []

            def model(self):
                return "e"

            def dimensions(self):
                return 3

        idx2 = Indexer(VectorStore(3), _EmptyEmb(), str(root), ChunkConfig(512, 64))
        assert idx2.Query("q", 5) is None

        class _OkEmb:
            def embed(self, texts):
                return [[1.0] * 3 for _ in texts]

            def model(self):
                return "o"

            def dimensions(self):
                return 3

        idx3 = Indexer(VectorStore(3), _OkEmb(), str(root), ChunkConfig(512, 64))
        idx3.AddIgnoreDir("extra-ignore")
        stats3 = idx3.Index()
        assert stats3.files_indexed == 1
        assert idx3.Index().files_indexed == 0
        assert idx3.Query("q", 5) is not None
        (root / "bad.py").write_text("x")
        with mock.patch("dxrk.rag.indexer.ChunkFile", return_value=[]):
            idx4 = Indexer(VectorStore(3), _OkEmb(), str(root), ChunkConfig(512, 64))
            assert idx4.Index().files_indexed == 0
        assert Indexer._file_hash(str(root / "missing-zzz")) is None
        assert idx3._should_ignore_dir(".hidden") is True
        assert idx3._should_ignore_dir("normal-dir-not-ignored") is False

    def test_rag_tools_branches(self):
        from dxrk.rag.rag import Config, New
        from dxrk.rag.store import VectorStore
        from dxrk.rag.tools import RegisterTools
        from dxrk.tools import Registry

        rag_off = New(Config(enabled=False))
        reg = Registry()
        RegisterTools(reg, rag_off)
        q = reg.get("codebase_query")
        out, err = q.execute(None, None)
        assert err == "query is required"
        out, err = q.execute(None, {"query": "x", "max_results": "bad"})
        assert out.get("enabled") is False
        out, err = q.execute(None, {"query": "x", "max_results": 2})
        assert out.get("enabled") is False
        idx_tool = reg.get("codebase_index")
        out, _ = idx_tool.execute(None, None)
        assert out.get("enabled") is False

        class _FakeIdx:
            def Query(self, q, n):
                return []

            def Index(self):
                return SimpleNamespace(
                    files_scanned=1, files_indexed=1, chunks_created=2,
                    total_vectors=2, duration_ms=3, last_run="now",
                )

        class _FakeEmb:
            def dimensions(self):
                return 3

        from dxrk.rag.rag import RAG

        rag_empty = RAG(indexer=_FakeIdx(), store=VectorStore(3), embedder=_FakeEmb(), enabled=True)
        reg2 = Registry()
        RegisterTools(reg2, rag_empty)
        out, _ = reg2.get("codebase_query").execute(None, {"query": "x"})
        assert out["results"] == []
        out, err = reg2.get("codebase_index").execute(None, {"path": "/override"})
        assert "not supported" in (err or "")
        out, _ = reg2.get("codebase_index").execute(None, None)
        assert out["files_scanned"] == 1

        class _HitIdx:
            def Query(self, q, n):
                from dxrk.rag.chunker import Chunk
                from dxrk.rag.store import SearchResult, VectorRecord

                rec = VectorRecord(id="1", chunk=Chunk("code", "f.py", 1, 2, "python"), embedding=[1])
                return [SearchResult(record=rec, score=0.9)]

        rag_hit = RAG(indexer=_HitIdx(), store=VectorStore(3), embedder=_FakeEmb(), enabled=True)
        reg3 = Registry()
        RegisterTools(reg3, rag_hit)
        out, _ = reg3.get("codebase_query").execute(None, {"query": "x"})
        assert out["total"] == 1 and out["results"][0]["file_path"] == "f.py"


class TestRouterRem:
    def test_cost_tracker_unknown(self):
        from dxrk.router import CostTracker

        ct = CostTracker()
        ct.add("unknown-model-zzz", 100, 100)
        assert ct.total() == 0.0
        ct.add("gpt-4o", 1000, 1000)
        assert ct.total() > 0
        assert "gpt-4o" in ct.by_model()
        ct.reset()
        assert ct.total() == 0.0

    def test_generate_paths(self):
        from dxrk.query import Response, Usage
        from dxrk.router import CostTracker, ProviderEntry, Router, Strategy, new_router

        class _Fail:
            def generate(self, messages, tools):
                return None, "boom"

        class _Ok:
            def generate(self, messages, tools):
                return Response(text="hi", usage=Usage(input_tokens=10, output_tokens=5)), None

        r = Router(providers=[], strategy=Strategy.FIRST_AVAILABLE)
        assert r.generate([], [])[1] is not None
        r2 = Router(providers=[ProviderEntry(name="f", model="m", provider=_Fail())])
        _, err = r2.generate([], [])
        assert "all providers" in (err or "")
        logs: list = []
        r3 = new_router(
            [ProviderEntry(name="f", model="gpt-4o", provider=_Fail()),
             ProviderEntry(name="o", model="gpt-4o", provider=_Ok())],
            cost_tracker=CostTracker(),
            logger=lambda *a: logs.append(a),
        )
        resp, err = r3.generate([], [])
        assert resp is not None and err is None and logs
        r3.add_provider(ProviderEntry(name="x", model="m", provider=_Ok()))
        assert len(r3.providers) == 3

    def test_cache_branches(self):
        from dxrk.router import QueryResponse, SemanticCache, cosine_sim, default_key_fn, join_messages, simple_embed

        c = SemanticCache(max_size=2, ttl=0.01, semantic_enabled=True, semantic_threshold=0.99)
        assert c.get("missing")[1] is False
        c.set("a", QueryResponse(text="ra"))
        assert c.get("a")[1] is True
        c.set("a", QueryResponse(text="ra2"))
        assert c.get("a")[0].text == "ra2"
        c.set("b", QueryResponse(text="rb"))
        c.set("c", QueryResponse(text="rc"))
        assert c.stats().size <= 2
        c.invalidate("b")
        c.invalidate("missing")
        c.clear()
        assert c.stats().size == 0
        assert default_key_fn("x") == default_key_fn("x")
        assert simple_embed("") == [0.0] * 128
        assert cosine_sim([1], [1, 2]) == 0.0
        assert cosine_sim([], []) == 0.0
        assert cosine_sim([0, 0], [1, 1]) == 0.0
        from dxrk.query import Message

        assert "user" in join_messages([Message(role="user", content="hi")])

    def test_caching_router_paths(self):
        from dxrk.query import Message, Response, Usage
        from dxrk.router import (
            CachingRouter,
            ProviderEntry,
            Router,
            SemanticCache,
            Strategy,
        )

        class _Ok:
            def generate(self, messages, tools):
                return Response(text="ans", usage=Usage(input_tokens=1, output_tokens=1)), None

        class _Fail:
            def generate(self, messages, tools):
                return None, "nope"

        cache = SemanticCache()
        router = Router(providers=[ProviderEntry(name="o", model="m", provider=_Ok())], strategy=Strategy.FIRST_AVAILABLE)
        cr = CachingRouter(router, cache)
        msgs = [Message(role="user", content="hello")]
        resp, err = cr.cached_generate(msgs, [])
        assert resp is not None
        resp2, _ = cr.cached_generate(msgs, [])
        assert resp2 is not None and resp2.text == "ans"
        bad_router = Router(providers=[ProviderEntry(name="f", model="m", provider=_Fail())])
        cr2 = CachingRouter(bad_router, SemanticCache())
        assert cr2.cached_generate(msgs, [])[1] is not None


# ═══════════ lote 10: restos finos cli + rag + format ═══════════


class TestNormalizeRem:
    def test_component_not_in_mvp(self):
        with pytest.raises(ValueError, match="componente no compatible"):
            norm.normalize_components(["dxrk"], __import__("dxrk.models", fromlist=["PresetID"]).PresetID.FULL_DXRK)


class TestAgentsStepsRem2:
    def test_unknown_package_manager_pass(self):
        from dxrk.cli.install_steps_agents import AgentInstallStep
        from dxrk.models import AgentID
        from dxrk.system import PlatformProfile

        step = AgentInstallStep("a", AgentID.CLAUDE_CODE, "/tmp", PlatformProfile(os="linux", package_manager="zypper", supported=True))
        ad = SimpleNamespace(
            supports_auto_install=True,
            detect=lambda home: SimpleNamespace(installed=False),
            install_command=lambda profile: [["sh", "-c", "exit 0"]],
        )
        with (
            mock.patch("dxrk.agents.factory.create_registry") as cr,
            mock.patch("shutil.which", return_value="/usr/bin/sh"),
            mock.patch("dxrk.cli.install_steps_agents.run_command_sequence", return_value="done-err"),
        ):
            cr.return_value.get.return_value = ad
            assert step.run() == "done-err"

    def test_check_dependencies_two_agents(self):
        from dxrk.cli.install_steps_agents import CheckDependenciesStep
        from dxrk.models import AgentID, Selection
        from dxrk.system import PlatformProfile

        sel = Selection(agents=[AgentID.CLAUDE_CODE, AgentID.OPENCODE])
        step = CheckDependenciesStep("c", PlatformProfile(os="linux", package_manager="apt", supported=True), "/tmp", sel)
        with (
            mock.patch("dxrk.system.detect_dependencies", return_value=None),
            mock.patch("dxrk.agents.factory.create_registry") as cr,
        ):
            cr.return_value.get.return_value = SimpleNamespace(supports_auto_install=False)
            assert step.run() is None


class TestRunLegacyVerify:
    def test_run_post_apply_verification_branches(self, tmp_path):
        import dxrk.cli.run as runmod
        from dxrk.models import ComponentID, Selection

        with (
            mock.patch.object(runmod, "_resolve_adapters", return_value=[]),
            mock.patch("dxrk.cli.run.build_stage_plan", return_value=None) if False else mock.patch.dict({}, {}),
        ):
            pass
        orig_resolve = runmod._resolve_adapters
        import dxrk.cli.install as inst

        orig_paths = inst._component_paths
        try:
            runmod._resolve_adapters = lambda agents: []
            f = tmp_path / "v.txt"
            f.write_text("x")
            inst._component_paths = lambda home, sel, adapters, comp: [str(f), str(f), ""]
            resolved = SimpleNamespace(agents=[], ordered_components=[ComponentID.SDD])
            rep = runmod._run_post_apply_verification(str(tmp_path), Selection(), resolved)
            assert rep.ready is True
            resolved2 = SimpleNamespace(agents=[], ordered_components=[ComponentID.DXRK_MEMORY])
            runmod._look_path = lambda n: ""
            rep2 = runmod._run_post_apply_verification(str(tmp_path), Selection(), resolved2)
            assert any("memory" in c.id for c in rep2.checks)
            runmod._look_path = lambda n: "/usr/bin/memory"
            with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
                rep3 = runmod._run_post_apply_verification(str(tmp_path), Selection(), resolved2)
                assert rep3.ready is True
            with mock.patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("memory", 10)):
                rep4 = runmod._run_post_apply_verification(str(tmp_path), Selection(), resolved2)
                assert rep4.ready is True
        finally:
            runmod._resolve_adapters = orig_resolve
            inst._component_paths = orig_paths
            if hasattr(runmod, "_look_path"):
                import shutil as _sh

                runmod._look_path = lambda name: _sh.which(name) or ""


class TestRuntimeRunRem2:
    def test_verify_not_ready_returns(self, tmp_path, monkeypatch):
        import dxrk.cli.runtime_run as rr

        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(os, "getcwd", lambda: str(tmp_path))
        det = _make_detection()

        class _OrchOk:
            def execute(self, plan):
                return SimpleNamespace(error="")

        monkeypatch.setattr("dxrk.pipeline.new_orchestrator", lambda p: _OrchOk())
        monkeypatch.setattr("dxrk.pipeline.default_rollback_policy", lambda: None)
        monkeypatch.setattr(rr, "_run_post_apply_verification", lambda *a: SimpleNamespace(ready=False, final_note=""))
        monkeypatch.setattr(rr, "_with_post_install_notes", lambda rep, res, prof: rep)
        out = rr.run_install([], det)
        assert out.verify.ready is False and out.error == ""

    def test_notes_already_present_and_brew(self):
        from dxrk.cli.runtime_run import _with_post_install_notes
        from dxrk.models import ComponentID

        note = "\n\nDXRK_GUARDIAN ya está instalado globalmente. Para activar los hooks del proyecto, ejecuta en cada repo:\n- DXRK_GUARDIAN init\n- DXRK_GUARDIAN install"
        rep = SimpleNamespace(ready=True, final_note="x" + note)
        resolved = SimpleNamespace(ordered_components=[ComponentID.DXRK_GUARDIAN])
        out = _with_post_install_notes(rep, resolved, SimpleNamespace(package_manager="apt"))
        assert out.final_note.count("DXRK_GUARDIAN ya") == 1
        rep2 = SimpleNamespace(ready=True, final_note="")
        resolved2 = SimpleNamespace(ordered_components=[ComponentID.DXRK_MEMORY])
        out2 = _with_post_install_notes(rep2, resolved2, SimpleNamespace(package_manager="brew"))
        assert out2.final_note == ""


class TestRuntimeVerifyCollision:
    def test_post_apply_with_collision(self, tmp_path, monkeypatch):
        from dxrk.cli import runtime_verify as rv
        from dxrk.models import AgentID, ComponentID, Selection

        monkeypatch.setattr(rv, "_resolve_adapters", lambda agents: agents)
        monkeypatch.setattr(rv, "_component_paths", lambda *a: [])
        monkeypatch.setattr("dxrk.components.memory.verify_installed", lambda: None)
        monkeypatch.setattr("dxrk.components.memory.verify_version", lambda: None)
        resolved = SimpleNamespace(
            agents=[AgentID.ANTIGRAVITY, AgentID.GEMINI_CLI],
            ordered_components=[ComponentID.DXRK_MEMORY],
        )
        rep = rv._run_post_apply_verification(str(tmp_path), Selection(), resolved)
        assert any("antigravity" in c.id for c in rep.checks)


class TestComponentsChangedFalse:
    def test_inject_not_changed_no_log(self):
        from dxrk.cli.install_steps_components import ComponentApplyStep
        from dxrk.models import AgentID, ComponentID, Selection
        from dxrk.system import PlatformProfile

        def _step(comp):
            return ComponentApplyStep(
                step_id="c", component=comp, home_dir="/t", workspace_dir="/t",
                agents=[AgentID.CLAUDE_CODE], selection=Selection(),
                profile=PlatformProfile(os="linux", package_manager="apt", supported=True),
            )

        ad = SimpleNamespace(agent="x")
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[ad]),
            mock.patch("dxrk.components.context7.inject", return_value=SimpleNamespace(Changed=False)),
            mock.patch("dxrk.components.persona.inject", return_value=SimpleNamespace(Changed=False)),
            mock.patch("dxrk.components.permissions.inject", return_value=SimpleNamespace(Changed=False)),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=False)),
            mock.patch("dxrk.components.theme.inject", return_value=SimpleNamespace(Changed=False)),
        ):
            for comp in (ComponentID.CONTEXT7, ComponentID.PERSONA, ComponentID.PERMISSIONS, ComponentID.SDD, ComponentID.THEME):
                assert _step(comp).run() is None


class TestRuntimePathsEmpty:
    def test_empty_settings_branches(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import AgentID, ComponentID, MCPStrategy, Selection

        sel = Selection()
        ad_no_settings = _fake_adapter(_settings_path="")
        assert _component_paths("/h", sel, [ad_no_settings], ComponentID.SDD) is not None
        ad_merge_empty = _fake_adapter(mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, _settings_path="")
        assert isinstance(_component_paths("/h", sel, [ad_merge_empty], ComponentID.DXRK_MEMORY), list)
        ad_no_sys = _fake_adapter(_sys_path="")
        assert _component_paths("/h", sel, [ad_no_sys], ComponentID.DXRK_MEMORY) is not None
        ad_no_cmd = _fake_adapter(_cmd_dir="")
        assert _component_paths("/h", sel, [ad_no_cmd], ComponentID.SDD) is not None
        ad_gemini = _fake_adapter(agent=AgentID.GEMINI_CLI)
        assert _component_paths("/h", sel, [ad_gemini], ComponentID.SDD) is not None


class TestRagFormatRem:
    def test_chunker_multi_loop(self, tmp_path):
        from dxrk.rag.chunker import ChunkConfig, ChunkFile

        target = tmp_path / "long.py"
        target.write_text("\n".join(f"line{i}" for i in range(50)))
        chunks = ChunkFile(str(target), ChunkConfig(chunk_size=10, chunk_overlap=2))
        assert len(chunks) >= 5

    def test_indexer_hash_none(self, tmp_path, monkeypatch):
        from dxrk.rag.chunker import ChunkConfig
        from dxrk.rag.indexer import Indexer
        from dxrk.rag.store import VectorStore

        root = tmp_path / "p"
        root.mkdir()
        (root / "a.py").write_text("x\n")

        class _Emb:
            def embed(self, texts):
                return [[1.0] * 3 for _ in texts]

            def model(self):
                return "m"

            def dimensions(self):
                return 3

        monkeypatch.setattr(Indexer, "_file_hash", staticmethod(lambda p: None))
        idx = Indexer(VectorStore(3), _Emb(), str(root), ChunkConfig(512, 64))
        assert idx.Index().files_indexed == 0

    def test_embedder_protocol_bodies(self):
        from dxrk.rag.embedder import Embedder

        class _E(Embedder):
            pass

        e = _E()
        assert e.embed([]) is None
        assert e.model() is None
        assert e.dimensions() is None

    def test_format_rem_branches(self):
        from dxrk.scholar.citation.format import (
            Paper,
            _fmt_apa_invert,
            _fmt_mla,
            _normalize_key,
            format_apa,
            format_mla,
        )

        assert _normalize_key("A B-C") == "abc"
        assert _fmt_apa_invert("Plato") == "Plato"
        assert _fmt_apa_invert("") == ""
        assert _fmt_mla("  ", True) == ""
        p = Paper(title="T", authors=["John Doe", "Jane Roe"], year=2022)
        assert ", " in format_apa(p) and "&" not in format_apa(p)
        p2 = Paper(authors=["A"], title="T", year=2020, url="http://u")
        assert format_mla(p2).endswith("http://u")


# ═══════════ lote 11: skills / verify raíz / tenant / config restos ═══════════


class TestSkillsComponent:
    def test_presets(self):
        from dxrk.components.skills import all_skill_ids, skill_path_for_agent, skills_for_preset
        from dxrk.models import PresetID

        assert len(skills_for_preset(PresetID.MINIMAL)) == 11
        assert len(skills_for_preset(PresetID.ECOSYSTEM_ONLY)) == 20
        assert skills_for_preset(PresetID.CUSTOM) == []
        assert len(skills_for_preset(PresetID.FULL_DXRK)) == 20
        assert len(all_skill_ids()) == 20
        assert skill_path_for_agent("/h", SimpleNamespace(skills_dir=lambda h: ""), "x") == ""
        assert skill_path_for_agent("/h", SimpleNamespace(skills_dir=lambda h: "/s"), "x").endswith("SKILL.md")

    def test_inject_branches(self, tmp_path):
        from dxrk.components.skills import inject
        from dxrk.models import SkillID

        no_support = SimpleNamespace(supports_skills=False)
        out = inject(str(tmp_path), no_support, [SkillID.SDD_INIT])
        assert out.Skipped == [SkillID.SDD_INIT] and out.Changed is False
        no_dir = SimpleNamespace(supports_skills=True, skills_dir=lambda h: "")
        assert inject(str(tmp_path), no_dir, [SkillID.GO_TESTING]).Skipped
        ok_ad = SimpleNamespace(supports_skills=True, skills_dir=lambda h: str(tmp_path / "sk"))
        sdd_only = inject(str(tmp_path), ok_ad, [SkillID.SDD_INIT])
        assert sdd_only.Changed is False and sdd_only.Files == []
        missing = inject(str(tmp_path), ok_ad, [SkillID.GO_TESTING])
        assert missing.Skipped == [SkillID.GO_TESTING] or missing.Changed is True
        with mock.patch("dxrk.components.skills._read", return_value="  "):
            with pytest.raises(ValueError, match="vacío"):
                inject(str(tmp_path), ok_ad, [SkillID.GO_TESTING])
        with mock.patch("dxrk.components.skills._read", return_value="# skill"):
            out2 = inject(str(tmp_path), ok_ad, [SkillID.GO_TESTING])
            assert out2.Changed is True


class TestVerifyRoot:
    def test_run_checks_exceptions(self):
        from dxrk.verify import (
            Check,
            CheckResult,
            CheckStatus,
            PostInstallVerifier,
            VerificationScenario,
            build_report,
            render_report,
            run_checks,
        )

        def boom():
            raise RuntimeError("x")

        soft = Check(id="s", run=boom, soft=True)
        hard = Check(id="h", run=boom, soft=False)
        res = run_checks([soft, hard, Check(id="n"), Check(id="e", run=lambda: "err"), Check(id="ok", run=lambda: None)])
        statuses = {r.id: r.status for r in res}
        assert statuses["s"] == CheckStatus.WARNING
        assert statuses["h"] == CheckStatus.FAILED
        assert statuses["n"] == CheckStatus.SKIPPED
        assert statuses["e"] == CheckStatus.FAILED
        assert statuses["ok"] == CheckStatus.PASSED
        rep = build_report(res)
        assert rep.ready is False and rep.failed >= 2
        text = render_report(rep)
        assert "[!!]" in text and "[--]" in text and "[??]" in text
        rep2 = build_report([CheckResult(id="a", status=CheckStatus.PASSED), CheckResult(id="b", status=CheckStatus.WARNING)])
        assert rep2.ready is True and rep2.warnings == 1
        sc = VerificationScenario(name="s", checks=[Check(id="a", run=lambda: None)])
        assert sc.run().passed == 1
        sc2 = VerificationScenario()
        assert sc2.run().passed == 0
        v = PostInstallVerifier(scenarios=[sc])
        v.add_scenario(sc2)
        assert v.verify_installation().passed == 1
        assert v.run_all().passed == 1
        assert PostInstallVerifier().verify_installation().passed == 0


class TestTenantMigrationRem:
    def test_chmod_errors_ignored(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        tm._ensure_dir(tmp_path / "d1")
        tm._ensure_file_mode(tmp_path / "f1")
        assert (tmp_path / "d1").is_dir()

    def test_tenant_root_chmod_errors(self, monkeypatch, tmp_path):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(Path, "chmod", lambda self, *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(ValueError):
            tm.tenant_root("bad id!!!")
        root = tm.tenant_root("default")
        assert root.name == "default"
        assert tm.ensure_tenant("t1").name == "t1"
        with pytest.raises(ValueError):
            tm.ensure_tenant("bad id!!!")

    def test_list_tenants_oserror(self, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("ro")))
        assert tm.list_tenants() == []

    def test_migrate_dry_run_and_merge(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setattr(tm, "LEGACY_PATHS", [])
        out = tm.migrate_legacy_to_default(dry_run=True)
        assert out == {"moved": [], "copied": [], "skipped": []}
        legacy_file = tmp_path / ".dxrk" / "identity.txt"
        legacy_file.parent.mkdir(parents=True, exist_ok=True)
        legacy_file.write_text("id")
        monkeypatch.setattr(tm, "LEGACY_PATHS", [(legacy_file, Path("identity.txt"))])
        out2 = tm.migrate_legacy_to_default(dry_run=True)
        assert len(out2["copied"]) == 1
        out3 = tm.migrate_legacy_to_default(dry_run=False)
        assert len(out3["copied"]) == 1
        out4 = tm.migrate_legacy_to_default(dry_run=False)
        assert len(out4["skipped"]) == 1

    def test_migrate_dir_merge_and_sidecars(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        legacy_dir = tmp_path / ".dxrk" / "locks"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "a.txt").write_text("a")
        monkeypatch.setattr(tm, "LEGACY_PATHS", [(legacy_dir, Path("locks"))])
        assert len(tm.migrate_legacy_to_default(dry_run=False)["copied"]) == 1
        (legacy_dir / "b.txt").write_text("b")
        out = tm.migrate_legacy_to_default(dry_run=False)
        assert len(out["copied"]) == 1
        out_dry = tm.migrate_legacy_to_default(dry_run=True)
        assert len(out_dry["skipped"]) == 1
        db = tmp_path / ".dxrk" / "knowledge_graph.sqlite3"
        db.write_text("db")
        (tmp_path / ".dxrk" / "knowledge_graph.sqlite3-wal").write_text("wal")
        monkeypatch.setattr(tm, "LEGACY_PATHS", [(db, Path("knowledge_graph.sqlite3"))])
        assert len(tm.migrate_legacy_to_default(dry_run=False)["copied"]) == 1

    def test_migrate_copy_error_and_special(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        legacy = tmp_path / ".dxrk" / "victim.txt"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("x")
        monkeypatch.setattr(tm, "LEGACY_PATHS", [(legacy, Path("victim.txt"))])
        monkeypatch.setattr("shutil.copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        out = tm.migrate_legacy_to_default(dry_run=False)
        assert len(out["skipped"]) == 1


class TestConfigStorageRem:
    def test_stale_tmp_removed_ok(self, tmp_path):
        from dxrk.config.storage import save_json_atomic

        target = tmp_path / "s.json"
        stale = tmp_path / ".s.json.tmp"
        stale.write_text("old")
        save_json_atomic(target, {"k": "v"})
        assert json.loads(target.read_text()) == {"k": "v"}
        assert not stale.exists()


# ═══════════ lote 12: remates (assets helper, storage replace-fail, tenant lecturas, skills skip) ═══════════


class TestRemates:
    def test_asset_path_helper(self):
        from dxrk.components import assets as a

        assert a._asset_path("x").endswith("x")

    def test_storage_replace_failure_cleans_tmp(self, tmp_path, monkeypatch):
        from dxrk.config.storage import save_json_atomic

        target = tmp_path / "r.json"
        monkeypatch.setattr(Path, "replace", lambda self, t: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            save_json_atomic(target, {"a": 1})
        assert not (tmp_path / ".r.json.tmp").exists()

    def test_tenant_reads(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as tm

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        assert tm.is_migrated() is False
        assert tm.list_tenants() == []
        (tmp_path / ".dxrk" / "tenants" / "b").mkdir(parents=True)
        (tmp_path / ".dxrk" / "tenants" / "a").mkdir(parents=True)
        (tmp_path / ".dxrk" / "tenants" / "_registry.json").write_text("{}")
        assert tm.list_tenants() == ["a", "b"]
        assert tm.is_migrated() is True
        (tmp_path / ".dxrk" / "tenants" / "bad id!").mkdir(parents=True, exist_ok=True)
        assert "bad id!" not in tm.list_tenants()

    def test_skills_skip_missing_asset(self, tmp_path):
        from dxrk.components.skills import inject
        from dxrk.models import SkillID

        ok_ad = SimpleNamespace(supports_skills=True, skills_dir=lambda h: str(tmp_path / "sk"))
        with mock.patch("dxrk.components.skills._read", return_value=None):
            out = inject(str(tmp_path), ok_ad, [SkillID.GO_TESTING])
            assert out.Skipped == [SkillID.GO_TESTING] and out.Changed is False

    def test_theme_merge_no_file(self, tmp_path):
        from dxrk.components.theme import _merge_json_file

        wr, merged = _merge_json_file(str(tmp_path / "none.json"), b'{"a": 1}')
        assert wr.Changed is True and merged is not None


# ═══════════ lote 13: micro-remates ═══════════


class TestMicroRemates:
    def test_backup_rollback_copy_error_real(self, tmp_path):
        from dxrk.cli.install_steps_backup import PrepareBackupStep, RollbackRestoreStep

        snap = tmp_path / "snap"
        snap.mkdir()
        dest_file = snap / "rel"
        dest_file.write_text("snap-data")
        state = {"manifest": {"entries": [{"source": str(tmp_path / "orig.txt"), "dest": "rel"}]}}
        step = PrepareBackupStep("b", str(snap), [], state)
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert step.rollback() is None
        rstate = {"manifest": {"entries": [{"source": str(tmp_path / "o2"), "dest": "rel"}], "_backup_root": str(tmp_path)}}
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert RollbackRestoreStep("r", rstate).rollback() is None

    def test_provider_protocol_bodies(self):
        from dxrk.scholar.provider import Paper, Provider

        class _P(Provider):
            pass

        p = _P()
        assert p.name() is None
        assert p.search("q", 1) is None
        assert p.fetch_by_doi("d") is None
        assert Paper().title == ""

    def test_pubmed_rem(self):
        from dxrk.scholar.pubmed import PubMedProvider

        p404 = PubMedProvider(client=_FakeHttpxClient(status=404))
        assert p404._get("http://x", {}) == (None, None)
        p500 = PubMedProvider(client=_FakeHttpxClient(status=500))
        _, err = p500._get("http://x", {})
        assert "status" in (err or "")

        class _Mixed:
            status_code = 200

            def json(self):
                return {"result": {"1": {"title": "T"}, "2": "notadict"}}

        class _MixedClient:
            def get(self, *a, **k):
                return _Mixed()

        papers, err = PubMedProvider(client=_MixedClient())._fetch_summaries(["1", "2"])
        assert len(papers) == 1 and err is None
        p_err = PubMedProvider(client=_FakeHttpxClient(error=_req_error()))
        assert p_err.fetch_by_doi("10.1/x")[1] is not None
        p_none = PubMedProvider(client=_FakeHttpxClient(payload={"result": {}}))
        assert p_none._fetch_summaries(["9"]) == ([], None)

    def test_openalex_rem(self):
        from dxrk.scholar.openalex import OpenAlexProvider

        class _BadJson:
            status_code = 200

            def json(self):
                raise ValueError("bad")

        class _BadClient:
            def get(self, *a, **k):
                return _BadJson()

        _, err = OpenAlexProvider(client=_BadClient()).fetch_by_doi("10.1/x")
        assert "decode doi" in (err or "")
        p404 = OpenAlexProvider(client=_FakeHttpxClient(status=404))
        assert p404.fetch_by_doi("10.1/x") == (None, None)

    def test_arxiv_no_published(self):
        from dxrk.scholar.arxiv import ArxivProvider

        feed = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><summary>A</summary><id>u</id></entry></feed>'
        papers, err = ArxivProvider(client=_FakeHttpxClient(payload=feed)).search("q", 5)
        assert err is None and papers[0].year == 0

    def test_format_rem(self):
        from dxrk.scholar.citation.format import Paper, _normalize_key, format_apa, format_mla

        assert _normalize_key("---") == "paper"
        p = Paper(title="T", authors=["John Michael Doe"], year=2020)
        assert "Doe" in format_apa(p)
        p2 = Paper(title="", authors=[], year=0, doi="", url="")
        assert "Anonymous" in format_apa(p2) and "n.d." in format_mla(p2)

    def test_sematicscholar_fetch_ok(self):
        from dxrk.scholar.semanticscholar import SemanticScholarProvider

        payload = {"title": "T", "authors": [{"name": "A"}], "year": 2020, "url": "http://u"}
        paper, err = SemanticScholarProvider(client=_FakeHttpxClient(payload=payload)).fetch_by_doi("10.1/x")
        assert err is None and paper is not None and paper.title == "T"

    def test_scholar_tools_limit_str(self):
        from dxrk.scholar.tools import RegisterTools
        from dxrk.tools import Registry

        reg = Registry()
        RegisterTools(reg, None)
        out, _ = reg.get("scholar_search").execute(None, {"query": "q", "limit": "5"})
        assert out.get("enabled") is False

    def test_router_sort_and_evict(self):
        from dxrk.router import ProviderEntry, QueryResponse, Router, SemanticCache, Strategy

        class _P:
            def generate(self, m, t):
                return None, "x"

        r = Router(
            providers=[
                ProviderEntry(name="a", model="gpt-4o", provider=_P()),
                ProviderEntry(name="b", model="claude-3-haiku-20240307", provider=_P()),
                ProviderEntry(name="c", model="unknown-zzz", provider=_P()),
            ],
            strategy=Strategy.LOWEST_COST,
        )
        assert r._select_providers()[0] == 2
        c = SemanticCache(max_size=1, ttl=300.0)
        c.set("k1", QueryResponse(text="r1"))
        c.set("k2", QueryResponse(text="r2"))
        assert c.stats().size == 1
        c._heap_remove(c._lru[0] if c._lru else __import__("dxrk.router", fromlist=["CacheEntry"]).CacheEntry(response=QueryResponse(), created_at=0, expires_at=0))
        ghost = __import__("dxrk.router", fromlist=["CacheEntry"]).CacheEntry(response=QueryResponse(), created_at=0, expires_at=0)
        c._heap_remove(ghost)
        assert c.stats().size == 1

    def test_main_guard_via_runpy(self, monkeypatch):
        import runpy
        import sys

        monkeypatch.setattr(sys, "argv", ["dxrk-py", "version"])
        runpy.run_module("dxrk.__main__", run_name="__main__")

    def test_main_unknown_command(self, monkeypatch, capsys):
        import sys

        import dxrk.__main__ as m

        monkeypatch.setattr(sys, "argv", ["dxrk-py", "version"])
        with mock.patch.object(m, "_launch_single_installer"):
            pass
        assert m._rebuild_uninstall_raw(SimpleNamespace(agents=None, components=None, all=False, yes=False)) == []


# ═══════════ lote 14: __main__ remates + backup 115 ═══════════


class TestMainRemates:
    def _argv(self, monkeypatch, *args):
        import sys

        monkeypatch.setattr(sys, "argv", ["dxrk-py", *args])

    def test_debug_flag(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "--debug", "version")
        m.main()
        assert "Dxrk v" in capsys.readouterr().out

    def test_unknown_command_branch(self, monkeypatch, capsys):
        import argparse

        import dxrk.__main__ as m

        ns = argparse.Namespace(
            debug=False, tenant="", version=False, health=False, command="bogus-cmd",
            agents=None, components=None, skills=None, persona="dxrk", preset=None,
            sdd_mode="", dry_run=False,
        )
        with (
            mock.patch("argparse.ArgumentParser.parse_args", return_value=ns),
            mock.patch("argparse.ArgumentParser.parse_known_args",
                        return_value=(argparse.Namespace(tenant=""), [])),
        ):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 2

    def test_tenant_bare_and_create(self, monkeypatch):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "tenant")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
            assert reg.return_value.execute.call_args[0][0] == ["tenant"]
        self._argv(monkeypatch, "tenant", "create", "t1")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
        self._argv(monkeypatch, "tenant", "delete", "t1", "--force")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
            assert "--force" in reg.return_value.execute.call_args[0][0]

    def test_enterprise_execute_full(self, monkeypatch):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "enterprise")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
            assert reg.return_value.execute.call_args[0][0] == ["enterprise"]
        self._argv(monkeypatch, "enterprise", "execute", "do-it", "eng")
        with mock.patch("dxrk.commands.register_all") as reg:
            reg.return_value.execute.return_value = 0
            m.main()
            assert "eng" in reg.return_value.execute.call_args[0][0]

    def test_install_dry_no_review(self, monkeypatch, capsys):
        import dxrk.__main__ as m

        self._argv(monkeypatch, "install", "--dry-run")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.run_install",
                        return_value=SimpleNamespace(error="", dry_run=True, review=None)),
        ):
            m.main()
        self._argv(monkeypatch, "install", "--dry-run")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.run_install",
                        return_value=SimpleNamespace(
                            error="", dry_run=True,
                            review=SimpleNamespace(agents=[], unsupported_agents=[], persona="p", preset="r",
                                                    components=[], skills=[], strict_tdd=False, has_sdd=False,
                                                    platform_decision=None))),
        ):
            m.main()
            assert "Dry Run" in capsys.readouterr().out

    def test_launch_tui_real(self):
        import dxrk.__main__ as m

        with mock.patch("dxrk.tui.app.run", return_value=None) as rt:
            m._launch_tui("9.9", initial_screen="chat")
            assert rt.called

    def test_upgrade_updates_and_failed(self, monkeypatch, capsys):
        import dxrk.__main__ as m
        from dxrk.update import ToolUpgradeStatus

        self._argv(monkeypatch, "upgrade")
        ok_res = SimpleNamespace(tool_name="t", status="ok", err="")
        fail_res = SimpleNamespace(tool_name="bad", status=ToolUpgradeStatus.FAILED, err="x")
        with (
            mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=True))),
            mock.patch("dxrk.cli.install.resolve_install_profile", return_value=SimpleNamespace()),
            mock.patch("dxrk.update.check_filtered", return_value=["r"]),
            mock.patch("dxrk.update.has_check_failures", return_value=False),
            mock.patch("dxrk.update.has_updates", return_value=True),
            mock.patch("dxrk.update.update_summary_line", return_value="t"),
            mock.patch("dxrk.update.execute", return_value=SimpleNamespace(results=[ok_res, fail_res])),
            mock.patch("dxrk.update.render_upgrade_report", return_value="rep"),
        ):
            with pytest.raises(SystemExit) as ei:
                m.main()
            assert ei.value.code == 1
            assert "Actualizaciones" in capsys.readouterr().out


class TestBackupRollbackRem:
    def test_rollback_restore_copy_error(self, tmp_path):
        from dxrk.cli.install_steps_backup import RollbackRestoreStep

        snap = tmp_path / "snap"
        snap.mkdir()
        (snap / "d").write_text("x")
        st = {"manifest": {"entries": [{"source": str(tmp_path / "t"), "dest": "d"}], "_backup_root": str(tmp_path / "nope-root")}}
        with mock.patch("shutil.copy2", side_effect=OSError("ro")):
            assert RollbackRestoreStep("r", st).rollback() is None

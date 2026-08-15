# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os

import pytest
from dxrk.models import (
    AgentID,
    ComponentID,
    PersonaID,
    PresetID,
    SDDModeID,
    SkillID,
    MCPStrategy,
)


class TestParseInstallFlags:
    def test_defaults(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags([])
        assert flags.agents == []
        assert flags.components == []
        assert flags.skills == []
        assert flags.persona == ""
        assert flags.preset == ""
        assert flags.sdd_mode == ""
        assert flags.dry_run is False

    def test_agent_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--agent", "claude-code"])
        assert flags.agents == ["claude-code"]

    def test_agents_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--agents", "claude-code,opencode"])
        assert flags.agents == ["claude-code", "opencode"]

    def test_multiple_agent_flags(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--agent", "claude-code", "--agent", "opencode"])
        assert flags.agents == ["claude-code", "opencode"]

    def test_component_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--component", "ENGRAM"])
        assert flags.components == ["ENGRAM"]

    def test_preset_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--preset", "minimal"])
        assert flags.preset == "minimal"

    def test_dry_run(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--dry-run"])
        assert flags.dry_run is True

    def test_unknown_flag_raises(self):
        from dxrk.cli.install import parse_install_flags

        with pytest.raises(ValueError, match="unexpected install argument"):
            parse_install_flags(["--bogus"])

    def test_persona_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--persona", "dxrk"])
        assert flags.persona == "dxrk"

    def test_skill_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--skill", "GO_TESTING"])
        assert flags.skills == ["GO_TESTING"]

    def test_sdd_mode_flag(self):
        from dxrk.cli.install import parse_install_flags

        flags = parse_install_flags(["--sdd-mode", "single"])
        assert flags.sdd_mode == "single"


class TestParseSyncFlags:
    def test_defaults(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags([])
        assert flags.agents == []
        assert flags.skills == []
        assert flags.sdd_mode == ""
        assert flags.sdd_profile_strategy == ""
        assert flags.strict_tdd is False
        assert flags.dry_run is False
        assert flags.profiles == []

    def test_agent_flag(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--agent", "claude-code"])
        assert flags.agents == ["claude-code"]

    def test_strict_tdd(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--strict-tdd"])
        assert flags.strict_tdd is True

    def test_include_permissions(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--include-permissions"])
        assert flags.include_permissions is True

    def test_include_theme(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--include-theme"])
        assert flags.include_theme is True

    def test_dry_run(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--dry-run"])
        assert flags.dry_run is True

    def test_sdd_profile_strategy_valid(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--sdd-profile-strategy", "generated-multi"])
        assert flags.sdd_profile_strategy == "generated-multi"

    def test_sdd_profile_strategy_invalid(self):
        from dxrk.cli.install import parse_sync_flags

        with pytest.raises(ValueError, match="unsupported sdd-profile-strategy"):
            parse_sync_flags(["--sdd-profile-strategy", "bogus"])

    def test_profile_flag(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(["--profile", "my-profile:anthropic/claude-3-opus"])
        assert len(flags.profiles) == 1
        assert flags.profiles[0]["name"] == "my-profile"

    def test_profile_phase_flag(self):
        from dxrk.cli.install import parse_sync_flags

        flags = parse_sync_flags(
            [
                "--profile",
                "my-profile:anthropic/claude-3-opus",
                "--profile-phase",
                "my-profile:sdd-propose:anthropic/claude-3-haiku",
            ]
        )
        assert len(flags.profiles) == 1
        assert flags.profiles[0]["name"] == "my-profile"
        assert "sdd-propose" in flags.profiles[0]["phase_assignments"]

    def test_unknown_flag_raises(self):
        from dxrk.cli.install import parse_sync_flags

        with pytest.raises(ValueError, match="unexpected sync argument"):
            parse_sync_flags(["--bogus"])


class TestParseUninstallFlags:
    def test_all_flag(self):
        from dxrk.cli.install import parse_uninstall_flags

        flags = parse_uninstall_flags(["--all"])
        assert flags.all is True

    def test_all_with_agents_raises(self):
        from dxrk.cli.install import parse_uninstall_flags

        with pytest.raises(ValueError, match="--all cannot be combined"):
            parse_uninstall_flags(["--all", "--agent", "claude-code"])

    def test_no_all_no_agents_raises(self):
        from dxrk.cli.install import parse_uninstall_flags

        with pytest.raises(ValueError, match="partial uninstall requires"):
            parse_uninstall_flags([])

    def test_agent_flag(self):
        from dxrk.cli.install import parse_uninstall_flags

        flags = parse_uninstall_flags(["--agent", "claude-code"])
        assert flags.agents == ["claude-code"]
        assert flags.all is False

    def test_yes_flag(self):
        from dxrk.cli.install import parse_uninstall_flags

        flags = parse_uninstall_flags(["--all", "--yes"])
        assert flags.yes is True

    def test_yes_short_flag(self):
        from dxrk.cli.install import parse_uninstall_flags

        flags = parse_uninstall_flags(["--all", "-y"])
        assert flags.yes is True

    def test_unknown_flag_raises(self):
        from dxrk.cli.install import parse_uninstall_flags

        with pytest.raises(ValueError, match="unexpected uninstall argument"):
            parse_uninstall_flags(["--bogus"])


class TestNormalizePersona:
    def test_defaults_to_dxrk(self):
        from dxrk.cli.install import normalize_persona

        assert normalize_persona("") == PersonaID.DXRK

    def test_dxrk(self):
        from dxrk.cli.install import normalize_persona

        assert normalize_persona("dxrk") == PersonaID.DXRK

    def test_custom(self):
        from dxrk.cli.install import normalize_persona

        assert normalize_persona("custom") == PersonaID.CUSTOM

    def test_unsupported_raises(self):
        from dxrk.cli.install import normalize_persona

        with pytest.raises(ValueError, match="unsupported persona"):
            normalize_persona("bogus")


class TestNormalizePreset:
    def test_defaults_to_full(self):
        from dxrk.cli.install import normalize_preset

        assert normalize_preset("") == PresetID.FULL_DXRK

    def test_minimal(self):
        from dxrk.cli.install import normalize_preset

        assert normalize_preset("minimal") == PresetID.MINIMAL

    def test_ecosystem(self):
        from dxrk.cli.install import normalize_preset

        assert normalize_preset("ecosystem-only") == PresetID.ECOSYSTEM_ONLY

    def test_full(self):
        from dxrk.cli.install import normalize_preset

        assert normalize_preset("full-dxrk") == PresetID.FULL_DXRK

    def test_unsupported_raises(self):
        from dxrk.cli.install import normalize_preset

        with pytest.raises(ValueError, match="unsupported preset"):
            normalize_preset("bogus")


class TestComponentsForPreset:
    def test_minimal(self):
        from dxrk.cli.install import components_for_preset

        result = components_for_preset(PresetID.MINIMAL)
        assert result == [ComponentID.DXRK_MEMORY]

    def test_ecosystem(self):
        from dxrk.cli.install import components_for_preset

        result = components_for_preset(PresetID.ECOSYSTEM_ONLY)
        assert ComponentID.DXRK_MEMORY in result
        assert ComponentID.SDD in result
        assert ComponentID.SKILLS in result
        assert ComponentID.CONTEXT7 in result
        assert ComponentID.DXRK_GUARDIAN in result
        assert ComponentID.PERSONA not in result

    def test_full(self):
        from dxrk.cli.install import components_for_preset

        result = components_for_preset(PresetID.FULL_DXRK)
        assert ComponentID.DXRK_MEMORY in result
        assert ComponentID.SDD in result
        assert ComponentID.SKILLS in result
        assert ComponentID.CONTEXT7 in result
        assert ComponentID.PERSONA in result
        assert ComponentID.PERMISSIONS in result
        assert ComponentID.DXRK_GUARDIAN in result

    def test_custom_returns_empty(self):
        from dxrk.cli.install import components_for_preset

        assert components_for_preset(PresetID.CUSTOM) == []


class TestNormalizeComponents:
    def test_empty_uses_preset(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_components",
            lambda: [ComponentID.DXRK_MEMORY],
            raising=False,
        )
        from dxrk.cli.install import normalize_components

        result = normalize_components([], PresetID.MINIMAL)
        assert result == [ComponentID.DXRK_MEMORY]

    def test_custom_list(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_components",
            lambda: [ComponentID.DXRK_MEMORY, ComponentID.SDD],
            raising=False,
        )
        from dxrk.cli.install import normalize_components

        result = normalize_components(["DXRK_MEMORY", "sdd"], PresetID.CUSTOM)
        assert result == [ComponentID.DXRK_MEMORY, ComponentID.SDD]

    def test_duplicates_removed(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_components",
            lambda: [ComponentID.DXRK_MEMORY],
            raising=False,
        )
        from dxrk.cli.install import normalize_components

        result = normalize_components(["DXRK_MEMORY", "DXRK_MEMORY"], PresetID.CUSTOM)
        assert result == [ComponentID.DXRK_MEMORY]

    def test_unsupported_raises(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_components",
            lambda: [ComponentID.DXRK_MEMORY],
            raising=False,
        )
        from dxrk.cli.install import normalize_components

        with pytest.raises(ValueError, match="unsupported component"):
            normalize_components(["bogus"], PresetID.CUSTOM)


class TestNormalizeSkills:
    def test_empty_returns_empty(self):
        from dxrk.cli.install import normalize_skills

        assert normalize_skills([]) == []

    def test_valid_skills(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_skills",
            lambda: [SkillID.GO_TESTING, SkillID.SKILL_CREATOR],
            raising=False,
        )
        from dxrk.cli.install import normalize_skills

        result = normalize_skills(["go-testing", "skill-creator"])
        assert SkillID.GO_TESTING in result
        assert SkillID.SKILL_CREATOR in result

    def test_unsupported_raises(self, monkeypatch):
        import dxrk.components.assets

        monkeypatch.setattr(
            dxrk.components.assets,
            "mvp_skills",
            lambda: [SkillID.GO_TESTING],
            raising=False,
        )
        from dxrk.cli.install import normalize_skills

        with pytest.raises(ValueError, match="unsupported skill"):
            normalize_skills(["bogus"])


class TestNormalizeSDDMode:
    def test_empty_returns_none(self):
        from dxrk.cli.install import normalize_sdd_mode

        assert normalize_sdd_mode("") is None

    def test_single(self):
        from dxrk.cli.install import normalize_sdd_mode

        assert normalize_sdd_mode("single") == SDDModeID.SINGLE

    def test_multi(self):
        from dxrk.cli.install import normalize_sdd_mode

        assert normalize_sdd_mode("multi") == SDDModeID.MULTI

    def test_invalid_raises(self):
        from dxrk.cli.install import normalize_sdd_mode

        with pytest.raises(ValueError, match="unsupported sdd-mode"):
            normalize_sdd_mode("bogus")


class TestParseModelSpec:
    def test_slash_separator(self):
        from dxrk.cli.install import _parse_model_spec

        ma = _parse_model_spec("anthropic/claude-3-opus")
        assert ma.provider_id == "anthropic"
        assert ma.model_id == "claude-3-opus"

    def test_colon_separator(self):
        from dxrk.cli.install import _parse_model_spec

        ma = _parse_model_spec("anthropic:claude-3-opus")
        assert ma.provider_id == "anthropic"
        assert ma.model_id == "claude-3-opus"

    def test_missing_provider_raises(self):
        from dxrk.cli.install import _parse_model_spec

        with pytest.raises(ValueError, match="invalid model spec"):
            _parse_model_spec("/model")

    def test_missing_model_raises(self):
        from dxrk.cli.install import _parse_model_spec

        with pytest.raises(ValueError, match="invalid model spec"):
            _parse_model_spec("provider/")

    def test_no_separator_raises(self):
        from dxrk.cli.install import _parse_model_spec

        with pytest.raises(ValueError, match="invalid model spec"):
            _parse_model_spec("justaname")


class TestVerifyHelpers:
    def test_run_checks_all_pass(self):
        from dxrk.cli.install import _run_checks, _VerifyCheck

        results = _run_checks(
            [
                lambda: None,
                lambda: None,
            ]
        )
        assert len(results) == 2
        assert all(not r.error for r in results)

    def test_run_checks_with_failure(self):
        from dxrk.cli.install import _run_checks, _VerifyCheck

        results = _run_checks(
            [
                lambda: None,
                lambda: "something failed",
            ]
        )
        assert len(results) == 2
        assert results[0].error == ""
        assert results[1].error == "something failed"

    def test_build_report_ready_when_all_pass(self):
        from dxrk.cli.install import _run_checks, _build_report, _VerifyCheck

        checks = _run_checks([lambda: None])
        report = _build_report(checks)
        assert report.ready is True

    def test_build_report_not_ready_on_hard_fail(self):
        from dxrk.cli.install import _run_checks, _build_report

        checks = _run_checks([lambda: "hard fail"])
        report = _build_report(checks)
        assert report.ready is False

    def test_build_report_ready_on_soft_fail(self):
        from dxrk.cli.install import _run_checks, _build_report

        def soft_check():
            pass

        soft_check._soft = True  # type: ignore
        soft_check._cid = "soft"  # type: ignore
        soft_check._desc = ""  # type: ignore
        checks = _run_checks([lambda: None, soft_check])
        report = _build_report(checks)
        assert report.ready is True


class TestDefaultAgentsFromDetection:
    def test_returns_detected_agents(self, tmp_path):
        from dxrk.cli.install import default_agents_from_detection
        from dxrk.system import DetectionResult, SystemInfo, ConfigState

        agent = ConfigState(agent="claude-code", exists=True)
        system = SystemInfo()
        detection = DetectionResult(system=system, configs=[agent], dependencies=None)

        agents = default_agents_from_detection(detection)
        assert AgentID.CLAUDE_CODE in agents

    def test_detected_agents_skip_not_found(self, tmp_path):
        from dxrk.cli.install import default_agents_from_detection
        from dxrk.system import DetectionResult, SystemInfo, ConfigState

        agent = ConfigState(agent="claude-code", exists=False)
        system = SystemInfo()
        detection = DetectionResult(system=system, configs=[agent], dependencies=None)

        agents = default_agents_from_detection(detection)

    def test_returns_all_when_none_detected(self, tmp_path):
        from dxrk.cli.install import default_agents_from_detection
        from dxrk.system import DetectionResult, SystemInfo, ConfigState

        agent = ConfigState(agent="bogus", exists=False)
        system = SystemInfo()
        detection = DetectionResult(system=system, configs=[agent], dependencies=None)

        agents = default_agents_from_detection(detection)
        assert len(agents) > 0


class TestNormalizeInstallFlags:
    def test_minimal_preset(self, tmp_path):
        from dxrk.cli.install import parse_install_flags, normalize_install_flags
        from dxrk.system import DetectionResult, SystemInfo, ConfigState

        flags = parse_install_flags(["--preset", "minimal"])
        system = SystemInfo()
        configs = [ConfigState(agent="claude-code", exists=True)]
        detection = DetectionResult(system=system, configs=configs, dependencies=None)

        result = normalize_install_flags(flags, detection)
        assert result.selection.preset == PresetID.MINIMAL
        assert result.selection.components == [ComponentID.DXRK_MEMORY]
        assert result.dry_run is False

    def test_dry_run_flag(self, tmp_path):
        from dxrk.cli.install import parse_install_flags, normalize_install_flags
        from dxrk.system import DetectionResult, SystemInfo, ConfigState

        flags = parse_install_flags(["--dry-run", "--preset", "minimal"])
        system = SystemInfo()
        configs = [ConfigState(agent="claude-code", exists=True)]
        detection = DetectionResult(system=system, configs=configs, dependencies=None)

        result = normalize_install_flags(flags, detection)
        assert result.dry_run is True


class TestComponentsForPresetSkills:
    def test_full_dxrk_skills(self):
        from dxrk.cli.install import _skills_for_preset

        skills = _skills_for_preset(PresetID.FULL_DXRK)
        assert SkillID.SDD_INIT in skills
        assert SkillID.GO_TESTING in skills
        assert SkillID.JUDGMENT_DAY in skills
        assert SkillID.BRANCH_PR in skills
        assert SkillID.ISSUE_CREATION in skills
        assert SkillID.SKILL_REGISTRY in skills
        assert len(skills) == 16

    def test_minimal_skills(self):
        from dxrk.cli.install import _skills_for_preset

        assert _skills_for_preset(PresetID.MINIMAL) == []

    def test_ecosystem_skills(self):
        from dxrk.cli.install import _skills_for_preset

        assert _skills_for_preset(PresetID.ECOSYSTEM_ONLY) == []


class TestRenderReport:
    def test_all_pass(self):
        from dxrk.cli.install import _render_report, _VerifyReport, _VerifyCheck

        report = _VerifyReport(
            checks=[
                _VerifyCheck(id="check1", error=""),
                _VerifyCheck(id="check2", error=""),
            ]
        )
        output = _render_report(report)
        assert "[PASS] check1" in output
        assert "[PASS] check2" in output
        assert "FAIL" not in output

    def test_with_failures(self):
        from dxrk.cli.install import _render_report, _VerifyReport, _VerifyCheck

        report = _VerifyReport(
            checks=[
                _VerifyCheck(id="check1", error="something broke"),
                _VerifyCheck(id="check2", error="", soft=True),
            ]
        )
        output = _render_report(report)
        assert "[FAIL] check1" in output
        assert "something broke" in output
        assert "[PASS] check2" in output

    def test_with_soft_fail(self):
        from dxrk.cli.install import _render_report, _VerifyReport, _VerifyCheck

        report = _VerifyReport(
            checks=[
                _VerifyCheck(id="soft-check", error="warning msg", soft=True),
            ]
        )
        output = _render_report(report)
        assert "[WARN] soft-check" in output
        assert "warning msg" in output

    def test_final_note(self):
        from dxrk.cli.install import _render_report, _VerifyReport

        report = _VerifyReport(final_note="All good")
        output = _render_report(report)
        assert "All good" in output


class TestUnique:
    def test_removes_duplicates(self):
        from dxrk.cli.install import _unique

        assert _unique([1, 2, 2, 3]) == [1, 2, 3]

    def test_empty(self):
        from dxrk.cli.install import _unique

        assert _unique([]) == []

    def test_already_unique(self):
        from dxrk.cli.install import _unique

        assert _unique([1, 2, 3]) == [1, 2, 3]


class TestCSVAppendType:
    def test_single(self):
        from dxrk.cli.install import _csv_append_type

        assert _csv_append_type("foo") == ["foo"]

    def test_csv(self):
        from dxrk.cli.install import _csv_append_type

        assert _csv_append_type("foo,bar") == ["foo", "bar"]

    def test_whitespace_stripped(self):
        from dxrk.cli.install import _csv_append_type

        assert _csv_append_type(" foo , bar ") == ["foo", "bar"]

    def test_empty_parts_removed(self):
        from dxrk.cli.install import _csv_append_type

        assert _csv_append_type("foo,,bar") == ["foo", "bar"]


class TestFlattenList:
    def test_basic(self):
        from dxrk.cli.install import _flatten_list

        assert _flatten_list([["a", "b"], ["c"]]) == ["a", "b", "c"]

    def test_empty(self):
        from dxrk.cli.install import _flatten_list

        assert _flatten_list([]) == []

    def test_single(self):
        from dxrk.cli.install import _flatten_list

        assert _flatten_list([["a"]]) == ["a"]


class TestParseProfiles:
    def test_single_profile(self):
        from dxrk.cli.install import _parse_profiles

        profiles = _parse_profiles(["my-profile:anthropic/claude-3-opus"], [])
        assert len(profiles) == 1
        assert profiles[0].name == "my-profile"

    def test_profile_with_phase(self):
        from dxrk.cli.install import _parse_profiles

        profiles = _parse_profiles(
            ["my-profile:anthropic/claude-3-opus"],
            ["my-profile:sdd-propose:anthropic/claude-3-haiku"],
        )
        assert len(profiles) == 1
        assert profiles[0].name == "my-profile"
        assert "sdd-propose" in profiles[0].phase_assignments

    def test_phase_only_creates_profile(self):
        from dxrk.cli.install import _parse_profiles

        profiles = _parse_profiles(
            [],
            ["my-profile:sdd-propose:anthropic/claude-3-haiku"],
        )
        assert len(profiles) == 1
        assert profiles[0].name == "my-profile"
        assert "sdd-propose" in profiles[0].phase_assignments

    def test_duplicate_profile_names_deduplicated(self):
        from dxrk.cli.install import _parse_profiles

        profiles = _parse_profiles(
            ["my-profile:anthropic/claude-3-opus"],
            ["my-profile:sdd-spec:anthropic/claude-3-haiku"],
        )
        assert len(profiles) == 1


class TestParseProfileFlag:
    def test_valid(self):
        from dxrk.cli.install import _parse_profile_flag

        profile = _parse_profile_flag("my-profile:anthropic/claude-3-opus")
        assert profile.name == "my-profile"
        assert profile.orchestrator_model.provider_id == "anthropic"
        assert profile.orchestrator_model.model_id == "claude-3-opus"

    def test_no_colon_raises(self):
        from dxrk.cli.install import _parse_profile_flag

        with pytest.raises(ValueError, match="invalid format"):
            _parse_profile_flag("my-profile")

    def test_empty_name_raises(self):
        from dxrk.cli.install import _parse_profile_flag

        with pytest.raises(ValueError, match="invalid format"):
            _parse_profile_flag(":anthropic/claude-3-opus")


class TestParseProfilePhaseFlag:
    def test_valid(self):
        from dxrk.cli.install import _parse_profile_phase_flag

        name, phase, assignment = _parse_profile_phase_flag(
            "my-profile:sdd-propose:anthropic/claude-3-haiku"
        )
        assert name == "my-profile"
        assert phase == "sdd-propose"
        assert assignment.provider_id == "anthropic"
        assert assignment.model_id == "claude-3-haiku"

    def test_empty_name_raises(self):
        from dxrk.cli.install import _parse_profile_phase_flag

        with pytest.raises(ValueError, match="profile name must not be empty"):
            _parse_profile_phase_flag(":propose:anthropic/claude-3-haiku")

    def test_empty_phase_raises(self):
        from dxrk.cli.install import _parse_profile_phase_flag

        with pytest.raises(ValueError, match="phase must not be empty"):
            _parse_profile_phase_flag("my-profile::anthropic/claude-3-haiku")

    def test_too_few_parts_raises(self):
        from dxrk.cli.install import _parse_profile_phase_flag

        with pytest.raises(ValueError, match="invalid format"):
            _parse_profile_phase_flag("my-profile:onlytwo")

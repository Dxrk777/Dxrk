# SPDX-License-Identifier: MIT
from __future__ import annotations

import os

from dxrk.components import skills
from dxrk.models import PresetID, SkillID

import pytest


class FakeAdapter:
    def __init__(self, supports_skills=True, skills_dir=None):
        self._supports_skills = supports_skills
        self._skills_dir = skills_dir

    @property
    def supports_skills(self):
        return self._supports_skills

    def skills_dir(self, home_dir: str) -> str:
        if self._skills_dir is None:
            return ""
        return os.path.join(home_dir, self._skills_dir)

    @property
    def agent(self):
        return "test"

    @property
    def supports_system_prompt(self):
        return True


class TestSkillsForPreset:
    def test_full_dxrk_returns_sdd_and_foundation(self):
        s = skills.skills_for_preset(PresetID.FULL_DXRK)
        assert SkillID.SDD_INIT in s
        assert SkillID.GO_TESTING in s

    def test_minimal_returns_only_sdd(self):
        s = skills.skills_for_preset(PresetID.MINIMAL)
        assert SkillID.SDD_INIT in s
        assert SkillID.GO_TESTING not in s
        assert SkillID.JUDGMENT_DAY in s

    def test_ecosystem_returns_sdd_and_foundation(self):
        s = skills.skills_for_preset(PresetID.ECOSYSTEM_ONLY)
        assert SkillID.SDD_INIT in s
        assert SkillID.GO_TESTING in s

    def test_custom_returns_empty(self):
        assert skills.skills_for_preset(PresetID.CUSTOM) == []


class TestAllSkillIds:
    def test_contains_all(self):
        s = skills.all_skill_ids()
        assert SkillID.SDD_INIT in s
        assert SkillID.GO_TESTING in s
        assert SkillID.SKILL_CREATOR in s


class TestInject:
    def test_skips_when_unsupported(self):
        adapter = FakeAdapter(supports_skills=False)
        result = skills.inject("/home/user", adapter, [SkillID.GO_TESTING])
        assert result.Changed is False
        assert result.Skipped == [SkillID.GO_TESTING]

    def test_skips_when_no_skills_dir(self):
        adapter = FakeAdapter(skills_dir=None)
        result = skills.inject("/home/user", adapter, [SkillID.GO_TESTING])
        assert result.Changed is False

    def test_skips_sdd_skills(self, tmp_path):
        adapter = FakeAdapter()
        result = skills.inject(str(tmp_path), adapter, [SkillID.SDD_INIT])
        assert result.Changed is False
        assert result.Files == []


class TestSkillPathForAgent:
    def test_returns_skill_path(self):
        adapter = FakeAdapter(skills_dir="/home/user/.opencode/skills")
        path = skills.skill_path_for_agent("/home/user", adapter, SkillID.GO_TESTING)
        assert path == "/home/user/.opencode/skills/go-testing/SKILL.md"

    def test_returns_empty_when_no_skills_dir(self):
        adapter = FakeAdapter(skills_dir=None)
        assert skills.skill_path_for_agent("/home/user", adapter, SkillID.GO_TESTING) == ""

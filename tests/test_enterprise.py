# SPDX-License-Identifier: MIT
"""Tests para Dxrk Enterprise: company, orchestrator, workforce, departments, skills y CLI.

Determinista: sin red ni sleeps. Aislamiento total via tmp_path (company con
config_path temporal) y HOME aislado para la CLI (DxrkEnterprise() default
escribe en ~/.dxrk).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

from dxrk.commands import register_all
from dxrk.enterprise import AIWorkforce, DxrkEnterprise, TaskOrchestrator
from dxrk.enterprise.departments import (
    BaseDepartment,
    DesignersDepartment,
    DevelopersDepartment,
    FinanceDepartment,
    LegalDepartment,
    MarketingDepartment,
    SmallBusinessDepartment,
    SocialMediaDepartment,
)
from dxrk.enterprise.skills.business_skills import get_all_business_skills
from dxrk.enterprise.skills.designer_skills import get_all_designer_skills
from dxrk.enterprise.skills.developer_skills import get_all_developer_skills
from dxrk.enterprise.skills.finance_skills import get_all_finance_skills
from dxrk.enterprise.skills.legal_skills import get_all_legal_skills
from dxrk.enterprise.skills.marketing_skills import get_all_marketing_skills
from dxrk.enterprise.skills.registry import SkillRegistry
from dxrk.enterprise.skills.skill_base import BaseSkill
from dxrk.enterprise.skills.social_skills import get_all_social_skills

NO_MATCH_TASK = "qxqx zkzk qwqw 9999"


def _make_company(tmp_path: Path) -> DxrkEnterprise:
    return DxrkEnterprise(config_path=str(tmp_path / "enterprise"))


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_VAULT_KEY", raising=False)
    for key in [k for k in os.environ if k.startswith("DXRK_VAULT_KEY_")]:
        monkeypatch.delenv(key, raising=False)
    return home


def _run(argv: list[str]) -> tuple[int, str, str]:
    reg = register_all()
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class TestCompanyLifecycle:
    def test_init_not_operational(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        assert company.is_operational is False

    def test_start_sets_operational(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        assert company.is_operational is True

    def test_start_activates_all_departments(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        assert len(company.departments) == 7
        assert all(d.is_active for d in company.departments.values())

    def test_start_writes_state_file(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        state_file = tmp_path / "enterprise" / "company_state.json"
        assert state_file.exists()
        assert "true" in state_file.read_text(encoding="utf-8").lower()

    def test_stop_sets_not_operational(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        company.stop_company()
        assert company.is_operational is False

    def test_stop_deactivates_departments(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        company.stop_company()
        assert all(not d.is_active for d in company.departments.values())

    def test_restart_cycle(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        company.stop_company()
        company.start_company()
        assert company.is_operational is True
        assert all(d.is_active for d in company.departments.values())


class TestCompanyExecute:
    def test_execute_without_start_returns_error(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        result = company.execute_task("debug python code")
        assert "error" in result
        assert "not operational" in result["error"].lower()

    def test_execute_with_explicit_department(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.execute_task("debug error fix bug", "developers")
        assert result.get("success") is True

    def test_execute_auto_routes_to_developers(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.execute_task("debug python code")
        assert result.get("success") is True

    def test_execute_auto_routes_to_legal(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.execute_task("contrato NDA")
        assert result.get("success") is True
        assert company.orchestrator.routing_history[-1]["routed_to"] == "legal"

    def test_execute_auto_routes_to_designers(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.execute_task("diseñar logo")
        assert result.get("success") is True
        assert company.orchestrator.routing_history[-1]["routed_to"] == "designers"

    def test_execute_unknown_department_returns_error(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.execute_task("debug python code", "noexiste")
        assert "error" in result
        assert "noexiste" in result["error"]

    def test_execute_records_completed_task(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        assert company.orchestrator.get_completed_tasks_count() == 0
        company.execute_task("debug python code", "developers")
        assert company.orchestrator.get_completed_tasks_count() == 1

    def test_execute_unknown_dept_does_not_record(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        company.execute_task("hola", "noexiste")
        assert company.orchestrator.get_completed_tasks_count() == 0


class TestCompanySkills:
    def test_install_skill_ok(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.install_skill("developers", "debug_master")
        assert result.get("success") is True

    def test_install_skill_duplicate(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        first = company.install_skill("developers", "debug_master")
        assert first.get("success") is True
        second = company.install_skill("developers", "debug_master")
        assert second.get("success") is False
        assert "already" in second["message"].lower()

    def test_install_skill_nonexistent(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        result = company.install_skill("developers", "skill_fantasma_xyz")
        assert "error" in result

    def test_install_skill_unknown_department(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        result = company.install_skill("noexiste", "debug_master")
        assert "error" in result

    def test_list_all_skills_seven_departments(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        skills = company.list_all_skills()
        assert set(skills) == {
            "developers",
            "designers",
            "marketing",
            "social_media",
            "finance",
            "small_business",
            "legal",
        }

    def test_list_all_skills_entries_have_installed_flag(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        skills = company.list_all_skills()
        for entries in skills.values():
            assert len(entries) > 0
            for entry in entries:
                assert "name" in entry and "installed" in entry

    def test_get_company_status_total_skills_79(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        status = company.get_company_status()
        assert status["total_skills"] == 79

    def test_get_company_status_structure(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        status = company.get_company_status()
        assert status["is_operational"] is True
        assert len(status["departments"]) == 7
        assert status["tasks_completed"] == 0

    def test_generate_report_contains_operational(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        company.start_company()
        assert "OPERATIONAL" in company.generate_company_report()

    def test_generate_report_stopped(self, tmp_path: Path) -> None:
        company = _make_company(tmp_path)
        report = company.generate_company_report()
        assert "STOPPED" in report


class TestOrchestrator:
    def test_route_to_developers(self) -> None:
        assert TaskOrchestrator().route_task("debug python code with tests") == "developers"

    def test_route_to_designers(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("design logo layout with figma brand") == "designers"

    def test_route_to_marketing(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("seo campaign email funnel copy marketing") == "marketing"

    def test_route_to_social_media(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("instagram post reel tiktok youtube social") == "social_media"

    def test_route_to_finance(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("finance budget tax audit balance accounting") == "finance"

    def test_route_to_small_business(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("invoice payroll inventory customer pricing business") == "small_business"

    def test_route_to_legal(self) -> None:
        orch = TaskOrchestrator()
        assert orch.route_task("legal contract nda agreement privacy compliance") == "legal"

    def test_initial_count_zero(self) -> None:
        assert TaskOrchestrator().get_completed_tasks_count() == 0

    def test_record_increments_count(self) -> None:
        orch = TaskOrchestrator()
        orch.record_completed_task("t1", "developers", {"success": True})
        orch.record_completed_task("t2", "legal", {"success": True})
        assert orch.get_completed_tasks_count() == 2

    def test_route_appends_history(self) -> None:
        orch = TaskOrchestrator()
        orch.route_task("debug python code")
        assert len(orch.routing_history) == 1
        assert orch.routing_history[0]["routed_to"] == "developers"


class TestWorkforce:
    def test_hire_returns_success(self) -> None:
        wf = AIWorkforce()
        result = wf.hire_agent("alice", "dev", "developers")
        assert result["success"] is True
        assert result["agent"]["name"] == "alice"

    def test_hire_multiple_size(self) -> None:
        wf = AIWorkforce()
        wf.hire_agent("a1", "r", "developers")
        wf.hire_agent("a2", "r", "legal")
        assert wf.get_workforce_size() == 2

    def test_fire_ok(self) -> None:
        wf = AIWorkforce()
        wf.hire_agent("bob", "dev", "developers")
        result = wf.fire_agent("bob")
        assert result["success"] is True
        assert result["agent"]["is_active"] is False

    def test_fire_unknown_returns_error(self) -> None:
        wf = AIWorkforce()
        result = wf.fire_agent("ghost")
        assert result["success"] is False
        assert "error" in result

    def test_list_agents(self) -> None:
        wf = AIWorkforce()
        wf.hire_agent("a1", "r", "developers")
        listed = wf.list_agents()
        assert len(listed["agents"]) == 1
        assert listed["active"] == 1

    def test_size_counts_only_active(self) -> None:
        wf = AIWorkforce()
        wf.hire_agent("a1", "r", "developers")
        wf.hire_agent("a2", "r", "legal")
        wf.fire_agent("a1")
        assert wf.get_workforce_size() == 1

    def test_fire_keeps_record(self) -> None:
        wf = AIWorkforce()
        wf.hire_agent("a1", "r", "developers")
        wf.fire_agent("a1")
        assert len(wf.list_agents()["agents"]) == 1
        assert wf.list_agents()["active"] == 0


class TestBaseDepartment:
    def test_execute_inactive_returns_error(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        result = dept.execute_task("debug error fix bug")
        assert "error" in result
        assert "not active" in result["error"].lower()

    def test_execute_no_skill_returns_error(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        dept.activate()
        result = dept.execute_task(NO_MATCH_TASK)
        assert result.get("success") is False
        assert "error" in result

    def test_full_cycle_via_real_registry(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        dept.activate()
        result = dept.execute_task("debug error fix bug")
        assert result.get("success") is True
        assert dept.tasks_completed == 1
        assert len(dept.task_history) == 1

    def test_registry_assert_without_registry(self) -> None:
        dept = BaseDepartment(skill_registry=None)
        with pytest.raises(AssertionError):
            dept._registry()

    def test_install_skill_uses_registry(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        result = dept.install_skill("debug_master")
        assert result.get("success") is True

    def test_get_status_fields(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        dept.activate()
        status = dept.get_status()
        assert status["id"] == "developers"
        assert status["skills_count"] == 12
        assert status["success_rate"] == 0

    def test_activate_deactivate_cycle(self) -> None:
        dept = DevelopersDepartment(SkillRegistry())
        dept.activate()
        assert dept.is_active is True
        dept.deactivate()
        assert dept.is_active is False


class TestSkillRegistry:
    def test_total_skills_79(self) -> None:
        assert SkillRegistry().get_total_skills() == 79

    def test_get_skill_none_when_missing(self) -> None:
        assert SkillRegistry().get_skill("skill_fantasma_xyz") is None

    def test_get_skill_exists(self) -> None:
        skill = SkillRegistry().get_skill("code_review")
        assert skill is not None
        assert skill.name == "code_review"

    def test_active_count(self) -> None:
        assert SkillRegistry().get_active_skills_count() == 79

    def test_list_all_skills_len_79(self) -> None:
        assert len(SkillRegistry().list_all_skills()) == 79

    def test_register_custom_skill(self) -> None:
        reg = SkillRegistry()
        before = reg.get_total_skills()
        reg.register_skill(BaseSkill())
        assert reg.get_total_skills() == before + 1


class TestBaseSkill:
    def test_execute_success(self) -> None:
        skill = BaseSkill()
        result = skill.execute("hello task")
        assert result["success"] is True
        assert result["skill"] == "base_skill"
        assert skill.usage_count == 1

    def test_execute_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        skill = BaseSkill()

        def _boom(task: str, context: dict) -> dict:
            raise ValueError("boom")

        monkeypatch.setattr(skill, "_perform_task", _boom)
        result = skill.execute("hello task")
        assert result["success"] is False
        assert result["error"] == "boom"

    def test_can_handle_true(self) -> None:
        skill = BaseSkill()
        skill.KEYWORDS = ["magicword"]  # type: ignore[assignment]
        assert skill.can_handle("please do magicword now") is True

    def test_can_handle_false(self) -> None:
        skill = BaseSkill()
        skill.KEYWORDS = ["magicword"]  # type: ignore[assignment]
        assert skill.can_handle("nothing relevant here") is False

    def test_stats_initial(self) -> None:
        stats = BaseSkill().get_stats()
        assert stats["usage_count"] == 0
        assert stats["success_rate"] == 0

    def test_stats_after_success(self) -> None:
        skill = BaseSkill()
        skill.execute("task one")
        stats = skill.get_stats()
        assert stats["usage_count"] == 1
        assert stats["success_rate"] == 1.0

    def test_name_property(self) -> None:
        assert BaseSkill().name == BaseSkill.SKILL_NAME

    def test_last_used_set(self) -> None:
        skill = BaseSkill()
        assert skill.last_used is None
        skill.execute("task one")
        assert skill.last_used is not None


class TestSkillModules:
    def test_developer_skills_count(self) -> None:
        assert len(get_all_developer_skills()) == 12

    def test_designer_skills_count(self) -> None:
        assert len(get_all_designer_skills()) == 6

    def test_marketing_skills_count(self) -> None:
        assert len(get_all_marketing_skills()) == 15

    def test_social_skills_count(self) -> None:
        assert len(get_all_social_skills()) == 17

    def test_finance_skills_count(self) -> None:
        assert len(get_all_finance_skills()) == 8

    def test_business_skills_count(self) -> None:
        assert len(get_all_business_skills()) == 12

    def test_legal_skills_count(self) -> None:
        assert len(get_all_legal_skills()) == 9

    def test_modules_sum_79(self) -> None:
        total = (
            len(get_all_developer_skills())
            + len(get_all_designer_skills())
            + len(get_all_marketing_skills())
            + len(get_all_social_skills())
            + len(get_all_finance_skills())
            + len(get_all_business_skills())
            + len(get_all_legal_skills())
        )
        assert total == 79


DEPT_CASES = [
    (DevelopersDepartment, "developers", 12),
    (DesignersDepartment, "designers", 6),
    (MarketingDepartment, "marketing", 15),
    (SocialMediaDepartment, "social_media", 17),
    (FinanceDepartment, "finance", 8),
    (SmallBusinessDepartment, "small_business", 12),
    (LegalDepartment, "legal", 9),
]


@pytest.mark.parametrize(("dept_cls", "dept_id", "n_skills"), DEPT_CASES)
class TestDepartments:
    def test_skills_not_empty(self, dept_cls: type[BaseDepartment], dept_id: str, n_skills: int) -> None:
        assert len(dept_cls.SKILLS) == n_skills
        assert len(dept_cls.SKILLS) > 0

    def test_activate_installs_five_by_default(
        self, dept_cls: type[BaseDepartment], dept_id: str, n_skills: int
    ) -> None:
        dept = dept_cls(SkillRegistry())
        assert len(dept.installed_skills) == 0
        dept.activate()
        assert len(dept.installed_skills) == 5

    def test_get_status(self, dept_cls: type[BaseDepartment], dept_id: str, n_skills: int) -> None:
        dept = dept_cls(SkillRegistry())
        dept.activate()
        status = dept.get_status()
        assert status["id"] == dept_id
        assert status["skills_count"] == n_skills
        assert status["installed_skills"] == 5
        assert status["is_active"] is True


class TestEnterpriseCLI:
    def test_parent_without_args_returns_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, err = _run(["enterprise"])
        assert code == 1
        assert err != ""

    def test_start_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "start"])
        assert code == 0
        assert out != ""

    def test_stop_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "stop"])
        assert code == 0
        assert "stopped" in out.lower()

    def test_status_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "status"])
        assert code == 0
        assert "DXRK ENTERPRISE" in out

    def test_skills_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "skills"])
        assert code == 0
        assert "developers" in out

    def test_report_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "report"])
        assert code == 0
        assert "DXRK ENTERPRISE" in out

    def test_execute_without_task_returns_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, _ = _run(["enterprise", "execute"])
        assert code == 1

    def test_execute_valid_task_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, out, _ = _run(["enterprise", "execute", "debug python code"])
        assert code == 0
        assert out != ""

    def test_execute_explicit_department_returns_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, _ = _run(["enterprise", "execute", "debug python code", "developers"])
        assert code == 0

    def test_execute_unknown_department_returns_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        code, _, err = _run(["enterprise", "execute", "debug python code", "noexiste"])
        assert code == 1
        assert err != ""

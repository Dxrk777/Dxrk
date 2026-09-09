"""Skill Registry - Registro central de todas las habilidades."""

from __future__ import annotations

from .skill_base import BaseSkill


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._register_default_skills()

    def register_skill(self, skill: BaseSkill):
        self._skills[skill.SKILL_NAME] = skill

    def get_skill(self, skill_name: str) -> BaseSkill | None:
        return self._skills.get(skill_name)

    def get_total_skills(self) -> int:
        return len(self._skills)

    def get_active_skills_count(self) -> int:
        return sum(1 for s in self._skills.values() if s.is_active)

    def list_all_skills(self) -> list[dict]:
        return [{"name": s.SKILL_NAME, "category": s.SKILL_CATEGORY} for s in self._skills.values()]

    def _register_default_skills(self):
        from .business_skills import get_all_business_skills
        from .designer_skills import get_all_designer_skills
        from .developer_skills import get_all_developer_skills
        from .finance_skills import get_all_finance_skills
        from .legal_skills import get_all_legal_skills
        from .marketing_skills import get_all_marketing_skills
        from .social_skills import get_all_social_skills

        for skill in get_all_developer_skills():
            self.register_skill(skill)
        for skill in get_all_designer_skills():
            self.register_skill(skill)
        for skill in get_all_marketing_skills():
            self.register_skill(skill)
        for skill in get_all_social_skills():
            self.register_skill(skill)
        for skill in get_all_finance_skills():
            self.register_skill(skill)
        for skill in get_all_business_skills():
            self.register_skill(skill)
        for skill in get_all_legal_skills():
            self.register_skill(skill)

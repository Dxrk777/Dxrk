"""Designer Skills - 6 skills de diseño."""


from .skill_base import BaseSkill


def create_design_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "design"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_designer_skills() -> list[BaseSkill]:
    configs = [
        ("ui_ux_pro_max", "UI/UX profesional", ["ui", "ux", "interface", "design"]),
        ("taste", "Gusto estético", ["taste", "aesthetic", "art", "style"]),
        ("frontend_design", "Diseño frontend", ["frontend", "html", "css", "responsive"]),
        ("transitions", "Animaciones", ["animation", "transition", "motion"]),
        ("web_artifacts_builder", "Artefactos web", ["artifact", "widget", "component"]),
        ("brand_guidelines", "Guías de marca", ["brand", "guidelines", "identity", "logo"]),
    ]
    return [create_design_skill(n, d, k)() for n, d, k in configs]

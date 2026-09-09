"""Legal Skills - 9 skills legales."""


from .skill_base import BaseSkill


def create_legal_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "legal"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_legal_skills() -> list[BaseSkill]:
    configs = [
        ("contract_drafting", "Contratos", ["contract", "draft", "agreement"]),
        ("contract_review", "Revisión", ["contract", "review"]),
        ("nda_creation", "NDAs", ["nda", "non-disclosure"]),
        ("nda_review", "Revisión NDA", ["nda", "review"]),
        ("terms_of_service", "Términos", ["terms", "service", "tos"]),
        ("privacy_policy", "Privacidad", ["privacy", "policy", "gdpr"]),
        ("compliance_check", "Cumplimiento", ["compliance", "regulation"]),
        ("intellectual_property", "Propiedad intelectual", ["intellectual", "property", "patent"]),
        ("dispute_resolution", "Disputas", ["dispute", "resolution", "conflict"]),
    ]
    return [create_legal_skill(n, d, k)() for n, d, k in configs]

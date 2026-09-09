"""Finance Skills - 8 skills de finanzas."""


from .skill_base import BaseSkill


def create_fin_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "finance"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_finance_skills() -> list[BaseSkill]:
    configs = [
        ("financial_statements", "Estados financieros", ["financial", "statement"]),
        ("balance_sheet", "Balance", ["balance", "assets"]),
        ("income_statement", "Resultados", ["income", "revenue", "profit"]),
        ("cash_flow_analysis", "Flujo de caja", ["cash", "flow"]),
        ("reconciliation", "Conciliaciones", ["reconcil", "bank"]),
        ("audit_preparation", "Auditorías", ["audit", "prepare"]),
        ("tax_planning", "Fiscal", ["tax", "planning"]),
        ("budget_forecasting", "Presupuestos", ["budget", "forecast"]),
    ]
    return [create_fin_skill(n, d, k)() for n, d, k in configs]

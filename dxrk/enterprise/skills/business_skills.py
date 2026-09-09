"""Business Skills - 12 skills de pequeñas empresas."""


from .skill_base import BaseSkill


def create_biz_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "small_business"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_business_skills() -> list[BaseSkill]:
    configs = [
        ("cash_flow_management", "Flujo de caja", ["cash", "flow"]),
        ("expense_tracking", "Gastos", ["expense", "track"]),
        ("revenue_tracking", "Ingresos", ["revenue", "income"]),
        ("payroll_processing", "Nómina", ["payroll", "salary"]),
        ("invoice_creation", "Facturas", ["invoice", "bill"]),
        ("invoice_tracking", "Seguimiento", ["invoice", "track"]),
        ("inventory_management", "Inventario", ["inventory", "stock"]),
        ("supplier_management", "Proveedores", ["supplier", "vendor"]),
        ("customer_service", "Clientes", ["customer", "service"]),
        ("business_plan", "Plan de negocios", ["business", "plan"]),
        ("market_analysis", "Mercado", ["market", "analysis"]),
        ("pricing_strategy", "Precios", ["pricing", "price"]),
    ]
    return [create_biz_skill(n, d, k)() for n, d, k in configs]

"""Departamento de pequeñas empresas: caja, nómina, facturación, operaciones."""

from .base import BaseDepartment


class SmallBusinessDepartment(BaseDepartment):
    DEPARTMENT_ID = "small_business"
    DEPARTMENT_NAME = "Pequeñas Empresas"
    DEPARTMENT_DESCRIPTION = "Flujo de caja, nómina, facturación, operaciones"
    SKILLS = [
        "cash_flow_management",
        "expense_tracking",
        "revenue_tracking",
        "payroll_processing",
        "invoice_creation",
        "invoice_tracking",
        "inventory_management",
        "supplier_management",
        "customer_service",
        "business_plan",
        "market_analysis",
        "pricing_strategy",
    ]

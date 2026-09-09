"""Departamento de finanzas: estados financieros, conciliaciones, auditorías."""

from .base import BaseDepartment


class FinanceDepartment(BaseDepartment):
    DEPARTMENT_ID = "finance"
    DEPARTMENT_NAME = "Finanzas"
    DEPARTMENT_DESCRIPTION = "Estados financieros, conciliaciones, auditorías"
    SKILLS = [
        "financial_statements",
        "balance_sheet",
        "income_statement",
        "cash_flow_analysis",
        "reconciliation",
        "audit_preparation",
        "tax_planning",
        "budget_forecasting",
    ]

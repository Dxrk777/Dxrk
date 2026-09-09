"""Departamento legal: contratos, NDAs, revisiones, cumplimiento."""

from .base import BaseDepartment


class LegalDepartment(BaseDepartment):
    DEPARTMENT_ID = "legal"
    DEPARTMENT_NAME = "Legal"
    DEPARTMENT_DESCRIPTION = "Contratos, NDAs, revisiones, cumplimiento"
    SKILLS = [
        "contract_drafting",
        "contract_review",
        "nda_creation",
        "nda_review",
        "terms_of_service",
        "privacy_policy",
        "compliance_check",
        "intellectual_property",
        "dispute_resolution",
    ]

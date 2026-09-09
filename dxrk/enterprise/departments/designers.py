"""Departamento de diseñadores: UI/UX, branding, diseño frontend."""

from .base import BaseDepartment


class DesignersDepartment(BaseDepartment):
    DEPARTMENT_ID = "designers"
    DEPARTMENT_NAME = "Diseñadores"
    DEPARTMENT_DESCRIPTION = "UI/UX, branding, diseño frontend"
    SKILLS = [
        "ui_ux_pro_max",
        "taste",
        "frontend_design",
        "transitions",
        "web_artifacts_builder",
        "brand_guidelines",
    ]

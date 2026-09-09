"""Departamento de desarrolladores: ingeniería, arquitectura, testing."""

from .base import BaseDepartment


class DevelopersDepartment(BaseDepartment):
    DEPARTMENT_ID = "developers"
    DEPARTMENT_NAME = "Desarrolladores"
    DEPARTMENT_DESCRIPTION = "Ingeniería de software, arquitectura, testing"
    SKILLS = [
        "superpowers",
        "context7",
        "skill_creator",
        "mcp_builder",
        "webapp_testing",
        "dxrk_mem",
        "code_review",
        "architecture_design",
        "debug_master",
        "refactoring_expert",
        "api_designer",
        "performance_optimizer",
    ]

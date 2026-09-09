"""Developer Skills - 12 skills de desarrollo."""


from .skill_base import BaseSkill


def create_dev_skill(name, desc, keywords):
    class S(BaseSkill):
        SKILL_NAME = name
        SKILL_DESCRIPTION = desc
        SKILL_CATEGORY = "development"
        KEYWORDS = keywords

        def _perform_task(self, task, context):
            return {"action": self.SKILL_NAME, "task": task}

    S.__name__ = name.replace("_", " ").title().replace(" ", "") + "Skill"
    return S


def get_all_developer_skills() -> list[BaseSkill]:
    configs = [
        ("superpowers", "Superpoderes de desarrollo", ["superpower", "advanced", "expert"]),
        ("context7", "Documentación actualizada", ["documentation", "docs", "library"]),
        ("skill_creator", "Crea nuevas habilidades", ["create", "skill", "generate"]),
        ("mcp_builder", "Construye servidores MCP", ["mcp", "server", "protocol"]),
        ("webapp_testing", "Pruebas web", ["test", "testing", "qa"]),
        ("dxrk_mem", "Memoria DxrkMemory", ["memory", "remember", "context"]),
        ("code_review", "Revisión de código", ["review", "code", "pr"]),
        ("architecture_design", "Diseño de arquitectura", ["architecture", "design", "system"]),
        ("debug_master", "Debugging avanzado", ["debug", "error", "bug", "fix"]),
        ("refactoring_expert", "Refactorización", ["refactor", "clean", "optimize"]),
        ("api_designer", "Diseño de APIs", ["api", "rest", "graphql", "endpoint"]),
        ("performance_optimizer", "Optimización", ["performance", "optimize", "speed"]),
    ]
    return [create_dev_skill(n, d, k)() for n, d, k in configs]

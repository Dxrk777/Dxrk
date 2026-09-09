"""
Contribution Weighting - Sistema de pesos por complejidad.
"""

from __future__ import annotations


class ContributionWeighting:
    """Valora más las contribuciones complejas."""

    BASE_SCORES = {
        "read_file": 0.1,
        "write_file": 0.5,
        "edit_file": 1.0,
        "debug_simple": 3.0,
        "debug_complex": 8.0,
        "refactor_small": 5.0,
        "refactor_large": 15.0,
        "architecture_design": 30.0,
        "novel_solution": 50.0,
        "library_mastery": 20.0,
    }

    def calculate_contribution_score(
        self,
        task_type: str,
        time_spent_minutes: float = 1.0,
        lines_of_code: int = 0,
        error_count_before: int = 0,
        error_count_after: int = 0,
        novelty_score: float = 0.0,
    ) -> float:
        base_score = self.BASE_SCORES.get(task_type, 1.0)
        time_multiplier = min(3.0, 1 + (time_spent_minutes / 60))
        code_multiplier = min(5.0, 1 + (lines_of_code / 100))
        impact_multiplier = 1.0
        if error_count_before > 0:
            errors_fixed = error_count_before - error_count_after
            impact_multiplier = 1 + (errors_fixed / error_count_before) * 2
        novelty_multiplier = 1 + novelty_score
        return round(base_score * time_multiplier * code_multiplier * impact_multiplier * novelty_multiplier, 2)

    def get_contribution_tier(self, score: float) -> str:
        if score >= 50:
            return "LEGENDARY"
        elif score >= 25:
            return "EXPERT"
        elif score >= 10:
            return "ADVANCED"
        elif score >= 5:
            return "INTERMEDIATE"
        return "BASIC"

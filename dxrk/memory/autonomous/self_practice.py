"""
Self-Practice Engine - El cerebro se genera problemas para practicar.
"""

from __future__ import annotations

from datetime import UTC, datetime


class SelfPracticeEngine:
    """El cerebro se genera problemas a sí mismo para practicar."""

    DIFFICULTY_LEVELS = ["beginner", "intermediate", "advanced", "expert", "genius"]

    def __init__(self, memory_engine=None, iq_engine=None):
        self.memory = memory_engine
        self.iq = iq_engine
        self.practice_history = []

    async def daily_practice_session(self):
        weak_areas = self.iq.get_weakest_dimensions(count=3) if self.iq else ["coding_mastery"]
        for area in weak_areas:
            problems = await self._generate_problems_for_area(area, count=3)
            for problem in problems:
                solution = await self._attempt_solution(problem)
                evaluation = self._evaluate_solution(problem, solution)
                await self._learn_from_practice(problem, solution, evaluation)

    async def _generate_problems_for_area(self, area: str, count: int = 3) -> list[dict]:
        problems = []
        for i in range(count):
            difficulty = self.DIFFICULTY_LEVELS[min(i, len(self.DIFFICULTY_LEVELS) - 1)]
            problems.append(
                {
                    "title": f"Practice {i + 1} for {area}",
                    "difficulty": difficulty,
                    "area": area,
                    "verification_criteria": [f"Addresses {area}", f"Level: {difficulty}"],
                }
            )
        return problems

    async def _attempt_solution(self, problem: dict) -> dict:
        return {"approach": "systematic", "confidence": 0.7}

    def _evaluate_solution(self, problem: dict, solution: dict) -> dict:
        score = solution.get("confidence", 0.5)
        return {"score": score, "passed": score >= 0.7, "feedback": []}

    async def _learn_from_practice(self, problem: dict, solution: dict, evaluation: dict):
        self.practice_history.append(
            {
                "problem": problem,
                "evaluation": evaluation,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if evaluation["passed"] and self.iq:
            self.iq.add_skill(
                skill_id=f"practice_{problem['area']}_{problem['difficulty']}",
                dimension=problem["area"],
                mastery_level=evaluation["score"],
            )

    def get_practice_stats(self) -> dict:
        total = len(self.practice_history)
        passed = sum(1 for p in self.practice_history if p["evaluation"]["passed"])
        return {
            "total_practices": total,
            "passed": passed,
            "success_rate": passed / total if total > 0 else 0,
        }

"""Task Orchestrator - Enruta tareas al departamento correcto."""

from __future__ import annotations

from datetime import UTC, datetime


class TaskOrchestrator:
    DEPARTMENT_KEYWORDS = {
        "developers": ["code", "program", "debug", "test", "api", "database", "python", "javascript"],
        "designers": ["design", "ui", "ux", "brand", "logo", "layout", "figma"],
        "marketing": ["marketing", "seo", "copy", "campaign", "lead", "funnel", "email"],
        "social_media": ["social", "instagram", "twitter", "tiktok", "youtube", "post", "reel"],
        "finance": ["finance", "accounting", "balance", "tax", "budget", "audit"],
        "small_business": ["business", "invoice", "payroll", "inventory", "customer", "pricing"],
        "legal": ["legal", "contract", "nda", "agreement", "privacy", "compliance"],
    }

    def __init__(self):
        self.completed_tasks = []
        self.routing_history = []

    def route_task(self, task_description: str) -> str:
        task_lower = task_description.lower()
        scores: dict[str, int] = {}
        for dept_id, keywords in self.DEPARTMENT_KEYWORDS.items():
            scores[dept_id] = sum(1 for kw in keywords if kw in task_lower)
        best_dept = max(scores, key=lambda dept_id: scores[dept_id])
        self.routing_history.append({"task": task_description, "routed_to": best_dept})
        return best_dept

    def record_completed_task(self, task: str, department: str, result: dict) -> None:
        self.completed_tasks.append(
            {
                "task": task,
                "department": department,
                "result": result,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def get_completed_tasks_count(self) -> int:
        return len(self.completed_tasks)

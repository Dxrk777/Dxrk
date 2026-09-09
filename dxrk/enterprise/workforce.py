"""AI Workforce - Gestión de la fuerza laboral de IA."""

from __future__ import annotations

from datetime import UTC, datetime


class AIWorkforce:
    def __init__(self):
        self.agents = []

    def hire_agent(self, agent_name: str, role: str, department: str) -> dict:
        agent = {
            "name": agent_name,
            "role": role,
            "department": department,
            "hired_at": datetime.now(UTC).isoformat(),
            "is_active": True,
        }
        self.agents.append(agent)
        return {"success": True, "agent": agent}

    def fire_agent(self, agent_name: str) -> dict:
        for agent in self.agents:
            if agent["name"] == agent_name:
                agent["is_active"] = False
                return {"success": True, "agent": agent}
        return {"success": False, "error": f"Agent '{agent_name}' not found."}

    def get_workforce_size(self) -> int:
        return len([a for a in self.agents if a["is_active"]])

    def list_agents(self) -> dict:
        return {"agents": self.agents, "active": self.get_workforce_size()}

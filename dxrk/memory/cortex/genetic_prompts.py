"""
Genetic Prompt Evolution - Los prompts evolucionan mediante selección natural.
Los mejores prompts sobreviven, se cruzan y mutan.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime


class GeneticPromptEvolution:
    """
    Evoluciona prompts mediante algoritmos genéticos.

    Proceso:
    1. Crear población de prompts (mutaciones del actual)
    2. Evaluar fitness de cada uno
    3. Seleccionar los mejores
    4. Cruzarlos para crear nueva generación
    5. Aplicar mutaciones aleatorias
    6. Repetir
    """

    def __init__(self, population_size: int = 10, mutation_rate: float = 0.2):
        self.population_size = population_size
        self.mutation_rate = mutation_rate
        self.generation = 0
        self.fitness_history: list[dict] = []

    async def evolve_system_prompt(
        self,
        current_prompt: str,
        task_history: list[dict],
        evaluate_fn: Callable | None = None,
    ) -> str:
        """Evoluciona el prompt del sistema."""
        # 1. Crear población inicial
        population = [current_prompt]
        for _ in range(self.population_size - 1):
            mutated = self._mutate_prompt(current_prompt)
            population.append(mutated)

        # 2. Evaluar fitness
        fitness_scores = []
        for prompt in population:
            if evaluate_fn:
                score = await evaluate_fn(prompt, task_history)
            else:
                score = self._quick_fitness(prompt, task_history)
            fitness_scores.append(score)

        # 3. Selección
        selected = self._select_best(population, fitness_scores, keep=3)

        # 4. Cruzamiento
        offspring = self._crossover(selected)

        # 5. Mutación
        new_generation = self._mutate_population(offspring)

        self.generation += 1
        self.fitness_history.append(
            {
                "generation": self.generation,
                "best_fitness": max(fitness_scores),
                "avg_fitness": sum(fitness_scores) / len(fitness_scores),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        # Retornar el mejor
        best_prompt: str = max(new_generation, key=lambda p: self._quick_fitness(p, task_history))
        return best_prompt

    def _mutate_prompt(self, prompt: str) -> str:
        """Aplica una mutación aleatoria."""
        mutations = [
            lambda p: p + "\n\nIMPORTANT: Always verify your reasoning step by step.",
            lambda p: p + "\n\nWhen solving complex problems, break them into smaller sub-problems.",
            lambda p: p.replace("You are", "You are an expert"),
            lambda p: p + "\n\nUse concrete examples when explaining concepts.",
            lambda p: p + "\n\nConsider edge cases and potential failure modes.",
            lambda p: p + "\n\nOptimize for clarity and correctness.",
            lambda p: p + "\n\nIf uncertain, state your confidence level explicitly.",
        ]
        if random.random() < self.mutation_rate:
            mutated: str = random.choice(mutations)(prompt)
            return mutated
        return prompt

    def _crossover(self, parents: list[str]) -> list[str]:
        """Combina prompts padres."""
        offspring = []
        for i in range(0, len(parents), 2):
            if i + 1 < len(parents):
                parent_a = parents[i]
                parent_b = parents[i + 1]
                split_a = len(parent_a) // 2
                split_b = len(parent_b) // 2
                child = parent_a[:split_a] + "\n" + parent_b[split_b:]
                offspring.append(child)
        return offspring if offspring else parents

    def _mutate_population(self, population: list[str]) -> list[str]:
        """Aplica mutaciones a toda la población."""
        return [self._mutate_prompt(p) for p in population]

    def _select_best(self, population: list[str], fitness: list[float], keep: int = 3) -> list[str]:
        """Selecciona los mejores."""
        paired = list(zip(fitness, population))
        paired.sort(reverse=True)
        return [p for _, p in paired[:keep]]

    def _quick_fitness(self, prompt: str, task_history: list[dict]) -> float:
        """Evaluación rápida de fitness."""
        score = 0.0
        if "step by step" in prompt.lower():
            score += 1.0
        if "verify" in prompt.lower():
            score += 0.5
        if "example" in prompt.lower():
            score += 0.5
        if len(prompt) > 100:
            score += 0.5
        return score

    def get_evolution_stats(self) -> dict:
        """Retorna estadísticas de evolución."""
        return {
            "generation": self.generation,
            "fitness_history": self.fitness_history[-10:],
            "population_size": self.population_size,
            "mutation_rate": self.mutation_rate,
        }

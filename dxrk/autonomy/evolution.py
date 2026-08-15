# SPDX-License-Identifier: MIT
"""Evolution: genetic prompt optimization"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .learner import Learner
from .metrics import IQMetrics

logger = logging.getLogger(__name__)

_BASE_PROMPTS = [
    "You are Dxrk, an autonomous AI coding agent. Be concise and correct.",
    "You are Dxrk, an expert software engineer. Write clean, tested code.",
    "You are Dxrk, a senior developer. Prioritize readability and maintainability.",
    "You are Dxrk. Think step by step, verify your work, and fix errors.",
    "You are Dxrk, a coding agent. Write idiomatic code with proper error handling.",
]

_POP_CAP = 50


@dataclass
class Genome:
    id: str = ""
    prompt: str = ""
    strategy: str = ""
    score: float = 0.0
    generations: int = 0
    created: str = ""
    parent_id: str = ""
    mutations: int = 0


class EvolutionEngine:
    """Evolves base prompts via crossover and mutation, tracking a population."""

    def __init__(self, path: str, learner: Learner, metrics: IQMetrics) -> None:
        self.mu = threading.Lock()
        self.path = path
        self._population: list[Genome] = []
        self.generation = 0
        self.mutation_rate = 0.3
        self.crossover_rate = 0.7
        self.learner = learner
        self.metrics = metrics
        self._load()
        if not self._population:
            self._seed()

    def _seed(self) -> None:
        now = datetime.now(UTC).isoformat()
        for i, prompt in enumerate(_BASE_PROMPTS):
            self._population.append(
                Genome(
                    id=f"gen-base-{i}",
                    prompt=prompt,
                    strategy="base",
                    score=50.0,
                    created=now,
                )
            )
        self._save()

    def evolve(self) -> Genome:
        with self.mu:
            self.generation += 1
            ranked = self._evaluate_population()
            self._population = ranked
            self._select_elite()
            children = self._reproduce()
            self._population.extend(children)
            self._population = self._population[:_POP_CAP]
            self._mutate()
            self._save()
            best = self._best_genome()
        self.metrics.record_evolution()
        return best

    def _evaluate_population(self) -> list[Genome]:
        return sorted(self._population, key=lambda g: g.score, reverse=True)

    def _select_elite(self) -> None:
        keep = len(self._population) // 2
        if keep < 2:
            keep = 2
        self._population = self._population[:keep]

    def _reproduce(self) -> list[Genome]:
        children: list[Genome] = []
        for _ in range(10):
            p1 = self._tournament_select()
            p2 = self._tournament_select()
            guard = 0
            while p1.id == p2.id and guard < 10:
                p2 = self._tournament_select()
                guard += 1
            child = Genome(
                id=f"gen-{self.generation}-{_rand_bytes(4).hex()}",
                generations=self.generation,
                created=datetime.now(UTC).isoformat(),
                parent_id=p1.id,
                strategy=f"cross_{p1.id[:8]}_{p2.id[:8]}",
            )
            child.prompt = self._crossover(p1.prompt, p2.prompt)
            child.score = (p1.score + p2.score) / 2
            children.append(child)
        return children

    def _tournament_select(self) -> Genome:
        k = min(3, len(self._population))
        indices = random.sample(range(len(self._population)), k)
        best = self._population[indices[0]]
        for idx in indices[1:]:
            if self._population[idx].score > best.score:
                best = self._population[idx]
        return best

    def _crossover(self, a: str, b: str) -> str:
        if len(a) < 3 or len(b) < 3:
            return a
        if random.randint(0, 99) > self.crossover_rate * 100:
            return a
        p1 = random.randint(1, len(a) - 2)
        p2 = random.randint(1, len(b) - 2)
        result = a[:p1] + b[p2:]
        if len(result) < 10:
            return a
        return result

    def _mutate(self) -> None:
        for genome in self._population:
            if random.randint(0, 99) > self.mutation_rate * 100:
                continue
            prompt = genome.prompt
            if len(prompt) < 5:
                continue
            pos = random.randrange(len(prompt))
            mutagen = random.randint(0, 2)
            if mutagen == 0:
                prompt = prompt[:pos] + prompt[pos + 1 :]
            elif mutagen == 1:
                prompt = prompt[:pos] + random.choice("!.,?") + prompt[pos:]
            elif pos + 1 < len(prompt):
                chars = list(prompt)
                chars[pos], chars[pos + 1] = chars[pos + 1], chars[pos]
                prompt = "".join(chars)
            genome.prompt = prompt
            genome.mutations += 1

    def _best_genome(self) -> Genome:
        if not self._population:
            return Genome()
        best = self._population[0]
        for genome in self._population[1:]:
            if genome.score > best.score:
                best = genome
        return best

    def best_genome(self) -> Genome:
        with self.mu:
            return self._best_genome()

    def update_score(self, genome_id: str, score: float) -> None:
        with self.mu:
            for genome in self._population:
                if genome.id == genome_id:
                    genome.score = (genome.score + score) / 2
                    return

    def population(self) -> list[Genome]:
        with self.mu:
            return list(self._population)

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except OSError:
            return
        except json.JSONDecodeError as exc:
            logger.info("[evolution] failed to unmarshal store: %s", exc)
            return
        self.generation = data.get("generation", 0)
        self._population = [Genome(**g) for g in data.get("population", [])]

    def _save(self) -> None:
        store = {
            "generation": self.generation,
            "population": [asdict(g) for g in self._population],
        }
        try:
            data = json.dumps(store, indent=2)
        except TypeError as exc:
            logger.info("[evolution] failed to marshal store: %s", exc)
            return
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, mode=0o750, exist_ok=True)
        except OSError as exc:
            logger.info("[evolution] failed to create dir: %s", exc)
            return
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
        except OSError as exc:
            logger.info("[evolution] failed to write file: %s", exc)


def _rand_bytes(n: int) -> bytes:
    return os.urandom(n)


def NewEvolutionEngine(
    path: str, learner: Learner, metrics: IQMetrics
) -> EvolutionEngine:
    return EvolutionEngine(path, learner, metrics)

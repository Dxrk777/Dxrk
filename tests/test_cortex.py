"""Tests para dxrk/memory/cortex/ (motor cognitivo v3.0).

Aislamiento: cada test que toca SQLite usa tmp_path (nunca ~/.dxrk real).
Sin red, sin sleeps, sin loops infinitos: se prueban _think_cycle,
dream_cycle y metodos puros en lugar de start_cognitive_loop /
schedule_dreaming / start_background_thinking.
"""

import math
import random

from dxrk.memory.cortex.autonomous_thinking import AutonomousThinking
from dxrk.memory.cortex.collective_intelligence import CollectiveIntelligence
from dxrk.memory.cortex.contribution_weighting import ContributionWeighting
from dxrk.memory.cortex.core import DxrkMemoryCognitiveCore
from dxrk.memory.cortex.dreaming_mode import DreamingMode
from dxrk.memory.cortex.genetic_prompts import GeneticPromptEvolution
from dxrk.memory.cortex.iq_database import IQDatabase
from dxrk.memory.cortex.iq_engine import DxrkIQEngine
from dxrk.memory.cortex.meta_learning import MetaLearningEngine
from dxrk.memory.cortex.network_effect import NetworkEffect
from dxrk.memory.cortex.self_awareness import SelfAwarenessLayer
from dxrk.memory.cortex.synapse import SynapseTokenSaver
from dxrk.memory.cortex.synaptic_plasticity import SynapticPlasticity
from dxrk.memory.cortex.usage_iq import UsageBasedIQ


def _engine(tmp_path, name="cortex.db"):
    return DxrkIQEngine(db_path=str(tmp_path / name))


# ---------------------------------------------------------------------------
# DxrkIQEngine
# ---------------------------------------------------------------------------


def test_iq_fresh_db_does_not_crash(tmp_path):
    eng = _engine(tmp_path)
    data = eng.measure_current_iq()
    assert set(data["dimensions"]) == set(DxrkIQEngine.DIMENSIONS)
    assert data["total_iq"] == 110.0
    eng.close()


def test_iq_measure_all_dimensions_start_at_100(tmp_path):
    eng = _engine(tmp_path)
    data = eng.measure_current_iq()
    assert all(score == 100.0 for score in data["dimensions"].values())
    assert "measured_at" in data
    eng.close()


def test_iq_record_then_latest_score(tmp_path):
    eng = _engine(tmp_path)
    data = eng.measure_current_iq()
    eng.record_iq(data)
    assert eng._get_latest_score("logical_reasoning") == 100.0
    eng.close()


def test_iq_record_updates_global_stats(tmp_path):
    eng = _engine(tmp_path)
    data = eng.measure_current_iq()
    eng.record_iq(data)
    cur = eng.conn.execute("SELECT total_iq FROM iq_global_stats WHERE id = 1").fetchone()
    assert float(cur[0]) == data["total_iq"]
    eng.close()


def test_iq_evolution_trend_empty_is_zero(tmp_path):
    eng = _engine(tmp_path)
    trends = eng.calculate_evolution_trend()
    assert set(trends) == set(DxrkIQEngine.DIMENSIONS)
    assert all(v == 0.0 for v in trends.values())
    eng.close()


def test_iq_evolution_trend_positive_after_growth(tmp_path):
    eng = _engine(tmp_path)
    first = eng.measure_current_iq()
    eng.record_iq(first)
    grown = {"dimensions": {d: s + 10.0 for d, s in first["dimensions"].items()}, "total_iq": first["total_iq"] + 10}
    eng.record_iq(grown)
    trends = eng.calculate_evolution_trend()
    assert all(v > 0 for v in trends.values())
    eng.close()


def test_iq_projection_covers_all_dimensions(tmp_path):
    eng = _engine(tmp_path)
    proj = eng.project_future_iq(days_ahead=30)
    assert set(proj) == set(DxrkIQEngine.DIMENSIONS)
    assert all(isinstance(v, float) for v in proj.values())
    eng.close()


def test_iq_weakest_strongest_counts(tmp_path):
    eng = _engine(tmp_path)
    assert len(eng.get_weakest_dimensions(count=3)) == 3
    assert len(eng.get_strongest_dimensions(count=2)) == 2
    eng.close()


def test_iq_skill_boosts_strongest_dimension(tmp_path):
    eng = _engine(tmp_path)
    eng.add_skill("py-master", "coding_mastery", mastery_level=5.0)
    assert eng.get_strongest_dimensions(count=1) == ["coding_mastery"]
    assert "coding_mastery" not in eng.get_weakest_dimensions(count=2)
    eng.close()


def test_iq_add_skill_repeat_increments_count(tmp_path):
    eng = _engine(tmp_path)
    eng.add_skill("s1", "logical_reasoning", 1.0)
    eng.add_skill("s2", "logical_reasoning", 2.0)
    assert eng.get_mastered_skills_count() == 2
    eng.add_skill("s1", "logical_reasoning", 1.0)
    assert eng.get_mastered_skills_count() == 2
    row = eng.conn.execute("SELECT usage_count FROM iq_skills_mastered WHERE skill_id = 's1'").fetchone()
    assert int(row[0]) == 2
    eng.close()


def test_iq_learning_velocity_is_float(tmp_path):
    eng = _engine(tmp_path)
    assert isinstance(eng.get_learning_velocity(), float)
    eng.close()


def test_iq_velocity_bonus_zero_without_history(tmp_path):
    eng = _engine(tmp_path)
    assert eng._calculate_velocity_bonus("logical_reasoning") == 0.0
    eng.close()


# ---------------------------------------------------------------------------
# UsageBasedIQ
# ---------------------------------------------------------------------------


def test_usage_record_returns_positive_gain(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    gained = usage.record_interaction("write_file", complexity_score=1.0)
    assert gained == round(0.5 * 1.0 * 1.0 * 5.0, 3)
    eng.close()


def test_usage_unknown_type_uses_default_weight(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    assert usage.record_interaction("invented_type_xyz") == round(0.5 * 1.0 * 1.0 * 5.0, 3)
    eng.close()


def test_usage_failure_pays_less_than_success(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    ok_gain = usage.record_interaction("debug_error", details={"case": "ok"})
    fail_gain = usage.record_interaction("debug_error", success=False, details={"case": "fail"})
    assert fail_gain < ok_gain
    eng.close()


def test_usage_novelty_bonus_only_first_time(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    first = usage.record_interaction("read_file", details={"f": "a.py"})
    second = usage.record_interaction("read_file", details={"f": "a.py"})
    assert first == round(0.1 * 5.0, 3)
    assert second == round(0.1 * 1.0, 3)
    eng.close()


def test_usage_complexity_is_clamped(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    huge = usage.record_interaction("read_file", complexity_score=99.0, details={"c": 1})
    tiny = usage.record_interaction("read_file", complexity_score=0.01, details={"c": 2})
    assert huge == round(0.1 * 3.0 * 5.0, 3)
    assert tiny == round(0.1 * 0.5 * 5.0, 3)
    eng.close()


def test_usage_calculate_current_iq_shape(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    usage.record_interaction("write_file")
    result = usage.calculate_current_iq()
    assert set(result) == {"total_iq", "interactions_count", "iq_gained", "diversity_score", "complexity_score"}
    assert result["interactions_count"] == 1
    assert result["total_iq"] > 100.0
    eng.close()


def test_usage_history_returns_records(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    usage.record_interaction("write_file", domain="python")
    history = usage.get_interaction_history()
    assert len(history) == 1
    assert history[0]["interaction_type"] == "write_file"
    eng.close()


def test_usage_history_limit_respected(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    for i in range(3):
        usage.record_interaction("read_file", details={"f": f"f{i}.py"})
    assert len(usage.get_interaction_history(limit=2)) == 2
    eng.close()


def test_usage_totals_accumulate(tmp_path):
    eng = _engine(tmp_path)
    usage = UsageBasedIQ(eng.conn)
    usage.record_interaction("read_file", details={"n": 1})
    usage.record_interaction("read_file", details={"n": 2})
    assert usage.total_interactions == 2
    assert usage.total_iq_gained > 0
    eng.close()


# ---------------------------------------------------------------------------
# GeneticPromptEvolution
# ---------------------------------------------------------------------------


async def test_genetic_evolve_one_generation():
    random.seed(1234)
    evo = GeneticPromptEvolution(population_size=4, mutation_rate=0.5)
    out = await evo.evolve_system_prompt("You are a helper.", task_history=[])
    assert isinstance(out, str) and len(out) > 0
    assert evo.generation == 1
    assert len(evo.fitness_history) == 1


async def test_genetic_evolve_two_generations():
    random.seed(7)
    evo = GeneticPromptEvolution(population_size=4, mutation_rate=0.5)
    await evo.evolve_system_prompt("You are a helper.", task_history=[])
    out = await evo.evolve_system_prompt("You are a helper.", task_history=[])
    assert evo.generation == 2
    assert isinstance(out, str) and len(out) > 0
    gens = [h["generation"] for h in evo.fitness_history]
    assert gens == [1, 2]


async def test_genetic_evolve_with_custom_evaluate_fn():
    random.seed(3)
    evo = GeneticPromptEvolution(population_size=4, mutation_rate=0.5)

    async def evaluate(prompt, history):
        return float(len(prompt))

    out = await evo.evolve_system_prompt("You are a helper.", task_history=[], evaluate_fn=evaluate)
    assert isinstance(out, str)
    assert evo.fitness_history[0]["best_fitness"] >= evo.fitness_history[0]["avg_fitness"]


def test_genetic_stats_shape():
    evo = GeneticPromptEvolution(population_size=6, mutation_rate=0.3)
    stats = evo.get_evolution_stats()
    assert stats == {"generation": 0, "fitness_history": [], "population_size": 6, "mutation_rate": 0.3}


def test_genetic_select_best_order():
    evo = GeneticPromptEvolution()
    best = evo._select_best(["a", "bb", "ccc"], [1.0, 3.0, 2.0], keep=2)
    assert best == ["bb", "ccc"]


def test_genetic_crossover_combines_parents():
    evo = GeneticPromptEvolution()
    kids = evo._crossover(["A" * 10, "B" * 10])
    assert len(kids) == 1
    assert kids[0] == "A" * 5 + "\n" + "B" * 5


def test_genetic_crossover_single_parent_passthrough():
    evo = GeneticPromptEvolution()
    assert evo._crossover(["solo"]) == ["solo"]


def test_genetic_quick_fitness_scores():
    evo = GeneticPromptEvolution()
    rich = "Verify step by step with example. " + "x" * 100
    assert evo._quick_fitness(rich, []) == 2.5
    assert evo._quick_fitness("hi", []) == 0.0


def test_genetic_mutate_no_rate_keeps_prompt():
    evo = GeneticPromptEvolution(mutation_rate=0.0)
    assert evo._mutate_prompt("You are a helper.") == "You are a helper."


def test_genetic_mutate_full_rate_changes_prompt():
    random.seed(0)
    evo = GeneticPromptEvolution(mutation_rate=1.0)
    assert evo._mutate_prompt("You are a helper.") != "You are a helper."


def test_genetic_mutate_population_same_size():
    random.seed(11)
    evo = GeneticPromptEvolution(mutation_rate=0.5)
    pop = ["p1", "p2", "p3"]
    assert len(evo._mutate_population(pop)) == 3


# ---------------------------------------------------------------------------
# MetaLearningEngine
# ---------------------------------------------------------------------------


def test_meta_record_attempt():
    meta = MetaLearningEngine()
    meta.record_learning_attempt("active_recall", success_rate=0.9, time_spent_minutes=30.0, topic="python")
    assert meta.total_attempts == 1
    assert meta.strategy_attempts["active_recall"] == 1
    assert meta.strategy_effectiveness["active_recall"] == (0.9 * 0.5 + 0.1 * 0.9)
    assert len(meta.learning_history) == 1


def test_meta_unknown_strategy_registered():
    meta = MetaLearningEngine()
    meta.record_learning_attempt("custom_xyz", success_rate=0.7, time_spent_minutes=10.0)
    assert "custom_xyz" in meta.strategy_effectiveness
    assert meta.strategy_attempts["custom_xyz"] == 1


def test_meta_optimal_prefers_untried_strategy():
    meta = MetaLearningEngine()
    assert meta.get_optimal_learning_strategy() == "repetition_spaced"
    for _ in range(5):
        meta.record_learning_attempt("repetition_spaced", success_rate=1.0, time_spent_minutes=5.0)
    assert meta.get_optimal_learning_strategy() == "active_recall"


async def test_meta_optimize_pipeline_rewards_success_penalizes_failure():
    meta = MetaLearningEngine()
    before_ok = meta.strategy_effectiveness["active_recall"]
    before_bad = meta.strategy_effectiveness["chunking"]
    await meta.optimize_learning_pipeline(
        [
            {"strategy": "active_recall", "success_rate": 0.95},
            {"strategy": "chunking", "success_rate": 0.1},
        ]
    )
    assert meta.strategy_effectiveness["active_recall"] > before_ok
    assert meta.strategy_effectiveness["chunking"] < before_bad


def test_meta_rankings_sorted_desc():
    meta = MetaLearningEngine()
    meta.record_learning_attempt("chunking", success_rate=1.0, time_spent_minutes=5.0)
    rankings = meta.get_strategy_rankings()
    assert len(rankings) == len(MetaLearningEngine.LEARNING_STRATEGIES)
    scores = [r["effectiveness"] for r in rankings]
    assert scores == sorted(scores, reverse=True)
    assert rankings[0]["strategy"] == "chunking"


def test_meta_stats_shape():
    meta = MetaLearningEngine()
    stats = meta.get_meta_learning_stats()
    assert set(stats) == {"total_attempts", "best_strategy", "strategy_rankings", "learning_velocity"}
    assert len(stats["strategy_rankings"]) == 5


def test_meta_velocity_needs_two_samples():
    meta = MetaLearningEngine()
    assert meta._calculate_learning_velocity() == 0.0
    meta.record_learning_attempt("chunking", success_rate=0.6, time_spent_minutes=5.0)
    assert meta._calculate_learning_velocity() == 0.0
    meta.record_learning_attempt("chunking", success_rate=1.0, time_spent_minutes=5.0)
    assert meta._calculate_learning_velocity() == 0.8


# ---------------------------------------------------------------------------
# DreamingMode
# ---------------------------------------------------------------------------


class _FakeDreamKG:
    def __init__(self, concepts):
        self._concepts = concepts
        self.created = []
        self.consolidated = False

    def get_random_concepts(self, count):
        return self._concepts[:count]

    def are_connected(self, a, b):
        return False

    def create_connection(self, a, b, weight=0.1):
        self.created.append((a, b, weight))

    def consolidate_dream_connections(self):
        self.consolidated = True


class _RaisingKG:
    def get_random_concepts(self, count):
        raise RuntimeError("boom")

    def are_connected(self, a, b):
        raise RuntimeError("boom")

    def create_connection(self, a, b, weight=0.1):
        raise RuntimeError("boom")

    def consolidate_dream_connections(self):
        raise RuntimeError("boom")


async def test_dream_cycle_generates_pairwise_insights():
    random.seed(1)
    kg = _FakeDreamKG(["alpha", "beta", "gamma"])
    dreamer = DreamingMode(knowledge_graph=kg)
    insights = await dreamer.dream_cycle()
    assert len(insights) == 3
    assert all(isinstance(i, str) for i in insights)
    assert dreamer.is_dreaming is False
    assert len(kg.created) == 3
    assert kg.consolidated is True
    assert len(dreamer.dream_history) == 1


async def test_dream_cycle_few_concepts_returns_empty():
    dreamer = DreamingMode(knowledge_graph=_FakeDreamKG(["lonely"]))
    assert await dreamer.dream_cycle() == []


async def test_dream_cycle_without_kg_uses_defaults():
    random.seed(2)
    dreamer = DreamingMode()
    insights = await dreamer.dream_cycle()
    assert len(insights) == 45
    assert dreamer.is_dreaming is False


async def test_dream_cycle_survives_broken_kg():
    random.seed(4)
    dreamer = DreamingMode(knowledge_graph=_RaisingKG())
    insights = await dreamer.dream_cycle()
    assert len(insights) == 45
    assert dreamer.is_dreaming is False


def test_dream_stats_empty():
    dreamer = DreamingMode()
    stats = dreamer.get_dream_stats()
    assert stats == {
        "total_dreams": 0,
        "total_insights": 0,
        "avg_insights_per_dream": 0,
        "is_currently_dreaming": False,
    }


async def test_dream_stats_after_cycle():
    random.seed(5)
    dreamer = DreamingMode(knowledge_graph=_FakeDreamKG(["a", "b"]))
    await dreamer.dream_cycle()
    stats = dreamer.get_dream_stats()
    assert stats["total_dreams"] == 1
    assert stats["total_insights"] == 1
    assert stats["avg_insights_per_dream"] == 1.0


# ---------------------------------------------------------------------------
# AutonomousThinking
# ---------------------------------------------------------------------------


class _FakeMemory:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_unresolved_tasks(self, limit=5):
        return self._tasks[:limit]


class _BrokenMemory:
    def get_unresolved_tasks(self, limit=5):
        raise RuntimeError("boom")


async def test_think_cycle_without_deps_logs_empty_thought():
    thinker = AutonomousThinking()
    await thinker._think_cycle()
    assert len(thinker.thought_log) == 1
    thought = thinker.thought_log[0]
    assert thought["reflections"] == [] and thought["plans"] == [] and thought["insights"] == []
    assert "timestamp" in thought


async def test_think_cycle_reflects_on_unsolved():
    mem = _FakeMemory([{"id": 1, "title": "fix flaky test"}])
    thinker = AutonomousThinking(memory=mem)
    await thinker._think_cycle()
    reflections = thinker.thought_log[0]["reflections"]
    assert len(reflections) == 1
    assert reflections[0]["confidence"] == 0.7
    assert len(reflections[0]["potential_solutions"]) == 3


async def test_think_cycle_survives_broken_memory():
    thinker = AutonomousThinking(memory=_BrokenMemory())
    await thinker._think_cycle()
    assert thinker.thought_log[0]["reflections"] == []


async def test_think_cycle_plans_weak_areas(tmp_path):
    eng = _engine(tmp_path)
    thinker = AutonomousThinking(iq_engine=eng)
    await thinker._think_cycle()
    plans = thinker.thought_log[0]["plans"]
    assert len(plans) == 2
    assert all(p["priority"] == "high" for p in plans)
    eng.close()


async def test_plan_without_iq_is_empty():
    thinker = AutonomousThinking()
    assert await thinker._plan_future_strategies() == []


async def test_generate_solutions_shape():
    thinker = AutonomousThinking()
    solutions = await thinker._generate_solutions({"title": "x"})
    assert len(solutions) == 3
    assert all(isinstance(s, str) for s in solutions)


async def test_spontaneous_insights_empty_by_default():
    thinker = AutonomousThinking()
    assert await thinker._generate_spontaneous_insights() == []


def test_stop_thinking_and_stats():
    thinker = AutonomousThinking()
    assert thinker.thinking_enabled is True
    thinker.stop_thinking()
    assert thinker.thinking_enabled is False
    stats = thinker.get_thinking_stats()
    assert stats == {"total_thought_cycles": 0, "total_insights": 0, "total_reflections": 0, "is_thinking": False}


# ---------------------------------------------------------------------------
# SelfAwarenessLayer
# ---------------------------------------------------------------------------


class _StubIQ:
    def __init__(self, dims):
        self._dims = dict(dims)

    def measure_current_iq(self):
        return {"dimensions": dict(self._dims), "total_iq": 120.0}

    def calculate_evolution_trend(self):
        return {"logical_reasoning": 1.0}

    def get_learning_velocity(self):
        return 0.5


class _GapKG:
    def find_isolated_concepts(self, threshold=2):
        return ["quantum", "bio"]


class _BrokenGapKG:
    def find_isolated_concepts(self, threshold=2):
        raise RuntimeError("boom")


def test_self_report_without_iq():
    layer = SelfAwarenessLayer()
    report = layer.generate_self_report()
    assert report["total_iq"] == 100
    assert report["iq_vector"] == {}
    assert report["strengths"] == [] and report["weaknesses"] == []
    assert report["knowledge_gaps"] == [] and report["learning_plan"] == []
    assert report["self_assessment"] == "I am DxrkMemory. My current IQ is 100.0."
    assert "generated_at" in report


def test_self_report_with_real_iq(tmp_path):
    eng = _engine(tmp_path)
    layer = SelfAwarenessLayer(iq_engine=eng)
    report = layer.generate_self_report()
    assert set(report["iq_vector"]) == set(DxrkIQEngine.DIMENSIONS)
    assert "Strongest" in report["self_assessment"]
    assert "Weakest" in report["self_assessment"]
    assert set(report["evolution_trend"]) == set(DxrkIQEngine.DIMENSIONS)
    eng.close()


def test_self_report_strengths_weaknesses_thresholds():
    layer = SelfAwarenessLayer(iq_engine=_StubIQ({"x": 140.0, "y": 90.0}))
    report = layer.generate_self_report()
    assert report["strengths"] == ["x"]
    assert report["weaknesses"] == ["y"]
    assert any(p["type"] == "improve_weakness" and p["target"] == "y" for p in report["learning_plan"])


def test_self_report_knowledge_gaps_fill_plan():
    layer = SelfAwarenessLayer(iq_engine=_StubIQ({"x": 110.0}), knowledge_graph=_GapKG())
    report = layer.generate_self_report()
    assert report["knowledge_gaps"] == ["quantum", "bio"]
    assert any(p["type"] == "fill_knowledge_gap" for p in report["learning_plan"])


def test_self_report_broken_kg_gives_no_gaps():
    layer = SelfAwarenessLayer(knowledge_graph=_BrokenGapKG())
    assert layer._identify_knowledge_gaps() == []


def test_self_assessment_text_with_velocity():
    layer = SelfAwarenessLayer(iq_engine=_StubIQ({"x": 140.0, "y": 90.0}))
    text = layer._generate_self_assessment_text({"dimensions": {"x": 140.0, "y": 90.0}, "total_iq": 120.0})
    assert "120.0" in text and "x" in text and "0.50" in text


# ---------------------------------------------------------------------------
# SynapticPlasticity
# ---------------------------------------------------------------------------


class _FakeSynKG:
    def __init__(self):
        self.strengthened = []
        self.decay_calls = []
        self.conns = {"b": 0.9, "c": 0.4}

    def strengthen_connection(self, a, b, delta):
        self.strengthened.append((a, b, delta))

    def apply_decay(self, factor):
        self.decay_calls.append(factor)

    def get_strongest_connections(self, concept, limit=5):
        return list(self.conns)[:limit]

    def get_total_connections(self):
        return 7

    def get_avg_connection_strength(self):
        return 0.65


class _BrokenSynKG:
    def strengthen_connection(self, a, b, delta):
        raise RuntimeError("boom")

    def apply_decay(self, factor):
        raise RuntimeError("boom")

    def get_strongest_connections(self, concept, limit=5):
        raise RuntimeError("boom")

    def get_total_connections(self):
        raise RuntimeError("boom")

    def get_avg_connection_strength(self):
        raise RuntimeError("boom")


def test_synaptic_update_strengthens_pairs_and_decays():
    kg = _FakeSynKG()
    syn = SynapticPlasticity(knowledge_graph=kg)
    syn.update_synaptic_weights(["a", "b", "c"])
    assert len(kg.strengthened) == 3
    assert all(d == 0.1 for _, _, d in kg.strengthened)
    assert kg.decay_calls == [0.995]


def test_synaptic_update_ignores_short_context():
    kg = _FakeSynKG()
    syn = SynapticPlasticity(knowledge_graph=kg)
    syn.update_synaptic_weights([])
    syn.update_synaptic_weights(["solo"])
    assert kg.strengthened == [] and kg.decay_calls == []


def test_synaptic_update_survives_broken_kg():
    syn = SynapticPlasticity(knowledge_graph=_BrokenSynKG())
    syn.update_synaptic_weights(["a", "b"])


def test_synaptic_associative_thoughts():
    syn = SynapticPlasticity(knowledge_graph=_FakeSynKG())
    assert syn.get_associative_thoughts("a", limit=1) == ["b"]
    assert SynapticPlasticity().get_associative_thoughts("a") == []
    assert SynapticPlasticity(knowledge_graph=_BrokenSynKG()).get_associative_thoughts("a") == []


def test_synaptic_stats_with_kg():
    syn = SynapticPlasticity(knowledge_graph=_FakeSynKG())
    stats = syn.get_synaptic_stats()
    assert stats == {
        "decay_factor": 0.995,
        "strengthen_delta": 0.1,
        "total_connections": 7,
        "avg_connection_strength": 0.65,
    }


def test_synaptic_stats_without_kg():
    stats = SynapticPlasticity().get_synaptic_stats()
    assert stats["total_connections"] == 0
    assert stats["avg_connection_strength"] == 0.0


# ---------------------------------------------------------------------------
# NetworkEffect
# ---------------------------------------------------------------------------


def test_network_multiplier_scale():
    net = NetworkEffect()
    assert net.calculate_network_multiplier(active_users=1) == 1.0
    assert net.calculate_network_multiplier(active_users=10) == 2.0
    assert net.calculate_network_multiplier(active_users=100) == 3.0
    assert net.calculate_network_multiplier(active_users=50) == 1.0 + math.log10(50)


def test_network_add_user():
    net = NetworkEffect()
    net.add_user()
    assert net.user_count == 2
    assert net.calculate_network_multiplier() == 1.0 + math.log10(2)


def test_network_growth_rate_positive_with_diversity():
    net = NetworkEffect()
    net.user_count = 10
    for _ in range(50):
        net.add_interaction(domain="python")
    for _ in range(50):
        net.add_interaction(domain="web")
    assert net.calculate_iq_growth_rate() > 0


def test_network_growth_rate_zero_users():
    net = NetworkEffect()
    net.user_count = 0
    assert net.calculate_iq_growth_rate() == 0.0


def test_network_diversity_empty_and_single():
    net = NetworkEffect()
    assert net._calculate_domain_diversity() == 0.0
    net.add_interaction(domain="only")
    assert net._calculate_domain_diversity() == 0.0
    net.add_interaction(domain="other")
    assert net._calculate_domain_diversity() == 1.0


def test_network_stats_shape():
    net = NetworkEffect()
    net.add_interaction(domain="python")
    stats = net.get_network_stats()
    assert set(stats) == {
        "user_count",
        "total_interactions",
        "network_multiplier",
        "domain_diversity",
        "iq_growth_rate",
        "active_domains",
    }
    assert stats["total_interactions"] == 1 and stats["active_domains"] == 1


# ---------------------------------------------------------------------------
# ContributionWeighting
# ---------------------------------------------------------------------------


def test_weighting_read_file_baseline():
    w = ContributionWeighting()
    assert w.calculate_contribution_score("read_file") == 0.1


def test_weighting_unknown_task_defaults_to_one():
    w = ContributionWeighting()
    assert w.calculate_contribution_score("invented_task") == round(1.0 * (1 + 1.0 / 60), 2)


def test_weighting_errors_fixed_boost_impact():
    w = ContributionWeighting()
    fixed = w.calculate_contribution_score("debug_simple", error_count_before=4, error_count_after=1)
    unfixed = w.calculate_contribution_score("debug_simple", error_count_before=4, error_count_after=4)
    assert fixed == round(3.0 * (1 + 1.0 / 60) * 2.5, 2)
    assert fixed > unfixed


def test_weighting_novelty_and_code_multipliers():
    w = ContributionWeighting()
    score = w.calculate_contribution_score(
        "novel_solution", time_spent_minutes=60, lines_of_code=200, novelty_score=1.0
    )
    assert score == round(50.0 * 2.0 * 3.0 * 1.0 * 2.0, 2)


def test_weighting_tiers():
    w = ContributionWeighting()
    assert w.get_contribution_tier(60.0) == "LEGENDARY"
    assert w.get_contribution_tier(50.0) == "LEGENDARY"
    assert w.get_contribution_tier(25.0) == "EXPERT"
    assert w.get_contribution_tier(10.0) == "ADVANCED"
    assert w.get_contribution_tier(5.0) == "INTERMEDIATE"
    assert w.get_contribution_tier(4.99) == "BASIC"


def test_weighting_base_scores_cover_known_tasks():
    assert set(ContributionWeighting.BASE_SCORES) >= {"read_file", "novel_solution", "architecture_design"}


# ---------------------------------------------------------------------------
# CollectiveIntelligence
# ---------------------------------------------------------------------------


def test_collective_create_insight_deterministic_hash():
    col = CollectiveIntelligence()
    a = col.create_insight("pattern", "same-data", 0.9, 2.0, "python")
    b = col.create_insight("pattern", "same-data", 0.9, 2.0, "python")
    c = col.create_insight("pattern", "other-data", 0.9, 2.0, "python")
    assert a.pattern_hash == b.pattern_hash
    assert a.pattern_hash != c.pattern_hash
    assert len(a.pattern_hash) == 16
    assert a.contributor_count == 1


def test_collective_stats_after_insights():
    col = CollectiveIntelligence()
    col.add_local_insight(col.create_insight("t", "d1", 0.8, 1.0, "python"))
    col.add_local_insight(col.create_insight("t", "d2", 0.7, 1.0, "web"))
    stats = col.get_collective_stats()
    assert stats["local_insights_count"] == 2
    assert set(stats["domains_covered"]) == {"python", "web"}
    assert stats["effective_iq"] == 100.0


def test_collective_empty_stats():
    stats = CollectiveIntelligence().get_collective_stats()
    assert stats["local_insights_count"] == 0
    assert stats["domains_covered"] == []
    assert stats["effective_iq"] == 100.0


def test_collective_network_multiplier():
    col = CollectiveIntelligence()
    assert col.calculate_network_multiplier(1) == 1.0
    assert col.calculate_network_multiplier(10) == 2.0
    assert col.calculate_network_multiplier(100) == 1.0 + math.log10(100)


# ---------------------------------------------------------------------------
# SynapseTokenSaver
# ---------------------------------------------------------------------------


def test_synapse_high_density_ok():
    saver = SynapseTokenSaver()
    out = saver.compress_to_high_density("read_file", {"file_path": "a.py"}, "line1\nline2")
    assert out == "[READ_FILE] a.py | lines:2 | status:ok"


def test_synapse_high_density_fail_and_fallback_path():
    saver = SynapseTokenSaver()
    out = saver.compress_to_high_density("read_file", {"path": "b.py"}, "Error: boom")
    assert out == "[READ_FILE] b.py | lines:1 | status:fail"
    assert saver.compress_to_high_density("read_file", {}, "ok") == "[READ_FILE] unknown | lines:1 | status:ok"


def test_synapse_observation_file_modification():
    saver = SynapseTokenSaver()
    obs = saver.compress_observation("write_file", {"file_path": "x.py"}, "success: file written")
    assert obs is not None
    assert obs["type"] == "file_modification"
    assert obs["entity"] == "x.py"
    assert obs["requires_llm"] is False


def test_synapse_observation_command_success():
    saver = SynapseTokenSaver()
    obs = saver.compress_observation("run_tests", {"command": "pytest -q"}, "12 passed")
    assert obs is not None
    assert obs["type"] == "command_success"
    assert obs["entity"] == "pytest -q"


def test_synapse_observation_generic_short():
    saver = SynapseTokenSaver()
    obs = saver.compress_observation("mystery_tool", {}, "tiny output")
    assert obs is not None
    assert obs["type"] == "generic_execution"
    assert obs["requires_llm"] is False


def test_synapse_observation_long_unknown_returns_none():
    saver = SynapseTokenSaver()
    assert saver.compress_observation("mystery_tool", {}, "z" * 500) is None


def test_synapse_observation_write_without_success_falls_through():
    saver = SynapseTokenSaver()
    obs = saver.compress_observation("write_file", {"file_path": "x.py"}, "writing...")
    assert obs is not None
    assert obs["type"] == "generic_execution"


# ---------------------------------------------------------------------------
# IQDatabase
# ---------------------------------------------------------------------------


def test_iqdb_record_and_get_user(tmp_path):
    db = IQDatabase(db_path=str(tmp_path / "iq.db"))
    db.record_interaction("u1", "write_file", 2.5, "python")
    assert db.get_user_iq("u1") == 102.5
    db.close()


def test_iqdb_unknown_user_defaults_100(tmp_path):
    db = IQDatabase(db_path=str(tmp_path / "iq.db"))
    assert db.get_user_iq("ghost") == 100.0
    db.close()


def test_iqdb_global_accumulates(tmp_path):
    db = IQDatabase(db_path=str(tmp_path / "iq.db"))
    assert db.get_global_iq() == 100.0
    db.record_interaction("u1", "write_file", 2.5, "python")
    db.record_interaction("u1", "debug_error", 1.5, "python")
    assert db.get_global_iq() == 104.0
    assert db.get_user_iq("u1") == 104.0
    db.close()


def test_iqdb_failed_interaction_still_recorded(tmp_path):
    db = IQDatabase(db_path=str(tmp_path / "iq.db"))
    db.record_interaction("u2", "run_tests", 1.0, "qa", success=False)
    row = db.conn.execute("SELECT success FROM interactions WHERE user_id = 'u2'").fetchone()
    assert int(row[0]) == 0
    db.close()


# ---------------------------------------------------------------------------
# DxrkMemoryCognitiveCore
# ---------------------------------------------------------------------------


def test_core_record_interaction_updates_network(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    gained = core.record_interaction("write_file", domain="python")
    assert gained == round(0.5 * 1.0 * 1.0 * 5.0, 3)
    assert core.network.total_interactions == 1
    assert core.network.domains == {"python": 1}
    core.iq_engine.close()


def test_core_record_interaction_default_domain(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    core.record_interaction("read_file")
    assert core.network.domains == {"general": 1}
    core.iq_engine.close()


def test_core_cognitive_status_shape(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    status = core.get_cognitive_status()
    assert set(status) == {
        "iq",
        "evolution_rate",
        "self_awareness",
        "learning_velocity",
        "skills_mastered",
        "network_stats",
        "dreaming_stats",
        "thinking_stats",
        "meta_learning_stats",
        "synaptic_stats",
        "collective_stats",
        "status_timestamp",
    }
    assert set(status["iq"]) == {"dimensions", "total_iq", "measured_at"}
    assert isinstance(status["self_awareness"], str) and len(status["self_awareness"]) > 0
    core.iq_engine.close()


def test_core_iq_report_shape(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    report = core.get_iq_report()
    assert set(report) == {
        "current_iq",
        "evolution_trend",
        "projection_1year",
        "weakest_dimensions",
        "strongest_dimensions",
        "learning_velocity",
    }
    assert len(report["weakest_dimensions"]) == 3
    assert len(report["strongest_dimensions"]) == 3
    assert set(report["projection_1year"]) == set(DxrkIQEngine.DIMENSIONS)
    core.iq_engine.close()


def test_core_stop_loop_disables_thinking(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    core.cognitive_loop_active = True
    core.stop_cognitive_loop()
    assert core.cognitive_loop_active is False
    assert core.autonomous_thinking.thinking_enabled is False
    core.iq_engine.close()


def test_core_subsystems_wired(tmp_path):
    core = DxrkMemoryCognitiveCore(db_path=str(tmp_path / "core.db"))
    assert isinstance(core.usage_iq, UsageBasedIQ)
    assert isinstance(core.genetic, GeneticPromptEvolution)
    assert isinstance(core.meta_learning, MetaLearningEngine)
    assert isinstance(core.dreaming, DreamingMode)
    assert isinstance(core.autonomous_thinking, AutonomousThinking)
    assert isinstance(core.self_awareness, SelfAwarenessLayer)
    assert isinstance(core.synaptic, SynapticPlasticity)
    assert isinstance(core.network, NetworkEffect)
    assert isinstance(core.weighting, ContributionWeighting)
    assert isinstance(core.collective, CollectiveIntelligence)
    core.iq_engine.close()

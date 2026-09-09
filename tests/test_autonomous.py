"""Tests para dxrk/memory/autonomous/ (7 motores de aprendizaje autonomo)."""

import random
import sys
import types

from dxrk.memory.autonomous.creative_synthesis import CreativeSynthesisEngine
from dxrk.memory.autonomous.deep_reflection import DeepReflectionEngine
from dxrk.memory.autonomous.expert_imitation import ExpertImitationEngine
from dxrk.memory.autonomous.omniscient_reader import OmniscientReader
from dxrk.memory.autonomous.self_assessment import SelfAssessmentEngine
from dxrk.memory.autonomous.self_experimentation import SelfExperimentationEngine
from dxrk.memory.autonomous.self_practice import SelfPracticeEngine


class FakeKnowledgeGraph:
    def __init__(self):
        self.concepts = []

    def add_concept(self, **kwargs):
        self.concepts.append(kwargs)


class FakeMemoryWithKG:
    def __init__(self):
        self.knowledge_graph = FakeKnowledgeGraph()


class FakeMemoryExplodingKG:
    class ExplodingKG:
        def add_concept(self, **kwargs):
            raise RuntimeError("boom")

    def __init__(self):
        self.knowledge_graph = FakeMemoryExplodingKG.ExplodingKG()


class FakeIQ:
    def __init__(self, weak=("area_a", "area_b")):
        self.weak = list(weak)
        self.skills = []

    def get_weakest_dimensions(self, count=3):
        return self.weak[:count]

    def add_skill(self, skill_id, dimension, mastery_level):
        self.skills.append({"skill_id": skill_id, "dimension": dimension, "mastery_level": mastery_level})


class FakeMemoryExperiences:
    def __init__(self, experiences):
        self._experiences = experiences

    def get_experiences_from_today(self):
        return self._experiences


class FakeMemoryRaising:
    def get_experiences_from_today(self):
        raise RuntimeError("boom")


def _install_fake_feedparser(monkeypatch, entries):
    module = types.ModuleType("feedparser")
    module.parse = lambda url: types.SimpleNamespace(entries=entries)
    monkeypatch.setitem(sys.modules, "feedparser", module)
    return module


# --- OmniscientReader ---


def test_reader_initial_stats():
    reader = OmniscientReader()
    assert reader.get_reading_stats() == {
        "total_reading_sessions": 0,
        "knowledge_gained_today": 0,
        "is_reading": False,
    }


def test_reader_get_sources():
    reader = OmniscientReader()
    sources = reader.get_sources()
    assert len(sources) == 5
    assert "http://arxiv.org/rss/cs.AI" in sources


def test_reader_calculate_relevance_default():
    assert OmniscientReader()._calculate_relevance({"title": "x", "summary": "y"}) == 0.5


async def test_reader_read_unknown_source_no_crash():
    reader = OmniscientReader()
    await reader._read_source("unknown_source_xyz", "http://example.com/feeds/x")
    assert reader.knowledge_gained_today == 0


async def test_reader_read_arxiv_source_delegates(monkeypatch):
    reader = OmniscientReader()
    calls = []
    orig = reader._read_arxiv

    async def fake(feed_url):
        calls.append(feed_url)
        await orig(feed_url)

    monkeypatch.delitem(sys.modules, "feedparser", raising=False)
    monkeypatch.setattr(reader, "_read_arxiv", fake)
    await reader._read_source("arxiv", "http://example.com/rss")
    assert calls == ["http://example.com/rss"]


async def test_reader_read_arxiv_high_relevance_stores(monkeypatch):
    reader = OmniscientReader(memory_engine=FakeMemoryWithKG())
    entries = [{"title": "Deep learning", "summary": "s" * 600}, {"title": "Other", "summary": "t" * 600}]
    _install_fake_feedparser(monkeypatch, entries)
    monkeypatch.setattr(reader, "_calculate_relevance", lambda content: 0.9)
    await reader._read_arxiv("http://arxiv.org/rss/cs.AI")
    assert reader.knowledge_gained_today == 2
    assert len(reader.memory.knowledge_graph.concepts) == 2
    assert reader.memory.knowledge_graph.concepts[0]["source"] == "arxiv"
    assert len(reader.memory.knowledge_graph.concepts[0]["definition"]) == 500


async def test_reader_read_arxiv_low_relevance_skips(monkeypatch):
    reader = OmniscientReader(memory_engine=FakeMemoryWithKG())
    _install_fake_feedparser(monkeypatch, [{"title": "t", "summary": "s"}])
    await reader._read_arxiv("http://arxiv.org/rss/cs.AI")
    assert reader.knowledge_gained_today == 0
    assert reader.memory.knowledge_graph.concepts == []


async def test_reader_read_arxiv_import_error_no_crash(monkeypatch):
    reader = OmniscientReader()
    monkeypatch.setitem(sys.modules, "feedparser", None)
    await reader._read_arxiv("http://arxiv.org/rss/cs.AI")
    assert reader.knowledge_gained_today == 0


def test_reader_store_knowledge_with_fake_memory():
    memory = FakeMemoryWithKG()
    reader = OmniscientReader(memory_engine=memory)
    reader._store_knowledge("concepto", "definicion", "arxiv", 0.9)
    assert len(memory.knowledge_graph.concepts) == 1
    assert memory.knowledge_graph.concepts[0]["concept"] == "concepto"


def test_reader_store_knowledge_no_memory_no_crash():
    OmniscientReader(memory_engine=None)._store_knowledge("c", "d", "arxiv", 0.9)
    OmniscientReader(memory_engine=object())._store_knowledge("c", "d", "arxiv", 0.9)
    OmniscientReader(memory_engine=FakeMemoryExplodingKG())._store_knowledge("c", "d", "arxiv", 0.9)


def test_reader_stop_reading():
    reader = OmniscientReader()
    reader.is_reading = True
    reader.stop_reading()
    assert reader.is_reading is False


async def test_reader_read_all_sources_logs_session(monkeypatch):
    reader = OmniscientReader()
    calls = []

    async def fake(source_type, url):
        calls.append((source_type, url))

    monkeypatch.setattr(reader, "_read_source", fake)
    await reader._read_all_sources()
    expected = sum(len(urls) for urls in OmniscientReader.SOURCES.values())
    assert len(calls) == expected == 5
    assert reader.get_reading_stats()["total_reading_sessions"] == 1


# --- SelfPracticeEngine ---


def test_practice_initial_stats():
    assert SelfPracticeEngine().get_practice_stats() == {"total_practices": 0, "passed": 0, "success_rate": 0}


async def test_practice_generate_problems_structure():
    engine = SelfPracticeEngine()
    problems = await engine._generate_problems_for_area("coding", count=3)
    assert len(problems) == 3
    assert [p["difficulty"] for p in problems] == ["beginner", "intermediate", "advanced"]
    assert all(p["area"] == "coding" for p in problems)
    assert all(p["verification_criteria"] for p in problems)


async def test_practice_attempt_solution_defaults():
    solution = await SelfPracticeEngine()._attempt_solution({"title": "x"})
    assert solution == {"approach": "systematic", "confidence": 0.7}


def test_practice_evaluate_passed_failed():
    engine = SelfPracticeEngine()
    ok = engine._evaluate_solution({}, {"confidence": 0.9})
    assert ok["passed"] is True and ok["score"] == 0.9
    bad = engine._evaluate_solution({}, {"confidence": 0.2})
    assert bad["passed"] is False and bad["score"] == 0.2
    default = engine._evaluate_solution({}, {})
    assert default["score"] == 0.5 and default["passed"] is False


async def test_practice_learn_from_practice_passed_calls_add_skill():
    iq = FakeIQ()
    engine = SelfPracticeEngine(iq_engine=iq)
    problem = {"area": "coding", "difficulty": "beginner", "title": "p1"}
    await engine._learn_from_practice(problem, {}, {"score": 0.9, "passed": True, "feedback": []})
    assert len(engine.practice_history) == 1
    assert len(iq.skills) == 1
    assert iq.skills[0]["skill_id"] == "practice_coding_beginner"
    assert iq.skills[0]["dimension"] == "coding"


async def test_practice_learn_from_practice_failed_no_skill():
    iq = FakeIQ()
    engine = SelfPracticeEngine(iq_engine=iq)
    problem = {"area": "coding", "difficulty": "beginner", "title": "p1"}
    await engine._learn_from_practice(problem, {}, {"score": 0.1, "passed": False, "feedback": []})
    assert len(engine.practice_history) == 1
    assert iq.skills == []
    assert engine.get_practice_stats() == {"total_practices": 1, "passed": 0, "success_rate": 0}


async def test_practice_daily_session_with_fake_iq():
    iq = FakeIQ(weak=("area_a", "area_b"))
    engine = SelfPracticeEngine(iq_engine=iq)
    await engine.daily_practice_session()
    assert len(engine.practice_history) == 6
    assert len(iq.skills) == 6
    stats = engine.get_practice_stats()
    assert stats["total_practices"] == 6 and stats["passed"] == 6 and stats["success_rate"] == 1.0


async def test_practice_daily_session_iq_none():
    engine = SelfPracticeEngine(iq_engine=None)
    await engine.daily_practice_session()
    assert len(engine.practice_history) == 3
    assert engine.get_practice_stats()["success_rate"] == 1.0


# --- DeepReflectionEngine ---


def test_reflection_initial_stats():
    assert DeepReflectionEngine().get_reflection_stats() == {"total_reflections": 0, "total_lessons": 0}


def test_reflection_no_experiences_when_memory_none():
    assert DeepReflectionEngine(memory_engine=None)._get_experiences_from_today() == []


def test_reflection_get_experiences_from_memory():
    exps = [{"success": True}]
    engine = DeepReflectionEngine(memory_engine=FakeMemoryExperiences(exps))
    assert engine._get_experiences_from_today() == exps


def test_reflection_get_experiences_swallows_errors():
    assert DeepReflectionEngine(memory_engine=FakeMemoryRaising())._get_experiences_from_today() == []


async def test_reflection_hidden_patterns_threshold():
    engine = DeepReflectionEngine()
    assert await engine._find_hidden_patterns([]) == []
    assert await engine._find_hidden_patterns([{}, {}]) == []
    patterns = await engine._find_hidden_patterns([{}, {}, {}])
    assert len(patterns) == 1 and patterns[0]["type"] == "repeated_action"


def test_reflection_repeated_mistakes_filter():
    engine = DeepReflectionEngine()
    experiences = [{"success": False}, {"success": True}, {}, {"success": None}, {"success": False}]
    mistakes = engine._find_repeated_mistakes(experiences)
    assert len(mistakes) == 2
    assert all(m["success"] is False for m in mistakes)


async def test_reflection_generate_lessons():
    engine = DeepReflectionEngine()
    assert await engine._generate_deep_lessons([], [], []) == []
    lessons = await engine._generate_deep_lessons([], [{"success": False}], [])
    assert len(lessons) == 1 and lessons[0]["depth"] == "deep"


async def test_reflection_nightly_empty():
    engine = DeepReflectionEngine(memory_engine=None)
    reflection = await engine.nightly_deep_reflection()
    assert reflection["patterns_found"] == 0
    assert reflection["mistakes_identified"] == 0
    assert reflection["lessons_learned"] == 0
    assert reflection["lessons"] == []
    assert engine.get_reflection_stats() == {"total_reflections": 1, "total_lessons": 0}


async def test_reflection_nightly_with_experiences():
    exps = [{"success": True}, {"success": False}, {"success": True}, {"success": False}]
    engine = DeepReflectionEngine(memory_engine=FakeMemoryExperiences(exps))
    reflection = await engine.nightly_deep_reflection()
    assert reflection["patterns_found"] == 1
    assert reflection["mistakes_identified"] == 2
    assert reflection["lessons_learned"] == 1
    assert engine.get_reflection_stats() == {"total_reflections": 1, "total_lessons": 1}


# --- ExpertImitationEngine ---


def test_expert_initial_stats():
    assert ExpertImitationEngine().get_expert_stats() == {"experts_studied": 0, "strategies_learned": 0}


async def test_expert_study_strategies():
    engine = ExpertImitationEngine()
    result = await engine.study_expert_strategies("coding")
    assert result == []
    assert engine.studied_experts == ["torvalds", "guido", "antirez"]


async def test_expert_stats_after_study():
    engine = ExpertImitationEngine()
    await engine.study_expert_strategies("coding")
    await engine.study_expert_strategies("coding")
    assert engine.get_expert_stats() == {"experts_studied": 6, "strategies_learned": 0}


# --- SelfExperimentationEngine ---


def test_experiment_initial_stats():
    assert SelfExperimentationEngine().get_experiment_stats() == {
        "total_experiments": 0,
        "successful": 0,
        "success_rate": 0,
    }


async def test_run_experiments_structure():
    engine = SelfExperimentationEngine()
    results = await engine.run_experiments("coding")
    assert len(results) == 2
    assert all(r["supported"] is True for r in results)
    assert all(r["improvement"] == 12.5 for r in results)
    assert all("hypothesis" in r for r in results)
    assert "coding" in results[0]["hypothesis"]


async def test_experiment_stats_after_run():
    engine = SelfExperimentationEngine()
    await engine.run_experiments("coding")
    assert engine.get_experiment_stats() == {"total_experiments": 2, "successful": 2, "success_rate": 1.0}


# --- CreativeSynthesisEngine ---


def test_synthesis_initial_stats():
    assert CreativeSynthesisEngine().get_synthesis_stats() == {"total_sessions": 0, "total_insights": 0}


async def test_generate_insights_all_pairs(monkeypatch):
    engine = CreativeSynthesisEngine()
    monkeypatch.setattr(random, "random", lambda: 0.99)
    insights = await engine.generate_creative_insights()
    assert len(insights) == 15
    assert all(isinstance(i, str) and i.startswith("Combining") for i in insights)
    assert engine.get_synthesis_stats() == {"total_sessions": 1, "total_insights": 15}


async def test_generate_insights_none(monkeypatch):
    engine = CreativeSynthesisEngine()
    monkeypatch.setattr(random, "random", lambda: 0.0)
    insights = await engine.generate_creative_insights()
    assert insights == []
    assert engine.get_synthesis_stats() == {"total_sessions": 1, "total_insights": 0}


# --- SelfAssessmentEngine ---


def test_assessment_initial_stats():
    assert SelfAssessmentEngine().get_assessment_stats() == {"total_assessments": 0, "latest_iq": 100}


async def test_run_weekly_assessment_iq_175():
    engine = SelfAssessmentEngine()
    assessment = await engine.run_weekly_assessment()
    assert assessment["total_iq"] == 175.0
    assert set(assessment["dimension_scores"]) == {"coding", "reasoning", "memory"}
    assert all(v["average_score"] == 0.75 for v in assessment["dimension_scores"].values())
    assert "timestamp" in assessment


async def test_assessment_stats_after_run():
    engine = SelfAssessmentEngine()
    await engine.run_weekly_assessment()
    await engine.run_weekly_assessment()
    assert engine.get_assessment_stats() == {"total_assessments": 2, "latest_iq": 175.0}

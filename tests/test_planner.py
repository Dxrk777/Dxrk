# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from dxrk.models import (
    AgentID,
    ComponentID,
    PersonaID,
    PresetID,
    SDDModeID,
    Selection,
    SkillID,
)
from dxrk.planner import (
    Graph,
    DependencyCycleError,
    DependencyResolver,
    ReviewPayload,
    apply_soft_ordering,
    build_review_payload,
    mvp_graph,
    new_resolver,
    platform_decision_from_profile,
    soft_ordering_constraints,
    topological_sort,
)
from dxrk.system import PlatformProfile


def _all_components() -> list[ComponentID]:
    e = ComponentID.DXRK_MEMORY
    s = ComponentID.SDD
    sk = ComponentID.SKILLS
    c7 = ComponentID.CONTEXT7
    p = ComponentID.PERSONA
    perm = ComponentID.PERMISSIONS
    g = ComponentID.DXRK_GUARDIAN
    t = ComponentID.THEME
    return [e, s, sk, c7, p, perm, g, t]


def test_mvp_graph_has_all():
    g = mvp_graph()
    for c in _all_components():
        assert g.has(c)


def test_graph_has_false():
    g = mvp_graph()
    fake = ComponentID.OPENCODE_DXRK_LOGO
    assert not g.has(fake)


def test_graph_dependencies_of_engram():
    g = mvp_graph()
    assert g.dependencies_of(ComponentID.DXRK_MEMORY) == []


def test_graph_dependencies_of_sdd():
    g = mvp_graph()
    assert g.dependencies_of(ComponentID.SDD) == [ComponentID.DXRK_MEMORY]


def test_graph_dependencies_of_skills():
    g = mvp_graph()
    assert g.dependencies_of(ComponentID.SKILLS) == [ComponentID.SDD]


def test_topological_sort_basic():
    deps = {
        ComponentID.SDD: [ComponentID.DXRK_MEMORY],
        ComponentID.SKILLS: [ComponentID.SDD],
    }
    result = topological_sort(deps)
    e = ComponentID.DXRK_MEMORY
    s = ComponentID.SDD
    sk = ComponentID.SKILLS

    assert e in result
    assert s in result
    assert sk in result
    assert result.index(e) < result.index(s)
    assert result.index(s) < result.index(sk)


def test_topological_sort_no_deps():
    deps = {
        ComponentID.DXRK_MEMORY: [],
        ComponentID.PERSONA: [],
        ComponentID.THEME: [],
    }
    result = topological_sort(deps)
    assert len(result) == 3


def test_topological_sort_cycle_raises():
    e = ComponentID.DXRK_MEMORY
    s = ComponentID.SDD
    deps = {e: [s], s: [e]}
    with pytest.raises(DependencyCycleError):
        topological_sort(deps)


def test_apply_soft_ordering_noop_when_already_correct():
    e = ComponentID.DXRK_MEMORY
    sk = ComponentID.SKILLS
    p = ComponentID.PERSONA
    ordered = [e, sk, p]
    pairs = [(p, e)]
    result = apply_soft_ordering(ordered, pairs)
    assert result.index(p) < result.index(e)


def test_apply_soft_ordering_moves_persona_before():
    e = ComponentID.DXRK_MEMORY
    sk = ComponentID.SKILLS
    p = ComponentID.PERSONA
    ordered = [e, sk, p]
    pairs = [(p, e)]
    result = apply_soft_ordering(ordered, pairs)
    assert result.index(p) < result.index(e)


def test_soft_ordering_constraints():
    constraints = soft_ordering_constraints()
    assert len(constraints) == 2
    first, second = constraints[0]
    assert first == ComponentID.PERSONA
    assert second == ComponentID.DXRK_MEMORY


class TestDependencyResolver:
    def test_resolve_empty_selection(self):
        resolver = new_resolver()
        selection = Selection()
        result = resolver.resolve(selection)
        assert result.ordered_components == []
        assert result.agents == []

    def test_resolve_with_engram(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.DXRK_MEMORY])
        result = resolver.resolve(selection)
        assert ComponentID.DXRK_MEMORY in result.ordered_components
        assert result.added_dependencies == []

    def test_resolve_with_sdd_adds_engram(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.SDD])
        result = resolver.resolve(selection)
        assert ComponentID.SDD in result.ordered_components
        assert ComponentID.DXRK_MEMORY in result.added_dependencies

    def test_resolve_with_skills_adds_sdd_and_engram(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.SKILLS])
        result = resolver.resolve(selection)
        assert ComponentID.SKILLS in result.ordered_components
        assert ComponentID.SDD in result.added_dependencies
        assert ComponentID.DXRK_MEMORY in result.added_dependencies

    def test_resolve_agents(self):
        resolver = new_resolver()
        selection = Selection(
            components=[ComponentID.DXRK_MEMORY],
            agents=[AgentID.CLAUDE_CODE, AgentID.OPENCODE],
        )
        result = resolver.resolve(selection)
        assert AgentID.CLAUDE_CODE in result.agents
        assert AgentID.OPENCODE in result.agents
        assert result.unsupported_agents == []


def test_resolve_unknown_component_raises():
    resolver = new_resolver()
    selection = Selection(components=[ComponentID.OPENCODE_DXRK_LOGO])
    with pytest.raises(ValueError, match="unknown component"):
        resolver.resolve(selection)


class TestBuildReviewPayload:
    def test_basic_review(self):
        from dxrk.planner import DependencyResolver

        resolver = new_resolver()
        selection = Selection(
            components=[ComponentID.DXRK_MEMORY, ComponentID.PERSONA],
            agents=[AgentID.CLAUDE_CODE],
            persona=PersonaID.DXRK,
            preset=PresetID.FULL_DXRK,
            strict_tdd=True,
            skills=[SkillID.GO_TESTING],
        )
        resolved = resolver.resolve(selection)
        review = build_review_payload(selection, resolved)

        assert review.agents == [AgentID.CLAUDE_CODE]
        assert review.persona == PersonaID.DXRK
        assert review.preset == PresetID.FULL_DXRK
        assert review.strict_tdd is True
        assert SkillID.GO_TESTING in review.skills

    def test_review_sdd_detection(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.SDD])
        resolved = resolver.resolve(selection)
        review = build_review_payload(selection, resolved)
        assert review.has_sdd is True

    def test_review_no_sdd(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.DXRK_MEMORY])
        resolved = resolver.resolve(selection)
        review = build_review_payload(selection, resolved)
        assert review.has_sdd is False

    def test_review_component_actions(self):
        resolver = new_resolver()
        selection = Selection(components=[ComponentID.SDD])
        resolved = resolver.resolve(selection)
        review = build_review_payload(selection, resolved)
        actions = {ca.id: ca.action for ca in review.components}
        assert actions[ComponentID.SDD] == "selected"
        assert actions[ComponentID.DXRK_MEMORY] == "auto-dependency"


def test_platform_decision_from_profile():
    profile = PlatformProfile(
        os="linux",
        linux_distro="ubuntu",
        package_manager="apt",
        supported=True,
    )
    decision = platform_decision_from_profile(profile)
    assert decision.os == "linux"
    assert decision.linux_distro == "ubuntu"
    assert decision.supported is True


class TestReviewPayloadDefaults:
    def test_review_payload_defaults(self):
        r = ReviewPayload()
        assert r.agents == []
        assert r.strict_tdd is False
        assert r.has_sdd is False
        assert r.persona is None
        assert r.preset is None

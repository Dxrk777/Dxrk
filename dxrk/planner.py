# SPDX-License-Identifier: MIT
"""Dependency planner"""

from __future__ import annotations

from dataclasses import dataclass, field

from dxrk.models import (
    AgentID,
    ComponentID,
    PersonaID,
    PresetID,
    Selection,
    SkillID,
)
from dxrk.system import PlatformProfile


class Resolver:
    def resolve(self, selection: Selection) -> ResolvedPlan:
        raise NotImplementedError


@dataclass
class ResolvedPlan:
    agents: list[AgentID] = field(default_factory=list)
    unsupported_agents: list[AgentID] = field(default_factory=list)
    ordered_components: list[ComponentID] = field(default_factory=list)
    added_dependencies: list[ComponentID] = field(default_factory=list)
    platform_decision: PlatformDecision | None = None


@dataclass
class ReviewPayload:
    agents: list[AgentID] = field(default_factory=list)
    unsupported_agents: list[AgentID] = field(default_factory=list)
    persona: PersonaID | None = None
    preset: PresetID | None = None
    components: list[ComponentAction] = field(default_factory=list)
    added_dependencies: list[ComponentID] = field(default_factory=list)
    platform_decision: PlatformDecision | None = None
    skills: list[SkillID] = field(default_factory=list)
    strict_tdd: bool = False
    has_sdd: bool = False


@dataclass
class PlatformDecision:
    os: str = ""
    linux_distro: str = ""
    package_manager: str = ""
    supported: bool = False


def platform_decision_from_profile(profile: PlatformProfile) -> PlatformDecision:
    return PlatformDecision(
        os=profile.os,
        linux_distro=profile.linux_distro,
        package_manager=profile.package_manager,
        supported=profile.supported,
    )


@dataclass
class ComponentAction:
    id: ComponentID
    action: str


# --- Graph ---


class Graph:
    def __init__(self, dependencies: dict[ComponentID, list[ComponentID]]):
        self._deps = {k: list(v) for k, v in dependencies.items()}

    def has(self, component: ComponentID) -> bool:
        return component in self._deps

    def dependencies_of(self, component: ComponentID) -> list[ComponentID]:
        return list(self._deps.get(component, []))


def _supported_agents() -> set[str]:
    from dxrk.models import AGENTS

    return set(a.value for a in AGENTS)


def mvp_graph() -> Graph:
    e = ComponentID.DXRK_MEMORY
    s = ComponentID.SDD
    sk = ComponentID.SKILLS
    c7 = ComponentID.CONTEXT7
    p = ComponentID.PERSONA
    perm = ComponentID.PERMISSIONS
    g = ComponentID.DXRK_GUARDIAN
    t = ComponentID.THEME
    return Graph(
        {
            e: [],
            s: [e],
            sk: [s],
            c7: [],
            p: [],
            perm: [],
            g: [],
            t: [],
        }
    )


SOFT_ORDERING_PAIRS: list[tuple[ComponentID, ComponentID]] = []


def _init_soft_pairs():
    from dxrk.models import ComponentEngram, ComponentPersona, ComponentSDD

    global SOFT_ORDERING_PAIRS
    SOFT_ORDERING_PAIRS = [
        (ComponentPersona, ComponentEngram),
        (ComponentPersona, ComponentSDD),
    ]


try:
    _init_soft_pairs()
except Exception:
    pass


def soft_ordering_constraints() -> list[tuple[ComponentID, ComponentID]]:
    return list(SOFT_ORDERING_PAIRS)


# --- Topological Sort (Kahn's algorithm) ---


class DependencyCycleError(ValueError):
    pass


def topological_sort(
    dependencies: dict[ComponentID, list[ComponentID]],
) -> list[ComponentID]:
    in_degree: dict[ComponentID, int] = {}
    children: dict[ComponentID, list[ComponentID]] = {}
    nodes: set[ComponentID] = set()

    for component, deps in dependencies.items():
        nodes.add(component)
        in_degree.setdefault(component, 0)
        for dep in deps:
            nodes.add(dep)
            in_degree[component] = in_degree.get(component, 0) + 1
            children.setdefault(dep, []).append(component)
            in_degree.setdefault(dep, 0)

    queue = sorted([n for n in nodes if in_degree.get(n, 0) == 0])
    ordered: list[ComponentID] = []

    while queue:
        node = queue.pop(0)
        ordered.append(node)
        for child in sorted(children.get(node, [])):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
                queue.sort()

    if len(ordered) != len(nodes):
        raise DependencyCycleError("dependency cycle detected")

    return ordered


def apply_soft_ordering(
    ordered: list[ComponentID],
    pairs: list[tuple[ComponentID, ComponentID]],
) -> list[ComponentID]:
    result = list(ordered)

    def index_of(items: list[ComponentID], target: ComponentID) -> int:
        for i, item in enumerate(items):
            if item == target:
                return i
        return -1

    for first, second in pairs:
        i = index_of(result, first)
        j = index_of(result, second)
        if i < 0 or j < 0 or i < j:
            continue

        item = result[i]
        result[j + 1 : i + 1] = result[j:i]
        result[j] = item

    return result


# --- Resolver ---


class DependencyResolver(Resolver):
    def __init__(self, graph: Graph):
        self._graph = graph

    def resolve(self, selection: Selection) -> ResolvedPlan:
        resolved = ResolvedPlan()
        selected_set: set[ComponentID] = set()
        dependencies: dict[ComponentID, list[ComponentID]] = {}

        for selected in selection.components:
            if not self._graph.has(selected):
                raise ValueError(f"unknown component {selected!r}")
            selected_set.add(selected)
            self._expand_dependencies(selected, dependencies)

        ordered_components = topological_sort(dependencies)
        ordered_components = apply_soft_ordering(
            ordered_components, soft_ordering_constraints()
        )

        for component in ordered_components:
            if component not in selected_set:
                resolved.added_dependencies.append(component)

        resolved.ordered_components = ordered_components

        supported = _supported_agents()
        for agent in selection.agents:
            if agent in supported:
                resolved.agents.append(agent)
            else:
                resolved.unsupported_agents.append(agent)

        return resolved

    def _expand_dependencies(
        self,
        component: ComponentID,
        dependencies: dict[ComponentID, list[ComponentID]],
    ):
        if component in dependencies:
            return
        deps = self._graph.dependencies_of(component)
        dependencies[component] = deps
        for dep in deps:
            if not self._graph.has(dep):
                raise ValueError(
                    f"component {component!r} depends on unknown dependency {dep!r}"
                )
            self._expand_dependencies(dep, dependencies)


def new_resolver(graph: Graph | None = None) -> DependencyResolver:
    return DependencyResolver(graph or mvp_graph())


# --- Review ---


def build_review_payload(selection: Selection, resolved: ResolvedPlan) -> ReviewPayload:
    auto_added = set(resolved.added_dependencies)
    components: list[ComponentAction] = []
    has_sdd = False

    from dxrk.models import ComponentSDD

    for component in resolved.ordered_components:
        action = "auto-dependency" if component in auto_added else "selected"
        if component == ComponentSDD:
            has_sdd = True
        components.append(ComponentAction(id=component, action=action))

    return ReviewPayload(
        agents=resolved.agents,
        unsupported_agents=resolved.unsupported_agents,
        persona=selection.persona,
        preset=selection.preset,
        components=components,
        added_dependencies=resolved.added_dependencies,
        platform_decision=resolved.platform_decision,
        skills=selection.skills,
        strict_tdd=selection.strict_tdd,
        has_sdd=has_sdd,
    )

# SPDX-License-Identifier: MIT
"""Skills component — ports internal/components/skills/.

Skill preset allocation and injection into agent skill directories.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dxrk.components import filemerge
from dxrk.components.assets import read as _read
from dxrk.models import PresetID, SkillID

# ─── Presets ───────────────────────────────────────────────────────────────

_SDD_SKILLS = [
    SkillID.SDD_INIT,
    SkillID.SDD_EXPLORE,
    SkillID.SDD_PROPOSE,
    SkillID.SDD_SPEC,
    SkillID.SDD_DESIGN,
    SkillID.SDD_TASKS,
    SkillID.SDD_APPLY,
    SkillID.SDD_VERIFY,
    SkillID.SDD_ARCHIVE,
    SkillID.SDD_ONBOARD,
    SkillID.JUDGMENT_DAY,
]

_FOUNDATION_SKILLS = [
    SkillID.GO_TESTING,
    SkillID.SKILL_CREATOR,
    SkillID.BRANCH_PR,
    SkillID.ISSUE_CREATION,
    SkillID.SKILL_REGISTRY,
    SkillID.CHAINED_PR,
    SkillID.COGNITIVE_DOC,
    SkillID.COMMENT_WRITER,
    SkillID.WORK_UNIT_COMMITS,
]


def skills_for_preset(preset: PresetID) -> list[SkillID]:
    if preset == PresetID.MINIMAL:
        return list(_SDD_SKILLS)
    if preset == PresetID.ECOSYSTEM_ONLY:
        return list(_SDD_SKILLS + _FOUNDATION_SKILLS)
    if preset == PresetID.CUSTOM:
        return []
    return list(_SDD_SKILLS + _FOUNDATION_SKILLS)


def all_skill_ids() -> list[SkillID]:
    return list(_SDD_SKILLS + _FOUNDATION_SKILLS)


# ─── Injection ─────────────────────────────────────────────────────────────


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)
    Skipped: list[SkillID] = field(default_factory=list)


def _is_sdd_skill(skill_id: SkillID) -> bool:
    return str(skill_id).startswith("sdd-")


def inject(home_dir: str, adapter, skill_ids: list[SkillID]) -> InjectionResult:
    if not adapter.supports_skills:
        return InjectionResult(Skipped=skill_ids)

    skill_dir = adapter.skills_dir(home_dir)
    if not skill_dir:
        return InjectionResult(Skipped=skill_ids)

    paths: list[str] = []
    skipped: list[SkillID] = []
    changed = False

    for skill_id in skill_ids:
        if _is_sdd_skill(skill_id):
            continue

        asset_path = f"skills/{skill_id}/SKILL.md"
        content = _read(asset_path)
        if content is None:
            skipped.append(skill_id)
            continue
        if not content.strip():
            raise ValueError(f"skill {skill_id!r}: embedded asset exists but is empty")

        out_path = os.path.join(skill_dir, skill_id, "SKILL.md")
        wr = filemerge.write_file_atomic(out_path, content.encode("utf-8"), 0o644)
        changed = changed or wr.Changed
        paths.append(out_path)

    return InjectionResult(Changed=changed, Files=paths, Skipped=skipped)


def skill_path_for_agent(home_dir: str, adapter, skill_id: SkillID) -> str:
    skill_dir = adapter.skills_dir(home_dir)
    if not skill_dir:
        return ""
    return os.path.join(skill_dir, skill_id, "SKILL.md")

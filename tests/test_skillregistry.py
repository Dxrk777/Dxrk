# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
from pathlib import Path

from dxrk.skillregistry import (
    CacheRelPath,
    RegistryRelPath,
    ensure_atl_ignored,
    fingerprint,
    project_skill_dirs,
    regenerate,
    user_skill_dirs,
)


def _write_skill(base: Path, rel: str, content: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _contains_path(paths: list[str], want: str) -> bool:
    want = os.path.normpath(want)
    return any(os.path.normpath(p) == want for p in paths)


def test_regenerate_writes_registry_and_cache_then_hits_cache(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        cwd,
        os.path.join("skills", "react", "SKILL.md"),
        """---
name: react
description: React patterns
---

## Compact Rules

- Prefer composition.
- Keep state local.
""",
    )

    ensure_atl_ignored(str(cwd))
    first = regenerate(str(cwd), str(home), False)
    assert first.regenerated is True
    assert first.skill_count == 1
    assert first.reason == "fingerprint-changed"
    registry = _read_text(cwd / RegistryRelPath)
    for want in ("### react", "- Trigger: React patterns", "  - Prefer composition."):
        assert want in registry
    assert (cwd / CacheRelPath).exists()

    second = regenerate(str(cwd), str(home), False)
    assert second.regenerated is False
    assert second.reason == "cache-hit"


def test_regenerate_force_bypasses_cache_and_project_skill_wins(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        home,
        os.path.join(".claude", "skills", "dup", "SKILL.md"),
        """---
name: dup
description: user copy
---

## Compact Rules

- User rule.
""",
    )
    _write_skill(
        cwd,
        os.path.join("skills", "dup", "SKILL.md"),
        """---
name: dup
description: project copy
---

## Compact Rules

- Project rule.
""",
    )

    first = regenerate(str(cwd), str(home), False)
    assert first.skill_count == 1
    forced = regenerate(str(cwd), str(home), True)
    assert forced.regenerated is True
    assert forced.reason == "forced"
    registry = _read_text(cwd / RegistryRelPath)
    assert "Project rule" in registry
    assert "User rule" not in registry


def test_regenerate_scans_project_opencode_skills_before_global_opencode(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        home,
        os.path.join(".config", "opencode", "skills", "dup", "SKILL.md"),
        """---
name: dup
description: global OpenCode copy
---

## Compact Rules

- Global OpenCode rule.
""",
    )
    _write_skill(
        cwd,
        os.path.join(".opencode", "skills", "dup", "SKILL.md"),
        """---
name: dup
description: project OpenCode copy
---

## Compact Rules

- Project OpenCode rule.
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    for want in ("- .opencode/skills", "Project OpenCode rule"):
        assert want in registry
    assert "Global OpenCode rule" not in registry


def test_regenerate_keeps_user_skill_source_order_for_global_duplicates(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        home,
        os.path.join(".claude", "skills", "dup", "SKILL.md"),
        """---
name: dup
description: Claude copy
---

## Compact Rules

- Claude rule.
""",
    )
    _write_skill(
        home,
        os.path.join(".config", "opencode", "skills", "dup", "SKILL.md"),
        """---
name: dup
description: OpenCode copy
---

## Compact Rules

- OpenCode rule.
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    assert "OpenCode rule" in registry
    assert "Claude rule" not in registry


def test_user_skill_dirs_includes_supported_agent_skill_locations(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    dirs = user_skill_dirs(str(home))
    for want in (
        os.path.join(home, ".config", "opencode", "skills"),
        os.path.join(home, ".config", "kilo", "skills"),
        os.path.join(home, ".claude", "skills"),
        os.path.join(home, ".gemini", "skills"),
        os.path.join(home, ".gemini", "antigravity", "skills"),
        os.path.join(home, ".cursor", "skills"),
        os.path.join(home, ".copilot", "skills"),
        os.path.join(home, ".codex", "skills"),
        os.path.join(home, ".codeium", "windsurf", "skills"),
        os.path.join(home, ".config", "agents", "skills"),
        os.path.join(home, ".kimi", "skills"),
        os.path.join(home, ".qwen", "skills"),
        os.path.join(home, ".kiro", "skills"),
        os.path.join(home, ".openclaw", "skills"),
        os.path.join(home, ".pi", "agent", "skills"),
        os.path.join(home, ".agents", "skills"),
    ):
        assert _contains_path(dirs, str(want)), f"missing {want!r} in {dirs!r}"


def test_project_skill_dirs_includes_workspace_skill_locations(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    dirs = project_skill_dirs(str(cwd))
    for want in (
        os.path.join(cwd, "skills"),
        os.path.join(cwd, ".opencode", "skills"),
        os.path.join(cwd, ".claude", "skills"),
        os.path.join(cwd, ".gemini", "skills"),
        os.path.join(cwd, ".cursor", "skills"),
        os.path.join(cwd, ".github", "skills"),
        os.path.join(cwd, ".codex", "skills"),
        os.path.join(cwd, ".qwen", "skills"),
        os.path.join(cwd, ".kiro", "skills"),
        os.path.join(cwd, ".openclaw", "skills"),
        os.path.join(cwd, ".pi", "skills"),
        os.path.join(cwd, ".agent", "skills"),
        os.path.join(cwd, ".agents", "skills"),
        os.path.join(cwd, ".atl", "skills"),
    ):
        assert _contains_path(dirs, str(want)), f"missing {want!r} in {dirs!r}"


def test_regenerate_extracts_hard_rules_when_compact_rules_are_absent(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        cwd,
        os.path.join("skills", "go-testing", "SKILL.md"),
        """---
name: go-testing
description: Go testing patterns
---

## Activation Contract

Use this for Go tests.

## Hard Rules

- Run focused tests before broad tests.
- Keep table tests readable.

## Execution Steps

- This should not be copied.
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    for want in ("Run focused tests before broad tests.", "Keep table tests readable."):
        assert want in registry
    from dxrk import skillregistry

    for dont_want in (
        skillregistry._fallback_compact_rules,
        "This should not be copied.",
    ):
        assert dont_want not in registry


def test_regenerate_extracts_legacy_rule_sections_when_compact_rules_are_absent(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        cwd,
        os.path.join("skills", "comment-writer", "SKILL.md"),
        """---
name: comment-writer
description: Comment writing
---

## Voice Rules

- Be warm and direct.
- Keep it short.

## Critical Rules

1. Link an approved issue.
2. Keep PRs within the review budget.

## Critical Patterns

- Start with the actionable point.
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    for want in (
        "Be warm and direct.",
        "Keep it short.",
        "Link an approved issue.",
        "Keep PRs within the review budget.",
        "Start with the actionable point.",
    ):
        assert want in registry
    from dxrk import skillregistry

    assert skillregistry._fallback_compact_rules not in registry


def test_regenerate_prefers_compact_rules_over_fallback_sections(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        cwd,
        os.path.join("skills", "explicit", "SKILL.md"),
        """---
name: explicit
---

## Compact Rules

- Explicit compact rule.

## Hard Rules

- Hard rule should not be copied.
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    assert "Explicit compact rule." in registry
    assert "Hard rule should not be copied." not in registry


def test_regenerate_caps_extracted_fallback_rules(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    rules = "\n".join(f"- Rule {i:02d}." for i in range(1, 17))
    _write_skill(
        cwd,
        os.path.join("skills", "many", "SKILL.md"),
        f"""---
name: many
---

## Hard Rules

{rules}
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    assert "Rule 15." in registry
    assert "Rule 16." not in registry


def test_regenerate_excludes_skill_registry_shared_and_sdd(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    _write_skill(
        cwd,
        os.path.join("skills", "_shared", "SKILL.md"),
        """---
name: _shared
---

## Compact Rules
- no
""",
    )
    _write_skill(
        cwd,
        os.path.join("skills", "skill-registry", "SKILL.md"),
        """---
name: skill-registry
---

## Compact Rules
- no
""",
    )
    _write_skill(
        cwd,
        os.path.join("skills", "sdd-apply", "SKILL.md"),
        """---
name: sdd-apply
---

## Compact Rules
- no
""",
    )
    _write_skill(
        cwd,
        os.path.join("skills", "go-testing", "SKILL.md"),
        """---
name: go-testing
---

## Compact Rules
- yes
""",
    )

    result = regenerate(str(cwd), str(home), False)
    assert result.skill_count == 1
    registry = _read_text(cwd / RegistryRelPath)
    assert "go-testing" in registry
    assert "### sdd-apply" not in registry
    assert "### skill-registry" not in registry

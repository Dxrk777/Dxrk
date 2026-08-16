# SPDX-License-Identifier: MIT
"""Integration test for the agent builder (mirrors internal/agentbuilder/integration_test.go)."""

from __future__ import annotations

from datetime import UTC, datetime

from dxrk import agentbuilder as ab
from dxrk.models import AgentClaudeCode, AgentOpenCode

CANNED_SKILL = """# CSS A11y Reviewer

## Description
Reviews CSS files for accessibility issues, focusing on color contrast, focus visibility, and proper ARIA usage.

## Trigger
When the user asks to "review CSS for a11y", "check accessibility in CSS", or "audit CSS accessibility".

## Instructions
1. Scan all CSS files in the project for potential accessibility issues.
2. Check color contrast ratios against WCAG 2.1 AA standards.
3. Verify focus indicators are visible (outline: none without alternative must be flagged).
4. Identify elements that may need ARIA attributes.
5. Generate a structured report with file, line, and issue description.

## Rules
- Always provide specific file and line references.
- Never mark issues as critical without clear WCAG citation.
- Suggest concrete fixes for each issue found.

## Examples
User: "Review CSS for a11y issues"
Agent: Scans and reports: "button.css:14 — focus outline removed without alternative (WCAG 2.4.7)"
"""


def test_integration_full_agent_builder_flow(tmp_path) -> None:
    # Step 1: Compose prompt.
    prompt = ab.compose_prompt("build an a11y CSS reviewer", None, [AgentClaudeCode])

    assert "a11y CSS reviewer" in prompt

    # Step 2: Call MockEngine.generate with the prompt.
    engine = ab.MockEngine(
        AgentIDVal=AgentClaudeCode,
        Output=CANNED_SKILL,
        IsAvailable=True,
    )
    raw = engine.generate(prompt)

    # Step 3: Parse the result.
    agent = ab.parse(raw)

    # Step 4: Assert GeneratedAgent has correct fields.
    assert agent.Name == "css-a11y-reviewer"
    assert agent.Title == "CSS A11y Reviewer"
    assert "accessibility" in agent.Description
    assert "a11y" in agent.Trigger

    # Step 5: Call install with temp dirs.
    dir1 = tmp_path / "claude-skills"
    dir2 = tmp_path / "opencode-skills"
    dir1.mkdir()
    dir2.mkdir()

    adapters = [
        ab.AdapterInfo(AgentID=AgentClaudeCode, SkillsDir=str(dir1)),
        ab.AdapterInfo(AgentID=AgentOpenCode, SkillsDir=str(dir2)),
    ]
    results = ab.install(agent, adapters)

    # Step 6: Assert files written.
    assert len(results) == 2
    for r in results:
        assert r.Success, f"result for {r.AgentID}: Success=False, err={r.Err}"

    skill_file = dir1 / "css-a11y-reviewer" / "SKILL.md"
    assert skill_file.exists()
    data = skill_file.read_text()
    assert "CSS A11y Reviewer" in data

    # Step 7: Call load_registry, add entry, verify entry added.
    reg_path = tmp_path / "custom-agents.json"
    reg = ab.load_registry(str(reg_path))
    reg.add(
        ab.RegistryEntry(
            Name=agent.Name,
            Title=agent.Title,
            Description=agent.Description,
            CreatedAt=datetime.now(UTC),
            GenerationEngine=AgentClaudeCode,
            InstalledAgents=[AgentClaudeCode, AgentOpenCode],
        )
    )
    ab.save_registry(str(reg_path), reg)

    loaded = ab.load_registry(str(reg_path))
    found = loaded.find_by_name("css-a11y-reviewer")
    assert found is not None, "registry entry not found after add+save+load"
    assert found.Title == "CSS A11y Reviewer"
    assert found.GenerationEngine == AgentClaudeCode

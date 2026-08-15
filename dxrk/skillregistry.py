# SPDX-License-Identifier: MIT
"""Skill registry"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from dxrk.components import filemerge
from dxrk.strconst import StrDescription

RegistryRelPath = ".atl/skill-registry.md"
CacheRelPath = ".atl/.skill-registry.cache.json"
RegistrySchema = 3
_section_marker = "## Selected skills and compact rules"
_atl_ignore_entry = ".atl/"
_fallback_compact_rules = (
    "No compact rules declared; delegators should load the full skill file before "
    "direct work, or pass an explicit fallback path only when Project Standards "
    "cannot be injected."
)

_exclude_names = {"_shared", "skill-registry"}
_exclude_prefixes = ["sdd-"]
_h2_heading_re = re.compile(r"^##\s+(.+?)\s*$")
_next_h2_re = re.compile(r"^##\s+")
_bullet_line_re = re.compile(r"^-\s+(.+)$")
_ordered_list_line_re = re.compile(r"^\d+[.)]\s+(.+)$")
_fallback_rule_headings = [
    "Hard Rules",
    "Critical Rules",
    "Critical Patterns",
    "Voice Rules",
    "Decision Gates",
]
_max_extracted_rule_count = 15
_frontmatter_line_re = re.compile(r"^(\w+):\s*(.*)$")


@dataclass
class SkillEntry:
    name: str = ""
    path: str = ""
    description: str = ""
    rules: list[str] = field(default_factory=list)


@dataclass
class Result:
    regenerated: bool = False
    skill_count: int = 0
    reason: str = ""
    registry: str = ""
    cache: str = ""


@dataclass
class _CacheFile:
    fingerprint: str = ""


# Keep these source roots in sync with the dxrk-pi skill-registry extension.
def user_skill_dirs(home: str) -> list[str]:
    return [
        # Dxrk AI/Pi and generic Agent Skills locations.
        os.path.join(home, ".pi", "agent", "skills"),
        os.path.join(home, ".config", "agents", "skills"),
        os.path.join(home, ".agents", "skills"),
        os.path.join(home, ".kimi", "skills"),
        # Agent-specific global skill locations supported by Dxrk AI adapters.
        os.path.join(home, ".config", "opencode", "skills"),
        os.path.join(home, ".config", "kilo", "skills"),
        os.path.join(home, ".claude", "skills"),
        os.path.join(home, ".gemini", "skills"),
        os.path.join(home, ".gemini", "antigravity", "skills"),
        os.path.join(home, ".cursor", "skills"),
        os.path.join(home, ".copilot", "skills"),
        os.path.join(home, ".codex", "skills"),
        os.path.join(home, ".codeium", "windsurf", "skills"),
        os.path.join(home, ".qwen", "skills"),
        os.path.join(home, ".kiro", "skills"),
        os.path.join(home, ".openclaw", "skills"),
    ]


def project_skill_dirs(cwd: str) -> list[str]:
    return [
        # Generic project skills first: repo-local intent beats user/global skills.
        os.path.join(cwd, "skills"),
        # Agent-native workspace skill locations.
        os.path.join(cwd, ".opencode", "skills"),
        os.path.join(cwd, ".claude", "skills"),
        os.path.join(cwd, ".gemini", "skills"),
        os.path.join(cwd, ".cursor", "skills"),
        os.path.join(cwd, ".github", "skills"),
        os.path.join(cwd, ".codex", "skills"),
        os.path.join(cwd, ".qwen", "skills"),
        os.path.join(cwd, ".kiro", "skills"),
        os.path.join(cwd, ".openclaw", "skills"),
        # Dxrk AI/Pi and generic Agent Skills workspace locations.
        os.path.join(cwd, ".pi", "skills"),
        os.path.join(cwd, ".agent", "skills"),
        os.path.join(cwd, ".agents", "skills"),
        os.path.join(cwd, ".atl", "skills"),
    ]


def regenerate(cwd: str, home: str, force: bool) -> Result:
    cwd = os.path.normpath(cwd)
    home = os.path.normpath(home)

    existing_dirs = _unique_existing_dirs(
        project_skill_dirs(cwd) + user_skill_dirs(home)
    )
    files = _find_all_skill_files(existing_dirs)

    registry_path = os.path.join(cwd, RegistryRelPath)
    cache_path = os.path.join(cwd, CacheRelPath)
    fp = fingerprint(files)
    cached = _read_cached_fingerprint(cache_path)
    if not force and cached == fp and _file_exists(registry_path):
        return Result(
            regenerated=False,
            reason="cache-hit",
            registry=registry_path,
            cache=cache_path,
        )

    entries: list[SkillEntry] = []
    for file in files:
        entry = load_skill(file)
        if entry is not None:
            entries.append(entry)
    entries = _dedupe_by_skill_name(entries, cwd)

    sources: list[str] = []
    for directory in existing_dirs:
        try:
            rel = os.path.relpath(directory, cwd)
        except ValueError:
            sources.append(directory)
            continue
        if rel != "." and not rel.startswith(".."):
            sources.append(rel)
        elif rel == ".":
            sources.append(".")

    try:
        os.makedirs(os.path.join(cwd, ".atl"), mode=0o750, exist_ok=True)
    except OSError as e:
        raise OSError(f"create .atl directory: {e}") from e
    md = render_registry(cwd, sources, entries)
    try:
        filemerge.write_file_atomic(registry_path, md.encode("utf-8"), 0o600)
    except OSError as e:
        raise OSError(f"write registry: {e}") from e
    cache_json = json.dumps(asdict(_CacheFile(fingerprint=fp)), indent=2)
    cache_bytes = (cache_json + "\n").encode("utf-8")
    try:
        filemerge.write_file_atomic(cache_path, cache_bytes, 0o600)
    except OSError as e:
        raise OSError(f"write registry cache: {e}") from e

    reason = "fingerprint-changed"
    if force:
        reason = "forced"
    return Result(
        regenerated=True,
        skill_count=len(entries),
        reason=reason,
        registry=registry_path,
        cache=cache_path,
    )


def ensure_atl_ignored(cwd: str) -> None:
    gitignore_path = os.path.join(cwd, ".gitignore")
    try:
        with open(gitignore_path, encoding="utf-8") as fh:
            existing = fh.read()
    except FileNotFoundError:
        existing = ""
    for line in existing.split("\n"):
        trimmed = line.strip()
        if trimmed == ".atl" or trimmed == _atl_ignore_entry:
            return
    prefix = ""
    if len(existing) > 0 and not existing.endswith("\n"):
        prefix = "\n"
    header = ""
    if (
        "# Local AI runtime state" not in existing
        and "# Local Pi runtime state" not in existing
    ):
        header = "# Local AI runtime state\n"
    fd = os.open(gitignore_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(existing + prefix + header + _atl_ignore_entry + "\n")


def fingerprint(files: list[str]) -> str:
    lines: list[str] = [f"schema:{RegistrySchema}"]
    for file in files:
        try:
            info = os.stat(file)
        except OSError:
            lines.append(file + ":missing")
            continue
        lines.append(f"{file}:{info.st_mtime_ns}:{info.st_size}")
    lines.sort()
    digest = hashlib.sha1("\n".join(lines).encode("utf-8")).digest()
    return digest.hex()


def load_skill(file: str) -> SkillEntry | None:
    try:
        with open(file, encoding="utf-8") as fh:
            data = fh.read()
    except OSError:
        return None
    name, desc, body = _parse_frontmatter(data)
    if name.strip() == "":
        name = os.path.basename(os.path.dirname(file))
    if _is_excluded(name):
        return None
    rules = _extract_compact_rules(body)
    if len(rules) == 0:
        rules = [_fallback_compact_rules]
    return SkillEntry(name=name, path=file, description=desc, rules=rules)


def render_registry(cwd: str, sources: list[str], entries: list[SkillEntry]) -> str:
    project_name = os.path.basename(cwd)
    lines: list[str] = []
    lines.append(f"# Skill Registry — {project_name}")
    lines.append("")
    lines.append(
        "<!-- Auto-generated by dxrk skill-registry refresh. Run `dxrk skill-registry "
        "refresh --force` to regenerate. -->"
    )
    lines.append("")
    lines.append("Last updated: " + datetime.now(UTC).strftime("%Y-%m-%d"))
    lines.append("")
    lines.append("## Sources scanned")
    lines.append("")
    for src in sources:
        lines.append("- " + src)
    lines.append("")
    lines.append("## Contract")
    lines.append("")
    lines.append(
        "**Delegator use only.** Any agent that launches subagents reads this registry "
        "to resolve compact rules, then injects matching rule text into subagent "
        "prompts under `## Project Standards (auto-resolved)`."
    )
    lines.append("")
    lines.append(
        "Subagents still read their assigned executor/phase skill. During normal "
        "runtime, they do **not** independently discover or load additional "
        "project/user `SKILL.md` files or this registry; project/user rules arrive "
        "pre-digested. Explicit fallback loading is degraded self-healing and must be "
        "reported in `skill_resolution` as `fallback-registry` or `fallback-path`."
    )
    lines.append("")
    lines.append(_section_marker)
    lines.append("")
    for entry in entries:
        lines.append("### " + entry.name)
        lines.append("- Path: " + entry.path)
        if entry.description.strip() != "":
            lines.append("- Trigger: " + entry.description)
        lines.append("- Rules:")
        for rule in entry.rules:
            lines.append("  - " + rule)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _find_all_skill_files(dirs: list[str]) -> list[str]:
    out: list[str] = []
    errors: list[OSError] = []

    def _onerror(error: OSError) -> None:
        errors.append(error)

    for root in dirs:
        for dirpath, _dirnames, filenames in os.walk(root, onerror=_onerror):
            if errors:
                raise errors[0]
            for name in filenames:
                if name == "SKILL.md":
                    out.append(os.path.join(dirpath, name))
    if errors:
        raise errors[0]
    return out


def _unique_existing_dirs(dirs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for directory in dirs:
        clean = os.path.normpath(directory)
        if clean in seen or not _dir_exists(clean):
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _parse_frontmatter(source: str) -> tuple[str, str, str]:
    if not source.startswith("---\n"):
        return "", "", source
    end = source.find("\n---", 4)
    if end == -1:
        return "", "", source
    fm = source[4:end]
    body = source[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    name = ""
    description = ""
    for line in fm.split("\n"):
        m = _frontmatter_line_re.match(line)
        if m is None:
            continue
        value = m.group(2).strip()
        value = value.strip("\"'")
        if m.group(1) == "name":
            name = value
        elif m.group(1) == StrDescription:
            description = value
    return name, description, body


def _extract_compact_rules(body: str) -> list[str]:
    rules = _extract_rules_from_headings(body, ["Compact Rules"])
    if len(rules) > 0:
        return rules
    return _extract_rules_from_headings(body, _fallback_rule_headings)


def _extract_rules_from_headings(body: str, headings: list[str]) -> list[str]:
    wanted = {_normalize_heading(heading) for heading in headings}

    in_section = False
    rules: list[str] = []
    for raw in body.split("\n"):
        line = raw.rstrip(" \t")
        m = _h2_heading_re.match(line)
        if m is not None:
            in_section = _normalize_heading(m.group(1)) in wanted
            continue
        if not in_section:
            continue
        if _next_h2_re.match(line):
            in_section = False
            continue
        rule = _extract_rule_line(line)
        if rule is not None:
            rules.append(rule)
            if len(rules) >= _max_extracted_rule_count:
                return rules
    return rules


def _extract_rule_line(line: str) -> str | None:
    trimmed = line.strip()
    if trimmed == "":
        return None
    m = _bullet_line_re.match(trimmed)
    if m is not None:
        return m.group(1).strip()
    m = _ordered_list_line_re.match(trimmed)
    if m is not None:
        return m.group(1).strip()
    if trimmed.startswith("|") and trimmed.endswith("|"):
        return _extract_rule_table_row(trimmed)
    return None


def _extract_rule_table_row(line: str) -> str | None:
    inner = line.strip("|")
    cells = [cell.strip() for cell in inner.split("|")]
    if len(cells) < 2:
        return None
    if (
        _is_table_separator(cells)
        or _is_table_header(cells)
        or cells[0] == ""
        or cells[1] == ""
    ):
        return None
    return cells[0] + ": " + cells[1]


def _is_table_separator(cells: list[str]) -> bool:
    for cell in cells:
        if cell.strip(" -:") != "":
            return False
    return True


def _is_table_header(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    first = _normalize_heading(cells[0])
    second = _normalize_heading(cells[1])
    return (first == "rule" and second == "requirement") or (
        first == "target" and second == "test pattern"
    )


def _normalize_heading(heading: str) -> str:
    return heading.lower().strip()


def _dedupe_by_skill_name(entries: list[SkillEntry], cwd: str) -> list[SkillEntry]:
    project_prefix = os.path.normpath(cwd) + os.sep
    buckets: dict[str, list[SkillEntry]] = {}
    for entry in entries:
        buckets.setdefault(entry.name, []).append(entry)
    out: list[SkillEntry] = []
    for bucket in buckets.values():
        chosen = bucket[0]
        for entry in bucket:
            if os.path.normpath(entry.path).startswith(project_prefix):
                chosen = entry
                break
        out.append(chosen)
    out.sort(key=lambda entry: entry.name)
    return out


def _read_cached_fingerprint(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            data = fh.read()
    except OSError:
        return ""
    try:
        cache = _CacheFile(**json.loads(data))
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""
    return cache.fingerprint


def _is_excluded(name: str) -> bool:
    if name in _exclude_names:
        return True
    for prefix in _exclude_prefixes:
        if name.startswith(prefix):
            return True
    return False


def _file_exists(path: str) -> bool:
    try:
        os.stat(path)
    except OSError:
        return False
    return not os.path.isdir(path)


def _dir_exists(path: str) -> bool:
    try:
        os.stat(path)
    except OSError:
        return False
    return os.path.isdir(path)

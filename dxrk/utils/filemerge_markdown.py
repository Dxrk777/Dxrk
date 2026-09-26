# SPDX-License-Identifier: MIT
"""Markdown section markers, legacy block stripping, and section injection."""

from __future__ import annotations

MARKER_PREFIX = "<!-- dxrk:"
MARKER_SUFFIX = " -->"
CLOSE_PREFIX = "<!-- /dxrk:"

ATL_BEGIN_MARKER = "<!-- BEGIN:agent-teams-lite -->"
ATL_END_MARKER = "<!-- END:agent-teams-lite -->"

LEGACY_PERSONA_FINGERPRINTS = ["## Personality", "Senior Architect", "## Rules"]


def open_marker(section_id: str) -> str:
    return MARKER_PREFIX + section_id + MARKER_SUFFIX


def close_marker(section_id: str) -> str:
    return CLOSE_PREFIX + section_id + MARKER_SUFFIX


def strip_legacy_persona_block(content: str) -> str:
    # Quick check: all fingerprints must be present somewhere in the file.
    for fp in LEGACY_PERSONA_FINGERPRINTS:
        if fp not in content:
            return content

    # Find the position of the first marker — everything before it is the
    # potential legacy zone. If there are no markers, the whole file is the
    # legacy zone.
    first_marker_idx = content.find(MARKER_PREFIX)

    zone = content if first_marker_idx < 0 else content[:first_marker_idx]

    # Verify that ALL fingerprints live in the pre-marker zone. Requiring every
    # fingerprint to appear inside the zone prevents a false positive where,
    # for example, "## Rules" is a legitimate user section header before the
    # first marker while the other two fingerprints exist only inside a marker
    # block.
    for fp in LEGACY_PERSONA_FINGERPRINTS:
        if fp not in zone:
            return content

    if first_marker_idx < 0:
        # No markers at all — the entire file is legacy persona content.
        # Return empty string so the caller can write a fresh section.
        return ""

    # Keep everything from the first marker onwards, trimming any leading
    # blank lines between the stripped block and the first marker.
    return content[first_marker_idx:].lstrip("\r\n")


def find_line_start(s: str, needle: str) -> int:
    offset = 0
    while True:
        idx = s.find(needle, offset)
        if idx < 0:
            return -1
        if idx == 0 or s[idx - 1] == "\n":
            return idx
        # Not at line start — continue searching after this occurrence.
        offset = idx + 1
        if offset >= len(s):
            return -1


def remove_line_start_markers(content: str, marker: str) -> str:
    while True:
        idx = find_line_start(content, marker)
        if idx < 0:
            return content
        end = idx + len(marker)
        # Also consume a trailing line ending (\r\n or \n) if present.
        if end < len(content) and content[end] == "\r":
            end += 1
        if end < len(content) and content[end] == "\n":
            end += 1
        content = content[:idx] + content[end:]


def strip_legacy_atl_block(content: str) -> str:
    while True:
        begin_idx = find_line_start(content, ATL_BEGIN_MARKER)
        if begin_idx < 0:
            # No (more) BEGIN marker — exit the loop and do post-loop cleanup.
            break

        # Search for the END marker starting from after the BEGIN marker so
        # that a stray END marker appearing before BEGIN does not prevent the
        # valid pair from being found.
        search_from = begin_idx + len(ATL_BEGIN_MARKER)
        rel_end_idx = find_line_start(content[search_from:], ATL_END_MARKER)
        if rel_end_idx < 0:
            # Open marker found but no matching close marker — break so that
            # post-loop cleanup still runs (e.g. orphan END markers are removed).
            break
        end_idx = search_from + rel_end_idx

        # Cut out the entire block including both markers.
        before = content[:begin_idx]
        after = content[end_idx + len(ATL_END_MARKER) :]

        # Trim trailing blank lines from the before segment and leading blank
        # lines from the after segment.
        before = before.rstrip("\r\n")
        after = after.lstrip("\r\n")

        if before == "" and after == "":
            content = ""
            continue

        parts: list[str] = []
        if before != "":
            parts.append(before)
            parts.append("\n")
        if after != "":
            if before != "":
                parts.append("\n")
            parts.append(after)
        content = "".join(parts)

    # Remove any orphan markers left behind. A stray END can appear before a
    # valid BEGIN...END pair; a stray BEGIN can appear without a matching END
    # (e.g. a partial manual edit). The loop only strips complete pairs, so
    # leftover markers must be cleaned up here.
    content = remove_line_start_markers(content, ATL_END_MARKER)
    content = remove_line_start_markers(content, ATL_BEGIN_MARKER)

    # Collapse any triple+ newlines into double newlines (done once here,
    # outside the loop, to avoid O(N × content_length) work for N blocks).
    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")

    return content


def inject_markdown_section(existing: str, section_id: str, content: str) -> str:
    open_mark = open_marker(section_id)
    close_mark = close_marker(section_id)

    open_idx = existing.find(open_mark)
    close_idx = existing.find(close_mark)

    # If both markers are found and in the correct order, replace the section.
    if open_idx >= 0 and close_idx >= 0 and close_idx > open_idx:
        # If content is empty, remove the entire section including markers.
        if content == "":
            before = existing[:open_idx]
            after = existing[close_idx + len(close_mark) :]

            # Clean up trailing newline after close marker.
            if len(after) > 0 and after[0] == "\n":
                after = after[1:]
            # Clean up trailing newline before open marker.
            result = before.rstrip("\n")
            if after != "":
                if result != "":
                    result += "\n"
                result += after
            elif result != "":
                result += "\n"
            return result

        before = existing[:open_idx]
        after = existing[close_idx + len(close_mark) :]

        parts = [before, open_mark, "\n", content]
        if not content.endswith("\n"):
            parts.append("\n")
        parts.append(close_mark)
        parts.append(after)
        return "".join(parts)

    # If content is empty and section doesn't exist, return existing unchanged.
    if content == "":
        return existing

    # Section not found — append at end.
    parts = [existing]
    if existing != "" and not existing.endswith("\n"):
        parts.append("\n")
    if existing != "":
        parts.append("\n")
    parts.append(open_mark)
    parts.append("\n")
    parts.append(content)
    if not content.endswith("\n"):
        parts.append("\n")
    parts.append(close_mark)
    parts.append("\n")
    return "".join(parts)

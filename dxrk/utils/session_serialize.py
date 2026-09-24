# SPDX-License-Identifier: MIT
"""Session serialization to JSON, Markdown, HTML, and XML."""

from __future__ import annotations

import json

from dxrk.utils.session_codec import _session_from_dict, _session_to_dict
from dxrk.utils.session_model import RoleAssistant, Session, SessionError, _fmt_rfc3339

# ─── serialization ─────────────────────────────────────────────────────────


class Format:
    JSON = 0
    Markdown = 1
    HTML = 2
    XML = 3


_GO_QUOTE_CHARS = {'"': r"\"", "\\": r"\\", "\n": r"\n", "\t": r"\t", "\r": r"\r"}


def _go_quote(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _GO_QUOTE_CHARS:
            out.append(_GO_QUOTE_CHARS[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def serialize(s: Session, format: int) -> str:
    if format == Format.JSON:
        return export_json(s)
    if format == Format.Markdown:
        return export_markdown(s)
    if format == Format.HTML:
        return export_html(s)
    if format == Format.XML:
        return export_xml(s)
    raise SessionError(f"unsupported format: {format}")


def deserialize(data: str, format: int) -> Session:
    if format != Format.JSON:
        raise SessionError("deserialize only supports JSON")
    return import_json(data)


def export_json(s: Session) -> str:
    return json.dumps(_session_to_dict(s), indent=2)


def import_json(data: str) -> Session:
    try:
        return _session_from_dict(json.loads(data))
    except (ValueError, TypeError) as e:
        raise SessionError(f"unmarshal session: {e}") from e


def compact_json(data: str) -> str:
    try:
        s = _session_from_dict(json.loads(data))
    except (ValueError, TypeError) as e:
        raise SessionError(str(e)) from e
    s.messages = []
    s.summary = ""
    return json.dumps(_session_to_dict(s), indent=2)


def _title_english(s: str) -> str:
    return " ".join(word.capitalize() for word in s.split())


def export_markdown(s: Session) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(f"session_id: {s.id}")
    if s.parent_id:
        lines.append(f"parent_id: {s.parent_id}")
    lines.append(f"title: {_go_quote(s.title)}")
    lines.append(f"model: {s.model}")
    lines.append(f"created_at: {_fmt_rfc3339(s.created_at) if s.created_at else ''}")
    lines.append(f"updated_at: {_fmt_rfc3339(s.updated_at) if s.updated_at else ''}")
    lines.append(f"status: {s.status}")
    lines.append(f"messages: {s.message_count}")
    lines.append(f"tokens: {s.token_count}")
    if s.tags:
        lines.append(f"tags: [{', '.join(s.tags)}]")
    lines.append("---")
    lines.append("")
    lines.append(f"# {s.title}")
    lines.append("")
    if s.summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(s.summary)
        lines.append("")
    for msg in s.messages:
        lines.append(f"### {_title_english(str(msg.role))}")
        ts = msg.timestamp.strftime("%Y-%m-%d %H:%M:%S") if msg.timestamp else ""
        lines.append(f"*{ts}*")
        lines.append("")
        if msg.content:
            if msg.role == RoleAssistant:
                lines.append("```")
                lines.append(msg.content)
                lines.append("```")
                lines.append("")
            else:
                lines.append(msg.content)
                lines.append("")
        for tc in msg.tool_calls:
            lines.append(f"**Tool: {tc.name}**")
            if tc.input:
                lines.append(f"Input: `{tc.input}`")
            if tc.output:
                lines.append(f"Output: `{tc.output}`")
            if tc.error:
                lines.append(f"Error: `{tc.error}`")
            lines.append("")
    return "\n".join(lines)


def export_html(s: Session) -> str:
    lines: list[str] = []
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    lines.append(f"<title>{html_escape(s.title)}</title>")
    lines.append(
        "<style>body{font-family:system-ui,sans-serif;max-width:800px;margin:0 auto;padding:2rem;line-height:1.6}"
    )
    lines.append("h1{border-bottom:2px solid #333;padding-bottom:.5rem}")
    lines.append(".msg{margin:1.5rem 0;padding:1rem;border-radius:8px;border-left:4px solid #ccc}")
    lines.append(".msg-user{background:#f0f7ff;border-color:#4a9eff}")
    lines.append(".msg-assistant{background:#f5fff0;border-color:#4aff4a}")
    lines.append(".msg-system{background:#fff8f0;border-color:#ffaa4a}")
    lines.append(".role{font-weight:bold;text-transform:capitalize}")
    lines.append(".time{color:#888;font-size:.85em}")
    lines.append("pre{background:#f4f4f4;padding:1rem;overflow-x:auto;border-radius:4px}")
    lines.append("code{background:#f4f4f4;padding:.15em .3em;border-radius:3px;font-size:.9em}")
    lines.append("</style></head><body>")
    lines.append("")
    lines.append(f"<h1>{html_escape(s.title)}</h1>")
    lines.append(
        f"<p><strong>Model:</strong> {html_escape(s.model)} &mdash; <strong>Messages:</strong> "
        f"{s.message_count} &mdash; <strong>Tokens:</strong> {s.token_count}</p>"
    )
    created = _fmt_rfc3339(s.created_at) if s.created_at else ""
    updated = _fmt_rfc3339(s.updated_at) if s.updated_at else ""
    lines.append(f"<p><em>Created: {created} &mdash; Updated: {updated} &mdash; Status: {s.status}</em></p>")
    lines.append("")
    if s.summary:
        lines.append(f"<h2>Summary</h2><div>{html_escape(s.summary)}</div>")
    for msg in s.messages:
        lines.append(f'<div class="msg msg-{msg.role}">')
        ts = _fmt_rfc3339(msg.timestamp) if msg.timestamp else ""
        lines.append(f'<span class="role">{html_escape(str(msg.role))}</span> <span class="time">{ts}</span>')
        if msg.content:
            lines.append(f"<pre><code>{html_escape(msg.content)}</code></pre>")
        for tc in msg.tool_calls:
            err = f" <em>(error: {html_escape(tc.error)})</em>" if tc.error else ""
            lines.append(f'<div class="tool-call"><strong>Tool: {html_escape(tc.name)}</strong>{err}</div>')
        lines.append("</div>")
    lines.append("</body></html>")
    return "\n".join(lines)


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&#34;").replace("'", "&#39;")


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def export_xml(s: Session) -> str:
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append("<session>")
    lines.append(f"  <id>{xml_escape(s.id)}</id>")
    lines.append(f"  <title>{xml_escape(s.title)}</title>")
    lines.append(f"  <model>{xml_escape(s.model)}</model>")
    lines.append(f"  <status>{s.status}</status>")
    lines.append(f"  <created_at>{_fmt_rfc3339(s.created_at) if s.created_at else ''}</created_at>")
    lines.append(f"  <updated_at>{_fmt_rfc3339(s.updated_at) if s.updated_at else ''}</updated_at>")
    lines.append(f"  <message_count>{s.message_count}</message_count>")
    lines.append(f"  <token_count>{s.token_count}</token_count>")
    if s.summary:
        lines.append(f"  <summary>{xml_escape(s.summary)}</summary>")
    lines.append("  <messages>")
    for msg in s.messages:
        lines.append("    <message>")
        ts = _fmt_rfc3339(msg.timestamp) if msg.timestamp else ""
        lines.append(f"      <id>{xml_escape(msg.id)}</id>")
        lines.append(f"      <role>{msg.role}</role>")
        lines.append(f"      <timestamp>{ts}</timestamp>")
        if msg.content:
            lines.append(f"      <content>{xml_escape(msg.content)}</content>")
        for tc in msg.tool_calls:
            lines.append("      <tool_call>")
            lines.append(f"        <name>{xml_escape(tc.name)}</name>")
            lines.append(f"        <input>{xml_escape(tc.input)}</input>")
            if tc.output:
                lines.append(f"        <output>{xml_escape(tc.output)}</output>")
            lines.append("      </tool_call>")
        lines.append("    </message>")
    lines.append("  </messages>")
    lines.append("</session>")
    return "\n".join(lines)


Serialize = serialize
Deserialize = deserialize
ExportJSON = export_json
ImportJSON = import_json
CompactJSON = compact_json
ExportMarkdown = export_markdown
ExportHTML = export_html
ExportXML = export_xml

# SPDX-License-Identifier: MIT
"""Session utils

Session persistence, serialization, restore, and management utilities:
a canonical session model, pluggable storage backends, JSON/Markdown/HTML/XML
serialization, and a version migration framework."""

from __future__ import annotations

import gzip as gzip
import os as os

__all__ = [
    "CurrentVersion",
    "SessionStatus",
    "MessageRole",
    "Session",
    "Message",
    "ToolCall",
    "SessionOpts",
    "SessionError",
    "Storage",
    "SessionSummary",
    "ListOpts",
    "FileStorage",
    "MemoryStorage",
    "SQLiteSessionStorage",
    "NewSQLiteSessionStorage",
    "JsonToSqliteResult",
    "open_session_storage",
    "migrate_json_dir_to_sqlite",
    "SESSION_BACKEND_ENV_VAR",
    "Serialize",
    "Deserialize",
    "ExportJSON",
    "ImportJSON",
    "CompactJSON",
    "ExportMarkdown",
    "ExportHTML",
    "ExportXML",
    "ResumeContext",
    "ResumeCriteria",
    "RestoreSession",
    "ResumeSession",
    "CreateSummary",
    "FindResumePoint",
    "AutoArchive",
    "CleanupExpired",
    "RegisterMigration",
    "MigrateSession",
    "ListMigrations",
    "HasMigration",
    "DetectVersion",
    "MigrateToCurrent",
]

from dxrk.utils.session_codec import _index_entry_from_dict as _index_entry_from_dict
from dxrk.utils.session_codec import _index_entry_to_dict as _index_entry_to_dict
from dxrk.utils.session_codec import _message_from_dict as _message_from_dict
from dxrk.utils.session_codec import _message_to_dict as _message_to_dict
from dxrk.utils.session_codec import _parse_role as _parse_role
from dxrk.utils.session_codec import _session_from_dict as _session_from_dict
from dxrk.utils.session_codec import _session_to_dict as _session_to_dict
from dxrk.utils.session_codec import _tool_call_from_dict as _tool_call_from_dict
from dxrk.utils.session_codec import _tool_call_to_dict as _tool_call_to_dict
from dxrk.utils.session_migrate import DetectVersion as DetectVersion
from dxrk.utils.session_migrate import HasMigration as HasMigration
from dxrk.utils.session_migrate import ListMigrations as ListMigrations
from dxrk.utils.session_migrate import MigrateSession as MigrateSession
from dxrk.utils.session_migrate import MigrateToCurrent as MigrateToCurrent
from dxrk.utils.session_migrate import MigrationFunc as MigrationFunc
from dxrk.utils.session_migrate import RegisterMigration as RegisterMigration
from dxrk.utils.session_migrate import _build_migrations as _build_migrations
from dxrk.utils.session_migrate import _migrations as _migrations
from dxrk.utils.session_migrate import _migrations_built as _migrations_built
from dxrk.utils.session_migrate import _migrations_mu as _migrations_mu
from dxrk.utils.session_migrate import detect_version as detect_version
from dxrk.utils.session_migrate import find_migration as find_migration
from dxrk.utils.session_migrate import has_migration as has_migration
from dxrk.utils.session_migrate import list_migrations as list_migrations
from dxrk.utils.session_migrate import migrate_session as migrate_session
from dxrk.utils.session_migrate import migrate_to_current as migrate_to_current
from dxrk.utils.session_migrate import register_migration as register_migration
from dxrk.utils.session_model import _EPOCH_UTC as _EPOCH_UTC
from dxrk.utils.session_model import _STATUS_BY_NAME as _STATUS_BY_NAME
from dxrk.utils.session_model import _STATUS_NAMES as _STATUS_NAMES
from dxrk.utils.session_model import CurrentVersion as CurrentVersion
from dxrk.utils.session_model import Message as Message
from dxrk.utils.session_model import MessageRole as MessageRole
from dxrk.utils.session_model import NewSession as NewSession
from dxrk.utils.session_model import RoleAssistant as RoleAssistant
from dxrk.utils.session_model import RoleSystem as RoleSystem
from dxrk.utils.session_model import RoleToolResult as RoleToolResult
from dxrk.utils.session_model import RoleToolUse as RoleToolUse
from dxrk.utils.session_model import RoleUser as RoleUser
from dxrk.utils.session_model import Session as Session
from dxrk.utils.session_model import SessionError as SessionError
from dxrk.utils.session_model import SessionOpts as SessionOpts
from dxrk.utils.session_model import SessionStatus as SessionStatus
from dxrk.utils.session_model import ToolCall as ToolCall
from dxrk.utils.session_model import _fmt_rfc3339 as _fmt_rfc3339
from dxrk.utils.session_model import _fmt_ts as _fmt_ts
from dxrk.utils.session_model import _from_ts as _from_ts
from dxrk.utils.session_model import estimate_tokens as estimate_tokens
from dxrk.utils.session_model import generate_id as generate_id
from dxrk.utils.session_model import new_session as new_session
from dxrk.utils.session_model import now as now
from dxrk.utils.session_restore import AutoArchive as AutoArchive
from dxrk.utils.session_restore import CleanupExpired as CleanupExpired
from dxrk.utils.session_restore import CreateSummary as CreateSummary
from dxrk.utils.session_restore import FindResumePoint as FindResumePoint
from dxrk.utils.session_restore import RestoreSession as RestoreSession
from dxrk.utils.session_restore import ResumeContext as ResumeContext
from dxrk.utils.session_restore import ResumeCriteria as ResumeCriteria
from dxrk.utils.session_restore import ResumeSession as ResumeSession
from dxrk.utils.session_restore import _build_incremental_summary as _build_incremental_summary
from dxrk.utils.session_restore import _build_message_summary as _build_message_summary
from dxrk.utils.session_restore import _collect_pending_tool_calls as _collect_pending_tool_calls
from dxrk.utils.session_restore import auto_archive as auto_archive
from dxrk.utils.session_restore import cleanup_expired as cleanup_expired
from dxrk.utils.session_restore import create_summary as create_summary
from dxrk.utils.session_restore import find_resume_point as find_resume_point
from dxrk.utils.session_restore import restore_session as restore_session
from dxrk.utils.session_restore import resume_session as resume_session
from dxrk.utils.session_restore import truncate as truncate
from dxrk.utils.session_serialize import _GO_QUOTE_CHARS as _GO_QUOTE_CHARS
from dxrk.utils.session_serialize import CompactJSON as CompactJSON
from dxrk.utils.session_serialize import Deserialize as Deserialize
from dxrk.utils.session_serialize import ExportHTML as ExportHTML
from dxrk.utils.session_serialize import ExportJSON as ExportJSON
from dxrk.utils.session_serialize import ExportMarkdown as ExportMarkdown
from dxrk.utils.session_serialize import ExportXML as ExportXML
from dxrk.utils.session_serialize import Format as Format
from dxrk.utils.session_serialize import ImportJSON as ImportJSON
from dxrk.utils.session_serialize import Serialize as Serialize
from dxrk.utils.session_serialize import _go_quote as _go_quote
from dxrk.utils.session_serialize import _title_english as _title_english
from dxrk.utils.session_serialize import compact_json as compact_json
from dxrk.utils.session_serialize import deserialize as deserialize
from dxrk.utils.session_serialize import export_html as export_html
from dxrk.utils.session_serialize import export_json as export_json
from dxrk.utils.session_serialize import export_markdown as export_markdown
from dxrk.utils.session_serialize import export_xml as export_xml
from dxrk.utils.session_serialize import html_escape as html_escape
from dxrk.utils.session_serialize import import_json as import_json
from dxrk.utils.session_serialize import serialize as serialize
from dxrk.utils.session_serialize import xml_escape as xml_escape
from dxrk.utils.session_storage import _SQLITE_SCHEMA as _SQLITE_SCHEMA
from dxrk.utils.session_storage import SESSION_BACKEND_ENV_VAR as SESSION_BACKEND_ENV_VAR
from dxrk.utils.session_storage import FileStorage as FileStorage
from dxrk.utils.session_storage import JsonToSqliteResult as JsonToSqliteResult
from dxrk.utils.session_storage import ListOpts as ListOpts
from dxrk.utils.session_storage import MemoryStorage as MemoryStorage
from dxrk.utils.session_storage import NewFileStorage as NewFileStorage
from dxrk.utils.session_storage import NewMemoryStorage as NewMemoryStorage
from dxrk.utils.session_storage import NewSQLiteSessionStorage as NewSQLiteSessionStorage
from dxrk.utils.session_storage import SessionSummary as SessionSummary
from dxrk.utils.session_storage import SQLiteSessionStorage as SQLiteSessionStorage
from dxrk.utils.session_storage import Storage as Storage
from dxrk.utils.session_storage import _atomic_write_bytes as _atomic_write_bytes
from dxrk.utils.session_storage import _atomic_write_gz_bytes as _atomic_write_gz_bytes
from dxrk.utils.session_storage import _atomic_write_text as _atomic_write_text
from dxrk.utils.session_storage import _cmp_int as _cmp_int
from dxrk.utils.session_storage import _cmp_time as _cmp_time
from dxrk.utils.session_storage import _fsync_parent as _fsync_parent
from dxrk.utils.session_storage import _migrated_or_raw as _migrated_or_raw
from dxrk.utils.session_storage import _parse_session_payload as _parse_session_payload
from dxrk.utils.session_storage import _read_gz_file as _read_gz_file
from dxrk.utils.session_storage import _sqlite_ts as _sqlite_ts
from dxrk.utils.session_storage import _summaries_from_entries as _summaries_from_entries
from dxrk.utils.session_storage import _validate_session_id as _validate_session_id
from dxrk.utils.session_storage import migrate_json_dir_to_sqlite as migrate_json_dir_to_sqlite
from dxrk.utils.session_storage import open_session_storage as open_session_storage

# SPDX-License-Identifier: MIT
"""File merging, markdown section injection, TOML upserts and atomic writes."""

from __future__ import annotations

import json as json
import os as os
import stat as stat
import sys as sys
import tempfile as tempfile

from dxrk.utils.filemerge_atomic import MAX_ATOMIC_FILE_SIZE as MAX_ATOMIC_FILE_SIZE
from dxrk.utils.filemerge_atomic import WriteResult as WriteResult
from dxrk.utils.filemerge_atomic import _default_sync_dir as _default_sync_dir
from dxrk.utils.filemerge_atomic import _runtime_goos as _runtime_goos
from dxrk.utils.filemerge_atomic import _sync_dir_fn as _sync_dir_fn
from dxrk.utils.filemerge_atomic import ensure_atomic_parent_dir as ensure_atomic_parent_dir
from dxrk.utils.filemerge_atomic import read_comparable_file as read_comparable_file
from dxrk.utils.filemerge_atomic import write_file_atomic as write_file_atomic
from dxrk.utils.filemerge_json import REPLACE_SENTINEL as REPLACE_SENTINEL
from dxrk.utils.filemerge_json import as_sentinel as as_sentinel
from dxrk.utils.filemerge_json import merge_json_objects as merge_json_objects
from dxrk.utils.filemerge_json import merge_objects as merge_objects
from dxrk.utils.filemerge_json import normalize_json as normalize_json
from dxrk.utils.filemerge_json import strip_json_comments as strip_json_comments
from dxrk.utils.filemerge_json import strip_trailing_commas as strip_trailing_commas
from dxrk.utils.filemerge_json import unmarshal_json_object as unmarshal_json_object
from dxrk.utils.filemerge_markdown import ATL_BEGIN_MARKER as ATL_BEGIN_MARKER
from dxrk.utils.filemerge_markdown import ATL_END_MARKER as ATL_END_MARKER
from dxrk.utils.filemerge_markdown import CLOSE_PREFIX as CLOSE_PREFIX
from dxrk.utils.filemerge_markdown import LEGACY_PERSONA_FINGERPRINTS as LEGACY_PERSONA_FINGERPRINTS
from dxrk.utils.filemerge_markdown import MARKER_PREFIX as MARKER_PREFIX
from dxrk.utils.filemerge_markdown import MARKER_SUFFIX as MARKER_SUFFIX
from dxrk.utils.filemerge_markdown import close_marker as close_marker
from dxrk.utils.filemerge_markdown import find_line_start as find_line_start
from dxrk.utils.filemerge_markdown import inject_markdown_section as inject_markdown_section
from dxrk.utils.filemerge_markdown import open_marker as open_marker
from dxrk.utils.filemerge_markdown import remove_line_start_markers as remove_line_start_markers
from dxrk.utils.filemerge_markdown import strip_legacy_atl_block as strip_legacy_atl_block
from dxrk.utils.filemerge_markdown import strip_legacy_persona_block as strip_legacy_persona_block
from dxrk.utils.filemerge_toml import go_quote as go_quote
from dxrk.utils.filemerge_toml import toml_quote as toml_quote
from dxrk.utils.filemerge_toml import upsert_codex_dxrk_memory_block as upsert_codex_dxrk_memory_block
from dxrk.utils.filemerge_toml import upsert_codex_mcp_server_block as upsert_codex_mcp_server_block
from dxrk.utils.filemerge_toml import upsert_top_level_toml_string as upsert_top_level_toml_string

# Aliases
MergeJSONObjects = merge_json_objects
StripLegacyATLBlock = strip_legacy_atl_block
StripLegacyPersonaBlock = strip_legacy_persona_block
InjectMarkdownSection = inject_markdown_section
UpsertCodexMCPServerBlock = upsert_codex_mcp_server_block
UpsertCodexDxrkMemoryBlock = upsert_codex_dxrk_memory_block
UpsertTopLevelTOMLString = upsert_top_level_toml_string
WriteFileAtomic = write_file_atomic

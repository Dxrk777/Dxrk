# SPDX-License-Identifier: MIT
"""File operation utilities.

Provides safe, cached, atomic file operations with encoding detection:
path validation and utilities, safe reading with encoding detection,
binary detection, atomic writes, search-and-replace editing with
indentation preservation and regex support, and a thread-safe LRU
file-content cache with TTL and modification-time auto-invalidation.

Concurrency mapping:

* ``sync.RWMutex`` -> ``threading.RLock`` / ``threading.Lock``
* ``time.Time`` -> ``datetime`` (wall clock)
* ``time.Duration`` -> ``datetime.timedelta``
* goroutines -> daemon threads
* ``errors.New`` sentinels -> :class:`FileopsError` instances returned
  as values (never raised)

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``ValidatePath`` splits on the OS separator and rejects any ``..``
  component.
* ``DetectEncoding`` returns the same labels (UTF-8, UTF-8-BOM,
  UTF-16LE, UTF-16BE, ASCII, Latin-1, Unknown).
* ``ReadFile`` never uses mmap; the original read is a plain
  ``io.ReadAll`` fallback, so both languages read the whole file.
* ``InvalidatePattern`` matches globs against the base name with
  ``fnmatch``, ``fnmatch``-style matching for names without
  path separators.
* ``splitChars``-style byte splitting does not apply here; Python
  strings are Unicode, so content is decoded with replacement.
* ``EditError`` mirrors the original struct plus its ``Error()`` formatting.
* ``ReadImage`` requires Pillow the original decodes
  image headers via the standard library.
"""

from __future__ import annotations

import base64 as base64
import fnmatch as fnmatch
import io as io
import os as os
import shutil as shutil
import sys as sys
import tempfile as tempfile
import threading as threading

from dxrk.utils.fileops_cache import _WATCH_INTERVAL as _WATCH_INTERVAL
from dxrk.utils.fileops_cache import CacheEntry as CacheEntry
from dxrk.utils.fileops_cache import CacheStats as CacheStats
from dxrk.utils.fileops_cache import FileCache as FileCache
from dxrk.utils.fileops_cache import NewFileCache as NewFileCache
from dxrk.utils.fileops_cache import new_file_cache as new_file_cache
from dxrk.utils.fileops_edit import ApplyEdits as ApplyEdits
from dxrk.utils.fileops_edit import ApplyRegexEdits as ApplyRegexEdits
from dxrk.utils.fileops_edit import EditError as EditError
from dxrk.utils.fileops_edit import EditFile as EditFile
from dxrk.utils.fileops_edit import EditFileRegex as EditFileRegex
from dxrk.utils.fileops_edit import EditOp as EditOp
from dxrk.utils.fileops_edit import FindAndReplace as FindAndReplace
from dxrk.utils.fileops_edit import FindAndReplaceAll as FindAndReplaceAll
from dxrk.utils.fileops_edit import RegexEditOp as RegexEditOp
from dxrk.utils.fileops_edit import ValidateEdits as ValidateEdits
from dxrk.utils.fileops_edit import _extract_indent as _extract_indent
from dxrk.utils.fileops_edit import _preserve_indent as _preserve_indent
from dxrk.utils.fileops_edit import _re as _re
from dxrk.utils.fileops_edit import apply_edits as apply_edits
from dxrk.utils.fileops_edit import apply_regex_edits as apply_regex_edits
from dxrk.utils.fileops_edit import edit_file as edit_file
from dxrk.utils.fileops_edit import edit_file_regex as edit_file_regex
from dxrk.utils.fileops_edit import find_and_replace as find_and_replace
from dxrk.utils.fileops_edit import find_and_replace_all as find_and_replace_all
from dxrk.utils.fileops_edit import validate_edits as validate_edits
from dxrk.utils.fileops_errors import ErrBinaryFile as ErrBinaryFile
from dxrk.utils.fileops_errors import ErrFileTooLarge as ErrFileTooLarge
from dxrk.utils.fileops_errors import ErrInvalidImage as ErrInvalidImage
from dxrk.utils.fileops_errors import ErrNotAbsolute as ErrNotAbsolute
from dxrk.utils.fileops_errors import ErrNullByte as ErrNullByte
from dxrk.utils.fileops_errors import ErrOutsideDir as ErrOutsideDir
from dxrk.utils.fileops_errors import ErrPathTraversal as ErrPathTraversal
from dxrk.utils.fileops_errors import FileopsError as FileopsError
from dxrk.utils.fileops_errors import ValidatePath as ValidatePath
from dxrk.utils.fileops_errors import validate_path as validate_path
from dxrk.utils.fileops_path import _STAT_IFMT as _STAT_IFMT
from dxrk.utils.fileops_path import _STAT_IFREG as _STAT_IFREG
from dxrk.utils.fileops_path import AbsPath as AbsPath
from dxrk.utils.fileops_path import ChangeExtension as ChangeExtension
from dxrk.utils.fileops_path import CleanPath as CleanPath
from dxrk.utils.fileops_path import DirExists as DirExists
from dxrk.utils.fileops_path import EnsureTrailingSep as EnsureTrailingSep
from dxrk.utils.fileops_path import ExecutableDir as ExecutableDir
from dxrk.utils.fileops_path import ExpandHome as ExpandHome
from dxrk.utils.fileops_path import FileExists as FileExists
from dxrk.utils.fileops_path import GetBaseName as GetBaseName
from dxrk.utils.fileops_path import GetExtension as GetExtension
from dxrk.utils.fileops_path import Glob as Glob
from dxrk.utils.fileops_path import HomeDir as HomeDir
from dxrk.utils.fileops_path import IsDir as IsDir
from dxrk.utils.fileops_path import IsFile as IsFile
from dxrk.utils.fileops_path import IsHidden as IsHidden
from dxrk.utils.fileops_path import IsSymlink as IsSymlink
from dxrk.utils.fileops_path import IsWithinDir as IsWithinDir
from dxrk.utils.fileops_path import MkdirTemp as MkdirTemp
from dxrk.utils.fileops_path import NormalizePath as NormalizePath
from dxrk.utils.fileops_path import Platform as Platform
from dxrk.utils.fileops_path import RealPath as RealPath
from dxrk.utils.fileops_path import RelativePath as RelativePath
from dxrk.utils.fileops_path import ResolvePath as ResolvePath
from dxrk.utils.fileops_path import SafeJoin as SafeJoin
from dxrk.utils.fileops_path import SplitPath as SplitPath
from dxrk.utils.fileops_path import TmpDir as TmpDir
from dxrk.utils.fileops_path import TmpFile as TmpFile
from dxrk.utils.fileops_path import UserCacheDir as UserCacheDir
from dxrk.utils.fileops_path import UserConfigDir as UserConfigDir
from dxrk.utils.fileops_path import WalkDir as WalkDir
from dxrk.utils.fileops_path import _glob as _glob
from dxrk.utils.fileops_path import _SkipDir as _SkipDir
from dxrk.utils.fileops_path import _stat as _stat
from dxrk.utils.fileops_path import abs_path as abs_path
from dxrk.utils.fileops_path import change_extension as change_extension
from dxrk.utils.fileops_path import clean_path as clean_path
from dxrk.utils.fileops_path import dir_exists as dir_exists
from dxrk.utils.fileops_path import ensure_trailing_sep as ensure_trailing_sep
from dxrk.utils.fileops_path import executable_dir as executable_dir
from dxrk.utils.fileops_path import expand_home as expand_home
from dxrk.utils.fileops_path import file_exists as file_exists
from dxrk.utils.fileops_path import get_base_name as get_base_name
from dxrk.utils.fileops_path import get_extension as get_extension
from dxrk.utils.fileops_path import glob as glob
from dxrk.utils.fileops_path import home_dir as home_dir
from dxrk.utils.fileops_path import is_dir as is_dir
from dxrk.utils.fileops_path import is_file as is_file
from dxrk.utils.fileops_path import is_hidden as is_hidden
from dxrk.utils.fileops_path import is_symlink as is_symlink
from dxrk.utils.fileops_path import is_within_dir as is_within_dir
from dxrk.utils.fileops_path import mkdir_temp as mkdir_temp
from dxrk.utils.fileops_path import normalize_path as normalize_path
from dxrk.utils.fileops_path import platform as platform
from dxrk.utils.fileops_path import real_path as real_path
from dxrk.utils.fileops_path import relative_path as relative_path
from dxrk.utils.fileops_path import resolve_path as resolve_path
from dxrk.utils.fileops_path import safe_join as safe_join
from dxrk.utils.fileops_path import split_path as split_path
from dxrk.utils.fileops_path import tmp_dir as tmp_dir
from dxrk.utils.fileops_path import tmp_file as tmp_file
from dxrk.utils.fileops_path import user_cache_dir as user_cache_dir
from dxrk.utils.fileops_path import user_config_dir as user_config_dir
from dxrk.utils.fileops_path import walk_dir as walk_dir
from dxrk.utils.fileops_read import _BINARY_CHECK_SIZE as _BINARY_CHECK_SIZE
from dxrk.utils.fileops_read import _MAX_TEXT_SIZE as _MAX_TEXT_SIZE
from dxrk.utils.fileops_read import _PILLOW_REQUIRED as _PILLOW_REQUIRED
from dxrk.utils.fileops_read import _READ_LIMIT_DEFAULT as _READ_LIMIT_DEFAULT
from dxrk.utils.fileops_read import DetectEncoding as DetectEncoding
from dxrk.utils.fileops_read import FileContent as FileContent
from dxrk.utils.fileops_read import ImageData as ImageData
from dxrk.utils.fileops_read import IsBinary as IsBinary
from dxrk.utils.fileops_read import ReadFile as ReadFile
from dxrk.utils.fileops_read import ReadFileLines as ReadFileLines
from dxrk.utils.fileops_read import ReadImage as ReadImage
from dxrk.utils.fileops_read import _PILImage as _PILImage
from dxrk.utils.fileops_read import detect_encoding as detect_encoding
from dxrk.utils.fileops_read import is_binary as is_binary
from dxrk.utils.fileops_read import read_file as read_file
from dxrk.utils.fileops_read import read_file_lines as read_file_lines
from dxrk.utils.fileops_read import read_image as read_image
from dxrk.utils.fileops_write import AppendFile as AppendFile
from dxrk.utils.fileops_write import BackupFile as BackupFile
from dxrk.utils.fileops_write import DefaultWriteOpts as DefaultWriteOpts
from dxrk.utils.fileops_write import EnsureDir as EnsureDir
from dxrk.utils.fileops_write import WriteAtomic as WriteAtomic
from dxrk.utils.fileops_write import WriteFile as WriteFile
from dxrk.utils.fileops_write import WriteLines as WriteLines
from dxrk.utils.fileops_write import WriteOpts as WriteOpts
from dxrk.utils.fileops_write import append_file as append_file
from dxrk.utils.fileops_write import backup_file as backup_file
from dxrk.utils.fileops_write import default_write_opts as default_write_opts
from dxrk.utils.fileops_write import ensure_dir as ensure_dir
from dxrk.utils.fileops_write import write_atomic as write_atomic
from dxrk.utils.fileops_write import write_file as write_file
from dxrk.utils.fileops_write import write_lines as write_lines

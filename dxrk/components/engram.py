# SPDX-License-Identifier: MIT
"""Engram component — ports internal/components/engram/.

Install, setup, download, inject, verify.
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from urllib.request import Request, urlopen

from dxrk.components import filemerge
from dxrk.components.assets import must_read
from dxrk.models import AgentID
from dxrk.system import PlatformProfile

# ─── Config / Setup ────────────────────────────────────────────────────────

SETUP_MODE_ENV_VAR = "GENTLE_AI_ENGRAM_SETUP_MODE"
SETUP_STRICT_ENV_VAR = "GENTLE_AI_ENGRAM_SETUP_STRICT"


class SetupMode:
    OFF = "off"
    OPENCODE = "opencode"
    SUPPORTED = "supported"


def parse_setup_mode(value: str) -> str:
    v = value.strip().lower()
    if v == SetupMode.OFF:
        return SetupMode.OFF
    if v == SetupMode.OPENCODE:
        return SetupMode.OPENCODE
    if v in ("", SetupMode.SUPPORTED):
        return SetupMode.SUPPORTED
    return SetupMode.SUPPORTED


def parse_setup_strict(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def setup_agent_slug(agent: AgentID) -> tuple[str, bool]:
    mapping: dict[AgentID, str] = {
        AgentID.OPENCODE: "opencode",
        AgentID.KILOCODE: "kilocode",
        AgentID.CLAUDE_CODE: "claude-code",
        AgentID.GEMINI_CLI: "gemini-cli",
        AgentID.CODEX: "codex",
        AgentID.WINDSURF: "windsurf",
    }
    if slug := mapping.get(agent):
        return slug, True
    if agent == AgentID.ANTIGRAVITY:
        return "gemini-cli", True
    return "", False


def should_attempt_setup(mode: str, agent: AgentID) -> bool:
    slug, ok = setup_agent_slug(agent)
    if not ok:
        return False
    if mode == SetupMode.OFF:
        return False
    if mode == SetupMode.OPENCODE:
        return slug == "opencode"
    return True


# ─── Injection ─────────────────────────────────────────────────────────────


@dataclass
class InjectionResult:
    Changed: bool = False
    Files: list[str] = field(default_factory=list)


_DXRK_MEMORY_look_path: Callable[[str], str | None] = shutil.which


def set_look_path_for_test(
    mock: Callable[[str], str | None],
) -> Callable[[str], str | None]:
    global _DXRK_MEMORY_look_path
    orig = _DXRK_MEMORY_look_path
    _DXRK_MEMORY_look_path = mock
    return orig


def _resolve_DXRK_MEMORY_command() -> tuple[str, bool]:
    p = _DXRK_MEMORY_look_path("DXRK_MEMORY")
    if not p:
        return "DXRK_MEMORY", False
    if _is_versioned_homebrew_cellar_path(p):
        return "DXRK_MEMORY", False
    return p, True


def _DXRK_MEMORY_server_json() -> bytes:
    cmd, _ = _resolve_DXRK_MEMORY_command()
    return _DXRK_MEMORY_server_json_with_cmd(cmd)


def _DXRK_MEMORY_server_json_with_cmd(cmd: str) -> bytes:
    cfg = {"command": cmd, "args": ["mcp", "--tools=agent"]}
    return (json.dumps(cfg, indent=2) + "\n").encode("utf-8")


def _DXRK_MEMORY_overlay_json(agent_id: AgentID, cmd: str) -> bytes:
    if agent_id in (AgentID.OPENCODE, AgentID.KILOCODE):
        cfg: dict[str, Any] = {
            "mcp": {
                "DXRK_MEMORY": {
                    "__replace__": {
                        "command": [cmd, "mcp", "--tools=agent"],
                        "type": "local",
                    }
                }
            }
        }
    else:
        cfg = {
            "mcpServers": {
                "DXRK_MEMORY": {
                    "command": cmd,
                    "args": ["mcp", "--tools=agent"],
                }
            }
        }
    return (json.dumps(cfg, indent=2) + "\n").encode("utf-8")


def _vs_code_DXRK_MEMORY_overlay_json(cmd: str) -> bytes:
    cfg = {
        "servers": {
            "DXRK_MEMORY": {
                "command": cmd,
                "args": ["mcp", "--tools=agent"],
            }
        }
    }
    return (json.dumps(cfg, indent=2) + "\n").encode("utf-8")


def inject(home_dir: str, adapter) -> InjectionResult:
    if not adapter.supports_mcp:
        return InjectionResult()

    files: list[str] = []
    changed = False

    strategy = adapter.mcp_strategy
    from dxrk.models import MCPStrategy

    if strategy == MCPStrategy.SEPARATE_MCP_FILES:
        mcp_path = adapter.mcp_config_path(home_dir, "DXRK_MEMORY")
        cmd = _stable_DXRK_MEMORY_command_for_merged_config(mcp_path, adapter.agent)
        content = _build_separate_mcp_content(
            mcp_path, _DXRK_MEMORY_server_json_with_cmd(cmd)
        )
        wr = filemerge.write_file_atomic(mcp_path, content, 0o644)
        changed = changed or wr.Changed
        files.append(mcp_path)

    elif strategy == MCPStrategy.MERGE_INTO_SETTINGS:
        settings_path = adapter.settings_path(home_dir)
        if settings_path:
            cmd = _stable_DXRK_MEMORY_command_for_merged_config(
                settings_path, adapter.agent
            )
            overlay = _DXRK_MEMORY_overlay_json(adapter.agent, cmd)
            sw, _ = _merge_json_file(settings_path, overlay)
            changed = changed or sw.Changed
            files.append(settings_path)

    elif strategy == MCPStrategy.MCP_CONFIG_FILE:
        mcp_path = adapter.mcp_config_path(home_dir, "DXRK_MEMORY")
        if mcp_path:
            cmd = _stable_DXRK_MEMORY_command_for_merged_config(mcp_path, adapter.agent)
            if adapter.agent == AgentID.VSCODE_COPILOT:
                overlay = _vs_code_DXRK_MEMORY_overlay_json(cmd)
            else:
                overlay = _DXRK_MEMORY_overlay_json(adapter.agent, cmd)
            mw, _ = _merge_json_file(mcp_path, overlay)
            changed = changed or mw.Changed
            files.append(mcp_path)

            if adapter.agent == AgentID.ANTIGRAVITY:
                sr = _ensure_antigravity_settings(home_dir, adapter)
                changed = changed or sr.Changed
                if sr.Path:
                    files.append(sr.Path)

    elif strategy == MCPStrategy.TOML_FILE:
        config_path = adapter.mcp_config_path(home_dir, "engram")
        if config_path:
            instr_path, compact_path, instr_err = _write_codex_instruction_files(
                home_dir
            )
            if instr_err:
                return InjectionResult()
            existing = _read_file_or_empty(config_path)
            engram_cmd = _stable_DXRK_MEMORY_command_for_merged_config(
                config_path, adapter.agent
            )
            with_mcp = filemerge.upsert_codex_DXRK_MEMORY_block(existing, engram_cmd)
            with_instr = filemerge.upsert_top_level_toml_string(
                with_mcp, "model_instructions_file", instr_path
            )
            with_compact = filemerge.upsert_top_level_toml_string(
                with_instr, "experimental_compact_prompt_file", compact_path
            )
            tw = filemerge.write_file_atomic(
                config_path, with_compact.encode("utf-8"), 0o644
            )
            changed = changed or tw.Changed
            files.append(config_path)

    # 2. Inject Engram memory protocol into system prompt
    if adapter.supports_system_prompt:
        from dxrk.models import SystemPromptStrategy

        sps = adapter.system_prompt_strategy

        if sps == SystemPromptStrategy.JINJA_MODULES:
            if hasattr(adapter, "bootstrap_template"):
                adapter.bootstrap_template(home_dir)
            config_dir = adapter.global_config_dir(home_dir)
            protocol_content = must_read("claude/engram-protocol.md")
            module_path = os.path.join(config_dir, "DXRK_MEMORY-protocol.md")
            wr = filemerge.write_file_atomic(
                module_path, protocol_content.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            files.append(module_path)
        elif sps in (SystemPromptStrategy.JINJA_MODULES,):
            pass
        else:
            prompt_path = adapter.system_prompt_file(home_dir)
            protocol_content = must_read("claude/engram-protocol.md")
            existing = _read_file_or_empty(prompt_path)
            updated = filemerge.inject_markdown_section(
                existing, "engram-protocol", protocol_content
            )
            wr = filemerge.write_file_atomic(
                prompt_path, updated.encode("utf-8"), 0o644
            )
            changed = changed or wr.Changed
            files.append(prompt_path)

    return InjectionResult(Changed=changed, Files=files)


@dataclass
class _SettingsBootstrapResult:
    Changed: bool = False
    Path: str = ""


def _ensure_antigravity_settings(home_dir: str, adapter) -> _SettingsBootstrapResult:
    settings_path = adapter.settings_path(home_dir)
    if not settings_path:
        return _SettingsBootstrapResult()
    if os.path.exists(settings_path):
        return _SettingsBootstrapResult(Path=settings_path)
    source_path = os.path.join(home_dir, ".gemini", "settings.json")
    try:
        with open(source_path) as f:
            content = f.read()
    except FileNotFoundError:
        content = "{}"
    wr = filemerge.write_file_atomic(settings_path, content.encode("utf-8"), 0o644)
    return _SettingsBootstrapResult(Changed=wr.Changed, Path=settings_path)


def _write_codex_instruction_files(home_dir: str) -> tuple[str, str, str | None]:
    codex_dir = os.path.join(home_dir, ".codex")
    instr_path = os.path.join(codex_dir, "DXRK_MEMORY-instructions.md")
    compact_path = os.path.join(codex_dir, "DXRK_MEMORY-compact-prompt.md")

    instr_content = must_read("codex/dxrk-memory-instructions.md")
    filemerge.write_file_atomic(instr_path, instr_content.encode("utf-8"), 0o644)
    compact_content = must_read("codex/dxrk-memory-compact-prompt.md")
    filemerge.write_file_atomic(compact_path, compact_content.encode("utf-8"), 0o644)
    return instr_path, compact_path, None


# --- JSON file helpers ---


def _merge_json_file(
    path: str, overlay: bytes
) -> tuple[filemerge.WriteResult, bytes | None]:
    base_json = _os_read_file(path)
    merged = filemerge.merge_json_objects(base_json, overlay)
    wr = filemerge.write_file_atomic(path, merged, 0o644)
    return wr, merged


def _os_read_file(path: str) -> bytes:
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return b""
    return b""


def _read_file_or_empty(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _stable_DXRK_MEMORY_command_for_merged_config(path: str, agent_id: AgentID) -> str:
    raw = _os_read_file(path)
    if raw:
        cmd, ok = _existing_merged_DXRK_MEMORY_command(raw, agent_id)
        if ok:
            return _stable_DXRK_MEMORY_command_for_existing(cmd, agent_id)
    if _is_standard_agent(agent_id):
        return _preferred_stable_DXRK_MEMORY_command()
    cmd, _ = _resolve_DXRK_MEMORY_command()
    return cmd


def _stable_DXRK_MEMORY_command_for_existing(
    cmd: str, agent_id: AgentID | None = None
) -> str:
    if _is_versioned_homebrew_cellar_path(cmd):
        stable = _preferred_stable_DXRK_MEMORY_command()
        return stable or "DXRK_MEMORY"
    return cmd


def _preferred_stable_DXRK_MEMORY_command() -> str:
    p = _DXRK_MEMORY_look_path("DXRK_MEMORY")
    if p and _is_stable_homebrew_DXRK_MEMORY_path(p):
        return p
    return "DXRK_MEMORY"


def _existing_merged_DXRK_MEMORY_command(
    raw: bytes, agent_id: AgentID
) -> tuple[str, bool]:
    if not raw:
        return "", False
    try:
        normalized = filemerge.merge_json_objects(raw, b"{}")
    except Exception:
        return "", False
    try:
        root = json.loads(normalized)
    except Exception:
        return "", False

    server = None
    if agent_id == AgentID.OPENCODE:
        mcp = root.get("mcp", {})
        server = mcp.get("DXRK_MEMORY") if isinstance(mcp, dict) else None
    elif agent_id == AgentID.VSCODE_COPILOT:
        servers = root.get("servers", {})
        server = servers.get("DXRK_MEMORY") if isinstance(servers, dict) else None
    else:
        mcp = root.get("mcpServers", {})
        server = mcp.get("DXRK_MEMORY") if isinstance(mcp, dict) else None

    if not isinstance(server, dict):
        return "", False
    return _executable_from_command_value(server.get("command"))


def _executable_from_command_value(command: Any) -> tuple[str, bool]:
    if isinstance(command, str):
        return (command, True) if command else ("", False)
    if isinstance(command, list) and len(command) > 0:
        first = command[0]
        return (first, True) if isinstance(first, str) and first else ("", False)
    return "", False


def _is_standard_agent(agent_id: AgentID) -> bool:
    return agent_id in (
        AgentID.OPENCODE,
        AgentID.QWEN_CODE,
        AgentID.CODEX,
        AgentID.GEMINI_CLI,
        AgentID.ANTIGRAVITY,
        AgentID.CLAUDE_CODE,
    )


def _build_separate_mcp_content(mcp_path: str, default_content: bytes) -> bytes:
    try:
        with open(mcp_path) as f:
            raw = f.read()
    except FileNotFoundError:
        return default_content

    try:
        existing = json.loads(raw)
    except json.JSONDecodeError:
        return default_content

    cmd, ok = _executable_from_command_value(existing.get("command"))
    if not ok or not _is_DXRK_MEMORY_command(cmd):
        return default_content
    cmd = _stable_DXRK_MEMORY_command_for_existing(cmd, None)
    rebuilt = {"command": cmd, "args": ["mcp", "--tools=agent"]}
    return (json.dumps(rebuilt, indent=2) + "\n").encode("utf-8")


def _is_DXRK_MEMORY_command(cmd: str) -> bool:
    if not cmd:
        return False
    base = os.path.basename(cmd)
    if os.name == "nt":
        return base.lower() in ("dxrk_memory.exe", "dxrk_memory")
    return base == "DXRK_MEMORY"


def _is_absolute_DXRK_MEMORY_path(path: str) -> bool:
    return os.path.isabs(path) and _is_DXRK_MEMORY_command(path)


def _is_versioned_homebrew_cellar_path(path: str) -> bool:
    clean = os.path.normpath(path).replace("\\", "/")
    return "/Cellar/DXRK_MEMORY/" in clean and _is_DXRK_MEMORY_command(clean)


def _is_stable_homebrew_DXRK_MEMORY_path(path: str) -> bool:
    clean = os.path.normpath(path).replace("\\", "/")
    return clean in (
        "/opt/homebrew/bin/DXRK_MEMORY",
        "/usr/local/bin/DXRK_MEMORY",
    ) and _is_DXRK_MEMORY_command(clean)


# ─── Download ──────────────────────────────────────────────────────────────

_ENGRAM_OWNER = "Dxrk777"
_ENGRAM_REPO = "engram"
_ENGRAM_NAME = "DXRK_MEMORY"

_engram_http_timeout = 300
_DXRK_MEMORY_github_base_url = "https://github.com"


def download_latest_binary(profile: PlatformProfile) -> str:
    version = _fetch_latest_DXRK_MEMORY_version()
    goos = profile.os
    goarch = _normalize_arch()
    asset_url = _DXRK_MEMORY_asset_url(
        _DXRK_MEMORY_github_base_url, version, goos, goarch
    )
    install_dir = _DXRK_MEMORY_install_dir(goos)
    os.makedirs(install_dir, mode=0o755, exist_ok=True)
    binary_name = _ENGRAM_NAME + (".exe" if goos == "windows" else "")
    out_path = os.path.join(install_dir, binary_name)

    if asset_url.endswith(".zip"):
        _download_and_extract_zip(asset_url, binary_name, out_path)
    else:
        _download_and_extract_tar_gz(asset_url, _ENGRAM_NAME, out_path)
    return out_path


def _fetch_latest_DXRK_MEMORY_version() -> str:
    token = _github_token()
    try:
        version, status = _fetch_latest_DXRK_MEMORY_version_request(token)
        if not status:
            raise RuntimeError(f"GitHub API returned HTTP {status}")
        return version
    except Exception:
        if token:
            version, _ = _fetch_latest_DXRK_MEMORY_version_request("")
            if version:
                return version
        raise


def _fetch_latest_DXRK_MEMORY_version_request(token: str) -> tuple[str, int]:
    api_url = f"{_DXRK_MEMORY_api_base_url()}/repos/{_ENGRAM_OWNER}/{_ENGRAM_REPO}/releases/latest"
    req = Request(api_url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    with urlopen(req, timeout=_engram_http_timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = data.get("tag_name", "")
    version = tag.lstrip("v")
    if not version:
        raise RuntimeError("empty tag_name in GitHub release response")
    return version, 200


def _github_token() -> str:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")


def _normalize_arch() -> str:
    import platform

    arch = platform.machine().lower()
    if arch in ("i386", "i686", "x86"):
        return "amd64"
    if arch in ("armv7l", "armv8l"):
        return "arm64"
    mapping = {
        "x86_64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "amd64": "amd64",
    }
    return mapping.get(arch, arch)


def _DXRK_MEMORY_api_base_url() -> str:
    base = _DXRK_MEMORY_github_base_url
    if "127.0.0.1" in base or "localhost" in base:
        return base
    return "https://api.github.com"


def _DXRK_MEMORY_asset_url(base_url: str, version: str, goos: str, goarch: str) -> str:
    ext = ".zip" if goos == "windows" else ".tar.gz"
    filename = f"{_ENGRAM_REPO}_{version}_{goos}_{goarch}{ext}"
    return f"{base_url}/{_ENGRAM_OWNER}/{_ENGRAM_REPO}/releases/download/v{version}/{filename}"


def _DXRK_MEMORY_install_dir(goos: str) -> str:
    if goos == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if not local_app_data:
            home = os.path.expanduser("~")
            local_app_data = os.path.join(home, "AppData", "Local")
        return os.path.join(local_app_data, "DXRK_MEMORY", "bin")

    candidate = "/usr/local/bin"
    if _is_writable_dir(candidate):
        return candidate
    home = os.path.expanduser("~")
    return os.path.join(home, ".local", "bin")


def _is_writable_dir(directory: str) -> bool:
    if not os.path.isdir(directory):
        return False
    try:
        fd, path = tempfile.mkstemp(prefix=".engram-write-test-", dir=directory)
        os.close(fd)
        os.unlink(path)
        return True
    except (OSError, PermissionError):
        return False


def _download_and_extract_tar_gz(url: str, binary_name: str, out_path: str) -> None:
    req = Request(url)
    with urlopen(req, timeout=_engram_http_timeout) as resp:
        data = resp.read()
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if os.path.basename(member.name) == binary_name and member.isfile():
                f = tar.extractfile(member)
                if f:
                    _write_executable(f.read(), out_path)
                    return
    raise FileNotFoundError(f"binary {binary_name!r} not found in archive")


def _download_and_extract_zip(url: str, binary_name: str, out_path: str) -> None:
    req = Request(url)
    with urlopen(req, timeout=_engram_http_timeout) as resp:
        data = resp.read()
    with zipfile.ZipFile(BytesIO(data)) as zf:
        for info in zf.infolist():
            if os.path.basename(info.filename) == binary_name and not info.is_dir():
                with zf.open(info) as f:
                    _write_executable(f.read(), out_path)
                    return
    raise FileNotFoundError(f"binary {binary_name!r} not found in zip archive")


def _write_executable(data: bytes, out_path: str) -> None:
    directory = os.path.dirname(out_path)
    os.makedirs(directory, mode=0o755, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".engram-upgrade-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(fd)
        os.chmod(tmp_path, 0o755)
        os.replace(tmp_path, out_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Verify ────────────────────────────────────────────────────────────────


class _Command:
    """Minimal command runner stub for verify."""

    def __init__(self, *args: str):
        self._args = args

    def output(self) -> str:
        import subprocess

        return subprocess.check_output(self._args, text=True).strip()


def verify_installed() -> str | None:
    if not shutil.which("DXRK_MEMORY"):
        return "DXRK_MEMORY binary not found in PATH"
    return None


def verify_version() -> str | None:
    try:
        import subprocess

        out = subprocess.check_output(["DXRK_MEMORY", "version"], text=True).strip()
        return out or "empty output"
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        return str(e)


def verify_health(base_url: str = "http://127.0.0.1:7437") -> str | None:
    import urllib.error
    import urllib.request as req

    try:
        with req.urlopen(f"{base_url.rstrip('/')}/health", timeout=2) as resp:
            if resp.status != 200:
                return f"engram health check returned status {resp.status}"
        return None
    except (urllib.error.URLError, OSError) as e:
        return str(e)


# ─── Install command ───────────────────────────────────────────────────────


def install_command(profile: PlatformProfile) -> list[list[str]]:
    """Resolve install commands for engram component."""
    from dxrk.models import ComponentID
    from dxrk.pipeline import resolve_component_install

    return resolve_component_install(profile, ComponentID.DXRK_MEMORY)

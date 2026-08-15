# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Protocol

from dxrk.models import AgentID, ComponentID
from dxrk.system import PlatformProfile
from dxrk.versions import ClaudeCode, Kilocode, OpenCode

__all__ = [
    "CommandSequence",
    "InstallError",
    "ProfileResolver",
    "Resolver",
    "git_bash_path",
    "new_resolver",
    "validate_agent_install_preflight",
    "validate_go_for_module_install",
]

# Package-level vars for testability (lookPath, stat, getenv, goVersion overrides)
_cmd_look_path = shutil.which
_os_stat = os.stat
_os_getenv = os.environ.get

_IGNORE_SCRIPTS = "--ignore-scripts"
_PACMAN = "pacman"
_WINGET = "winget"
_INSTALL = "install"
_SUDO = "sudo"
_NPM = "npm"
_BREW = "brew"
_APT_GET = "apt-get"
_DNF = "dnf"
_FLAG_GLOBAL = "-g"
_FLAG_YES = "-y"
_FLAG_NO_CONFIRM = "--noconfirm"
_FLAG_SYNC = "-S"
_FLAG_WINGET_ID = "--id"
_FLAG_EXACT = "-e"
_FLAG_SOURCE_AGREEMENTS = "--accept-source-agreements"
_FLAG_PKG_AGREEMENTS = "--accept-package-agreements"
_OS_LINUX = "linux"
_OS_WINDOWS = "windows"


class InstallError(Exception):
    pass


CommandSequence = list[list[str]]


class Resolver(Protocol):
    def resolve_agent_install(
        self, profile: PlatformProfile, agent: AgentID
    ) -> CommandSequence: ...

    def resolve_component_install(
        self, profile: PlatformProfile, component: ComponentID
    ) -> CommandSequence: ...

    def resolve_dependency_install(
        self, profile: PlatformProfile, dependency: str
    ) -> CommandSequence: ...


class ProfileResolver:
    def resolve_agent_install(
        self, profile: PlatformProfile, agent: AgentID
    ) -> CommandSequence:
        if agent == AgentID.CLAUDE_CODE:
            return _resolve_claude_code_install(profile)
        if agent == AgentID.OPENCODE:
            return _resolve_opencode_install(profile)
        if agent == AgentID.KILOCODE:
            return _resolve_kilocode_install(profile)
        if agent == AgentID.KIMI:
            return _resolve_kimi_install(profile)
        raise InstallError(f'install command is not supported for agent "{agent}"')

    def resolve_component_install(
        self, profile: PlatformProfile, component: ComponentID
    ) -> CommandSequence:
        if component == ComponentID.DXRK_MEMORY:
            return _resolve_dxrk_memory_install(profile)
        if component == ComponentID.DXRK_GUARDIAN:
            return _resolve_dxrk_guardian_install(profile)
        raise InstallError(
            f'install command is not supported for component "{component}"'
        )

    def resolve_dependency_install(
        self, profile: PlatformProfile, dependency: str
    ) -> CommandSequence:
        if not dependency:
            raise InstallError("dependency name is required")

        pm = profile.package_manager
        if pm == _BREW:
            return [[_BREW, _INSTALL, dependency]]
        if pm == "apt":
            return [[_SUDO, _APT_GET, _INSTALL, _FLAG_YES, dependency]]
        if pm == _PACMAN:
            return [[_SUDO, _PACMAN, _FLAG_SYNC, _FLAG_NO_CONFIRM, dependency]]
        if pm == _DNF:
            return [[_SUDO, _DNF, _INSTALL, _FLAG_YES, dependency]]
        if pm == _WINGET:
            return [
                [
                    _WINGET,
                    _INSTALL,
                    _FLAG_WINGET_ID,
                    dependency,
                    _FLAG_EXACT,
                    _FLAG_SOURCE_AGREEMENTS,
                    _FLAG_PKG_AGREEMENTS,
                ]
            ]
        raise InstallError(
            f'unsupported package manager "{pm}" for os="{profile.os}" distro="{profile.linux_distro}"'
        )


def new_resolver() -> Resolver:
    return ProfileResolver()


# ---------------------------------------------------------------------------
# Agent install resolvers
# ---------------------------------------------------------------------------


def _resolve_claude_code_install(profile: PlatformProfile) -> CommandSequence:
    pkg = f"@anthropic-ai/claude-code@{ClaudeCode}"
    if profile.os == _OS_LINUX and not profile.npm_writable:
        return [[_SUDO, _NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]
    return [[_NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]


def _resolve_kilocode_install(profile: PlatformProfile) -> CommandSequence:
    pkg = f"@kilocode/cli@{Kilocode}"
    if profile.os == _OS_LINUX and not profile.npm_writable:
        return [[_SUDO, _NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]
    return [[_NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]


def _resolve_kimi_install(profile: PlatformProfile) -> CommandSequence:
    if not profile.supported:
        raise InstallError(
            f"kimi is not supported on this platform ({profile.os}/{profile.linux_distro})"
        )
    return [["uv", "tool", _INSTALL, "--python", "3.13", "kimi-cli"]]


def _resolve_opencode_install(profile: PlatformProfile) -> CommandSequence:
    pm = profile.package_manager
    if pm == _BREW:
        return [[_BREW, _INSTALL, "opencode"]]
    if pm in ("apt", _PACMAN, _DNF):
        pkg = f"opencode-ai@{OpenCode}"
        if profile.npm_writable:
            return [[_NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]
        return [[_SUDO, _NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, pkg]]
    if pm == _WINGET:
        return [
            [_NPM, _INSTALL, _FLAG_GLOBAL, _IGNORE_SCRIPTS, f"opencode-ai@{OpenCode}"]
        ]
    raise InstallError(
        f'unsupported platform for opencode: os="{profile.os}" distro="{profile.linux_distro}" pm="{pm}"'
    )


# ---------------------------------------------------------------------------
# Component install resolvers
# ---------------------------------------------------------------------------


def _resolve_dxrk_memory_install(profile: PlatformProfile) -> CommandSequence:
    if profile.package_manager == _BREW:
        return [
            [_BREW, "tap", "Dxrk777/homebrew-tap"],
            [_BREW, _INSTALL, "dxrk-memory"],
        ]
    raise InstallError(
        f'dxrk-memory on "{profile.os}"/"{profile.package_manager}" uses direct binary download '
        "— use dxrkmemory.DownloadLatestBinary() instead of CommandSequence"
    )


def _resolve_dxrk_guardian_install(profile: PlatformProfile) -> CommandSequence:
    pm = profile.package_manager
    if pm == _BREW:
        return [
            [_BREW, "tap", "Dxrk777/homebrew-tap"],
            [_BREW, "reinstall", "dxrk-guardian"],
        ]
    if pm in ("apt", _PACMAN, _DNF):
        tmp_dir = "/tmp/dxrk-guardian-angel"
        return [
            ["rm", "-rf", tmp_dir],
            [
                "git",
                "clone",
                "https://github.com/Dxrk777/dxrk-guardian-angel.git",
                tmp_dir,
            ],
            ["bash", f"{tmp_dir}/install.sh"],
        ]
    if pm == _WINGET:
        clone_dst = os.path.join(tempfile.gettempdir(), "dxrk-guardian-angel")
        bash = _git_bash_path()
        return [
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Remove-Item -Recurse -Force -ErrorAction SilentlyContinue '{clone_dst}'; exit 0",
            ],
            [
                "git",
                "clone",
                "https://github.com/Dxrk777/dxrk-guardian-angel.git",
                clone_dst,
            ],
            [bash, _bash_script_path(profile, os.path.join(clone_dst, "install.sh"))],
        ]
    raise InstallError(
        f'unsupported platform for dxrk-guardian: os="{profile.os}" distro="{profile.linux_distro}" pm="{pm}"'
    )


# ---------------------------------------------------------------------------
# Preflight validation
# ---------------------------------------------------------------------------


def validate_agent_install_preflight(profile: PlatformProfile, agent: AgentID) -> None:
    if agent == AgentID.KIMI:
        _validate_kimi_install_preflight(profile)
    elif agent == AgentID.PI:
        _validate_pi_install_preflight()


def _validate_pi_install_preflight() -> None:
    if _cmd_look_path("pi") is None:
        raise InstallError(
            "Pi requires the `pi` executable in PATH before installing Dxrk AI Pi packages"
        )


def _validate_kimi_install_preflight(profile: PlatformProfile) -> None:
    if not profile.supported:
        raise InstallError(
            f"kimi is not supported on this platform ({profile.os}/{profile.linux_distro})"
        )

    if _cmd_look_path("uv") is None:
        raise InstallError(
            "Kimi requires Astral uv, but `uv` was not found in PATH.\n"
            f"Install uv and retry:\n  {_uv_install_hint(profile)}"
        )


def _uv_install_hint(profile: PlatformProfile) -> str:
    hints = {
        _BREW: "brew install uv",
        "apt": "sudo apt-get install -y uv (or see https://docs.astral.sh/uv/getting-started/installation/)",
        _PACMAN: "sudo pacman -S --noconfirm uv",
        _DNF: "sudo dnf install -y uv",
        _WINGET: "winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements",
    }
    return hints.get(
        profile.package_manager,
        "https://docs.astral.sh/uv/getting-started/installation/",
    )


# ---------------------------------------------------------------------------
# Preflight validation (DxrkMemory on non-brew platforms)
# ---------------------------------------------------------------------------


def _get_go_version_output() -> str:
    try:
        result = subprocess.run(
            ["go", "version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def validate_go_for_module_install(profile: PlatformProfile) -> None:
    if _cmd_look_path("go") is None:
        raise InstallError(
            "Go 1.24+ is required to install DxrkMemory but was not found in PATH.\n"
            "Please install Go from https://go.dev/dl/ and restart your terminal."
        )

    out = _get_go_version_output()
    if not out:
        raise InstallError(
            "Go 1.24+ is required but could not verify the installed version.\n"
            "Please ensure Go is properly installed: https://go.dev/dl/"
        )

    parts = out.split()
    if len(parts) >= 3:
        version_str = parts[2].removeprefix("go")
        ver_parts = version_str.split(".", 2)
        if len(ver_parts) >= 2:
            try:
                major = int(ver_parts[0])
                minor = int(ver_parts[1])
            except ValueError:
                major = minor = 0
            if major < 1 or (major == 1 and minor < 24):
                raise InstallError(
                    f"Go 1.24+ is required to install DxrkMemory, but found go{version_str}.\n"
                    "Please update Go: https://go.dev/dl/"
                )

    if _os_getenv("GO111MODULE") == "off":
        fix = "export GO111MODULE=on  # then retry"
        if profile.os == _OS_WINDOWS:
            fix = '$env:GO111MODULE = "on"  # PowerShell, then retry'
        raise InstallError(f"go modules are disabled (GO111MODULE=off).\nRun: {fix}")


# ---------------------------------------------------------------------------
# Git Bash path resolution (Windows)
# ---------------------------------------------------------------------------


def _git_bash_path() -> str:
    git_path = _cmd_look_path("git")
    if git_path is not None:
        git_dir = os.path.dirname(git_path)
        parent = os.path.dirname(git_dir)

        candidate = os.path.join(parent, "bin", "bash.exe")
        if _file_exists(candidate):
            return candidate

        candidate = os.path.join(git_dir, "bash.exe")
        if _file_exists(candidate):
            return candidate

    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Git", "bin", "bash.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Git", "bin", "bash.exe"),
        r"C:\Program Files\Git\bin\bash.exe",
    ]

    for c in candidates:
        if c and _file_exists(c):
            return c

    return "bash"


def git_bash_path() -> str:
    return _git_bash_path()


def _file_exists(path: str) -> bool:
    try:
        return _os_stat(path) is not None
    except OSError:
        return False


def _bash_script_path(profile: PlatformProfile, path: str) -> str:
    if profile.os == _OS_WINDOWS:
        return path.replace("\\", "/")
    return path

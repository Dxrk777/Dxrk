# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import tempfile

import pytest

from dxrk.installcmd import (
    InstallError,
    _bash_script_path,
    git_bash_path,
    new_resolver,
    validate_agent_install_preflight,
    validate_go_for_module_install,
)
from dxrk.models import AgentID, ComponentID
from dxrk.system import PlatformProfile
from dxrk.versions import ClaudeCode, Kilocode, OpenCode


def _go_version(version: str, platform: str = "linux/amd64") -> str:
    return f"go version go{version} {platform}"


class TestValidateGoForModuleInstall:
    def test_go_not_in_path_returns_error_mentioning_go_124(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        monkeypatch.setattr("dxrk.installcmd._get_go_version_output", lambda: "")
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="Go 1.24\\+"):
            validate_go_for_module_install(profile)

    def test_go_version_below_124_returns_error(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.21.0"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="Go 1.24\\+"):
            validate_go_for_module_install(profile)

    def test_go_version_123_returns_error(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.23.5"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="Go 1.24\\+"):
            validate_go_for_module_install(profile)

    def test_go111module_off_on_linux_returns_error_with_export_fix(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.24.0"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: "off")
        profile = PlatformProfile(os="linux", package_manager="apt")
        with pytest.raises(InstallError, match="export GO111MODULE=on"):
            validate_go_for_module_install(profile)

    def test_go111module_off_on_windows_returns_error_with_powershell_fix(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path", lambda _: r"C:\Go\bin\go.exe"
        )
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.24.0", "windows/amd64"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: "off")
        profile = PlatformProfile(os="windows", package_manager="winget")
        with pytest.raises(InstallError, match=r"\$env:GO111MODULE"):
            validate_go_for_module_install(profile)

    def test_go_124_without_go111module_off_succeeds(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.24.0"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        validate_go_for_module_install(profile)

    def test_go_125_succeeds(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: "/usr/bin/go")
        monkeypatch.setattr(
            "dxrk.installcmd._get_go_version_output",
            lambda: _go_version("1.25.0"),
        )
        monkeypatch.setattr("dxrk.installcmd._os_getenv", lambda k: None)
        profile = PlatformProfile(os="linux", package_manager="apt")
        validate_go_for_module_install(profile)


class TestEngramBrewBypassesGoValidation:
    def test_brew_memory_resolves_without_go(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_MEMORY)
        assert cmds


class TestResolveDependencyInstall:
    @pytest.mark.parametrize(
        ("profile", "want"),
        [
            (
                PlatformProfile(os="darwin", package_manager="brew"),
                [["brew", "install", "somepkg"]],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="ubuntu", package_manager="apt"
                ),
                [["sudo", "apt-get", "install", "-y", "somepkg"]],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="arch", package_manager="pacman"
                ),
                [["sudo", "pacman", "-S", "--noconfirm", "somepkg"]],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="fedora", package_manager="dnf"
                ),
                [["sudo", "dnf", "install", "-y", "somepkg"]],
            ),
            (
                PlatformProfile(os="windows", package_manager="winget"),
                [
                    [
                        "winget",
                        "install",
                        "--id",
                        "somepkg",
                        "-e",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ]
                ],
            ),
        ],
    )
    def test_known_package_managers(self, profile, want):
        resolver = new_resolver()
        assert resolver.resolve_dependency_install(profile, "somepkg") == want

    def test_unsupported_package_manager_returns_error(self):
        resolver = new_resolver()
        profile = PlatformProfile(
            os="linux", linux_distro="ubuntu", package_manager="zypper"
        )
        with pytest.raises(InstallError, match="unsupported package manager"):
            resolver.resolve_dependency_install(profile, "somepkg")

    def test_empty_dependency_returns_error(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="dependency name is required"):
            resolver.resolve_dependency_install(profile, "")


class TestGitBashPathResolvesFromGitOnPath:
    def test_resolves_bash_from_git_on_path(self, tmp_path, monkeypatch):
        cmd_dir = tmp_path / "cmd"
        bin_dir = tmp_path / "bin"
        cmd_dir.mkdir()
        bin_dir.mkdir()
        fake_git = cmd_dir / "git.exe"
        fake_bash = bin_dir / "bash.exe"
        fake_git.write_text("fake")
        fake_bash.write_text("fake")

        def look_path(name: str) -> str | None:
            if name == "git":
                return str(fake_git)
            return None

        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", look_path)
        assert git_bash_path() == str(fake_bash)


class TestGitBashPathFallsBackToBareWhenNoGit:
    def test_falls_back_to_bare_when_no_git(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        monkeypatch.setattr("dxrk.installcmd._file_exists", lambda _: False)
        assert git_bash_path() == "bash"


class TestBashScriptPathWindowsUsesForwardSlashes:
    def test_uses_forward_slashes(self):
        profile = PlatformProfile(os="windows", package_manager="winget")
        got = _bash_script_path(
            profile,
            r"C:\Users\jorge\AppData\Local\Temp\dxrk-guardian-angel\install.sh",
        )
        assert got == "C:/Users/jorge/AppData/Local/Temp/dxrk-guardian-angel/install.sh"


class TestResolveAgentInstall:
    @pytest.mark.parametrize(
        ("profile", "agent", "want"),
        [
            (
                PlatformProfile(os="darwin", package_manager="brew"),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="ubuntu", package_manager="apt"
                ),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "sudo",
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux",
                    linux_distro="ubuntu",
                    package_manager="apt",
                    npm_writable=True,
                ),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="arch", package_manager="pacman"
                ),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "sudo",
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux",
                    linux_distro="fedora",
                    package_manager="dnf",
                    npm_writable=True,
                ),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(os="darwin", package_manager="brew"),
                AgentID.OPENCODE,
                [["brew", "install", "opencode"]],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="ubuntu", package_manager="apt"
                ),
                AgentID.OPENCODE,
                [
                    [
                        "sudo",
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux",
                    linux_distro="ubuntu",
                    package_manager="apt",
                    npm_writable=True,
                ),
                AgentID.OPENCODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="arch", package_manager="pacman"
                ),
                AgentID.OPENCODE,
                [
                    [
                        "sudo",
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux", linux_distro="fedora", package_manager="dnf"
                ),
                AgentID.OPENCODE,
                [
                    [
                        "sudo",
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="linux",
                    linux_distro="fedora",
                    package_manager="dnf",
                    npm_writable=True,
                ),
                AgentID.OPENCODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(
                    os="windows", package_manager="winget", npm_writable=True
                ),
                AgentID.CLAUDE_CODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"@anthropic-ai/claude-code@{ClaudeCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(os="windows", package_manager="winget"),
                AgentID.OPENCODE,
                [
                    [
                        "npm",
                        "install",
                        "-g",
                        "--ignore-scripts",
                        f"opencode-ai@{OpenCode}",
                    ]
                ],
            ),
            (
                PlatformProfile(os="windows", package_manager="winget", supported=True),
                AgentID.KIMI,
                [["uv", "tool", "install", "--python", "3.13", "kimi-cli"]],
            ),
            (
                PlatformProfile(
                    os="linux",
                    linux_distro="ubuntu",
                    package_manager="apt",
                    supported=True,
                ),
                AgentID.KIMI,
                [["uv", "tool", "install", "--python", "3.13", "kimi-cli"]],
            ),
        ],
    )
    def test_known_agents(self, profile, agent, want):
        resolver = new_resolver()
        assert resolver.resolve_agent_install(profile, agent) == want

    def test_kimi_on_unsupported_profile_returns_error(self):
        resolver = new_resolver()
        profile = PlatformProfile(
            os="linux",
            linux_distro="ubuntu",
            package_manager="apt",
            supported=False,
        )
        with pytest.raises(InstallError, match="not supported on this platform"):
            resolver.resolve_agent_install(profile, AgentID.KIMI)

    def test_unsupported_agent_returns_error(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="install command is not supported"):
            resolver.resolve_agent_install(profile, "unsupported")


class TestValidateAgentInstallPreflight:
    def test_kimi_on_unsupported_platform_returns_error_before_uv_lookup(
        self, monkeypatch
    ):
        calls: list[str] = []
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path",
            lambda name: calls.append(name) or None,
        )
        profile = PlatformProfile(
            os="linux", linux_distro="unknown", package_manager="", supported=False
        )
        with pytest.raises(InstallError) as excinfo:
            validate_agent_install_preflight(profile, AgentID.KIMI)
        assert "not supported on this platform" in str(excinfo.value)
        assert "install uv" not in str(excinfo.value).lower()
        assert calls == []

    def test_kimi_missing_uv_returns_actionable_remediation(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path",
            lambda name: None if name == "uv" else f"/usr/bin/{name}",
        )
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        with pytest.raises(InstallError, match="brew install uv"):
            validate_agent_install_preflight(profile, AgentID.KIMI)

    def test_kimi_with_uv_present_passes_preflight(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path",
            lambda name: "/usr/bin/uv" if name == "uv" else None,
        )
        profile = PlatformProfile(os="linux", package_manager="apt", supported=True)
        validate_agent_install_preflight(profile, AgentID.KIMI)

    def test_pi_missing_binary_returns_actionable_remediation(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path",
            lambda name: None if name == "pi" else f"/usr/bin/{name}",
        )
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        with pytest.raises(InstallError, match="Pi requires the `pi` executable"):
            validate_agent_install_preflight(profile, AgentID.PI)

    def test_pi_with_binary_present_passes_preflight(self, monkeypatch):
        monkeypatch.setattr(
            "dxrk.installcmd._cmd_look_path",
            lambda name: "/usr/bin/pi" if name == "pi" else None,
        )
        profile = PlatformProfile(os="linux", package_manager="apt", supported=True)
        validate_agent_install_preflight(profile, AgentID.PI)

    def test_non_kimi_agent_does_not_require_uv(self, monkeypatch):
        monkeypatch.setattr("dxrk.installcmd._cmd_look_path", lambda _: None)
        profile = PlatformProfile(os="darwin", package_manager="brew", supported=True)
        validate_agent_install_preflight(profile, AgentID.CLAUDE_CODE)


class TestResolveComponentInstall:
    def test_dxrk_memory_on_darwin_uses_brew_tap_and_install(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_MEMORY)
        assert cmds == [
            ["brew", "tap", "Dxrk777/homebrew-tap"],
            ["brew", "install", "dxrk-memory"],
        ]

    @pytest.mark.parametrize(
        "profile",
        [
            PlatformProfile(os="linux", linux_distro="ubuntu", package_manager="apt"),
            PlatformProfile(os="linux", linux_distro="arch", package_manager="pacman"),
            PlatformProfile(os="linux", linux_distro="fedora", package_manager="dnf"),
            PlatformProfile(os="windows", package_manager="winget"),
        ],
    )
    def test_dxrk_memory_on_other_platforms_returns_error(self, profile):
        resolver = new_resolver()
        with pytest.raises(InstallError, match="dxrk-memory on"):
            resolver.resolve_component_install(profile, ComponentID.DXRK_MEMORY)

    def test_dxrk_guardian_on_darwin_uses_brew_tap_and_reinstall(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_GUARDIAN)
        assert cmds == [
            ["brew", "tap", "Dxrk777/homebrew-tap"],
            ["brew", "reinstall", "dxrk-guardian"],
        ]

    @pytest.mark.parametrize(
        "profile",
        [
            PlatformProfile(os="linux", linux_distro="ubuntu", package_manager="apt"),
            PlatformProfile(os="linux", linux_distro="arch", package_manager="pacman"),
            PlatformProfile(os="linux", linux_distro="fedora", package_manager="dnf"),
        ],
    )
    def test_dxrk_guardian_on_linux_uses_git_clone_and_install_sh(self, profile):
        resolver = new_resolver()
        cmds = resolver.resolve_component_install(profile, ComponentID.DXRK_GUARDIAN)
        assert cmds == [
            ["rm", "-rf", "/tmp/dxrk-guardian-angel"],
            [
                "git",
                "clone",
                "https://github.com/Dxrk777/dxrk-guardian-angel.git",
                "/tmp/dxrk-guardian-angel",
            ],
            ["bash", "/tmp/dxrk-guardian-angel/install.sh"],
        ]

    def test_dxrk_guardian_on_windows_cleans_temp_dir_and_uses_git_bash(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="windows", package_manager="winget")
        clone_dst = os.path.join(tempfile.gettempdir(), "dxrk-guardian-angel")
        want = [
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
            [
                git_bash_path(),
                _bash_script_path(
                    PlatformProfile(os="windows"),
                    os.path.join(clone_dst, "install.sh"),
                ),
            ],
        ]
        assert (
            resolver.resolve_component_install(profile, ComponentID.DXRK_GUARDIAN)
            == want
        )

    def test_unsupported_component_returns_error(self):
        resolver = new_resolver()
        profile = PlatformProfile(os="darwin", package_manager="brew")
        with pytest.raises(InstallError, match="install command is not supported"):
            resolver.resolve_component_install(profile, "unsupported")

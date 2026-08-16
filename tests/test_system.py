import os
import platform

import pytest

from dxrk.system import (
    LINUX_DISTRO_ARCH,
    LINUX_DISTRO_DEBIAN,
    LINUX_DISTRO_FEDORA,
    LINUX_DISTRO_UBUNTU,
    LINUX_DISTRO_UNKNOWN,
    ConfigState,
    Dependency,
    DependencyReport,
    DetectionResult,
    PlatformProfile,
    ToolStatus,
    _add_to_process_path,
    _define_dependencies,
    _detect_from_inputs,
    _detect_linux_distro,
    _detect_single_dep,
    _escape_power_shell_string,
    _install_hint_brew,
    _install_hint_curl,
    _install_hint_git,
    _install_hint_go,
    _install_hint_node,
    _install_hint_npm,
    _parse_version,
    _resolve_platform_profile,
    _version_at_least,
    _version_parts,
    add_to_user_path,
    detect_dependencies,
    detect_tools,
    ensure_supported_os,
    ensure_supported_platform,
    format_missing_deps_message,
    install_commands_for_dep,
    is_supported_os,
    known_agent_config_dirs,
    render_dependency_report,
    scan_configs,
)


def make_dep(
    name="git",
    required=True,
    min_version="",
    detect_cmd=None,
    installed=False,
    version="",
    install_hint="hint",
):
    return Dependency(
        name=name,
        required=required,
        min_version=min_version,
        detect_cmd=detect_cmd or [],
        installed=installed,
        version=version,
        install_hint=install_hint,
    )


class TestIsSupportedOS:
    @pytest.mark.parametrize("goos", ["darwin", "linux", "windows"])
    def test_supported(self, goos):
        assert is_supported_os(goos)

    def test_freebsd_not_supported(self):
        assert not is_supported_os("freebsd")


class TestEnsureFunctions:
    def test_supported_os_darwin(self):
        ensure_supported_os("darwin")

    def test_supported_os_windows(self):
        ensure_supported_os("windows")

    def test_unsupported_os_raises(self):
        with pytest.raises(OSError, match="unsupported operating system"):
            ensure_supported_os("freebsd")

    def test_unsupported_os_message(self):
        with pytest.raises(OSError) as excinfo:
            ensure_supported_os("freebsd")
        assert str(excinfo.value) == (
            "unsupported operating system: only macOS, Linux, and Windows are supported (detected freebsd)"
        )

    def test_supported_platform_ubuntu(self):
        ensure_supported_platform(
            PlatformProfile(
                os="linux", linux_distro=LINUX_DISTRO_UBUNTU, supported=True
            )
        )

    def test_supported_platform_fedora(self):
        ensure_supported_platform(
            PlatformProfile(
                os="linux",
                linux_distro=LINUX_DISTRO_FEDORA,
                package_manager="dnf",
                supported=True,
            )
        )

    def test_supported_platform_unsupported_os_raises(self):
        with pytest.raises(OSError, match="unsupported operating system"):
            ensure_supported_platform(PlatformProfile(os="freebsd"))

    def test_unsupported_platform_raises(self):
        with pytest.raises(OSError, match="unsupported linux distro"):
            ensure_supported_platform(
                PlatformProfile(
                    os="linux", linux_distro=LINUX_DISTRO_UNKNOWN, supported=False
                )
            )

    def test_unsupported_platform_message(self):
        with pytest.raises(OSError) as excinfo:
            ensure_supported_platform(
                PlatformProfile(
                    os="linux", linux_distro=LINUX_DISTRO_UNKNOWN, supported=False
                )
            )
        assert str(excinfo.value) == (
            "unsupported linux distro: Linux support is limited to Ubuntu/Debian, Arch, and Fedora/RHEL family (detected unknown)"
        )


class TestScanConfigs:
    def test_returns_all_known_agents_with_exists_flag(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(mode=0o750)
        configs = scan_configs(str(tmp_path))
        assert len(configs) >= 14
        claude = next(c for c in configs if c.agent == "claude-code")
        assert claude.exists is True
        assert claude.is_directory is True
        assert sum(1 for c in configs if c.exists) == 1

    def test_agent_field_matches_model_agent_id(self, tmp_path):
        expected = {
            "claude-code",
            "opencode",
            "kilocode",
            "gemini-cli",
            "cursor",
            "vscode-copilot",
            "codex",
            "antigravity",
            "windsurf",
            "kimi",
            "qwen-code",
            "kiro-ide",
            "openclaw",
            "pi",
        }
        configs = scan_configs(str(tmp_path))
        agents = {c.agent for c in configs}
        assert expected.issubset(agents)

    def test_path_field_is_non_empty(self, tmp_path):
        configs = scan_configs(str(tmp_path))
        assert all(c.path for c in configs)

    def test_exists_false_when_dir_absent(self, tmp_path):
        configs = scan_configs(str(tmp_path))
        assert len(configs) >= 14
        assert all(not c.exists for c in configs)

    def test_is_directory_set_for_existing_dirs(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".config" / "opencode").mkdir(parents=True)
        configs = scan_configs(str(tmp_path))
        claude = next(c for c in configs if c.agent == "claude-code")
        opencode = next(c for c in configs if c.agent == "opencode")
        assert claude.exists is True and claude.is_directory is True
        assert opencode.exists is True and opencode.is_directory is True

    def test_known_agent_config_dirs_returns_14(self, tmp_path):
        entries = known_agent_config_dirs(str(tmp_path))
        assert len(entries) == 14


class TestDetectTools:
    def test_detect_tools_returns_status(self):
        tools = detect_tools(["git"])
        git = tools["git"]
        assert isinstance(git, ToolStatus)
        assert git.name == "git"
        assert git.installed is True
        assert git.path

    def test_unknown_tool_not_installed(self):
        tools = detect_tools(["zzz_nonexistent_tool_42"])
        status = tools["zzz_nonexistent_tool_42"]
        assert status.installed is False
        assert status.path == ""


class TestParseVersion:
    @pytest.mark.parametrize(
        ("name", "output", "expected"),
        [
            ("node", "v18.0.0\n", "18.0.0"),
            ("node", "v20.11.1\n", "20.11.1"),
            ("npm", "10.2.4\n", "10.2.4"),
            ("git", "git version 2.43.0\n", "2.43.0"),
            ("curl", "curl 8.4.0 (x86_64-apple-darwin23.0) libcurl/8.4.0\n", "8.4.0"),
            ("go", "go version go1.22.5 darwin/arm64\n", "1.22.5"),
            ("go", "go1.21.0\n", "1.21.0"),
            ("brew", "Homebrew 4.2.0\n", "4.2.0"),
            ("node", "", ""),
            ("node", "   \n  ", ""),
            ("node", "some random text", ""),
        ],
    )
    def test_parse_version(self, name, output, expected):
        assert _parse_version(name, output) == expected


class TestVersionAtLeast:
    @pytest.mark.parametrize(
        ("version", "minimum", "expected"),
        [
            ("18.0.0", "18.0.0", True),
            ("20.0.0", "18.0.0", True),
            ("18.5.0", "18.0.0", True),
            ("18.0.1", "18.0.0", True),
            ("16.0.0", "18.0.0", False),
            ("17.9.0", "18.0.0", False),
            ("18.0", "18.0.0", True),
            ("18.0.0", "18.0", True),
            ("0.0.0", "0.0.0", True),
        ],
    )
    def test_version_at_least(self, version, minimum, expected):
        assert _version_at_least(version, minimum) is expected


class TestVersionParts:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("18.2.3", (18, 2, 3)),
            ("18.2", (18, 2, 0)),
            ("18", (18, 0, 0)),
            ("", (0, 0, 0)),
            ("abc.def.ghi", (0, 0, 0)),
        ],
    )
    def test_version_parts(self, version, expected):
        assert _version_parts(version) == expected


class TestDefineDependencies:
    def test_darwin_includes_brew(self):
        deps = _define_dependencies(
            PlatformProfile(os="darwin", package_manager="brew")
        )
        names = {d.name for d in deps}
        assert {"git", "curl", "node", "npm", "brew"} <= names
        brew = next(d for d in deps if d.name == "brew")
        assert brew.required is False

    def test_linux_has_no_brew(self):
        deps = _define_dependencies(
            PlatformProfile(
                os="linux",
                linux_distro=LINUX_DISTRO_UBUNTU,
                package_manager="apt",
                supported=True,
            )
        )
        names = [d.name for d in deps]
        assert "brew" not in names
        assert names == ["git", "curl", "node", "npm", "go"]

    def test_node_min_version(self):
        deps = _define_dependencies(PlatformProfile(os="linux"))
        node = next(d for d in deps if d.name == "node")
        assert node.min_version == "18.0.0"

    def test_git_curl_required(self):
        deps = _define_dependencies(PlatformProfile(os="linux"))
        git = next(d for d in deps if d.name == "git")
        curl = next(d for d in deps if d.name == "curl")
        assert git.required is True
        assert curl.required is True

    def test_go_detect_cmd_uses_version(self):
        deps = _define_dependencies(PlatformProfile(os="linux"))
        go = next(d for d in deps if d.name == "go")
        assert go.detect_cmd == ["go", "version"]


class TestDetectSingleDep:
    def test_installed_with_version(self):
        dep = make_dep(detect_cmd=["echo", "v1.0.0"])
        result = _detect_single_dep(dep)
        assert result.installed is True
        assert result.version == "1.0.0"

    def test_tool_not_found(self):
        dep = make_dep(detect_cmd=["zzz_nonexistent_tool_42", "--version"])
        result = _detect_single_dep(dep)
        assert result.installed is False
        assert result.version == ""

    def test_min_version_not_met(self):
        dep = make_dep(min_version="99.0.0", detect_cmd=["echo", "v1.0.0"])
        result = _detect_single_dep(dep)
        assert result.installed is False
        assert result.version == "1.0.0"

    def test_empty_detect_cmd(self):
        dep = make_dep(detect_cmd=[])
        result = _detect_single_dep(dep)
        assert result.installed is False


class TestDetectDependencies:
    def test_report_all_present(self, monkeypatch):
        deps = [
            make_dep(name="git", installed=True, version="2.43.0"),
            make_dep(name="node", installed=True, version="20.11.0"),
        ]
        monkeypatch.setattr("dxrk.system._define_dependencies", lambda profile: deps)
        report = detect_dependencies(PlatformProfile(os="linux"))
        assert report.all_present is True
        assert report.missing_required == []
        assert report.missing_optional == []

    def test_report_missing_required(self, monkeypatch):
        deps = [
            make_dep(name="git", installed=False),
            make_dep(name="node", required=False, installed=False),
        ]
        monkeypatch.setattr("dxrk.system._define_dependencies", lambda profile: deps)
        report = detect_dependencies(PlatformProfile(os="linux"))
        assert report.all_present is False
        assert report.missing_required == ["git"]
        assert report.missing_optional == ["node"]


class TestRenderDependencyReport:
    def test_all_present(self):
        report = DependencyReport(
            dependencies=[
                make_dep(name="git", installed=True, version="2.43.0"),
                make_dep(name="node", installed=True, version="20.11.0"),
            ],
            all_present=True,
            missing_required=[],
            missing_optional=[],
        )
        rendered = render_dependency_report(report)
        assert "Dependencies:" in rendered
        assert "git" in rendered
        assert "v 2.43.0" in rendered
        assert "node" in rendered
        assert "v 20.11.0" in rendered

    def test_missing(self):
        report = DependencyReport(
            dependencies=[make_dep(name="node", installed=False)],
            all_present=False,
            missing_required=["node"],
            missing_optional=[],
        )
        rendered = render_dependency_report(report)
        assert "node" in rendered
        assert "x NOT FOUND" in rendered
        assert "Missing required: node" in rendered

    def test_installed_without_version_shows_found(self):
        report = DependencyReport(
            dependencies=[make_dep(name="git", installed=True, version="")],
            all_present=True,
            missing_required=[],
            missing_optional=[],
        )
        rendered = render_dependency_report(report)
        assert "v found" in rendered

    def test_optional_marker(self):
        report = DependencyReport(
            dependencies=[make_dep(name="go", required=False, installed=False)],
            all_present=True,
            missing_required=[],
            missing_optional=["go"],
        )
        rendered = render_dependency_report(report)
        assert "x NOT FOUND (optional)" in rendered
        assert "Missing optional: go" in rendered


class TestFormatMissingDepsMessage:
    def test_all_present(self):
        report = DependencyReport(
            dependencies=[make_dep(name="git")],
            all_present=True,
            missing_required=[],
            missing_optional=[],
        )
        assert (
            format_missing_deps_message(report)
            == "All required dependencies are present."
        )

    def test_missing_required_with_hints(self):
        report = DependencyReport(
            dependencies=[
                make_dep(
                    name="node", installed=False, install_hint="brew install node"
                ),
                make_dep(name="git", installed=True),
            ],
            all_present=False,
            missing_required=["node"],
            missing_optional=[],
        )
        message = format_missing_deps_message(report)
        assert "node" in message
        assert "brew install node" in message
        assert "Install hints:" in message

    def test_missing_none_when_empty(self):
        report = DependencyReport(
            dependencies=[make_dep(name="git")],
            all_present=False,
            missing_required=[],
            missing_optional=["go"],
        )
        message = format_missing_deps_message(report)
        assert "Missing 0 required dependency(ies): none" in message


class TestDetectFromInputs:
    def test_marks_supported_macos(self):
        result = _detect_from_inputs("darwin", "arm64", "/bin/zsh", "", {}, [])
        assert result.system.supported is True
        assert result.system.profile.package_manager == "brew"
        assert result.system.os == "darwin"
        assert result.system.arch == "arm64"
        assert result.system.shell == "/bin/zsh"

    def test_marks_fedora_supported(self):
        os_release = 'ID=fedora\nID_LIKE="rhel fedora"\n'
        result = _detect_from_inputs("linux", "amd64", "/bin/bash", os_release, {}, [])
        assert result.system.supported is True
        assert result.system.profile.linux_distro == LINUX_DISTRO_FEDORA
        assert result.system.profile.package_manager == "dnf"

    def test_marks_ubuntu_supported(self):
        os_release = "ID=ubuntu\nID_LIKE=debian\n"
        result = _detect_from_inputs("linux", "amd64", "/bin/bash", os_release, {}, [])
        assert result.system.supported is True
        assert result.system.profile.linux_distro == LINUX_DISTRO_UBUNTU
        assert result.system.profile.package_manager == "apt"

    def test_marks_arch_supported(self):
        os_release = "ID=arch\nID_LIKE=archlinux\n"
        result = _detect_from_inputs("linux", "amd64", "/bin/bash", os_release, {}, [])
        assert result.system.supported is True
        assert result.system.profile.linux_distro == LINUX_DISTRO_ARCH
        assert result.system.profile.package_manager == "pacman"

    def test_shell_defaults_to_unknown(self):
        result = _detect_from_inputs("darwin", "arm64", "", "", {}, [])
        assert result.system.shell == "unknown"

    def test_windows_shell_defaults_to_powershell(self):
        result = _detect_from_inputs("windows", "amd64", "", "", {}, [])
        assert result.system.shell == "powershell"

    def test_marks_windows_supported(self):
        result = _detect_from_inputs("windows", "amd64", "powershell", "", {}, [])
        assert result.system.supported is True
        assert result.system.profile.package_manager == "winget"

    def test_profile_is_populated_in_system(self):
        result = _detect_from_inputs("darwin", "arm64", "/bin/zsh", "", {}, [])
        assert result.system.supported == result.system.profile.supported

    def test_unsupported_os(self):
        result = _detect_from_inputs("freebsd", "amd64", "/bin/sh", "", {}, [])
        assert result.system.supported is False

    def test_result_holds_tools_and_configs(self):
        tools = {"git": ToolStatus(name="git", installed=True, path="/usr/bin/git")}
        configs = [ConfigState(agent="claude-code", path="/tmp/.claude")]
        result = _detect_from_inputs(
            "linux", "amd64", "/bin/bash", "ID=ubuntu\n", tools, configs
        )
        assert result.tools == tools
        assert result.configs == configs


class TestDetectLinuxDistro:
    @pytest.mark.parametrize(
        ("os_release", "expected"),
        [
            ('ID=ubuntu\nVERSION_ID="22.04"\n', LINUX_DISTRO_UBUNTU),
            ('ID=debian\nVERSION_ID="12"\n', LINUX_DISTRO_DEBIAN),
            (
                'ID=linuxmint\nID_LIKE="ubuntu debian"\nVERSION_ID="21.3"\n',
                LINUX_DISTRO_UBUNTU,
            ),
            ('ID=pop\nID_LIKE="ubuntu debian"\n', LINUX_DISTRO_UBUNTU),
            ("ID=arch\n", LINUX_DISTRO_ARCH),
            ("ID=manjaro\nID_LIKE=arch\n", LINUX_DISTRO_ARCH),
            ("ID=endeavouros\nID_LIKE=arch\n", LINUX_DISTRO_ARCH),
            ('ID=fedora\nID_LIKE="rhel fedora"\n', LINUX_DISTRO_FEDORA),
            ('ID=centos\nID_LIKE="rhel fedora"\n', LINUX_DISTRO_FEDORA),
            ("ID=rhel\nID_LIKE=fedora\n", LINUX_DISTRO_FEDORA),
            ('ID=rocky\nID_LIKE="rhel centos fedora"\n', LINUX_DISTRO_FEDORA),
            ('ID=almalinux\nID_LIKE="rhel centos fedora"\n', LINUX_DISTRO_FEDORA),
            ("ID=nobara\n", LINUX_DISTRO_FEDORA),
            ('ID=custom-linux\nID_LIKE="nobara"\n', LINUX_DISTRO_FEDORA),
            ("", LINUX_DISTRO_UNKNOWN),
            ("   \n  \n", LINUX_DISTRO_UNKNOWN),
            ("# comment line\n# another\n", LINUX_DISTRO_UNKNOWN),
            ("no-equals-sign\nID=ubuntu\n", LINUX_DISTRO_UBUNTU),
            ('ID="ubuntu"\nID_LIKE="debian"\n', LINUX_DISTRO_UBUNTU),
        ],
    )
    def test_matrix(self, os_release, expected):
        assert _detect_linux_distro(os_release) == expected


class TestResolvePlatformProfile:
    def test_darwin(self):
        profile = _resolve_platform_profile("darwin", "", {})
        assert profile.package_manager == "brew"
        assert profile.supported is True

    def test_linux_with_brew_installed(self):
        tools = {
            "brew": ToolStatus(
                name="brew", installed=True, path="/opt/homebrew/bin/brew"
            )
        }
        profile = _resolve_platform_profile("linux", "ID=debian\n", tools)
        assert profile.package_manager == "brew"
        assert profile.supported is True
        assert profile.linux_distro == LINUX_DISTRO_DEBIAN

    def test_linux_ubuntu(self):
        profile = _resolve_platform_profile("linux", "ID=ubuntu\n", {})
        assert profile.package_manager == "apt"
        assert profile.supported is True

    def test_linux_debian(self):
        profile = _resolve_platform_profile("linux", "ID=debian\n", {})
        assert profile.package_manager == "apt"
        assert profile.supported is True

    def test_linux_arch(self):
        profile = _resolve_platform_profile("linux", "ID=arch\n", {})
        assert profile.package_manager == "pacman"
        assert profile.supported is True

    def test_linux_fedora(self):
        profile = _resolve_platform_profile("linux", "ID=fedora\n", {})
        assert profile.package_manager == "dnf"
        assert profile.supported is True

    def test_windows(self):
        profile = _resolve_platform_profile("windows", "", {})
        assert profile.package_manager == "winget"
        assert profile.supported is True

    def test_linux_unknown(self):
        profile = _resolve_platform_profile("linux", "", {})
        assert profile.package_manager == ""
        assert profile.supported is False
        assert profile.linux_distro == LINUX_DISTRO_UNKNOWN


class TestInstallHints:
    def test_git_darwin(self):
        assert (
            _install_hint_git(PlatformProfile(os="darwin", package_manager="brew"))
            == "brew install git"
        )

    def test_git_ubuntu(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        assert "apt-get install" in _install_hint_git(profile)

    def test_git_arch(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_ARCH, package_manager="pacman"
        )
        assert "pacman -S" in _install_hint_git(profile)

    def test_git_windows(self):
        assert (
            _install_hint_git(PlatformProfile(os="windows", package_manager="winget"))
            == "winget install Git.Git"
        )

    def test_node_darwin(self):
        assert (
            _install_hint_node(PlatformProfile(os="darwin", package_manager="brew"))
            == "brew install node"
        )

    def test_node_ubuntu(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        assert "nodesource" in _install_hint_node(profile)

    def test_node_arch(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_ARCH, package_manager="pacman"
        )
        hint = _install_hint_node(profile)
        assert "pacman" in hint
        assert "nodejs" in hint

    def test_node_fedora(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_FEDORA, package_manager="dnf"
        )
        hint = _install_hint_node(profile)
        assert "rpm.nodesource.com" in hint
        assert "dnf install -y nodejs" in hint

    def test_node_windows(self):
        assert (
            _install_hint_node(PlatformProfile(os="windows", package_manager="winget"))
            == "winget install OpenJS.NodeJS.LTS"
        )

    def test_brew_hint(self):
        assert "Homebrew" in _install_hint_brew(
            PlatformProfile(os="darwin", package_manager="brew")
        )

    def test_go_darwin(self):
        assert (
            _install_hint_go(PlatformProfile(os="darwin", package_manager="brew"))
            == "brew install go"
        )

    def test_go_ubuntu(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        assert "apt-get install" in _install_hint_go(profile)

    def test_go_windows(self):
        assert (
            _install_hint_go(PlatformProfile(os="windows", package_manager="winget"))
            == "winget install GoLang.Go"
        )

    def test_curl_windows(self):
        hint = _install_hint_curl(
            PlatformProfile(os="windows", package_manager="winget")
        )
        assert "pre-installed" in hint

    def test_npm_hint(self):
        hint = _install_hint_npm(PlatformProfile(os="linux"))
        assert "npm is included with node" in hint


class TestInstallCommandsForDep:
    def test_git_darwin(self):
        cmds = install_commands_for_dep(
            "git", PlatformProfile(os="darwin", package_manager="brew")
        )
        assert cmds == [["brew", "install", "git"]]
        assert cmds is not None
        assert len(cmds) == 1

    def test_git_ubuntu(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        cmds = install_commands_for_dep("git", profile)
        assert cmds is not None
        assert len(cmds) == 1
        assert cmds[0][0] == "sudo"

    def test_git_arch(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_ARCH, package_manager="pacman"
        )
        cmds = install_commands_for_dep("git", profile)
        assert cmds is not None
        assert cmds[0][0] == "sudo"
        assert cmds[0][1] == "pacman"

    def test_git_fedora(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_FEDORA, package_manager="dnf"
        )
        cmds = install_commands_for_dep("git", profile)
        assert cmds is not None
        assert cmds[0][0] == "sudo"
        assert cmds[0][1] == "dnf"

    def test_git_windows(self):
        cmds = install_commands_for_dep(
            "git", PlatformProfile(os="windows", package_manager="winget")
        )
        assert cmds is not None
        assert len(cmds) == 1
        assert cmds[0][0] == "winget"

    def test_node_ubuntu_two_steps(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        cmds = install_commands_for_dep("node", profile)
        assert cmds is not None
        assert len(cmds) == 2

    def test_node_fedora_two_steps(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_FEDORA, package_manager="dnf"
        )
        cmds = install_commands_for_dep("node", profile)
        assert cmds is not None
        assert len(cmds) == 2
        assert cmds[0][0] == "bash"
        assert "rpm.nodesource.com/setup_lts.x" in cmds[0][2]
        assert cmds[1] == ["sudo", "dnf", "install", "-y", "nodejs"]

    def test_node_windows(self):
        cmds = install_commands_for_dep(
            "node", PlatformProfile(os="windows", package_manager="winget")
        )
        assert cmds is not None
        assert len(cmds) == 1
        assert cmds[0][0] == "winget"

    def test_npm_returns_none(self):
        assert install_commands_for_dep("npm", PlatformProfile(os="linux")) is None

    def test_brew_linux_returns_none(self):
        profile = PlatformProfile(
            os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
        )
        assert install_commands_for_dep("brew", profile) is None

    def test_brew_darwin(self):
        cmds = install_commands_for_dep(
            "brew", PlatformProfile(os="darwin", package_manager="brew")
        )
        assert cmds is not None
        assert len(cmds) == 1

    def test_curl_windows_returns_none(self):
        assert (
            install_commands_for_dep(
                "curl", PlatformProfile(os="windows", package_manager="winget")
            )
            is None
        )

    def test_brew_windows_returns_none(self):
        assert (
            install_commands_for_dep(
                "brew", PlatformProfile(os="windows", package_manager="winget")
            )
            is None
        )

    def test_unknown_tool_returns_none(self):
        assert (
            install_commands_for_dep("zzz_nonexistent", PlatformProfile(os="linux"))
            is None
        )

    @pytest.mark.parametrize(
        "profile",
        [
            PlatformProfile(os="darwin", package_manager="brew"),
            PlatformProfile(
                os="linux", linux_distro=LINUX_DISTRO_UBUNTU, package_manager="apt"
            ),
            PlatformProfile(
                os="linux", linux_distro=LINUX_DISTRO_ARCH, package_manager="pacman"
            ),
            PlatformProfile(
                os="linux", linux_distro=LINUX_DISTRO_FEDORA, package_manager="dnf"
            ),
        ],
    )
    @pytest.mark.parametrize("name", ["git", "curl", "node", "go"])
    def test_full_matrix(self, profile, name):
        cmds = install_commands_for_dep(name, profile)
        assert cmds is not None
        assert len(cmds) > 0
        assert all(cmd for cmd in cmds)


class TestAddToUserPath:
    def test_already_present(self, monkeypatch):
        target = "/usr/local/bin"
        monkeypatch.setenv("PATH", f"{target}{os.pathsep}/usr/bin")
        result = add_to_user_path(target)
        assert result is None
        assert os.environ["PATH"].split(os.pathsep).count(target) == 1

    def test_adds_to_process_env(self, monkeypatch):
        target = "/opt/dxrk/bin"
        monkeypatch.setenv("PATH", "/usr/bin")
        add_to_user_path(target)
        assert target in os.environ["PATH"].split(os.pathsep)

    def test_no_op_on_non_windows(self):
        if platform.system().lower() == "windows":
            pytest.skip("windows only")
        target = "/opt/dxrk/bin"
        add_to_user_path(target)
        assert target in os.environ["PATH"].split(os.pathsep)

    def test_add_to_process_path_prepends(self, monkeypatch):
        target = "/opt/dxrk/bin"
        monkeypatch.setenv("PATH", "/usr/bin")
        _add_to_process_path(target)
        entries = os.environ["PATH"].split(os.pathsep)
        assert entries[0] == target

    def test_escape_power_shell_string(self):
        assert _escape_power_shell_string("it's") == "it''s"


class TestDetectResultType:
    def test_detection_result_is_typed(self):
        result = _detect_from_inputs(
            "linux", "amd64", "/bin/bash", "ID=ubuntu\n", {}, []
        )
        assert isinstance(result, DetectionResult)
        assert result.dependencies is None

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")

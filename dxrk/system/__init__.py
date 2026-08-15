from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field

from ..strconst import StrUnknown, StrVersion

version_flag = "--version"

LINUX_DISTRO_UNKNOWN = StrUnknown
LINUX_DISTRO_UBUNTU = "ubuntu"
LINUX_DISTRO_DEBIAN = "debian"
LINUX_DISTRO_ARCH = "arch"
LINUX_DISTRO_FEDORA = "fedora"

OS_DARWIN = "darwin"
OS_LINUX = "linux"
OS_WINDOWS = "windows"

PKG_APT = "apt"
PKG_DNF = "dnf"
PKG_BREW = "brew"
PKG_PACMAN = "pacman"
PKG_WINGET = "winget"

SUPPORTED_OS = (OS_DARWIN, OS_LINUX, OS_WINDOWS)

ERROR_UNSUPPORTED_OS = "unsupported operating system"
ERROR_UNSUPPORTED_LINUX_DISTRO = "unsupported linux distro"

version_regexp = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
go_version_regexp = re.compile(r"go(\d+\.\d+(?:\.\d+)?)")


@dataclass
class ConfigState:
    agent: str = ""
    path: str = ""
    exists: bool = False
    is_directory: bool = False


@dataclass
class ToolStatus:
    name: str = ""
    installed: bool = False
    path: str = ""


@dataclass
class PlatformProfile:
    os: str = ""
    linux_distro: str = LINUX_DISTRO_UNKNOWN
    package_manager: str = ""
    npm_writable: bool = False
    supported: bool = False


@dataclass
class SystemInfo:
    os: str = ""
    arch: str = ""
    shell: str = ""
    supported: bool = False
    profile: PlatformProfile = field(default_factory=PlatformProfile)


@dataclass
class Dependency:
    name: str = ""
    required: bool = False
    min_version: str = ""
    detect_cmd: list[str] = field(default_factory=list)
    installed: bool = False
    version: str = ""
    install_hint: str = ""


@dataclass
class DependencyReport:
    dependencies: list[Dependency] = field(default_factory=list)
    all_present: bool = True
    missing_required: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)


@dataclass
class DetectionResult:
    system: SystemInfo = field(default_factory=SystemInfo)
    tools: dict[str, ToolStatus] = field(default_factory=dict)
    configs: list[ConfigState] = field(default_factory=list)
    dependencies: DependencyReport | None = None


def known_agent_config_dirs(home: str) -> list[tuple[str, str]]:
    return [
        ("claude-code", os.path.join(home, ".claude")),
        ("opencode", os.path.join(home, ".config", "opencode")),
        ("kilocode", os.path.join(home, ".config", "kilo")),
        ("gemini-cli", os.path.join(home, ".gemini")),
        ("cursor", os.path.join(home, ".cursor")),
        ("vscode-copilot", os.path.join(home, ".copilot")),
        ("codex", os.path.join(home, ".codex")),
        ("antigravity", os.path.join(home, ".gemini", "antigravity")),
        ("windsurf", os.path.join(home, ".codeium", "windsurf")),
        ("kimi", os.path.join(home, ".kimi")),
        ("qwen-code", os.path.join(home, ".qwen")),
        ("kiro-ide", os.path.join(home, ".kiro")),
        ("openclaw", os.path.join(home, ".openclaw")),
        ("pi", os.path.join(home, ".pi")),
    ]


def scan_configs(home: str) -> list[ConfigState]:
    configs = []
    for agent, path in known_agent_config_dirs(home):
        state = ConfigState(agent=agent, path=path)
        try:
            info = os.stat(path)
        except OSError:
            configs.append(state)
            continue
        state.exists = True
        state.is_directory = stat.S_ISDIR(info.st_mode)
        configs.append(state)
    return configs


def detect_tools(names: list[str]) -> dict[str, ToolStatus]:
    tools = {}
    for name in names:
        path = shutil.which(name)
        tools[name] = ToolStatus(name=name, installed=path is not None, path=path or "")
    return tools


def is_supported_os(goos: str) -> bool:
    return goos in SUPPORTED_OS


def ensure_supported_os(goos: str) -> None:
    if is_supported_os(goos):
        return
    raise OSError(
        f"{ERROR_UNSUPPORTED_OS}: only macOS, Linux, and Windows are supported (detected {goos})"
    )


def ensure_supported_platform(profile: PlatformProfile) -> None:
    ensure_supported_os(profile.os)
    if profile.os == OS_LINUX and not profile.supported:
        raise OSError(
            f"{ERROR_UNSUPPORTED_LINUX_DISTRO}: Linux support is limited to Ubuntu/Debian, Arch, and Fedora/RHEL family (detected {profile.linux_distro})"
        )


def _install_hint_git(profile: PlatformProfile) -> str:
    if profile.os == OS_DARWIN:
        return "brew install git"
    if profile.os == OS_WINDOWS:
        return "winget install Git.Git"
    if profile.package_manager == PKG_APT:
        return "sudo apt-get install -y git"
    if profile.package_manager == PKG_PACMAN:
        return "sudo pacman -S --noconfirm git"
    if profile.package_manager == PKG_DNF:
        return "sudo dnf install -y git"
    return "install git from https://git-scm.com/"


def _install_hint_curl(profile: PlatformProfile) -> str:
    if profile.os == OS_DARWIN:
        return "brew install curl"
    if profile.os == OS_WINDOWS:
        return "curl is pre-installed on Windows 10+"
    if profile.package_manager == PKG_APT:
        return "sudo apt-get install -y curl"
    if profile.package_manager == PKG_PACMAN:
        return "sudo pacman -S --noconfirm curl"
    if profile.package_manager == PKG_DNF:
        return "sudo dnf install -y curl"
    return "install curl from https://curl.se/"


def _install_hint_node(profile: PlatformProfile) -> str:
    if profile.os == OS_DARWIN:
        return "brew install node"
    if profile.os == OS_WINDOWS:
        return "winget install OpenJS.NodeJS.LTS"
    if profile.package_manager == PKG_APT:
        return "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs"
    if profile.package_manager == PKG_PACMAN:
        return "sudo pacman -S --noconfirm nodejs npm"
    if profile.package_manager == PKG_DNF:
        return "curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash - && sudo dnf install -y nodejs"
    return "install node from https://nodejs.org/"


def _install_hint_npm(profile: PlatformProfile) -> str:
    return "npm is included with node — install node first"


def _install_hint_brew(profile: PlatformProfile) -> str:
    return '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'


def _install_hint_go(profile: PlatformProfile) -> str:
    if profile.os == OS_DARWIN:
        return "brew install go"
    if profile.os == OS_WINDOWS:
        return "winget install GoLang.Go"
    if profile.package_manager == PKG_APT:
        return "sudo apt-get install -y golang"
    if profile.package_manager == PKG_PACMAN:
        return "sudo pacman -S --noconfirm go"
    if profile.package_manager == PKG_DNF:
        return "sudo dnf install -y golang"
    return "install go from https://go.dev/dl/"


def _define_dependencies(profile: PlatformProfile) -> list[Dependency]:
    dependencies = [
        Dependency(
            name="git",
            required=True,
            min_version="",
            detect_cmd=["git", "--version"],
            installed=False,
            version="",
            install_hint=_install_hint_git(profile),
        ),
        Dependency(
            name="curl",
            required=True,
            min_version="",
            detect_cmd=["curl", "--version"],
            installed=False,
            version="",
            install_hint=_install_hint_curl(profile),
        ),
        Dependency(
            name="node",
            required=True,
            min_version="18.0.0",
            detect_cmd=["node", "--version"],
            installed=False,
            version="",
            install_hint=_install_hint_node(profile),
        ),
        Dependency(
            name="npm",
            required=True,
            min_version="",
            detect_cmd=["npm", "--version"],
            installed=False,
            version="",
            install_hint=_install_hint_npm(profile),
        ),
    ]
    if profile.os == OS_DARWIN:
        dependencies.append(
            Dependency(
                name="brew",
                required=False,
                min_version="",
                detect_cmd=["brew", "--version"],
                installed=False,
                version="",
                install_hint=_install_hint_brew(profile),
            )
        )
    dependencies.append(
        Dependency(
            name="go",
            required=False,
            min_version="",
            detect_cmd=["go", StrVersion],
            installed=False,
            version="",
            install_hint=_install_hint_go(profile),
        )
    )
    return dependencies


def _version_parts(version: str) -> tuple[int, int, int]:
    parts = version.split(".", 2)
    result = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return (result[0], result[1], result[2])


def _version_at_least(version: str, min_version: str) -> bool:
    version_parts = _version_parts(version)
    min_parts = _version_parts(min_version)
    for i in range(3):
        if version_parts[i] > min_parts[i]:
            return True
        if version_parts[i] < min_parts[i]:
            return False
    return True


def _parse_version(name: str, output: str) -> str:
    output = output.strip()
    if not output:
        return ""
    if name == "go":
        match = go_version_regexp.search(output)
        if match:
            return match.group(1)
    match = version_regexp.search(output)
    if match:
        return match.group(1)
    return ""


def _detect_single_dep(dep: Dependency) -> Dependency:
    if not dep.detect_cmd:
        return dep
    if shutil.which(dep.detect_cmd[0]) is None:
        return dep
    dep.installed = True
    try:
        result = subprocess.run(
            dep.detect_cmd, capture_output=True, text=True, check=False
        )
    except OSError:
        return dep
    if result.returncode != 0:
        return dep
    dep.version = _parse_version(dep.name, result.stdout)
    if (
        dep.min_version
        and dep.version
        and not _version_at_least(dep.version, dep.min_version)
    ):
        dep.installed = False
    return dep


def detect_dependencies(profile: PlatformProfile) -> DependencyReport:
    dependencies = _define_dependencies(profile)
    for dep in dependencies:
        _detect_single_dep(dep)
    report = DependencyReport(
        dependencies=dependencies,
        all_present=True,
        missing_required=[],
        missing_optional=[],
    )
    for dep in dependencies:
        if dep.required and not dep.installed:
            report.all_present = False
            report.missing_required.append(dep.name)
        elif not dep.required and not dep.installed:
            report.missing_optional.append(dep.name)
    return report


def render_dependency_report(report: DependencyReport) -> str:
    lines = ["Dependencies:"]
    for dep in report.dependencies:
        if dep.installed:
            marker = "v"
            status = dep.version if dep.version else "found"
        else:
            marker = "x"
            status = "NOT FOUND"
        if not dep.installed and dep.required:
            suffix = " (required)"
        elif not dep.required:
            suffix = " (optional)"
        else:
            suffix = ""
        lines.append(f"  {dep.name}: {marker} {status}{suffix}")
    if report.missing_required:
        lines.append(f"Missing required: {', '.join(report.missing_required)}")
    if report.missing_optional:
        lines.append(f"Missing optional: {', '.join(report.missing_optional)}")
    return "\n".join(lines)


def format_missing_deps_message(report: DependencyReport) -> str:
    if report.all_present:
        return "All required dependencies are present."
    missing = ", ".join(report.missing_required) if report.missing_required else "none"
    message = (
        f"Missing {len(report.missing_required)} required dependency(ies): {missing}\n"
    )
    message += "\nInstall hints:\n"
    for dep in report.dependencies:
        if not dep.installed and dep.required:
            message += f"  {dep.name}: {dep.install_hint}\n"
    return message


def _install_commands_git(profile: PlatformProfile) -> list[list[str]] | None:
    if profile.os == OS_DARWIN:
        return [["brew", "install", "git"]]
    if profile.os == OS_WINDOWS:
        return [
            [
                "winget",
                "install",
                "--id",
                "Git.Git",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        ]
    if profile.package_manager == PKG_APT:
        return [["sudo", "apt-get", "install", "-y", "git"]]
    if profile.package_manager == PKG_PACMAN:
        return [["sudo", "pacman", "-S", "--noconfirm", "git"]]
    if profile.package_manager == PKG_DNF:
        return [["sudo", "dnf", "install", "-y", "git"]]
    return None


def _install_commands_curl(profile: PlatformProfile) -> list[list[str]] | None:
    if profile.os == OS_DARWIN:
        return [["brew", "install", "curl"]]
    if profile.os == OS_WINDOWS:
        return None
    if profile.package_manager == PKG_APT:
        return [["sudo", "apt-get", "install", "-y", "curl"]]
    if profile.package_manager == PKG_PACMAN:
        return [["sudo", "pacman", "-S", "--noconfirm", "curl"]]
    if profile.package_manager == PKG_DNF:
        return [["sudo", "dnf", "install", "-y", "curl"]]
    return None


def _install_commands_node(profile: PlatformProfile) -> list[list[str]] | None:
    if profile.os == OS_DARWIN:
        return [["brew", "install", "node"]]
    if profile.os == OS_WINDOWS:
        return [
            [
                "winget",
                "install",
                "--id",
                "OpenJS.NodeJS.LTS",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        ]
    if profile.package_manager == PKG_APT:
        return [
            [
                "bash",
                "-c",
                "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -",
            ],
            ["sudo", "apt-get", "install", "-y", "nodejs"],
        ]
    if profile.package_manager == PKG_PACMAN:
        return [["sudo", "pacman", "-S", "--noconfirm", "nodejs", "npm"]]
    if profile.package_manager == PKG_DNF:
        return [
            [
                "bash",
                "-c",
                "curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -",
            ],
            ["sudo", "dnf", "install", "-y", "nodejs"],
        ]
    return None


def _install_commands_brew(profile: PlatformProfile) -> list[list[str]] | None:
    if profile.os == OS_DARWIN:
        return [
            [
                "bash",
                "-c",
                "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)",
            ]
        ]
    return None


def _install_commands_go(profile: PlatformProfile) -> list[list[str]] | None:
    if profile.os == OS_DARWIN:
        return [["brew", "install", "go"]]
    if profile.os == OS_WINDOWS:
        return [
            [
                "winget",
                "install",
                "--id",
                "GoLang.Go",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        ]
    if profile.package_manager == PKG_APT:
        return [["sudo", "apt-get", "install", "-y", "golang"]]
    if profile.package_manager == PKG_PACMAN:
        return [["sudo", "pacman", "-S", "--noconfirm", "go"]]
    if profile.package_manager == PKG_DNF:
        return [["sudo", "dnf", "install", "-y", "golang"]]
    return None


def install_commands_for_dep(
    name: str, profile: PlatformProfile
) -> list[list[str]] | None:
    if name == "git":
        return _install_commands_git(profile)
    if name == "curl":
        return _install_commands_curl(profile)
    if name == "node":
        return _install_commands_node(profile)
    if name == "brew":
        return _install_commands_brew(profile)
    if name == "go":
        return _install_commands_go(profile)
    return None


def _is_ubuntu_like(distro_id: str, id_like: str) -> bool:
    if distro_id in ("ubuntu", "debian"):
        return True
    return any(token in ("ubuntu", "debian") for token in id_like.split())


def _is_arch_like(distro_id: str, id_like: str) -> bool:
    if distro_id == "arch":
        return True
    return any(token == "arch" for token in id_like.split())


def _is_fedora_like(distro_id: str, id_like: str) -> bool:
    fedora_family = ("fedora", "rhel", "centos", "rocky", "almalinux", "nobara")
    if distro_id in fedora_family:
        return True
    return any(token in fedora_family for token in id_like.split())


def _detect_linux_distro(os_release: str) -> str:
    if not os_release.strip():
        return LINUX_DISTRO_UNKNOWN
    fields: dict[str, str] = {}
    for line in os_release.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').lower()
        fields[key] = value
    distro_id = fields.get("ID", "")
    id_like = fields.get("ID_LIKE", "")
    if _is_ubuntu_like(distro_id, id_like):
        if distro_id == "debian":
            return LINUX_DISTRO_DEBIAN
        return LINUX_DISTRO_UBUNTU
    if _is_arch_like(distro_id, id_like):
        return LINUX_DISTRO_ARCH
    if _is_fedora_like(distro_id, id_like):
        return LINUX_DISTRO_FEDORA
    return LINUX_DISTRO_UNKNOWN


def _resolve_platform_profile(
    goos: str, linux_os_release: str, tools: dict[str, ToolStatus]
) -> PlatformProfile:
    profile = PlatformProfile(os=goos)
    if goos == OS_DARWIN:
        profile.package_manager = PKG_BREW
        profile.supported = True
        return profile
    if goos == OS_LINUX:
        profile.linux_distro = _detect_linux_distro(linux_os_release)
        brew = tools.get("brew")
        if brew is not None and brew.installed:
            profile.package_manager = PKG_BREW
            profile.supported = True
            return profile
        if profile.linux_distro in (LINUX_DISTRO_UBUNTU, LINUX_DISTRO_DEBIAN):
            profile.package_manager = PKG_APT
            profile.supported = True
            return profile
        if profile.linux_distro == LINUX_DISTRO_ARCH:
            profile.package_manager = PKG_PACMAN
            profile.supported = True
            return profile
        if profile.linux_distro == LINUX_DISTRO_FEDORA:
            profile.package_manager = PKG_DNF
            profile.supported = True
            return profile
        return profile
    if goos == OS_WINDOWS:
        profile.package_manager = PKG_WINGET
        profile.supported = True
        return profile
    return profile


def _detect_from_inputs(
    goos: str,
    arch: str,
    shell: str,
    linux_os_release: str,
    tools: dict[str, ToolStatus],
    configs: list[ConfigState],
) -> DetectionResult:
    if shell == "":
        shell = "powershell" if goos == OS_WINDOWS else "unknown"
    profile = _resolve_platform_profile(goos, linux_os_release, tools)
    system = SystemInfo(
        os=goos, arch=arch, shell=shell, supported=profile.supported, profile=profile
    )
    return DetectionResult(system=system, tools=tools, configs=configs)


def _detect_npm_writable(home: str) -> bool:
    try:
        result = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    prefix = result.stdout.strip()
    return prefix.startswith(home)


def detect() -> DetectionResult:
    goos = platform.system().lower()
    home = os.path.expanduser("~")
    tools = detect_tools(["git", "curl", "brew", "node"])
    configs = scan_configs(home)
    os_release_content = ""
    if goos == OS_LINUX:
        try:
            with open("/etc/os-release", encoding="utf-8") as file:
                os_release_content = file.read()
        except OSError:
            os_release_content = ""
    result = _detect_from_inputs(
        goos,
        platform.machine().lower(),
        os.environ.get("SHELL", ""),
        os_release_content,
        tools,
        configs,
    )
    profile = result.system.profile
    if goos == OS_WINDOWS:
        profile.npm_writable = True
    else:
        profile.npm_writable = _detect_npm_writable(home)
    result.dependencies = detect_dependencies(profile)
    return result


def _escape_power_shell_string(value: str) -> str:
    return value.replace("'", "''")


def _add_to_process_path(dir: str) -> None:
    current = os.environ.get("PATH", "")
    target = os.path.normcase(os.path.normpath(dir))
    for entry in current.split(os.pathsep):
        if entry and os.path.normcase(os.path.normpath(entry)) == target:
            return None
    if not current:
        os.environ["PATH"] = dir
    else:
        os.environ["PATH"] = dir + os.pathsep + current
    return None


def _path_contains(dir: str) -> bool:
    target = os.path.normcase(os.path.normpath(dir))
    return any(
        entry and os.path.normcase(os.path.normpath(entry)) == target
        for entry in os.environ.get("PATH", "").split(os.pathsep)
    )


def add_to_user_path(dir: str) -> None:
    if platform.system().lower() != OS_WINDOWS:
        return _add_to_process_path(dir)
    if _path_contains(dir):
        return None
    _add_to_process_path(dir)
    safe_dir = _escape_power_shell_string(dir)
    script = (
        "`$current = [Environment]::GetEnvironmentVariable('PATH', 'User'); "
        f"if ((`$current.Split(';')) -notcontains '{safe_dir}') "
        f"{{ [Environment]::SetEnvironmentVariable('PATH', '{safe_dir};' + `$current, 'User') }}"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    return None

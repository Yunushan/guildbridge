from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CHECK_TARGETS = ("cli", "desktop-gui", "web-gui", "dev")


@dataclass(frozen=True)
class SupportedPlatform:
    name: str
    family: str
    identifiers: tuple[str, ...]
    package_managers: tuple[str, ...]
    python_package: str
    tk_package: str
    cli_support: str
    desktop_gui_support: str
    web_gui_support: str
    ci_coverage: str
    notes: str

    @property
    def support_summary(self) -> str:
        return (
            f"CLI: {self.cli_support}; desktop GUI: {self.desktop_gui_support}; "
            f"web GUI: {self.web_gui_support}; CI: {self.ci_coverage}"
        )


@dataclass(frozen=True)
class RuntimeCheckEvaluation:
    target: str
    ready: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]


SUPPORTED_PLATFORMS: tuple[SupportedPlatform, ...] = (
    SupportedPlatform(
        name="Windows",
        family="Windows",
        identifiers=("windows", "win32"),
        package_managers=("winget", "chocolatey", "scoop"),
        python_package="Python 3.10+ from python.org, Microsoft Store, winget, Chocolatey, or Scoop",
        tk_package="bundled with the standard python.org installer",
        cli_support="CI tested on GitHub Actions",
        desktop_gui_support="supported when Tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="GitHub Actions: windows-2025-vs2026; compatibility: windows-2022; self-hosted: Windows 10/11/Server 2019/2026",
        notes="Use PowerShell, Command Prompt, Windows Terminal, or the GUI launcher.",
    ),
    SupportedPlatform(
        name="Windows Server",
        family="Windows",
        identifiers=("windows server",),
        package_managers=("winget", "chocolatey", "scoop"),
        python_package="Python 3.10+ from python.org, winget, Chocolatey, or Scoop",
        tk_package="bundled with the standard python.org installer",
        cli_support="install documented; not CI tested",
        desktop_gui_support="requires Desktop Experience and Tkinter",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="manual self-hosted: Windows Server 2019/2026; hosted compatibility: windows-2022",
        notes="Server Core is CLI-only; the GUI requires Desktop Experience and Tk support.",
    ),
    SupportedPlatform(
        name="Debian",
        family="Debian",
        identifiers=("debian",),
        package_managers=("apt",),
        python_package="python3 python3-pip python3-venv",
        tk_package="python3-tk",
        cli_support="CI tested through the GitLab python image",
        desktop_gui_support="supported when python3-tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="GitLab CI: python:3.12 Debian image",
        notes="Supported on stable and current testing releases with Python 3.10+.",
    ),
    SupportedPlatform(
        name="Ubuntu",
        family="Debian",
        identifiers=("ubuntu",),
        package_managers=("apt",),
        python_package="python3 python3-pip python3-venv",
        tk_package="python3-tk",
        cli_support="CI tested on GitHub Actions",
        desktop_gui_support="supported when python3-tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="GitHub Actions: ubuntu-24.04; manual self-hosted: ubuntu-26.04",
        notes="Supported on Ubuntu LTS and current releases with Python 3.10+.",
    ),
    SupportedPlatform(
        name="Linux Mint",
        family="Debian",
        identifiers=("linuxmint", "mint"),
        package_managers=("apt",),
        python_package="python3 python3-pip python3-venv",
        tk_package="python3-tk",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported as an Ubuntu/Debian-family platform.",
    ),
    SupportedPlatform(
        name="RHEL",
        family="RHEL",
        identifiers=("rhel", "redhat", "red hat enterprise linux"),
        package_managers=("dnf", "yum"),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Use an enabled AppStream/BaseOS repository that provides Python 3.10+.",
    ),
    SupportedPlatform(
        name="AlmaLinux",
        family="RHEL",
        identifiers=("almalinux", "alma"),
        package_managers=("dnf",),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported as a RHEL-compatible platform.",
    ),
    SupportedPlatform(
        name="Rocky Linux",
        family="RHEL",
        identifiers=("rocky", "rocky linux"),
        package_managers=("dnf",),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported as a RHEL-compatible platform.",
    ),
    SupportedPlatform(
        name="Oracle Linux",
        family="RHEL",
        identifiers=("ol", "oracle", "oracle linux"),
        package_managers=("dnf", "yum"),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported as a RHEL-compatible platform.",
    ),
    SupportedPlatform(
        name="Fedora",
        family="Fedora",
        identifiers=("fedora",),
        package_managers=("dnf",),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported on current Fedora releases.",
    ),
    SupportedPlatform(
        name="CentOS",
        family="RHEL",
        identifiers=("centos",),
        package_managers=("dnf", "yum"),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported when Python 3.10+ is available; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported when Python 3.10+ is available from enabled repositories or an approved Python source.",
    ),
    SupportedPlatform(
        name="CentOS Stream",
        family="RHEL",
        identifiers=("centos stream", "centos-stream"),
        package_managers=("dnf",),
        python_package="python3 python3-pip",
        tk_package="python3-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when python3-tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported on current Stream releases with Python 3.10+.",
    ),
    SupportedPlatform(
        name="Arch Linux",
        family="Arch",
        identifiers=("arch", "arch linux"),
        package_managers=("pacman",),
        python_package="python python-pip",
        tk_package="tk",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported on rolling Arch installs with current Python.",
    ),
    SupportedPlatform(
        name="Manjaro Linux",
        family="Arch",
        identifiers=("manjaro", "manjaro linux"),
        package_managers=("pacman", "pamac"),
        python_package="python python-pip",
        tk_package="tk",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Supported as an Arch-family platform.",
    ),
    SupportedPlatform(
        name="Gentoo",
        family="Gentoo",
        identifiers=("gentoo",),
        package_managers=("emerge",),
        python_package="dev-lang/python dev-python/pip",
        tk_package="dev-lang/tk",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when Tk USE support and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Enable Python/Tk USE flags according to the local Gentoo profile.",
    ),
    SupportedPlatform(
        name="FreeBSD",
        family="BSD",
        identifiers=("freebsd",),
        package_managers=("pkg", "ports"),
        python_package="python py311-pip or py312-pip",
        tk_package="py311-tkinter or py312-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when Tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Desktop GUI requires X11/Wayland and Tk; web GUI works from a browser.",
    ),
    SupportedPlatform(
        name="NetBSD",
        family="BSD",
        identifiers=("netbsd",),
        package_managers=("pkgin", "pkg_add", "pkgsrc"),
        python_package="python312 py312-pip",
        tk_package="py312-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when Tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Desktop GUI requires X11/Wayland and Tk; web GUI works from a browser.",
    ),
    SupportedPlatform(
        name="OpenBSD",
        family="BSD",
        identifiers=("openbsd",),
        package_managers=("pkg_add", "ports"),
        python_package="python%3.12 py3-pip",
        tk_package="python-tkinter",
        cli_support="install-script supported; not CI tested",
        desktop_gui_support="supported when Tk and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="not covered by project CI",
        notes="Desktop GUI requires X11/Wayland and Tk; web GUI works from a browser.",
    ),
    SupportedPlatform(
        name="macOS",
        family="Darwin",
        identifiers=("macos", "darwin", "osx", "mac os"),
        package_managers=("homebrew", "macports", "python.org"),
        python_package="Python 3.10+ from python.org, Homebrew, or MacPorts",
        tk_package="bundled with python.org builds; install python-tk through the selected package manager if needed",
        cli_support="CI tested on GitHub Actions",
        desktop_gui_support="supported when Tkinter and a desktop session are available",
        web_gui_support="supported locally or on a trusted LAN with --allow-lan",
        ci_coverage="GitHub Actions: macos-15; compatibility: macos-26",
        notes="Supports CLI, Tk desktop GUI, and local web GUI.",
    ),
    SupportedPlatform(
        name="Android",
        family="Mobile",
        identifiers=("android", "termux"),
        package_managers=("termux pkg", "pydroid"),
        python_package="python through Termux or a Python-capable Android environment",
        tk_package="Tkinter is not a reliable Android GUI target; use guildbridge-web from a mobile browser.",
        cli_support="experimental on-device Python support; not CI tested",
        desktop_gui_support="not supported",
        web_gui_support="browser client supported against guildbridge-web",
        ci_coverage="not covered by project CI",
        notes="CLI and web GUI are supported where Python 3.10+, pip, TLS certificates, and network access are available.",
    ),
    SupportedPlatform(
        name="Apple iOS",
        family="Mobile",
        identifiers=("ios", "iphoneos", "ipados", "apple ios"),
        package_managers=("Pyto", "a-Shell", "Pythonista-style environments"),
        python_package="Python 3.10+ through an iOS Python environment",
        tk_package="Tkinter is not available for normal iOS apps; use guildbridge-web from Safari or another browser.",
        cli_support="experimental on-device Python support; not CI tested",
        desktop_gui_support="not supported",
        web_gui_support="browser client supported against guildbridge-web",
        ci_coverage="not covered by project CI",
        notes="Browser GUI is supported against a GuildBridge web server; on-device CLI depends on the chosen iOS Python runtime.",
    ),
)


def platform_names() -> tuple[str, ...]:
    return tuple(platform.name for platform in SUPPORTED_PLATFORMS)


def find_supported_platform(name: str) -> SupportedPlatform | None:
    normalized = name.lower().strip()
    for supported in SUPPORTED_PLATFORMS:
        names = (supported.name.lower(), *supported.identifiers)
        if normalized in names:
            return supported
    return None


def detect_current_platform() -> SupportedPlatform | None:
    if _looks_like_ios():
        return find_supported_platform("ios")
    if _looks_like_android():
        return find_supported_platform("android")

    system = platform.system().lower()
    if system == "windows":
        return find_supported_platform("windows")
    if system == "darwin":
        return find_supported_platform("macos")
    if system in {"freebsd", "netbsd", "openbsd"}:
        return find_supported_platform(system)

    os_release = Path("/etc/os-release")
    if os_release.exists():
        values: dict[str, str] = {}
        for line in os_release.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
        candidates = (
            values.get("ID", ""),
            values.get("NAME", ""),
            values.get("ID_LIKE", ""),
        )
        for candidate in candidates:
            for part in candidate.lower().replace(",", " ").split():
                match = find_supported_platform(part)
                if match:
                    return match
            match = find_supported_platform(candidate)
            if match:
                return match
    return None


def _looks_like_android() -> bool:
    return any(os.getenv(name) for name in ("ANDROID_ROOT", "ANDROID_DATA", "TERMUX_VERSION"))


def _looks_like_ios() -> bool:
    if sys.platform in {"ios", "iphoneos"}:
        return True
    platform_text = platform.platform().lower()
    machine = platform.machine().lower()
    return "iphone" in platform_text or "ipad" in platform_text or machine.startswith(("iphone", "ipad"))


def _check_bool(checks: Mapping[str, object], key: str) -> bool:
    return checks.get(key) is True


def evaluate_runtime_check(checks: Mapping[str, object], target: str = "cli") -> RuntimeCheckEvaluation:
    if target not in CHECK_TARGETS:
        raise ValueError(f"Unknown platform check target: {target}")

    failures: list[str] = []
    warnings: list[str] = []

    if not _check_bool(checks, "supported_platform"):
        failures.append("platform is not in the GuildBridge support registry")
    if not _check_bool(checks, "python_ok"):
        failures.append("Python 3.10+ is required")
    if not _check_bool(checks, "requests_available"):
        failures.append("requests is not installed")
    if not _check_bool(checks, "dotenv_available"):
        failures.append("python-dotenv is not installed")

    desktop_gui_support = str(checks.get("desktop_gui_support", ""))
    if target == "desktop-gui":
        if desktop_gui_support == "not supported":
            failures.append("desktop GUI is not supported on this platform")
        if not _check_bool(checks, "tkinter_available"):
            failures.append("Tkinter is required for the desktop GUI")
    elif not _check_bool(checks, "tkinter_available"):
        warnings.append("Tkinter is not available; desktop GUI checks would fail")

    if target == "dev" and not _check_bool(checks, "git_available"):
        failures.append("Git is required for development and clone workflows")
    elif not _check_bool(checks, "git_available"):
        warnings.append("Git is not available; clone and development workflows need Git")

    if checks.get("ci_coverage") == "not covered by project CI":
        warnings.append("this platform is not covered by project CI")

    cli_support = str(checks.get("cli_support", ""))
    if target in {"cli", "dev"} and "experimental" in cli_support:
        warnings.append("CLI support is experimental on this platform")

    return RuntimeCheckEvaluation(target=target, ready=not failures, failures=tuple(failures), warnings=tuple(warnings))


def runtime_check() -> dict[str, str | bool]:
    detected = detect_current_platform()
    python_ok = sys.version_info >= (3, 10)
    tk_ok = importlib.util.find_spec("tkinter") is not None
    requests_ok = importlib.util.find_spec("requests") is not None
    dotenv_ok = importlib.util.find_spec("dotenv") is not None

    checks: dict[str, str | bool] = {
        "platform": detected.name if detected else platform.platform(),
        "supported_platform": detected is not None,
        "cli_support": detected.cli_support if detected else "unknown platform",
        "desktop_gui_support": detected.desktop_gui_support if detected else "unknown platform",
        "web_gui_support": detected.web_gui_support if detected else "unknown platform",
        "ci_coverage": detected.ci_coverage if detected else "not covered by project CI",
        "python": sys.version.split()[0],
        "python_ok": python_ok,
        "tkinter_available": tk_ok,
        "web_gui_available": python_ok,
        "requests_available": requests_ok,
        "dotenv_available": dotenv_ok,
        "openssl": ssl.OPENSSL_VERSION,
        "git_available": shutil.which("git") is not None,
    }
    checks["cli_ready"] = evaluate_runtime_check(checks, "cli").ready
    checks["desktop_gui_ready"] = evaluate_runtime_check(checks, "desktop-gui").ready
    checks["web_gui_ready"] = evaluate_runtime_check(checks, "web-gui").ready
    checks["dev_tools_ready"] = evaluate_runtime_check(checks, "dev").ready
    return checks

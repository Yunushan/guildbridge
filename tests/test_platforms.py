from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from guildbridge.cli import main
from guildbridge.platforms import (
    SUPPORTED_PLATFORMS,
    evaluate_runtime_check,
    find_supported_platform,
    platform_names,
    runtime_check,
)

ROOT = Path(__file__).resolve().parents[1]


def load_script_module(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load script module: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requested_platforms_are_listed() -> None:
    names = set(platform_names())
    expected = {
        "Windows",
        "Windows Server",
        "Debian",
        "Ubuntu",
        "RHEL",
        "AlmaLinux",
        "Rocky Linux",
        "Oracle Linux",
        "Linux Mint",
        "Arch Linux",
        "Manjaro Linux",
        "Gentoo",
        "Fedora",
        "CentOS",
        "CentOS Stream",
        "FreeBSD",
        "NetBSD",
        "OpenBSD",
        "macOS",
        "Android",
        "Apple iOS",
    }
    assert expected <= names


def test_platform_alias_lookup() -> None:
    assert find_supported_platform("linuxmint") is not None
    assert find_supported_platform("rocky") is not None
    assert find_supported_platform("ol") is not None
    assert find_supported_platform("win32") is not None
    assert find_supported_platform("darwin") is not None
    assert find_supported_platform("termux") is not None
    assert find_supported_platform("ipados") is not None


def test_platform_support_metadata_is_complete() -> None:
    for supported in SUPPORTED_PLATFORMS:
        assert supported.cli_support
        assert supported.desktop_gui_support
        assert supported.web_gui_support
        assert supported.ci_coverage
        assert "CLI:" in supported.support_summary
        assert "desktop GUI:" in supported.support_summary
        assert "web GUI:" in supported.support_summary
        assert "CI:" in supported.support_summary


def test_ci_coverage_claims_are_explicit() -> None:
    ci_tested = {platform.name for platform in SUPPORTED_PLATFORMS if platform.ci_coverage != "not covered by project CI"}
    assert ci_tested == {"Windows", "Debian", "Ubuntu", "macOS"}


def test_mobile_support_is_browser_client_first() -> None:
    android = find_supported_platform("android")
    ios = find_supported_platform("ios")
    assert android is not None
    assert ios is not None
    assert android.desktop_gui_support == "not supported"
    assert ios.desktop_gui_support == "not supported"
    assert "browser client" in android.web_gui_support
    assert "browser client" in ios.web_gui_support


def _check_fixture(**overrides: object) -> dict[str, object]:
    checks: dict[str, object] = {
        "supported_platform": True,
        "python_ok": True,
        "requests_available": True,
        "dotenv_available": True,
        "tkinter_available": True,
        "git_available": True,
        "ci_coverage": "GitHub Actions: ubuntu-24.04",
        "cli_support": "CI tested on GitHub Actions",
        "desktop_gui_support": "supported when Tkinter and a desktop session are available",
    }
    checks.update(overrides)
    return checks


def test_cli_check_allows_optional_gui_and_git_warnings() -> None:
    evaluation = evaluate_runtime_check(
        _check_fixture(tkinter_available=False, git_available=False),
        "cli",
    )
    assert evaluation.ready is True
    assert "Tkinter is not available" in evaluation.warnings[0]
    assert "Git is not available" in evaluation.warnings[1]


def test_desktop_gui_check_requires_tkinter() -> None:
    evaluation = evaluate_runtime_check(_check_fixture(tkinter_available=False), "desktop-gui")
    assert evaluation.ready is False
    assert "Tkinter is required for the desktop GUI" in evaluation.failures


def test_desktop_gui_check_rejects_mobile_platforms() -> None:
    evaluation = evaluate_runtime_check(_check_fixture(desktop_gui_support="not supported"), "desktop-gui")
    assert evaluation.ready is False
    assert "desktop GUI is not supported on this platform" in evaluation.failures


def test_dev_check_requires_git() -> None:
    evaluation = evaluate_runtime_check(_check_fixture(git_available=False), "dev")
    assert evaluation.ready is False
    assert "Git is required for development and clone workflows" in evaluation.failures


def test_unsupported_platform_fails_runtime_check() -> None:
    evaluation = evaluate_runtime_check(_check_fixture(supported_platform=False), "web-gui")
    assert evaluation.ready is False
    assert "platform is not in the GuildBridge support registry" in evaluation.failures


def test_unknown_check_target_is_rejected() -> None:
    try:
        evaluate_runtime_check(_check_fixture(), "invalid")
    except ValueError as exc:
        assert "Unknown platform check target" in str(exc)
    else:
        raise AssertionError("expected invalid check target to fail")


def test_runtime_check_shape() -> None:
    checks = runtime_check()
    assert "platform" in checks
    assert "cli_support" in checks
    assert "desktop_gui_support" in checks
    assert "web_gui_support" in checks
    assert "ci_coverage" in checks
    assert "python_ok" in checks
    assert "cli_ready" in checks
    assert "desktop_gui_ready" in checks
    assert "web_gui_ready" in checks
    assert "dev_tools_ready" in checks
    assert checks["python_ok"] is True


def test_platforms_cli(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["platforms"]) == 0
    out = capsys.readouterr().out
    assert "Windows Server" in out
    assert "Linux Mint" in out
    assert "FreeBSD" in out
    assert "Apple iOS" in out
    assert "CI:" in out
    assert "desktop GUI:" in out


def test_platforms_check_cli(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["platforms", "--check", "--require", "cli"]) == 0
    out = capsys.readouterr().out
    assert "required_target: cli" in out
    assert "check_ready: True" in out


def test_check_platform_script_json_output(capsys) -> None:  # type: ignore[no-untyped-def]
    module = load_script_module("check-platform")

    assert module.main(["--require", "cli", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["evaluation"]["target"] == "cli"
    assert data["evaluation"]["ready"] is True
    assert "python_ok" in data["checks"]


def test_install_system_deps_script_has_safe_dry_run_contracts() -> None:
    script = (ROOT / "scripts" / "install-system-deps.sh").read_text(encoding="utf-8")

    assert "--dry-run" in script
    assert "--require cli|desktop-gui|web-gui|dev" in script
    assert "GUILDBRIDGE_OS_RELEASE" in script
    assert "GUILDBRIDGE_UNAME_S" in script
    assert "pkg_add -I" in script
    assert 'scripts/check-platform.py --require "$REQUIRE_TARGET"' in script


def test_windows_check_script_has_safe_require_contracts() -> None:
    script = (ROOT / "scripts" / "check-platform.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("cli", "desktop-gui", "web-gui", "dev")]' in script
    assert 'Join-Path $ScriptRoot "check-platform.py"' in script
    assert "--require $Require" in script
    assert "--accept-package-agreements --accept-source-agreements" in script

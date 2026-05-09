from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_windows_build_extra_and_assets_are_declared() -> None:
    pyproject = _text("pyproject.toml")
    manifest = _text("MANIFEST.in")
    verifier = _text("scripts/verify-dist.py")

    assert "windows-build = [" in pyproject
    assert '"pyinstaller>=6.16.0"' in pyproject
    assert "recursive-include packaging *.py *.wxs" in manifest
    assert "docs/WINDOWS_RELEASE.md" in verifier
    assert "packaging/windows/GuildBridge.wxs" in verifier
    assert "packaging/windows/guildbridge-cli.py" in verifier
    assert "scripts/build-windows-dist.ps1" in verifier


def test_windows_launchers_point_to_console_gui_and_web_entrypoints() -> None:
    assert "from guildbridge.cli import main" in _text("packaging/windows/guildbridge-cli.py")
    assert "from guildbridge.gui import main" in _text("packaging/windows/guildbridge-gui.py")
    assert "from guildbridge.web import main" in _text("packaging/windows/guildbridge-web.py")


def test_windows_build_script_creates_zip_exe_and_optional_msi() -> None:
    script = _text("scripts/build-windows-dist.ps1")

    assert "PyInstaller" in script
    assert "--onefile" in script
    assert "guildbridge.exe" in script
    assert "guildbridge-gui.exe" in script
    assert "guildbridge-web.exe" in script
    assert "Compress-Archive" in script
    assert "wix" in script
    assert "GuildBridge-$Version-windows-x64.msi" in script
    assert "GuildBridge-$Version-windows-x64.zip" in script
    assert "Refusing to remove path outside repository" in script


def test_windows_msi_source_has_expected_executables_and_shortcuts() -> None:
    wxs = _text("packaging/windows/GuildBridge.wxs")
    ET.fromstring(wxs)

    assert 'Name="GuildBridge"' in wxs
    assert 'UpgradeCode="8D88BE6B-1F95-48D0-BAB9-21BB4A941AB1"' in wxs
    assert 'Source="$(var.SourceDir)\\guildbridge.exe"' in wxs
    assert 'Source="$(var.SourceDir)\\guildbridge-gui.exe"' in wxs
    assert 'Source="$(var.SourceDir)\\guildbridge-web.exe"' in wxs
    assert 'Name="GuildBridge GUI"' in wxs
    assert 'Name="GuildBridge Web GUI"' in wxs
    assert 'Name="GuildBridge CLI"' in wxs


def test_release_workflow_uploads_windows_zip_and_msi() -> None:
    release = _text(".github/workflows/release.yml")

    assert "windows-artifacts:" in release
    assert "runs-on: windows-2025-vs2026" in release
    assert 'python -m pip install -e ".[dev,windows-build]"' in release
    assert "dotnet tool install --global wix" in release
    assert ".\\scripts\\build-windows-dist.ps1" in release
    assert "name: guildbridge-windows" in release
    assert "dist/GuildBridge-*-windows-x64.zip" in release
    assert "dist/GuildBridge-*-windows-x64.msi" in release


def test_windows_release_docs_explain_zip_msi_and_signing() -> None:
    docs = _text("docs/WINDOWS_RELEASE.md")
    readme = _text("README.md")
    turkish = _text("README.tr.md")

    assert "GuildBridge-<version>-windows-x64.zip" in docs
    assert "GuildBridge-<version>-windows-x64.msi" in docs
    assert "Code Signing" in docs
    assert "SmartScreen" in docs
    assert "portable ZIP" in readme
    assert "MSI installer" in readme
    assert "portable ZIP" in turkish
    assert "MSI installer" in turkish

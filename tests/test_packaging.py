from __future__ import annotations

import re
from pathlib import Path

import guildbridge

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/Yunushan/guildbridge"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_project_metadata_uses_real_repository_urls() -> None:
    pyproject = _text("pyproject.toml")
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")
    schema = _text("schema/community-template.schema.json")

    assert "YOUR_ORG" not in pyproject
    assert "YOUR_ORG" not in readme
    assert "YOUR_ORG" not in turkish_readme
    assert "https://example.org/guildbridge" not in schema
    assert f'Homepage = "{REPO_URL}"' in pyproject
    assert f'Issues = "{REPO_URL}/issues"' in pyproject
    assert f"git clone {REPO_URL}.git" in readme
    assert f"git clone {REPO_URL}.git" in turkish_readme
    assert "https://raw.githubusercontent.com/Yunushan/guildbridge/main/schema/community-template.schema.json" in schema


def test_project_metadata_lists_current_providers() -> None:
    pyproject = _text("pyproject.toml")
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")
    env_example = _text(".env.example")
    api_notes = _text("docs/API_NOTES.md")

    assert "Spacebar" in pyproject
    assert "Daccord" in pyproject
    assert "Mattermost" in pyproject
    assert "Zulip" in pyproject
    assert "Rocket.Chat" in pyproject
    assert "Mumble" in pyproject
    assert "Spacebar · Daccord · Matrix/Element · Rocket.Chat · Mumble · Mattermost · Zulip" in readme
    assert "Spacebar · Daccord · Matrix/Element · Rocket.Chat · Mumble · Mattermost · Zulip" in turkish_readme
    assert "masaustu GUI" in turkish_readme
    assert "web/mobil GUI" in turkish_readme
    assert "--confirm-apply APPLY" in turkish_readme
    assert "SPACEBAR_BOT_TOKEN" in env_example
    assert "DACCORD_BOT_TOKEN" in env_example
    assert "ROCKET_CHAT_AUTH_TOKEN" in env_example
    assert "MUMBLE_API_TOKEN" in env_example
    assert "MATTERMOST_TOKEN" in env_example
    assert "ZULIP_API_KEY" in env_example
    assert "## Spacebar" in api_notes
    assert "## Daccord" in api_notes
    assert "## Rocket.Chat" in api_notes
    assert "## Mumble / Murmur" in api_notes
    assert "## Mattermost" in api_notes
    assert "## Zulip" in api_notes


def test_readmes_demonstrate_end_user_gui_workflows() -> None:
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")

    assert "### Desktop GUI workflow" in readme
    assert "guildbridge-gui.exe" in readme
    assert "Keep **Apply writes** unchecked for the first run" in readme
    assert "Reviewed plan JSON" in readme
    assert "Journal output JSON" in readme
    assert "### Browser and mobile workflow" in readme
    assert "http://127.0.0.1:8765" in readme
    assert "--allow-lan --auth-token" in readme
    assert "Keep this token private" in readme

    assert "### Masaustu GUI akisi" in turkish_readme
    assert "guildbridge-gui.exe" in turkish_readme
    assert "**Apply writes** isaretli olmasin" in turkish_readme
    assert "Reviewed plan JSON" in turkish_readme
    assert "Journal output JSON" in turkish_readme
    assert "### Tarayici ve mobil akis" in turkish_readme
    assert "http://127.0.0.1:8765" in turkish_readme
    assert "--allow-lan --auth-token" in turkish_readme
    assert "Bu token'i gizli tutun" in turkish_readme


def test_supported_paths_use_readable_list_layout() -> None:
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")

    assert "| From | To | Status | Notes |" not in readme
    assert "| Kaynak | Hedef | Durum | Notlar |" not in turkish_readme
    assert "### Enterprise chat and voice paths" in readme
    assert "### Core provider paths" in readme
    assert "**Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix -> Rocket.Chat**: supported" in readme
    assert "**Matrix/Element -> Discord/Fluxer/Stoat/Spacebar/Daccord/Rocket.Chat/Mumble/Mattermost/Zulip**: supported" in readme
    assert "### Enterprise chat ve voice yollari" in turkish_readme
    assert "### Temel saglayici yollari" in turkish_readme


def test_project_metadata_uses_modern_license_fields() -> None:
    pyproject = _text("pyproject.toml")

    assert 'requires = ["setuptools>=77", "wheel"]' in pyproject
    assert 'license = "MIT"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject
    assert '"Programming Language :: Python :: 3.13"' in pyproject
    assert '"Programming Language :: Python :: 3.14"' in pyproject
    assert "License :: OSI Approved" not in pyproject


def test_project_version_matches_package_version() -> None:
    pyproject = _text("pyproject.toml")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert match is not None
    assert match.group(1) == guildbridge.__version__


def test_console_entry_points_are_declared() -> None:
    pyproject = _text("pyproject.toml")

    assert 'guildbridge = "guildbridge.cli:main"' in pyproject
    assert 'guildbridge-gui = "guildbridge.gui:main"' in pyproject
    assert 'guildbridge-web = "guildbridge.web:main"' in pyproject


def test_source_distribution_manifest_includes_project_assets() -> None:
    manifest = _text("MANIFEST.in")

    assert "include LICENSE" in manifest
    assert "include README.tr.md" in manifest
    assert "recursive-include docs *.md" in manifest
    assert "Release Checklist" in _text("docs/RELEASE.md")
    assert "recursive-include examples *.json" in manifest
    assert "recursive-include schema *.json" in manifest
    assert "recursive-include scripts *.sh *.py *.ps1" in manifest


def test_dev_dependencies_include_release_build_tools() -> None:
    pyproject = _text("pyproject.toml")

    assert '"build>=' in pyproject
    assert '"twine>=' in pyproject


def test_distribution_verifier_is_shipped() -> None:
    verifier = _text("scripts/verify-dist.py")
    manifest = _text("MANIFEST.in")

    assert "REQUIRED_SDIST_SUFFIXES" in verifier
    assert "README.tr.md" in verifier
    assert "docs/RELEASE.md" in verifier
    assert "REQUIRED_WHEEL_SUFFIXES" in verifier
    assert "guildbridge-web" in verifier
    assert "guildbridge/providers/spacebar.py" in verifier
    assert "guildbridge/providers/daccord.py" in verifier
    assert "guildbridge/providers/mumble.py" in verifier
    assert "guildbridge/providers/rocket_chat.py" in verifier
    assert "guildbridge/providers/mattermost.py" in verifier
    assert "guildbridge/providers/zulip.py" in verifier
    assert "recursive-include scripts *.sh *.py *.ps1" in manifest


def test_powershell_release_scripts_tolerate_crlf_version_lines() -> None:
    windows_dist = _text("scripts/build-windows-dist.ps1")
    release_ps1 = _text("scripts/release.ps1")

    assert '(?m)^version = "([^"]+)"\\r?$' in windows_dist
    assert '(?m)^version = "([^"]+)"\\r?$' in release_ps1
    assert '(?m)^__version__ = "([^"]+)"\\r?$' in release_ps1
    assert '(?m)^version = "[^"]+"\\r?$' in release_ps1
    assert '(?m)^__version__ = "[^"]+"\\r?$' in release_ps1


def test_windows_release_accepts_pinned_wix_v7_eula() -> None:
    release = _text(".github/workflows/release.yml")
    windows_dist = _text("scripts/build-windows-dist.ps1")
    windows_doc = _text("docs/WINDOWS_RELEASE.md")

    assert "dotnet tool install --global wix --version 7.*" in release
    assert r".\scripts\build-windows-dist.ps1 -WixEulaId wix7" in release
    assert '[string]$WixEulaId = "wix7"' in windows_dist
    assert '"-acceptEula", $WixEulaId' in windows_dist
    assert "`-acceptEula wix7`" in windows_doc


def test_release_workflow_attaches_built_files_to_github_release() -> None:
    release = _text(".github/workflows/release.yml")
    release_doc = _text("docs/RELEASE.md")
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")

    assert "publish-release:" in release
    assert "if: github.ref_type == 'tag'" in release
    assert "needs: [build, windows-artifacts]" in release
    assert "contents: write" in release
    assert "actions/download-artifact@v7" in release
    assert "merge-multiple: true" in release
    assert "GH_REPO: ${{ github.repository }}" in release
    assert "gh release create" in release
    assert "gh release upload" in release
    assert "release-assets/* --clobber" in release
    assert "attaches those files as release assets" in release_doc
    assert "Manual workflow runs upload workflow artifacts only" in release_doc
    assert "attaches them to the GitHub Release for tag builds" in readme
    assert "GitHub Release asset'i olarak ekler" in turkish_readme


def test_ci_builds_without_uploading_distribution_artifacts() -> None:
    github_ci = _text(".github/workflows/ci.yml")
    release = _text(".github/workflows/release.yml")
    self_hosted = _text(".github/workflows/self-hosted-platforms.yml")
    gitlab = _text(".gitlab-ci.yml")

    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in github_ci
    assert 'PIP_NO_CACHE_DIR: "1"' in github_ci
    assert "ubuntu-24.04" in github_ci
    assert "windows-2025-vs2026" in github_ci
    assert "macos-15" in github_ci
    assert '"3.13"' in github_ci
    assert '"3.14"' in github_ci
    assert "hosted-compatibility" in github_ci
    assert "windows-2022" in github_ci
    assert "macos-26" in github_ci
    assert "needs: [test, hosted-compatibility]" in github_ci
    assert "windows-latest" not in github_ci
    assert "actions/checkout@v6" in github_ci
    assert "actions/setup-python@v6" in github_ci
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in github_ci
    assert "python scripts/check-platform.py --require cli --format json" in github_ci
    assert "actions/upload-artifact@v7" not in github_ci
    assert "guildbridge-dist" not in github_ci
    assert "python -m build" in github_ci
    assert "python -m twine check dist/*" in github_ci
    assert "python scripts/verify-dist.py" in github_ci
    assert "name: Release Artifacts" in release
    assert 'PIP_NO_CACHE_DIR: "1"' in release
    assert "ubuntu-24.04" in release
    assert 'python-version: "3.14"' in release
    assert "python -m pytest -q" in release
    assert "python scripts/check-platform.py --require cli --format json" in release
    assert "actions/upload-artifact@v7" in release
    assert "name: guildbridge-dist" in release
    assert "python scripts/verify-dist.py" in release
    assert "name: Self-hosted Platform Compatibility" in self_hosted
    assert "windows-10" in self_hosted
    assert "windows-11" in self_hosted
    assert "windows-server-2019" in self_hosted
    assert "windows-server-2026" in self_hosted
    assert "ubuntu-26.04" in self_hosted
    assert "- \"3.13\"" in self_hosted
    assert "- \"3.14\"" in self_hosted
    assert "- package" in gitlab
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in gitlab
    assert "python scripts/check-platform.py --require cli --format json" in gitlab
    assert "python -m build" in gitlab
    assert "dist/" in gitlab


def test_helper_scripts_match_current_cli_contracts() -> None:
    migrate = _text("scripts/migrate.sh")
    bootstrap = _text("scripts/bootstrap.sh")
    contributing = _text("CONTRIBUTING.md")
    security = _text("SECURITY.md")
    makefile = _text("Makefile")
    release_doc = _text("docs/RELEASE.md")

    assert "ARGS+=(--apply --confirm-apply APPLY --plan-in migration.plan.json --plan-out migration.result.json)" in migrate
    assert 'python -m pip install -e ".[dev]"' in bootstrap
    assert "`--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>`" in contributing
    assert "`--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>`" in security
    assert "release-check: check package" in makefile
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in release_doc
    assert "Normal CI builds and verifies packages but does not upload downloadable artifacts" in release_doc
    assert "does not publish to PyPI automatically" in release_doc

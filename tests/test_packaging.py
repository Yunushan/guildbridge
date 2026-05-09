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

    assert "Rocket.Chat" in pyproject
    assert "Mumble" in pyproject
    assert "Rocket.Chat · Mumble" in readme
    assert "Rocket.Chat · Mumble" in turkish_readme
    assert "masaustu GUI" in turkish_readme
    assert "web/mobil GUI" in turkish_readme
    assert "--confirm-apply APPLY" in turkish_readme
    assert "ROCKET_CHAT_AUTH_TOKEN" in env_example
    assert "MUMBLE_API_TOKEN" in env_example
    assert "## Rocket.Chat" in api_notes
    assert "## Mumble / Murmur" in api_notes


def test_project_metadata_uses_modern_license_fields() -> None:
    pyproject = _text("pyproject.toml")

    assert 'requires = ["setuptools>=77", "wheel"]' in pyproject
    assert 'license = "MIT"' in pyproject
    assert 'license-files = ["LICENSE"]' in pyproject
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
    assert "guildbridge/providers/mumble.py" in verifier
    assert "guildbridge/providers/rocket_chat.py" in verifier
    assert "recursive-include scripts *.sh *.py *.ps1" in manifest


def test_ci_builds_and_uploads_distribution_artifacts() -> None:
    github_ci = _text(".github/workflows/ci.yml")
    release = _text(".github/workflows/release.yml")
    gitlab = _text(".gitlab-ci.yml")

    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in github_ci
    assert "actions/checkout@v6" in github_ci
    assert "actions/setup-python@v6" in github_ci
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in github_ci
    assert "python scripts/check-platform.py --require cli --format json" in github_ci
    assert "actions/upload-artifact@v7" in github_ci
    assert "python -m build" in github_ci
    assert "python -m twine check dist/*" in github_ci
    assert "python scripts/verify-dist.py" in github_ci
    assert "name: Release Artifacts" in release
    assert "python -m pytest -q" in release
    assert "python scripts/check-platform.py --require cli --format json" in release
    assert "actions/upload-artifact@v7" in release
    assert "python scripts/verify-dist.py" in release
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
    assert "does not publish to PyPI automatically" in release_doc

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
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
    assert "Click **Dry-run Check** first" in readme
    assert "click **Actual Run**" in readme
    assert "Use the **Theme** selector" in readme
    assert "light/dark theme selection" in readme
    assert "Reviewed plan JSON" in readme
    assert "Journal output JSON" in readme
    assert "### Browser and mobile workflow" in readme
    assert "http://127.0.0.1:8765" in readme
    assert "--allow-lan --auth-token" in readme
    assert "Keep this token private" in readme

    assert "### Masaustu GUI akisi" in turkish_readme
    assert "guildbridge-gui.exe" in turkish_readme
    assert "Once **Dry-run Check** dugmesine basin" in turkish_readme
    assert "**Actual Run** dugmesine basin" in turkish_readme
    assert "**Theme** secicisini" in turkish_readme
    assert "acik/koyu tema secimi" in turkish_readme
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
    assert '"Development Status :: 5 - Production/Stable"' in pyproject
    assert '"Development Status :: 3 - Alpha"' not in pyproject
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
    assert "recursive-include docs/assets *.svg" in manifest
    assert "Release Checklist" in _text("docs/RELEASE.md")
    assert "Production Readiness Evidence" in _text("docs/PRODUCTION_READINESS.md")
    assert "recursive-include examples *.json" in manifest
    assert "recursive-include schema *.json" in manifest
    assert "recursive-include scripts *.sh *.py *.ps1" in manifest
    assert "recursive-include src/guildbridge/assets *.ico *.png *.svg" in manifest


def test_dev_dependencies_include_release_build_tools() -> None:
    pyproject = _text("pyproject.toml")

    assert '"build>=' in pyproject
    assert '"coverage>=' in pyproject
    assert '"twine>=' in pyproject


def test_distribution_verifier_is_shipped() -> None:
    verifier = _text("scripts/verify-dist.py")
    manifest = _text("MANIFEST.in")

    assert "REQUIRED_SDIST_SUFFIXES" in verifier
    assert "README.tr.md" in verifier
    assert "docs/assets/guildbridge-icon.svg" in verifier
    assert "docs/RELEASE.md" in verifier
    assert "docs/OPERATIONS.md" in verifier
    assert "Production Repository Settings" in _text("docs/REPOSITORY_SETTINGS.md")
    assert "REQUIRED_WHEEL_SUFFIXES" in verifier
    assert "guildbridge/assets/guildbridge-icon.png" in verifier
    assert "guildbridge/assets/guildbridge-icon.ico" in verifier
    assert "guildbridge-web" in verifier
    assert "guildbridge/providers/spacebar.py" in verifier
    assert "guildbridge/providers/daccord.py" in verifier
    assert "guildbridge/providers/mumble.py" in verifier
    assert "guildbridge/providers/rocket_chat.py" in verifier
    assert "guildbridge/providers/mattermost.py" in verifier
    assert "guildbridge/providers/zulip.py" in verifier
    assert "scripts/check-release-controls.py" in verifier
    assert "scripts/check-secret-hygiene.py" in verifier
    assert "scripts/check-security-baseline.py" in verifier
    assert "recursive-include scripts *.sh *.py *.ps1" in manifest


def test_readmes_show_project_icon() -> None:
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")

    assert "docs/assets/guildbridge-icon.svg" in readme
    assert "docs/assets/guildbridge-icon.svg" in turkish_readme


def test_powershell_release_scripts_tolerate_crlf_version_lines() -> None:
    windows_dist = _text("scripts/build-windows-dist.ps1")
    release_ps1 = _text("scripts/release.ps1")

    assert '(?m)^version = "([^"]+)"\\r?$' in windows_dist
    assert '(?m)^version = "([^"]+)"\\r?$' in release_ps1
    assert '(?m)^__version__ = "([^"]+)"\\r?$' in release_ps1
    assert '(?m)^version = "[^"]+"\\r?$' in release_ps1
    assert '(?m)^__version__ = "[^"]+"\\r?$' in release_ps1
    assert "scripts/check-github-production-settings.py" in release_ps1
    assert "Get-GitHubRepository" in release_ps1
    assert "-SkipChecks may only be used with -SkipTag" in release_ps1
    assert '"coverage", "run", "-m", "pytest", "-q"' in release_ps1
    assert '"coverage", "report"' in release_ps1
    assert '(@("-m", "twine", "check") + $wheels + $sdists)' in release_ps1
    assert '(@("-m", "twine", "check") + $distFiles)' not in release_ps1


def test_unix_release_script_requires_hosted_production_controls() -> None:
    release_sh = _text("scripts/release.sh")

    assert "scripts/check-github-production-settings.py" in release_sh
    assert "github_repository()" in release_sh
    assert "require_command gh" in release_sh
    assert "--skip-checks may only be used with --skip-tag" in release_sh
    assert "-m coverage run -m pytest -q" in release_sh
    assert "-m coverage report" in release_sh


def test_windows_release_accepts_pinned_wix_v7_eula() -> None:
    release = _text(".github/workflows/release.yml")
    windows_dist = _text("scripts/build-windows-dist.ps1")
    windows_doc = _text("docs/WINDOWS_RELEASE.md")

    assert "dotnet tool install --global wix --version 7.0.0" in release
    assert "dotnet tool install --global wix --version 7.*" not in release
    assert r".\scripts\build-windows-dist.ps1 -WixEulaId wix7" in release
    assert '[string]$WixEulaId = "wix7"' in windows_dist
    assert "function Get-WixMajorVersion" in windows_dist
    assert "if ($wixMajor -ge 7)" in windows_dist
    assert "WiX Toolset v$wixMajor does not require -acceptEula" in windows_dist
    assert '"-acceptEula", $WixEulaId' in windows_dist
    assert "`-acceptEula wix7`" in windows_doc
    assert "dotnet tool install --global wix --version 7.0.0" in windows_doc


def test_release_workflow_attaches_built_files_to_github_release() -> None:
    release = _text(".github/workflows/release.yml")
    release_doc = _text("docs/RELEASE.md")
    readme = _text("README.md")
    turkish_readme = _text("README.tr.md")

    assert "publish-release:" in release
    assert "if: github.ref_type == 'tag'" in release
    assert "needs: [build, sign-windows-artifacts]" in release
    assert "contents: write" in release
    assert "actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131 # v7" in release
    assert "Download Python distributions" in release
    assert "Download signed Windows artifacts" in release
    assert "name: guildbridge-dist" in release
    assert release.count("name: guildbridge-windows") >= 2
    assert "merge-multiple: true" not in release
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
    codeql = _text(".github/workflows/codeql.yml")
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
    assert "desktop-gui-smoke:" in github_ci
    assert "xvfb-run -a python -m pytest -q tests/test_gui_workflows.py" in github_ci
    assert "container-smoke:" in github_ci
    assert "docker run --rm guildbridge:${{ github.sha }} --version" in github_ci
    assert "needs: [test, hosted-compatibility, desktop-gui-smoke, container-smoke]" in github_ci
    assert "windows-latest" not in github_ci
    assert "actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6" in github_ci
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6" in github_ci
    assert github_ci.count("fetch-depth: 0") >= 5
    assert github_ci.count("persist-credentials: false") >= 5
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in github_ci
    assert "python -m ruff check --select S src scripts" in github_ci
    assert "python -m ruff check --select BLE src scripts" in github_ci
    assert "python scripts/check-platform.py --require cli --format json" in github_ci
    assert "actions/upload-artifact@v7" not in github_ci
    assert "guildbridge-dist" not in github_ci
    assert "python -m build" in github_ci
    assert "python -m twine check dist/*.whl dist/*.tar.gz" in github_ci
    assert "python scripts/verify-dist.py" in github_ci
    assert "python scripts/pip-audit-truststore.py --strict" in github_ci
    assert "--require-hashes -r requirements/release.txt" in github_ci
    assert github_ci.count("--require-hashes -r requirements/release.txt") >= 4
    assert github_ci.count('--no-deps -e ".[dev]"') >= 4
    assert "--require-hashes -r requirements/release.txt" in self_hosted
    assert '--no-deps -e ".[dev]"' in self_hosted
    assert "fetch-depth: 0" in self_hosted
    assert "persist-credentials: false" in self_hosted
    assert "python -m coverage report" in self_hosted
    assert "python scripts/check-secret-hygiene.py --history" in self_hosted
    assert "python scripts/check-security-baseline.py" in self_hosted
    assert "python -m ruff check --select S src scripts" in self_hosted
    assert "python -m ruff check --select BLE src scripts" in self_hosted
    assert "python -m coverage run -m pytest -q" in github_ci
    assert "python -m coverage report" in github_ci
    assert "python scripts/check-release-controls.py" in github_ci
    assert "python scripts/check-secret-hygiene.py" in github_ci
    assert "python scripts/check-security-baseline.py" in github_ci
    assert "scripts/check-github-production-settings.py" in github_ci
    assert "security-events: write" in codeql
    assert "actions: read" in codeql
    assert "language: [python, actions]" in codeql
    assert "languages: ${{ matrix.language }}" in codeql
    assert "github/codeql-action/init@7188fc363630916deb702c7fdcf4e481b751f97a # v4" in codeql
    assert "github/codeql-action/analyze@7188fc363630916deb702c7fdcf4e481b751f97a # v4" in codeql
    assert "security-extended,security-and-quality" in codeql
    assert "fetch-depth: 0" in codeql
    assert "persist-credentials: false" in codeql
    assert "name: Release Artifacts" in release
    assert 'PIP_NO_CACHE_DIR: "1"' in release
    assert "ubuntu-24.04" in release
    assert 'python-version: "3.14"' in release
    assert "python -m coverage run -m pytest -q" in release
    assert "python -m coverage report" in release
    assert "Docker runtime smoke test" in release
    assert "docker run --rm guildbridge:${{ github.sha }} --version" in release
    assert "python scripts/check-platform.py --require cli --format json" in release
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in release
    assert "name: guildbridge-dist" in release
    assert "python scripts/verify-dist.py" in release
    assert "actions/attest-build-provenance@96b4a1ef7235a096b17240c259729fdd70c83d45 # v2" in release
    assert "Verify build provenance attestations" in release
    assert "gh attestation verify" in release
    assert "--deny-self-hosted-runners" in release
    assert "SHA256SUMS" in release
    assert "scripts/pip-audit-truststore.py --strict" in release
    assert "--require-hashes -r requirements/release.txt" in release
    assert "--no-deps -e \".[dev]\"" in release
    assert "--no-deps -e \".[dev,windows-build]\"" in release
    assert "--no-deps ." in release
    assert "--sbom-out" in release
    assert "python scripts/check-secret-hygiene.py" in release
    assert "python scripts/check-security-baseline.py" in release
    assert "python -m ruff check --select S src scripts" in release
    assert "python -m ruff check --select BLE src scripts" in release
    assert "scripts/check-github-production-settings.py" in release
    assert release.count("fetch-depth: 0") >= 4
    assert release.count("persist-credentials: false") >= 4
    assert "python scripts/check-release-assets.py --assets-dir release-assets --evidence" in release
    assert "sign-windows-artifacts:" in release
    assert "Require protected signing materials" in release
    assert "Sign and verify Windows ZIP and MSI" in release
    assert "Upload signed Windows artifacts" in release
    assert "Attest signed Windows installers" in release
    assert "environment: production-release" in release
    assert release.count("environment: production-release") >= 2
    assert "concurrency:" in release
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
    assert "python -m ruff check --select S src scripts" in gitlab
    assert "python -m ruff check --select BLE src scripts" in gitlab
    assert "python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97" in gitlab
    assert "--require-hashes -r requirements/release.txt" in gitlab
    assert '--no-deps -e ".[dev]"' in gitlab
    assert "python -m coverage run -m pytest -q" in gitlab
    assert "python -m coverage report" in gitlab
    assert "python scripts/check-secret-hygiene.py --history" in gitlab
    assert "python scripts/check-security-baseline.py" in gitlab
    assert "python scripts/pip-audit-truststore.py --strict" in gitlab
    assert "python scripts/check-platform.py --require cli --format json" in gitlab
    assert "python -m build" in gitlab
    assert "python -m twine check dist/*.whl dist/*.tar.gz" in gitlab
    assert "python -m twine check dist/*\n" not in gitlab
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
    assert "exception-lint" in makefile
    assert "python -m twine check dist/*.whl dist/*.tar.gz" in makefile
    assert "python -m twine check dist/*\n" not in makefile
    assert "python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py" in release_doc
    assert "python scripts/pip-audit-truststore.py --strict" in release_doc
    assert "python scripts/check-secret-hygiene.py --history" in release_doc
    assert "python scripts/check-security-baseline.py" in release_doc
    assert "python scripts/check-github-production-settings.py --repo Yunushan/guildbridge" in release_doc
    assert "python -m ruff check --select S src scripts" in release_doc
    assert "python -m ruff check --select BLE src scripts" in release_doc
    assert "python -m coverage run -m pytest -q" in release_doc
    assert "python -m pip_audit --strict" not in release_doc
    assert "Normal CI builds and verifies packages but does not upload downloadable artifacts" in release_doc
    assert "does not publish to PyPI automatically" in release_doc
    assert "Public tag-push builds fail unless the Windows code-signing secrets are configured" in release_doc


def test_release_controls_are_machine_verified() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check-release-controls.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "immutable" in completed.stdout


def test_container_runtime_dependencies_are_hash_locked() -> None:
    dockerfile = _text("Dockerfile")
    dockerignore = _text(".dockerignore")
    runtime_lock = _text("requirements/runtime-linux.txt")
    requirements_readme = _text("requirements/README.md")

    assert "COPY requirements/runtime-linux.txt" in dockerfile
    assert "--require-hashes -r requirements/runtime-linux.txt" in dockerfile
    assert "--no-deps ." in dockerfile
    assert "@sha256:" in dockerfile
    assert "keyring==" in runtime_lock
    assert "secretstorage==" in runtime_lock
    assert "--hash=sha256:" in runtime_lock
    assert "make lock-runtime-linux" in requirements_readme
    assert ".git/" in dockerignore
    assert ".env" in dockerignore
    assert ".guildbridge/" in dockerignore
    assert "production-evidence*.json" in dockerignore
    assert "github-production-settings-audit*.json" in dockerignore
    assert "*.receipt.json" in dockerignore
    assert "*.content.json" in dockerignore
    assert "*.dead-letter.json" in dockerignore
    assert "*.migration-report.json" in dockerignore
    assert "*.incremental-state.json" in dockerignore
    assert "*.content.lock" in dockerignore
    assert "thread-archives/" in dockerignore


def test_local_audit_uses_the_system_certificate_store() -> None:
    pyproject = _text("pyproject.toml")
    makefile = _text("Makefile")
    audit_wrapper = _text("scripts/pip-audit-truststore.py")

    assert '"truststore>=' in pyproject
    assert "scripts/pip-audit-truststore.py --strict" in makefile
    assert "truststore.inject_into_ssl()" in audit_wrapper
    assert "from pip_audit._cli import audit" in audit_wrapper
    assert "requirements/release.txt" in audit_wrapper
    assert "_add_release_requirements_if_needed" in audit_wrapper
    assert "Missing module:" in audit_wrapper

    assert "--history" in _text("scripts/release.ps1")
    assert "scripts/check-security-baseline.py" in _text("scripts/release.ps1")
    assert '"--select", "S"' in _text("scripts/release.ps1")
    assert "scripts/pip-audit-truststore.py" in _text("scripts/release.ps1")
    assert "--history" in _text("scripts/release.sh")
    assert "scripts/check-security-baseline.py" in _text("scripts/release.sh")
    assert "--select S src scripts" in _text("scripts/release.sh")
    assert "scripts/pip-audit-truststore.py" in _text("scripts/release.sh")


def test_local_audit_defaults_to_the_hash_locked_release_requirements(monkeypatch: object) -> None:
    spec = importlib.util.spec_from_file_location("pip_audit_truststore", ROOT / "scripts" / "pip-audit-truststore.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module.sys, "argv", ["pip-audit-truststore.py", "--strict"])
    module._add_release_requirements_if_needed()

    assert module.sys.argv == [
        "pip-audit-truststore.py",
        "--requirement",
        str(ROOT / "requirements" / "release.txt"),
        "--strict",
    ]

    monkeypatch.setattr(module.sys, "argv", ["pip-audit-truststore.py", "--requirement", "custom.txt"])
    module._add_release_requirements_if_needed()

    assert module.sys.argv == ["pip-audit-truststore.py", "--requirement", "custom.txt"]

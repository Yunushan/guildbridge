from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_REFERENCE = re.compile(
    r"^\s*-\s+uses:\s*(?P<action>[^\s@]+)@(?P<reference>[^\s#]+)", re.MULTILINE
)
FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}\Z")


def main() -> int:
    errors: list[str] = []
    workflow_text = _read_workflows(errors)
    ci = workflow_text.get("ci.yml", "")
    release = workflow_text.get("release.yml", "")
    codeql = workflow_text.get("codeql.yml", "")
    self_hosted = workflow_text.get("self-hosted-platforms.yml", "")
    gitlab = _read(ROOT / ".gitlab-ci.yml", errors)

    for name, text in workflow_text.items():
        if "pull_request_target:" in text:
            errors.append(f"{name}: pull_request_target is prohibited for this repository.")
        errors.extend(_action_pin_errors(name, text))

    _require(ci, 'permissions:\n  contents: read', "ci.yml must default to read-only contents permission.", errors)
    _require(ci, "concurrency:", "ci.yml must define workflow concurrency.", errors)
    _require(ci, "python scripts/check-release-controls.py", "ci.yml must verify release controls.", errors)
    _require(ci, "python scripts/check-secret-hygiene.py --history", "ci.yml must check repository history for likely secrets.", errors)
    if ci.count("fetch-depth: 0") < 5 or ci.count("persist-credentials: false") < 5:
        errors.append("ci.yml must use full-depth checkouts without persisted credentials in every job.")
    _require(ci, "python scripts/check-security-baseline.py", "ci.yml must run the static security baseline.", errors)
    _require(ci, "python scripts/check-content-capability-scope.py", "ci.yml must verify live-content scope.", errors)
    _require(ci, "scripts/check-production-readiness.py", "ci.yml must lint the production-readiness preflight.", errors)
    _require(ci, "scripts/record-provider-drill-receipt.py", "ci.yml must lint the provider-drill receipt tool.", errors)
    _require(ci, "python -m ruff check --select S src scripts", "ci.yml must run Ruff security lint.", errors)
    _require(ci, "python -m ruff check --select BLE src scripts", "ci.yml must run Ruff exception lint.", errors)
    _require(ci, "python -m coverage run -m pytest -q", "ci.yml must measure source coverage.", errors)
    _require(ci, "python -m coverage report", "ci.yml must enforce the source coverage threshold.", errors)
    _require(ci, "--require-hashes -r requirements/release.txt", "ci.yml package job must use the release lock.", errors)
    if ci.count("--require-hashes -r requirements/release.txt") != 1:
        errors.append("ci.yml must reserve the hash-locked release dependency graph for the package job.")
    if ci.count('--no-deps -e ".[dev]"') != 1:
        errors.append("ci.yml package job must install the project without resolving additional dependencies.")
    if ci.count('python -m pip install -e ".[dev]"') < 3:
        errors.append("ci.yml compatibility and GUI smoke jobs must resolve interpreter-compatible development dependencies.")
    _require(
        self_hosted,
        "--require-hashes -r requirements/release.txt",
        "self-hosted-platforms.yml must use the hash-locked release dependency graph.",
        errors,
    )
    _require(
        self_hosted,
        "--no-deps -e \".[dev]\"",
        "self-hosted-platforms.yml must install the project without resolving unpinned development dependencies.",
        errors,
    )
    _require(self_hosted, "fetch-depth: 0", "self-hosted-platforms.yml must fetch Git history for secret scanning.", errors)
    _require(self_hosted, "persist-credentials: false", "self-hosted-platforms.yml must not persist GitHub credentials.", errors)
    _require(self_hosted, "python -m coverage report", "self-hosted-platforms.yml must enforce the source coverage threshold.", errors)
    _require(self_hosted, "python scripts/check-secret-hygiene.py --history", "self-hosted-platforms.yml must scan full Git history for likely secrets.", errors)
    _require(self_hosted, "python scripts/check-security-baseline.py", "self-hosted-platforms.yml must run the static security baseline.", errors)
    _require(self_hosted, "python scripts/check-content-capability-scope.py", "self-hosted-platforms.yml must verify live-content scope.", errors)
    _require(self_hosted, "scripts/check-production-readiness.py", "self-hosted-platforms.yml must lint the production-readiness preflight.", errors)
    _require(self_hosted, "scripts/record-provider-drill-receipt.py", "self-hosted-platforms.yml must lint the provider-drill receipt tool.", errors)
    _require(self_hosted, "python -m ruff check --select S src scripts", "self-hosted-platforms.yml must run Ruff security lint.", errors)
    _require(self_hosted, "python -m ruff check --select BLE src scripts", "self-hosted-platforms.yml must run Ruff exception lint.", errors)
    _require(self_hosted, "python scripts/check-release-controls.py", "self-hosted-platforms.yml must verify repository release controls.", errors)

    for required in (
        "python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97",
        "PIP_NO_CACHE_DIR: \"1\"",
        "--require-hashes -r requirements/release.txt",
        '--no-deps -e ".[dev]"',
        "python -m ruff check --select S src scripts",
        "python -m ruff check --select BLE src scripts",
        "python -m coverage run -m pytest -q",
        "python -m coverage report",
        "python scripts/check-release-controls.py",
        "python scripts/check-secret-hygiene.py --history",
        "python scripts/check-security-baseline.py",
        "python scripts/check-content-capability-scope.py",
        "scripts/check-production-readiness.py",
        "scripts/record-provider-drill-receipt.py",
        "python scripts/pip-audit-truststore.py --strict",
        "rm -rf dist",
        "python -m twine check dist/*.whl dist/*.tar.gz",
    ):
        _require(gitlab, required, f".gitlab-ci.yml is missing required production control: {required}", errors)
    _require(ci, "desktop-gui-smoke:", "ci.yml must include a real desktop GUI smoke job.", errors)
    _require(ci, "xvfb-run -a python -m pytest -q tests/test_gui_workflows.py", "ci.yml must construct the GUI under Xvfb.", errors)
    _require(ci, "container-smoke:", "ci.yml must build and run the pinned runtime container.", errors)
    _require(ci, "docker run --rm guildbridge:${{ github.sha }} --version", "ci.yml must verify the container entry point.", errors)
    _require(ci, "needs: [test, hosted-compatibility, desktop-gui-smoke, container-smoke]", "ci.yml package must wait for every smoke job.", errors)
    _require(codeql, "security-events: write", "codeql.yml must allow CodeQL security-event uploads.", errors)
    _require(codeql, "actions: read", "codeql.yml must allow Actions workflow analysis.", errors)
    _require(codeql, "language: [python, actions]", "codeql.yml must analyze Python and Actions workflows.", errors)
    _require(codeql, "languages: ${{ matrix.language }}", "codeql.yml must initialize each CodeQL language separately.", errors)
    _require(codeql, "build-mode: none", "codeql.yml must use Python's no-build mode.", errors)
    _require(codeql, "security-extended,security-and-quality", "codeql.yml must use extended security queries.", errors)
    _require(codeql, "github/codeql-action/init@", "codeql.yml must initialize CodeQL.", errors)
    _require(codeql, "github/codeql-action/analyze@", "codeql.yml must publish CodeQL analysis.", errors)
    _require(codeql, "fetch-depth: 0", "codeql.yml must use full Git history for analysis.", errors)
    _require(codeql, "persist-credentials: false", "codeql.yml must not persist checkout credentials.", errors)

    if _workflow_default_permissions(release) != {"contents": "read"}:
        errors.append("release.yml must default to exactly contents: read permissions.")
    _require_release_job_permissions(
        release,
        "build",
        {"contents": "read", "attestations": "write", "id-token": "write"},
        errors,
    )
    _require_release_job_permissions(release, "windows-artifacts", {"contents": "read"}, errors)
    _require_release_job_permissions(
        release,
        "sign-windows-artifacts",
        {"contents": "read", "attestations": "write", "id-token": "write"},
        errors,
    )
    _require_release_job_permissions(
        release,
        "publish-release",
        {"contents": "write", "actions": "read", "attestations": "read"},
        errors,
    )

    for required in (
        'tags:\n      - "v*"',
        "attestations: write",
        "id-token: write",
        "concurrency:",
        "cancel-in-progress: false",
        "python scripts/check-release-controls.py",
        "python scripts/check-secret-hygiene.py",
        "python scripts/check-secret-hygiene.py --history",
        "python scripts/check-security-baseline.py",
        "python scripts/check-content-capability-scope.py",
        "scripts/check-production-readiness.py",
        "scripts/record-provider-drill-receipt.py",
        "python -m ruff check --select S src scripts",
        "python -m ruff check --select BLE src scripts",
        "Docker runtime smoke test",
        "docker run --rm guildbridge:${{ github.sha }} --version",
        "python -m coverage run -m pytest -q",
        "python -m coverage report",
        "python scripts/pip-audit-truststore.py --strict",
        "--require-hashes -r requirements/release.txt",
        "rm -rf dist",
        "--no-deps -e \".[dev]\"",
        "--no-deps -e \".[dev,windows-build]\"",
        "--no-deps .",
        "SHA256SUMS",
        "attest-build-provenance@",
        "--sbom-out",
        "dotnet tool install --global wix --version 7.0.0",
        "sign-windows-artifacts:",
        "Require protected signing materials",
        "Sign and verify Windows ZIP and MSI",
        "Upload signed Windows artifacts",
        "Attest signed Windows installers",
        "GUILDBRIDGE_CODESIGN_PFX_BASE64",
        "GUILDBRIDGE_CODESIGN_PFX_PASSWORD",
        "environment: production-release",
        "GUILDBRIDGE_PRODUCTION_EVIDENCE_JSON",
        "attestations: read",
        "Verify build provenance attestations",
        "gh attestation verify",
        "--signer-workflow",
        "--source-ref",
        "--source-digest",
        "--deny-self-hosted-runners",
        "Verify private production evidence",
        "scripts/check-production-evidence.py",
        "scripts/check-release-assets.py",
        "scripts/check-github-production-settings.py",
        "Verify public tag is based on main",
        "git merge-base --is-ancestor",
        "Public release tag must target a commit reachable from origin/main.",
        "--expected-commit",
        "--assets-dir release-assets",
        "SOURCE_COMMIT: ${{ github.sha }}",
        "signed-windows/SHA256SUMS-windows.txt",
    ):
        _require(release, required, f"release.yml is missing required production control: {required}", errors)
    if release.count("fetch-depth: 0") < 4 or release.count("persist-credentials: false") < 4:
        errors.append("release.yml must use full-depth checkouts without persisted credentials in every job.")
    if release.count("environment: production-release") < 2:
        errors.append("release.yml must protect both Windows signing and release publication with production-release.")
    if release.count("if: github.event_name == 'push' && github.ref_type == 'tag'") < 2:
        errors.append("release.yml must restrict signing and publication to tag push events, not manual dispatches.")
    if release.count("name: guildbridge-windows") < 2:
        errors.append("release.yml must publish only the named signed Windows artifact.")

    dependabot = _read(ROOT / ".github" / "dependabot.yml", errors)
    for ecosystem in ('package-ecosystem: docker', 'package-ecosystem: github-actions', 'package-ecosystem: pip'):
        _require(dependabot, ecosystem, f"dependabot.yml must monitor {ecosystem.split(': ', 1)[1]}.", errors)

    dockerfile = _read(ROOT / "Dockerfile", errors)
    for required in (
        "USER guildbridge",
        "HEALTHCHECK",
        "--no-cache-dir",
        "@sha256:",
        "requirements/runtime-linux.txt",
        "--require-hashes -r requirements/runtime-linux.txt",
        "--no-deps .",
    ):
        _require(dockerfile, required, f"Dockerfile is missing required hardening: {required}", errors)

    dockerignore = _read(ROOT / ".dockerignore", errors)
    for required in (
        ".git/",
        ".env",
        ".guildbridge/",
        "production-evidence*.json",
        "github-production-settings-audit*.json",
        "*.receipt.json",
        "*.content.json",
        "*.dead-letter.json",
        "*.migration-report.json",
        "*.incremental-state.json",
        "*.content.lock",
        "thread-archives/",
        "*.token",
    ):
        _require(dockerignore, required, f".dockerignore is missing required build-context protection: {required}", errors)

    runtime_lock = _read(ROOT / "requirements" / "runtime-linux.txt", errors)
    for required in ("--hash=sha256:", "keyring==", "requests==", "secretstorage=="):
        _require(
            runtime_lock,
            required,
            f"requirements/runtime-linux.txt is missing required locked runtime dependency evidence: {required}",
            errors,
        )

    pyproject = _read(ROOT / "pyproject.toml", errors)
    _require(
        pyproject,
        '"Development Status :: 5 - Production/Stable"',
        "pyproject.toml must declare the production release maturity level.",
        errors,
    )
    _require(pyproject, "fail_under = 80", "pyproject.toml must define the source coverage baseline.", errors)

    release_lock = _read(ROOT / "requirements" / "release.txt", errors)
    for required in (
        "--hash=sha256:",
        "pip==",
        "setuptools==",
        "pyinstaller==",
        "pip-audit==",
        "truststore==",
        "secretstorage==",
        "jeepney==",
    ):
        _require(
            release_lock,
            required,
            f"requirements/release.txt is missing required locked dependency evidence: {required}",
            errors,
        )

    for path in (ROOT / "scripts" / "release.ps1", ROOT / "scripts" / "release.sh"):
        release_script = _read(path, errors)
        for required in (
            "scripts/check-secret-hygiene.py",
            "--history",
            "scripts/check-security-baseline.py",
            "scripts/check-content-capability-scope.py",
            "scripts/check-production-readiness.py",
            "scripts/record-provider-drill-receipt.py",
            "--select",
            "S",
            "BLE",
            "coverage",
            "report",
            "scripts/pip-audit-truststore.py",
            "scripts/check-github-production-settings.py",
        ):
            _require(
                release_script,
                required,
                f"{path.name} is missing required local release gate: {required}",
                errors,
            )

    if errors:
        print("check-release-controls: error:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release controls are present and action references are immutable.")
    return 0


def _read_workflows(errors: list[str]) -> dict[str, str]:
    found = {path.name: _read(path, errors) for path in sorted(WORKFLOWS.glob("*.yml"))}
    if not found:
        errors.append("No GitHub Actions workflow files were found.")
    return found


def _read(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Could not read {path.relative_to(ROOT)}: {exc}")
        return ""


def _require(text: str, value: str, message: str, errors: list[str]) -> None:
    if value not in text:
        errors.append(message)


def _require_release_job_permissions(
    release: str, job_name: str, expected: dict[str, str], errors: list[str]
) -> None:
    block = _workflow_job_block(release, job_name)
    permissions = _workflow_job_permissions(block)
    if permissions != expected:
        errors.append(
            f"release.yml job {job_name} must use exactly these permissions: "
            + ", ".join(f"{key}: {value}" for key, value in sorted(expected.items()))
        )


def _workflow_default_permissions(workflow: str) -> dict[str, str]:
    match = re.search(r"^permissions:\n(?P<body>(?:  [^\n]+\n?)+)", workflow, re.MULTILINE)
    return _workflow_permissions_from_body(match.group("body")) if match else {}


def _workflow_job_block(workflow: str, job_name: str) -> str:
    pattern = re.compile(rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z][A-Za-z0-9_-]*:|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(workflow)
    return match.group("body") if match else ""


def _workflow_job_permissions(job_block: str) -> dict[str, str]:
    match = re.search(r"^    permissions:\n(?P<body>(?:      [^\n]+\n?)+)", job_block, re.MULTILINE)
    return _workflow_permissions_from_body(match.group("body")) if match else {}


def _workflow_permissions_from_body(body: str) -> dict[str, str]:
    permissions: dict[str, str] = {}
    for line in body.splitlines():
        key, separator, value = line.strip().partition(":")
        if separator and key and value.strip():
            permissions[key] = value.strip()
    return permissions


def _action_pin_errors(name: str, text: str) -> list[str]:
    errors: list[str] = []
    for match in ACTION_REFERENCE.finditer(text):
        reference = match.group("reference")
        if not FULL_COMMIT_SHA.fullmatch(reference):
            errors.append(
                f"{name}: action reference is not pinned to a full commit SHA: "
                f"{match.group('action')}@{reference}"
            )
    return errors


if __name__ == "__main__":
    raise SystemExit(main())

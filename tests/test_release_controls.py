from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_release_controls", ROOT / "scripts" / "check-release-controls.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_control_checker_rejects_mutable_action_references() -> None:
    module = _module()

    errors = module._action_pin_errors("ci.yml", "      - uses: actions/checkout@v6\n")

    assert errors == ["ci.yml: action reference is not pinned to a full commit SHA: actions/checkout@v6"]


def test_release_control_checker_rejects_action_references_without_a_commit() -> None:
    module = _module()

    errors = module._action_pin_errors("ci.yml", "      - uses: actions/checkout\n")

    assert errors == ["ci.yml: action reference is not pinned to a full commit SHA: actions/checkout"]


def test_release_control_checker_accepts_immutable_action_references() -> None:
    module = _module()

    errors = module._action_pin_errors(
        "ci.yml", "      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6\n"
    )

    assert errors == []


def test_release_control_checker_rejects_mutable_named_step_action_references() -> None:
    module = _module()

    errors = module._action_pin_errors(
        "codeql.yml",
        "      - name: Analyze\n        uses: github/codeql-action/analyze@v4\n",
    )

    assert errors == [
        "codeql.yml: action reference is not pinned to a full commit SHA: "
        "github/codeql-action/analyze@v4"
    ]


def test_release_control_checker_requires_an_immutable_container_reference() -> None:
    module = _module()

    errors: list[str] = []
    module._require("FROM python:3.14.5-slim", "@sha256:", "digest required", errors)

    assert errors == ["digest required"]


def test_release_control_checker_requires_public_release_signing_gate() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "Require signing materials for public tag release", "signing gate required", errors)

    assert errors == ["signing gate required"]


def test_release_control_checker_requires_private_evidence_gate() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "GUILDBRIDGE_PRODUCTION_EVIDENCE_JSON", "evidence gate required", errors)

    assert errors == ["evidence gate required"]


def test_release_control_checker_requires_tag_push_gating_for_public_release_jobs() -> None:
    module = _module()
    errors: list[str] = []

    module._require(
        "",
        "if: github.event_name == 'push' && github.ref_type == 'tag'",
        "tag push gate required",
        errors,
    )

    assert errors == ["tag push gate required"]


def test_release_control_checker_requires_public_tag_main_ancestry_gate() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "git merge-base --is-ancestor", "main ancestry gate required", errors)

    assert errors == ["main ancestry gate required"]


def test_release_control_checker_requires_clean_distribution_directory() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "rm -rf dist", "clean dist required", errors)

    assert errors == ["clean dist required"]


def test_release_control_checker_requires_history_secret_scan() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "python scripts/check-secret-hygiene.py --history", "history scan required", errors)

    assert errors == ["history scan required"]


def test_release_control_checker_requires_content_scope_guard() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "python scripts/check-content-capability-scope.py", "content scope required", errors)

    assert errors == ["content scope required"]


def test_release_control_checker_requires_production_readiness_preflight() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "scripts/check-production-readiness.py", "preflight required", errors)

    assert errors == ["preflight required"]


def test_release_control_checker_requires_provider_drill_receipt_tool() -> None:
    module = _module()
    errors: list[str] = []

    module._require("", "scripts/record-provider-drill-receipt.py", "receipt required", errors)

    assert errors == ["receipt required"]


def test_release_control_checker_extracts_exact_job_permissions() -> None:
    module = _module()
    workflow = """jobs:
  build:
    permissions:
      contents: read
      attestations: write
    runs-on: ubuntu-24.04
  publish-release:
    permissions:
      contents: write
    runs-on: ubuntu-24.04
"""

    build = module._workflow_job_block(workflow, "build")

    assert module._workflow_job_permissions(build) == {"contents": "read", "attestations": "write"}


def test_release_control_checker_extracts_default_workflow_permissions() -> None:
    module = _module()
    workflow = """name: Release

permissions:
  contents: read

jobs:
  build:
    runs-on: ubuntu-24.04
"""

    assert module._workflow_default_permissions(workflow) == {"contents": "read"}


def test_release_control_checker_rejects_overprivileged_job_permissions() -> None:
    module = _module()
    errors: list[str] = []
    workflow = """jobs:
  windows-artifacts:
    permissions:
      contents: read
      id-token: write
"""

    module._require_release_job_permissions(workflow, "windows-artifacts", {"contents": "read"}, errors)

    assert errors == ["release.yml job windows-artifacts must use exactly these permissions: contents: read"]


def test_codeowners_covers_production_sensitive_paths() -> None:
    codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")

    assert "@Yunushan" in codeowners
    for path in ("/.github/", "/packaging/", "/scripts/", "/src/guildbridge/providers/"):
        assert path in codeowners


def test_release_control_checker_rejects_a_generic_hidden_test_artifact() -> None:
    module = _module()
    errors = module._generic_gitignore_errors("/test\n")

    assert errors == [".gitignore must not hide a generic top-level /test artifact path."]


def test_release_control_checker_rejects_crlf_shell_scripts(tmp_path: Path) -> None:
    module = _module()
    script = tmp_path / "release.sh"
    script.write_bytes(b"#!/usr/bin/env sh\r\nset -eu\r\n")

    assert module._shell_line_ending_errors(script, root=tmp_path) == [
        "release.sh: shell scripts must use LF line endings."
    ]


def test_release_control_checker_accepts_lf_shell_scripts(tmp_path: Path) -> None:
    module = _module()
    script = tmp_path / "release.sh"
    script.write_bytes(b"#!/usr/bin/env sh\nset -eu\n")

    assert module._shell_line_ending_errors(script, root=tmp_path) == []

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from guildbridge.config import RuntimeConfig
from guildbridge.providers import get_provider, provider_names

TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:[A-Za-z0-9.-]+)?$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WORKFLOW_RUN_PATTERN = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/actions/runs/\d+(?:/attempts/\d+)?$"
)
PRIVATE_EVIDENCE_REF_PATTERN = re.compile(r"^private://[A-Za-z0-9][A-Za-z0-9._/-]*$")
PROVIDERS = tuple(sorted(provider_names()))
REQUIRED_FLAGS = (
    "branch_protection_verified",
    "environment_protection_verified",
    "artifact_sha256_verified",
    "sbom_reviewed",
    "provenance_verified",
    "windows_signature_verified",
    "tls_reviewed",
    "operations_reviewed",
)
REQUIRED_ARTIFACTS = (
    "wheel",
    "sdist",
    "windows_zip",
    "windows_msi",
    "sha256s",
    "windows_sha256s",
    "sbom",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate private evidence for a public GuildBridge release.")
    parser.add_argument("--evidence", required=True, type=Path, help="private JSON evidence file; never commit it")
    parser.add_argument("--tag", required=True, help="release tag being verified, for example v1.0.9")
    parser.add_argument(
        "--expected-commit",
        help="full commit SHA the release workflow checked out; requires source_commit to match",
    )
    args = parser.parse_args(argv)

    errors = validate_evidence_path(args.evidence, args.tag, expected_commit=args.expected_commit)
    if errors:
        print("check-production-evidence: error:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Production evidence is complete for {args.tag}.")
    return 0


def validate_evidence_path(path: Path, tag: str, *, expected_commit: str | None = None) -> list[str]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [f"could not read evidence file: {exc}"]
    except json.JSONDecodeError as exc:
        return [f"evidence file is not valid JSON: {exc.msg}"]
    if not isinstance(parsed, dict):
        return ["evidence file must contain a JSON object."]
    return validate_evidence(parsed, tag, expected_commit=expected_commit)


def validate_evidence(evidence: dict[str, Any], tag: str, *, expected_commit: str | None = None) -> list[str]:
    errors: list[str] = []
    if not TAG_PATTERN.fullmatch(tag):
        errors.append("--tag must be a v-prefixed semantic version.")
    if evidence.get("release_tag") != tag:
        errors.append("release_tag must exactly match --tag.")
    if not isinstance(evidence.get("source_commit"), str) or not SHA_PATTERN.fullmatch(evidence["source_commit"]):
        errors.append("source_commit must be a full 40-character commit SHA.")
    elif expected_commit is not None:
        normalized_expected = expected_commit.lower()
        if not SHA_PATTERN.fullmatch(normalized_expected):
            errors.append("--expected-commit must be a full 40-character commit SHA.")
        elif evidence["source_commit"] != normalized_expected:
            errors.append("source_commit must exactly match --expected-commit.")
    if not isinstance(evidence.get("reviewed_by"), str) or not evidence["reviewed_by"].strip():
        errors.append("reviewed_by must be a non-empty string.")
    if not _is_timestamp(evidence.get("reviewed_at")):
        errors.append("reviewed_at must be an ISO 8601 timestamp with an explicit timezone.")
    if not isinstance(evidence.get("workflow_run_url"), str) or not WORKFLOW_RUN_PATTERN.fullmatch(
        evidence["workflow_run_url"]
    ):
        errors.append("workflow_run_url must be a GitHub Actions run URL.")
    for key in (
        "github_settings_evidence_ref",
        "tls_evidence_ref",
        "operations_evidence_ref",
        "signing_evidence_ref",
    ):
        _validate_private_evidence_ref(evidence.get(key), key, errors)
    for key in REQUIRED_FLAGS:
        if evidence.get(key) is not True:
            errors.append(f"{key} must be true.")

    _validate_artifact_checksums(evidence.get("artifact_checksums"), errors)
    drills = evidence.get("provider_drills")
    if not isinstance(drills, list):
        errors.append("provider_drills must be a list of per-source evidence bundles.")
    else:
        _validate_provider_drills(drills, errors)
    content_drills = evidence.get("content_provider_drills")
    if not isinstance(content_drills, list):
        errors.append("content_provider_drills must be a list of enabled live-content route evidence bundles.")
    else:
        _validate_content_provider_drills(content_drills, errors)
    return errors


def _is_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _validate_artifact_checksums(value: object, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("artifact_checksums must be an object containing every published artifact checksum.")
        return
    digests: list[str] = []
    for artifact in REQUIRED_ARTIFACTS:
        checksum = value.get(artifact)
        if not isinstance(checksum, str) or not SHA256_PATTERN.fullmatch(checksum):
            errors.append(f"artifact_checksums.{artifact} must be a lowercase SHA-256 digest.")
            continue
        if checksum == "0" * 64:
            errors.append(f"artifact_checksums.{artifact} must not use the all-zero placeholder digest.")
        digests.append(checksum)
    if len(digests) == len(REQUIRED_ARTIFACTS) and len(set(digests)) != len(digests):
        errors.append("artifact_checksums must contain distinct digests for every published artifact.")


def _validate_provider_drills(drills: list[object], errors: list[str]) -> None:
    bundles: dict[str, dict[str, Any]] = {}
    for index, drill in enumerate(drills, start=1):
        if not isinstance(drill, dict):
            errors.append(f"provider_drills[{index}] must be an object.")
            continue
        source = drill.get("source")
        if not isinstance(source, str) or source not in PROVIDERS:
            errors.append(f"provider_drills[{index}].source must name a supported provider.")
            continue
        if source in bundles:
            errors.append(f"provider_drills has duplicate evidence bundles for {source}.")
            continue
        bundles[source] = drill
        targets = drill.get("targets")
        expected_targets = {provider for provider in PROVIDERS if provider != source}
        if not isinstance(targets, list) or {target for target in targets if isinstance(target, str)} != expected_targets:
            errors.append(f"provider_drills[{index}].targets must contain every other supported provider exactly once.")
        elif len(targets) != len(expected_targets):
            errors.append(f"provider_drills[{index}].targets contains duplicate providers.")
        for key in ("dry_run", "apply_recovery", "least_privilege_reviewed"):
            if drill.get(key) is not True:
                errors.append(f"provider_drills[{index}].{key} must be true.")
        _validate_private_evidence_ref(
            drill.get("evidence_bundle_ref"), f"provider_drills[{index}].evidence_bundle_ref", errors
        )
        _validate_route_evidence_refs(
            drill.get("route_evidence_refs"),
            expected_targets,
            f"provider_drills[{index}].route_evidence_refs",
            errors,
        )

    missing = [provider for provider in PROVIDERS if provider not in bundles]
    if missing:
        errors.append(
            "provider_drills must cover every supported provider as a source; missing: "
            + ", ".join(missing)
        )


def _content_route_matrix() -> dict[str, set[str]]:
    config = RuntimeConfig.from_env()
    exporters: set[str] = set()
    importers: set[str] = set()
    for provider in PROVIDERS:
        capability = get_provider(provider, config).content_capabilities()
        if capability.export.get("messages") == "supported":
            exporters.add(provider)
        if capability.import_.get("messages") == "supported":
            importers.add(provider)
    return {source: importers - {source} for source in exporters}


def _validate_content_provider_drills(drills: list[object], errors: list[str]) -> None:
    expected_routes = _content_route_matrix()
    bundles: dict[str, dict[str, Any]] = {}
    for index, drill in enumerate(drills, start=1):
        if not isinstance(drill, dict):
            errors.append(f"content_provider_drills[{index}] must be an object.")
            continue
        source = drill.get("source")
        if not isinstance(source, str) or source not in expected_routes:
            errors.append(f"content_provider_drills[{index}].source must name a content-export-capable provider.")
            continue
        if source in bundles:
            errors.append(f"content_provider_drills has duplicate evidence bundles for {source}.")
            continue
        bundles[source] = drill
        expected_targets = expected_routes[source]
        targets = drill.get("targets")
        if not isinstance(targets, list) or {target for target in targets if isinstance(target, str)} != expected_targets:
            errors.append(
                f"content_provider_drills[{index}].targets must contain every enabled live-content target exactly once."
            )
        elif len(targets) != len(expected_targets):
            errors.append(f"content_provider_drills[{index}].targets contains duplicate providers.")
        for key in ("archive_export_verified", "dry_run", "apply_recovery", "least_privilege_reviewed"):
            if drill.get(key) is not True:
                errors.append(f"content_provider_drills[{index}].{key} must be true.")
        _validate_private_evidence_ref(
            drill.get("evidence_bundle_ref"), f"content_provider_drills[{index}].evidence_bundle_ref", errors
        )
        _validate_route_evidence_refs(
            drill.get("route_evidence_refs"),
            expected_targets,
            f"content_provider_drills[{index}].route_evidence_refs",
            errors,
        )

    missing = [provider for provider in expected_routes if provider not in bundles]
    if missing:
        errors.append(
            "content_provider_drills must cover every content-export-capable provider as a source; missing: "
            + ", ".join(sorted(missing))
        )


def _validate_route_evidence_refs(
    value: object,
    expected_targets: set[str],
    field: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{field} must map every target provider to a private evidence reference.")
        return
    if set(value) != expected_targets:
        errors.append(f"{field} must contain every target provider exactly once.")
        return
    for target in sorted(expected_targets):
        _validate_private_evidence_ref(value[target], f"{field}.{target}", errors)


def _validate_private_evidence_ref(value: object, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not PRIVATE_EVIDENCE_REF_PATTERN.fullmatch(value):
        errors.append(f"{field} must be an opaque private:// evidence reference.")


if __name__ == "__main__":
    raise SystemExit(main())

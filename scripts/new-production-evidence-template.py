"""Create a credential-free private production-evidence template."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from guildbridge.config import RuntimeConfig
from guildbridge.providers import get_provider, provider_names

TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:[A-Za-z0-9.-]+)?$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PLACEHOLDER_SHA256 = "0" * 64


def content_route_matrix(providers: tuple[str, ...]) -> dict[str, list[str]]:
    config = RuntimeConfig.from_env()
    importers: set[str] = set()
    exporters: set[str] = set()
    for provider in providers:
        capability = get_provider(provider, config).content_capabilities()
        if capability.import_.get("messages") == "supported":
            importers.add(provider)
        if capability.export.get("messages") == "supported":
            exporters.add(provider)
    return {source: sorted(importers - {source}) for source in sorted(exporters)}


def build_template(tag: str, commit: str) -> dict[str, Any]:
    providers = tuple(sorted(provider_names()))
    content_routes = content_route_matrix(providers)
    provider_drills = []
    for source in providers:
        targets = [target for target in providers if target != source]
        provider_drills.append(
            {
                "source": source,
                "targets": targets,
                "dry_run": False,
                "apply_recovery": False,
                "least_privilege_reviewed": False,
                "evidence_bundle_ref": f"private://release-evidence/{tag}/{source}-routes",
                "route_evidence_refs": {
                    target: f"private://release-evidence/{tag}/routes/{source}-to-{target}" for target in targets
                },
            }
        )
    return {
        "release_tag": tag,
        "source_commit": commit,
        "reviewed_by": "replace-with-release-owner",
        "reviewed_at": "2026-01-01T00:00:00Z",
        "workflow_run_url": "https://github.com/OWNER/REPOSITORY/actions/runs/0000000000",
        "github_settings_evidence_ref": f"private://release-evidence/{tag}/github-production-settings-audit",
        "tls_evidence_ref": f"private://release-evidence/{tag}/tls-review",
        "operations_evidence_ref": f"private://release-evidence/{tag}/operations-review",
        "signing_evidence_ref": f"private://release-evidence/{tag}/windows-signing",
        "branch_protection_verified": False,
        "environment_protection_verified": False,
        "artifact_sha256_verified": False,
        "sbom_reviewed": False,
        "provenance_verified": False,
        "windows_signature_verified": False,
        "tls_reviewed": False,
        "operations_reviewed": False,
        "artifact_checksums": {
            "wheel": PLACEHOLDER_SHA256,
            "sdist": PLACEHOLDER_SHA256,
            "windows_zip": PLACEHOLDER_SHA256,
            "windows_msi": PLACEHOLDER_SHA256,
            "sha256s": PLACEHOLDER_SHA256,
            "windows_sha256s": PLACEHOLDER_SHA256,
            "sbom": PLACEHOLDER_SHA256,
            "dependency_audit": PLACEHOLDER_SHA256,
        },
        "provider_drills": provider_drills,
        "content_provider_drills": [
            {
                "source": source,
                "targets": targets,
                "archive_export_verified": False,
                "dry_run": False,
                "apply_recovery": False,
                "least_privilege_reviewed": False,
                "evidence_bundle_ref": f"private://release-evidence/{tag}/{source}-content-routes",
                "route_evidence_refs": {
                    target: f"private://release-evidence/{tag}/content-routes/{source}-to-{target}"
                    for target in targets
                },
            }
            for source, targets in content_routes.items()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a private GuildBridge production-evidence template.")
    parser.add_argument("--tag", required=True, help="release tag, for example v1.0.10")
    parser.add_argument("--commit", required=True, help="full lowercase 40-character source commit SHA")
    parser.add_argument("--out", required=True, type=Path, help="private evidence output path")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing template file")
    args = parser.parse_args(argv)

    if not TAG_PATTERN.fullmatch(args.tag):
        parser.error("--tag must be a v-prefixed semantic version.")
    if not SHA_PATTERN.fullmatch(args.commit):
        parser.error("--commit must be a full lowercase 40-character commit SHA.")
    if args.out.exists() and not args.overwrite:
        parser.error(f"{args.out} already exists; pass --overwrite to replace it.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(build_template(args.tag, args.commit), indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(f"Wrote private production-evidence template: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

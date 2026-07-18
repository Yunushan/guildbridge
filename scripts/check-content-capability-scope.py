"""Verify that documented live-content migration scope matches provider capabilities."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from guildbridge.config import RuntimeConfig
from guildbridge.providers import get_provider, provider_names

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_EXPORTERS = {"discord"}
EXPECTED_IMPORTERS = set(provider_names()) - {"mumble"}
REQUIRED_DOCUMENTATION = {
    "README.md": (
        "Live content migration currently exports from Discord archives only.",
        "Mumble does not currently support live content import.",
    ),
    "docs/PLATFORMS.md": (
        "Discord is the only supported live-content export source",
        "Mumble live-content import is not implemented.",
    ),
}


def capability_matrix() -> dict[str, dict[str, bool]]:
    config = RuntimeConfig.from_env()
    matrix: dict[str, dict[str, bool]] = {}
    for name in sorted(provider_names()):
        capability = get_provider(name, config).content_capabilities()
        matrix[name] = {
            "export_messages": capability.export.get("messages") == "supported",
            "import_messages": capability.import_.get("messages") == "supported",
        }
    return matrix


def validate_scope(root: Path = ROOT) -> list[str]:
    matrix = capability_matrix()
    exporters = {name for name, capability in matrix.items() if capability["export_messages"]}
    importers = {name for name, capability in matrix.items() if capability["import_messages"]}
    errors: list[str] = []
    if exporters != EXPECTED_EXPORTERS:
        errors.append(
            "live-content exporters changed; update the expected scope, documentation, and disposable-tenant evidence plan: "
            + ", ".join(sorted(exporters))
        )
    if importers != EXPECTED_IMPORTERS:
        errors.append(
            "live-content importers changed; update the expected scope, documentation, and disposable-tenant evidence plan: "
            + ", ".join(sorted(importers))
        )
    for relative_path, required_lines in REQUIRED_DOCUMENTATION.items():
        text = (root / relative_path).read_text(encoding="utf-8")
        for required_line in required_lines:
            if required_line not in text:
                errors.append(f"{relative_path} must document: {required_line}")
    return errors


def main() -> int:
    matrix = capability_matrix()
    errors = validate_scope()
    if errors:
        print("check-content-capability-scope: error:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(json.dumps(matrix, indent=2, sort_keys=True))
    print("Live-content capability scope matches the documented release boundary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

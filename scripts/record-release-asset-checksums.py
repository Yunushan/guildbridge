"""Record verified public release-asset checksums in private production evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ASSET_PATTERNS = {
    "wheel": "guildbridge-*.whl",
    "sdist": "guildbridge-*.tar.gz",
    "windows_zip": "GuildBridge-*-windows-x64.zip",
    "windows_msi": "GuildBridge-*-windows-x64.msi",
    "sha256s": "SHA256SUMS",
    "windows_sha256s": "SHA256SUMS-windows.txt",
    "sbom": "guildbridge-*.spdx.json",
}
MANIFESTS = {
    "sha256s": ("wheel", "sdist", "sbom"),
    "windows_sha256s": ("windows_zip", "windows_msi"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify release checksum manifests and record artifact digests in private evidence."
    )
    parser.add_argument("--assets-dir", required=True, type=Path, help="directory containing downloaded release assets")
    parser.add_argument("--evidence", required=True, type=Path, help="private production evidence JSON; never commit it")
    args = parser.parse_args(argv)

    try:
        assets = select_assets(args.assets_dir)
        verify_manifests(assets)
        record_checksums(args.evidence, assets)
    except ValueError as exc:
        print(f"record-release-asset-checksums: error: {exc}", file=sys.stderr)
        return 1

    print(f"Recorded verified release-asset checksums in {args.evidence}.")
    return 0


def select_assets(assets_dir: Path) -> dict[str, Path]:
    if not assets_dir.is_dir():
        raise ValueError(f"assets directory does not exist: {assets_dir}")
    selected: dict[str, Path] = {}
    for key, pattern in ASSET_PATTERNS.items():
        matches = sorted(path for path in assets_dir.glob(pattern) if path.is_file())
        if len(matches) != 1:
            raise ValueError(f"expected exactly one {key} asset matching {pattern}, found {len(matches)}")
        selected[key] = matches[0]
    return selected


def verify_manifests(assets: dict[str, Path]) -> None:
    for manifest_key, asset_keys in MANIFESTS.items():
        entries = parse_manifest(assets[manifest_key])
        expected_names = {assets[key].name for key in asset_keys}
        if set(entries) != expected_names:
            raise ValueError(
                f"{assets[manifest_key].name} must contain exactly: {', '.join(sorted(expected_names))}"
            )
        for key in asset_keys:
            path = assets[key]
            if entries[path.name] != sha256(path):
                raise ValueError(f"{assets[manifest_key].name} checksum mismatch for {path.name}")


def parse_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"could not read checksum manifest {path.name}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        digest, separator, filename = line.partition("  ")
        if separator != "  " or not SHA256_PATTERN.fullmatch(digest) or not filename:
            raise ValueError(f"{path.name}:{line_number} is not a valid SHA-256 checksum entry")
        if Path(filename).name != filename or filename in entries:
            raise ValueError(f"{path.name}:{line_number} has an unsafe or duplicate filename")
        entries[filename] = digest
    return entries


def record_checksums(evidence_path: Path, assets: dict[str, Path]) -> None:
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read evidence file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"evidence file is not valid JSON: {exc.msg}") from exc
    if not isinstance(evidence, dict):
        raise ValueError("evidence file must contain a JSON object")

    evidence["artifact_checksums"] = {key: sha256(path) for key, path in assets.items()}
    temporary = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(evidence_path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

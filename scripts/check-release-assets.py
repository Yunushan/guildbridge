"""Verify downloaded release assets against checksum manifests and private evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from guildbridge.release_assets import ASSET_PATTERNS, PYTHON_MANIFEST_KEYS, WINDOWS_MANIFEST_KEYS

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:[A-Za-z0-9.-]+)?$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify release assets against their manifests and private evidence.")
    parser.add_argument("--assets-dir", required=True, type=Path, help="directory containing downloaded release assets")
    parser.add_argument("--evidence", required=True, type=Path, help="private production evidence JSON")
    parser.add_argument("--tag", required=True, help="release tag whose version must appear in every asset name")
    args = parser.parse_args(argv)

    errors = validate_release_assets(args.assets_dir, args.evidence, tag=args.tag)
    if errors:
        print("check-release-assets: error:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release assets match checksum manifests and private evidence.")
    return 0


def validate_release_assets(assets_dir: Path, evidence_path: Path, *, tag: str | None = None) -> list[str]:
    errors: list[str] = []
    assets = _select_assets(assets_dir, errors)
    evidence = _load_evidence(evidence_path, errors)
    if errors:
        return errors

    if tag is not None:
        _verify_asset_versions(assets, tag, errors)
    _verify_asset_inventory(assets_dir, assets, errors)
    _verify_manifest(assets["sha256s"], assets, PYTHON_MANIFEST_KEYS, errors)
    _verify_manifest(assets["windows_sha256s"], assets, WINDOWS_MANIFEST_KEYS, errors)
    _verify_evidence_checksums(evidence, assets, errors)
    return errors


def _verify_asset_versions(assets: dict[str, Path], tag: str, errors: list[str]) -> None:
    if not TAG_PATTERN.fullmatch(tag):
        errors.append("--tag must be a v-prefixed semantic version.")
        return
    version = tag[1:]
    expected_names = {
        "sdist": f"guildbridge-{version}.tar.gz",
        "windows_zip": f"GuildBridge-{version}-windows-x64.zip",
        "windows_msi": f"GuildBridge-{version}-windows-x64.msi",
        "sbom": f"guildbridge-{tag}.spdx.json",
        "dependency_audit": f"guildbridge-{tag}.dependency-audit.json",
    }
    for key, expected_name in expected_names.items():
        actual_name = assets[key].name
        if actual_name != expected_name:
            errors.append(f"{key} asset must be named {expected_name}, found {actual_name}.")
    wheel_prefix = f"guildbridge-{version}-"
    if not assets["wheel"].name.startswith(wheel_prefix) or not assets["wheel"].name.endswith(".whl"):
        errors.append(
            f"wheel asset must start with {wheel_prefix!r} and end with '.whl', found {assets['wheel'].name}."
        )


def _select_assets(assets_dir: Path, errors: list[str]) -> dict[str, Path]:
    selected: dict[str, Path] = {}
    if not assets_dir.is_dir():
        errors.append(f"assets directory does not exist: {assets_dir}")
        return selected
    for key, pattern in ASSET_PATTERNS.items():
        matches = sorted(path for path in assets_dir.glob(pattern) if path.is_file())
        if len(matches) != 1:
            errors.append(f"expected exactly one {key} asset matching {pattern}, found {len(matches)}")
            continue
        selected[key] = matches[0]
    return selected


def _load_evidence(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"could not read evidence file: {exc}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"evidence file is not valid JSON: {exc.msg}")
        return {}
    if not isinstance(value, dict):
        errors.append("evidence file must contain a JSON object")
        return {}
    return value


def _verify_manifest(manifest_path: Path, assets: dict[str, Path], keys: tuple[str, ...], errors: list[str]) -> None:
    entries = _parse_manifest(manifest_path, errors)
    expected_names = {assets[key].name for key in keys}
    unexpected_names = sorted(set(entries) - expected_names)
    missing_names = sorted(expected_names - set(entries))
    if unexpected_names:
        errors.append(f"{manifest_path.name} contains unexpected entries: {', '.join(unexpected_names)}")
    if missing_names:
        errors.append(f"{manifest_path.name} is missing entries: {', '.join(missing_names)}")
    for key in keys:
        path = assets[key]
        expected = entries.get(path.name)
        if expected is None:
            errors.append(f"{manifest_path.name} does not contain {path.name}")
        elif expected != _sha256(path):
            errors.append(f"{manifest_path.name} checksum mismatch for {path.name}")


def _verify_asset_inventory(assets_dir: Path, assets: dict[str, Path], errors: list[str]) -> None:
    expected_names = {path.name for path in assets.values()}
    found_names: set[str] = set()
    for path in sorted(assets_dir.iterdir()):
        if path.is_symlink():
            errors.append(f"release assets must not contain symbolic links: {path.name}")
            continue
        if not path.is_file():
            errors.append(f"release assets must be flat files: {path.name}")
            continue
        found_names.add(path.name)
    unexpected_names = sorted(found_names - expected_names)
    if unexpected_names:
        errors.append("release assets contain unexpected files: " + ", ".join(unexpected_names))


def _parse_manifest(path: Path, errors: list[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"could not read checksum manifest {path.name}: {exc}")
        return entries
    for index, line in enumerate(lines, start=1):
        digest, separator, filename = line.partition("  ")
        if separator != "  " or not SHA256_PATTERN.fullmatch(digest) or not filename:
            errors.append(f"{path.name}:{index} is not a valid SHA-256 checksum entry")
            continue
        candidate = Path(filename)
        if candidate.name != filename or filename in entries:
            errors.append(f"{path.name}:{index} has an unsafe or duplicate filename")
            continue
        entries[filename] = digest
    return entries


def _verify_evidence_checksums(evidence: dict[str, Any], assets: dict[str, Path], errors: list[str]) -> None:
    checksums = evidence.get("artifact_checksums")
    if not isinstance(checksums, dict):
        errors.append("evidence artifact_checksums must be an object")
        return
    for key, path in assets.items():
        expected = checksums.get(key)
        if not isinstance(expected, str) or not SHA256_PATTERN.fullmatch(expected):
            errors.append(f"evidence artifact_checksums.{key} must be a lowercase SHA-256 digest")
        elif expected != _sha256(path):
            errors.append(f"evidence checksum does not match downloaded {key} asset")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

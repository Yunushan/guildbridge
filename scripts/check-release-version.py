from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
INIT_PATH = REPO_ROOT / "src" / "guildbridge" / "__init__.py"


def _read_match(path: Path, pattern: str, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not read {label} from {path.relative_to(REPO_ROOT)}.")
    return match.group(1)


def _expected_version(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        raise ValueError("Release tag is empty.")
    return tag[1:] if tag.startswith("v") else tag


def check_release_version(tag: str) -> None:
    expected = _expected_version(tag)
    project_version = _read_match(PYPROJECT_PATH, r'^version = "([^"]+)"\r?$', "project version")
    package_version = _read_match(INIT_PATH, r'^__version__ = "([^"]+)"\r?$', "package version")
    mismatches = []
    if project_version != expected:
        mismatches.append(f"pyproject.toml={project_version!r}")
    if package_version != expected:
        mismatches.append(f"src/guildbridge/__init__.py={package_version!r}")
    if mismatches:
        joined = ", ".join(mismatches)
        raise ValueError(f"Release tag {tag!r} expects version {expected!r}, but found {joined}.")
    print(f"Release tag {tag} matches package metadata version {expected}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify release tag and package metadata versions match.")
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME", ""), help="release tag, for example v1.0.6")
    args = parser.parse_args(argv)
    try:
        check_release_version(args.tag)
    except ValueError as exc:
        print(f"check-release-version: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env sh
set -eu

usage() {
  cat <<'USAGE'
Usage:
  scripts/release.sh VERSION [options]

Options:
  --python COMMAND          Python command to use (default: python)
  --release-branch NAME    Required release branch (default: main)
  --skip-checks            Skip lint, type checks, tests, and platform check
  --skip-build             Skip dist build and distribution verification
  --skip-commit            Do not create the release commit
  --skip-tag               Do not create the release tag
  --allow-dirty            Allow an otherwise dirty worktree
  --no-clean-dist          Do not delete dist/ before building
  -h, --help               Show this help

The script updates project versions, runs local release gates, creates a
release commit, and creates an annotated tag. It never pushes to a remote.
USAGE
}

die() {
  printf '%s\n' "release.sh: error: $*" >&2
  exit 1
}

run() {
  printf '> %s\n' "$*"
  "$@"
}

checked_output() {
  "$@"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command was not found on PATH: $1"
}

script_dir() {
  CDPATH= cd "$(dirname "$0")" && pwd -P
}

VERSION=""
PYTHON="python"
RELEASE_BRANCH="main"
SKIP_CHECKS=0
SKIP_BUILD=0
SKIP_COMMIT=0
SKIP_TAG=0
ALLOW_DIRTY=0
NO_CLEAN_DIST=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --python)
      [ "$#" -ge 2 ] || die "--python requires a command"
      PYTHON="$2"
      shift 2
      ;;
    --release-branch)
      [ "$#" -ge 2 ] || die "--release-branch requires a branch name"
      RELEASE_BRANCH="$2"
      shift 2
      ;;
    --skip-checks)
      SKIP_CHECKS=1
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --skip-commit)
      SKIP_COMMIT=1
      shift
      ;;
    --skip-tag)
      SKIP_TAG=1
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    --no-clean-dist)
      NO_CLEAN_DIST=1
      shift
      ;;
    -*)
      die "Unknown option: $1"
      ;;
    *)
      [ -z "$VERSION" ] || die "Only one VERSION argument is allowed"
      VERSION="$1"
      shift
      ;;
  esac
done

[ -n "$VERSION" ] || {
  usage >&2
  exit 2
}

printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([A-Za-z0-9.-]+)?$' \
  || die "Version must look like 1.0.0 or 1.0.0rc1"

SCRIPT_DIR=$(script_dir)
REPO_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd -P)
PYPROJECT_PATH="$REPO_ROOT/pyproject.toml"
INIT_PATH="$REPO_ROOT/src/guildbridge/__init__.py"
TAG_NAME="v$VERSION"

cd "$REPO_ROOT"

require_command git
require_command "$PYTHON"
require_command grep

git_status() {
  checked_output git status --porcelain
}

assert_clean_worktree() {
  reason="$1"
  status=$(git_status)
  if [ -n "$status" ]; then
    die "Refusing release prep with uncommitted changes $reason. Commit or stash them first, or rerun with --allow-dirty."
  fi
}

assert_tag_available() {
  if git show-ref --tags --verify --quiet "refs/tags/$TAG_NAME"; then
    die "Tag already exists locally: $TAG_NAME"
  fi
}

remove_repo_path() {
  target=$1
  case "$target" in
    "$REPO_ROOT"/*) ;;
    *) die "Refusing to remove path outside repository: $target" ;;
  esac
  if [ -e "$target" ]; then
    rm -rf "$target"
  fi
}

if [ "$ALLOW_DIRTY" -eq 0 ]; then
  assert_clean_worktree "before version bump"
fi

current_branch=$(checked_output git rev-parse --abbrev-ref HEAD)
if [ -n "$RELEASE_BRANCH" ] && [ "$current_branch" != "$RELEASE_BRANCH" ]; then
  die "Release prep must run on '$RELEASE_BRANCH'. Current branch is '$current_branch'. Use --release-branch '$current_branch' to override."
fi

assert_tag_available

VERSION="$VERSION" PYPROJECT_PATH="$PYPROJECT_PATH" INIT_PATH="$INIT_PATH" "$PYTHON" - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

version = os.environ["VERSION"]
pyproject_path = Path(os.environ["PYPROJECT_PATH"])
init_path = Path(os.environ["INIT_PATH"])


def update(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update {label} in {path}")
    path.write_text(updated, encoding="utf-8")


update(pyproject_path, r'^version = "[^"]+"$', f'version = "{version}"', "project version")
update(init_path, r'^__version__ = "[^"]+"$', f'__version__ = "{version}"', "package version")
PY

VERSION="$VERSION" PYPROJECT_PATH="$PYPROJECT_PATH" INIT_PATH="$INIT_PATH" "$PYTHON" - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

version = os.environ["VERSION"]
pyproject = Path(os.environ["PYPROJECT_PATH"]).read_text(encoding="utf-8")
init = Path(os.environ["INIT_PATH"]).read_text(encoding="utf-8")
project_match = re.search(r'^version = "([^"]+)"$', pyproject, flags=re.MULTILINE)
package_match = re.search(r'^__version__ = "([^"]+)"$', init, flags=re.MULTILINE)
project_version = project_match.group(1) if project_match else None
package_version = package_match.group(1) if package_match else None
if project_version != version or package_version != version:
    raise SystemExit(
        f"Version mismatch after update: pyproject.toml={project_version}, "
        f"__init__.py={package_version}, expected={version}"
    )
PY

if [ "$SKIP_CHECKS" -eq 1 ]; then
  printf '%s\n' "Warning: skipping lint, type checks, tests, and platform check." >&2
else
  run "$PYTHON" -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py
  run "$PYTHON" -m mypy src
  run "$PYTHON" -m pytest -q
  run "$PYTHON" scripts/check-platform.py --require cli --format json
fi

if [ "$SKIP_BUILD" -eq 1 ]; then
  printf '%s\n' "Warning: skipping package build and distribution verification." >&2
else
  if [ "$NO_CLEAN_DIST" -eq 0 ]; then
    remove_repo_path "$REPO_ROOT/dist"
  fi

  run "$PYTHON" -m build

  wheel_count=0
  for file in dist/*.whl; do
    [ -e "$file" ] || continue
    wheel_count=$((wheel_count + 1))
  done
  sdist_count=0
  for file in dist/*.tar.gz; do
    [ -e "$file" ] || continue
    sdist_count=$((sdist_count + 1))
  done
  [ "$wheel_count" -eq 1 ] && [ "$sdist_count" -eq 1 ] \
    || die "Expected exactly one wheel and one source archive in dist/."

  run "$PYTHON" -m twine check dist/*
  run "$PYTHON" scripts/verify-dist.py
fi

version_status=$(checked_output git status --porcelain -- pyproject.toml src/guildbridge/__init__.py)
if [ "$SKIP_COMMIT" -eq 1 ]; then
  if [ -n "$version_status" ] && [ "$SKIP_TAG" -eq 0 ]; then
    die "Version files changed but --skip-commit was set. Commit manually before tagging, or rerun without --skip-commit."
  fi
  printf '%s\n' "Warning: skipping release commit." >&2
else
  if [ -z "$version_status" ]; then
    printf '%s\n' "Version files already match $VERSION; no release commit needed."
  else
    run git add pyproject.toml src/guildbridge/__init__.py
    run git commit -m "Release $TAG_NAME"
  fi
fi

if [ "$SKIP_TAG" -eq 1 ]; then
  printf '%s\n' "Warning: skipping release tag." >&2
else
  if [ "$ALLOW_DIRTY" -eq 0 ]; then
    assert_clean_worktree "before tagging"
  fi
  assert_tag_available
  run git tag -a "$TAG_NAME" -m "Release $TAG_NAME"
fi

printf '\n%s\n' "Release prep complete for $TAG_NAME."
printf '%s\n' "Review the result, then publish with:"
printf '%s\n' "  git push origin $current_branch"
printf '%s\n' "  git push origin $TAG_NAME"

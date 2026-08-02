"""Run the fail-closed checks required to claim a GuildBridge release is production-ready."""

from __future__ import annotations

import argparse
import importlib.util
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
Check = tuple[str, Callable[[], int]]


def _load_script(filename: str):
    path = ROOT / "scripts" / filename
    module_name = filename.removesuffix(".py").replace("-", "_")
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Could not load production-readiness check: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def run_checks(checks: list[Check]) -> list[str]:
    failures: list[str] = []
    for name, check in checks:
        print(f"==> {name}")
        try:
            result = check()
        except Exception:  # noqa: BLE001 - aggregate every independent release gate failure.
            print(f"{name} failed unexpectedly; inspect its local log for details.")
            failures.append(name)
            continue
        if result != 0:
            failures.append(name)
    return failures


def build_checks(
    *, repo: str, evidence: Path, assets_dir: Path, tag: str, expected_commit: str
) -> list[Check]:
    release_controls = _load_script("check-release-controls.py")
    secret_hygiene = _load_script("check-secret-hygiene.py")
    security_baseline = _load_script("check-security-baseline.py")
    content_scope = _load_script("check-content-capability-scope.py")
    operations = _load_script("check-operations-readiness.py")
    github_settings = _load_script("check-github-production-settings.py")
    production_evidence = _load_script("check-production-evidence.py")
    release_assets = _load_script("check-release-assets.py")
    evidence_arguments = ["--repo", repo, "--evidence", str(evidence), "--tag", tag]
    github_settings_arguments = ["--repo", repo, "--release-tag", tag]
    evidence_arguments.extend(["--expected-commit", expected_commit])
    github_settings_arguments.extend(["--expected-commit", expected_commit])
    return [
        ("Repository release controls", release_controls.main),
        ("Git history secret hygiene", lambda: secret_hygiene.main(["--history"])),
        ("Static security baseline", security_baseline.main),
        ("Live-content capability scope", content_scope.main),
        ("Operations runbook", operations.main),
        ("Live GitHub production settings", lambda: github_settings.main(github_settings_arguments)),
        ("Private release evidence", lambda: production_evidence.main(evidence_arguments)),
        (
            "Downloaded release assets",
            lambda: release_assets.main(
                ["--assets-dir", str(assets_dir), "--evidence", str(evidence), "--tag", tag]
            ),
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository in OWNER/REPOSITORY form")
    parser.add_argument("--evidence", required=True, type=Path, help="private production-evidence JSON file")
    parser.add_argument(
        "--assets-dir",
        required=True,
        type=Path,
        help="directory containing the exact downloaded release assets and manifests",
    )
    parser.add_argument("--tag", required=True, help="release tag, for example v1.0.10")
    parser.add_argument(
        "--expected-commit",
        required=True,
        help="full main-branch commit SHA the exact release evidence must support",
    )
    args = parser.parse_args(argv)

    failures = run_checks(
        build_checks(
            repo=args.repo,
            evidence=args.evidence,
            assets_dir=args.assets_dir,
            tag=args.tag,
            expected_commit=args.expected_commit,
        )
    )
    if failures:
        print("Production readiness is incomplete; failed checks: " + ", ".join(failures))
        return 1
    print(f"Production readiness is complete for {args.tag}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    *, repo: str, evidence: Path, tag: str, expected_commit: str | None
) -> list[Check]:
    release_controls = _load_script("check-release-controls.py")
    secret_hygiene = _load_script("check-secret-hygiene.py")
    security_baseline = _load_script("check-security-baseline.py")
    content_scope = _load_script("check-content-capability-scope.py")
    github_settings = _load_script("check-github-production-settings.py")
    production_evidence = _load_script("check-production-evidence.py")
    evidence_arguments = ["--evidence", str(evidence), "--tag", tag]
    if expected_commit:
        evidence_arguments.extend(["--expected-commit", expected_commit])
    return [
        ("Repository release controls", release_controls.main),
        ("Git history secret hygiene", lambda: secret_hygiene.main(["--history"])),
        ("Static security baseline", security_baseline.main),
        ("Live-content capability scope", content_scope.main),
        ("Live GitHub production settings", lambda: github_settings.main(["--repo", repo])),
        ("Private release evidence", lambda: production_evidence.main(evidence_arguments)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository in OWNER/REPOSITORY form")
    parser.add_argument("--evidence", required=True, type=Path, help="private production-evidence JSON file")
    parser.add_argument("--tag", required=True, help="release tag, for example v1.0.10")
    parser.add_argument("--expected-commit", help="optional full release commit SHA")
    args = parser.parse_args(argv)

    failures = run_checks(
        build_checks(
            repo=args.repo,
            evidence=args.evidence,
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

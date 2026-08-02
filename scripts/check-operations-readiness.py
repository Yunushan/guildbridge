"""Verify that the production operations runbook retains its safety controls."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "OPERATIONS.md"

REQUIRED_TEXT = (
    "# Operations Runbook",
    "## Before an apply",
    "dedicated least-privilege migration account",
    "sanitized source template",
    "disposable-tenant dry run",
    "incident owner",
    "compensating action",
    "## During an apply",
    "Stop on unexpected provider authorization",
    "--resume-journal",
    "## Recovery and retention",
    "target snapshot and reviewed plan",
    "approved audit period",
    "Rotate affected credentials",
    "private security advisory",
    "final outcome, recovery actions, and operator approval",
)


def main() -> int:
    try:
        text = RUNBOOK.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"check-operations-readiness: could not read {RUNBOOK}: {exc}", file=sys.stderr)
        return 1

    missing = [value for value in REQUIRED_TEXT if value not in text]
    if missing:
        print("check-operations-readiness: required runbook controls are missing:", file=sys.stderr)
        for value in missing:
            print(f"- {value}", file=sys.stderr)
        return 1

    print("Operations runbook contains the required production safety controls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

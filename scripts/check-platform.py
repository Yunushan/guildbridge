from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from guildbridge.platforms import CHECK_TARGETS, evaluate_runtime_check, runtime_check  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether this runtime can run GuildBridge.")
    parser.add_argument(
        "--require",
        choices=CHECK_TARGETS,
        default="cli",
        help="capability to require: cli, desktop-gui, web-gui, or dev",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="output format",
    )
    args = parser.parse_args(argv)

    checks = runtime_check()
    evaluation = evaluate_runtime_check(checks, args.require)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "checks": checks,
                    "evaluation": {
                        "target": evaluation.target,
                        "ready": evaluation.ready,
                        "failures": list(evaluation.failures),
                        "warnings": list(evaluation.warnings),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if evaluation.ready else 1

    for key, value in checks.items():
        print(f"{key}: {value}")
    print(f"required_target: {evaluation.target}")
    print(f"check_ready: {evaluation.ready}")

    if evaluation.failures:
        print("failures:")
        for failure in evaluation.failures:
            print(f"- {failure}")
    if evaluation.warnings:
        print("warnings:")
        for warning in evaluation.warnings:
            print(f"- {warning}")

    return 0 if evaluation.ready else 1


if __name__ == "__main__":
    sys.exit(main())

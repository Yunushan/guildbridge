"""Create a credential-free receipt for a structural or live-content provider drill."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guildbridge.providers import provider_names

PLAN_SCHEMA = "guildbridge.apply-plan.v1"
BATCH_RESULT_SCHEMA = "guildbridge.batch-result.v1"
STRUCTURAL_JOURNAL_SCHEMA = "guildbridge.apply-journal.v1"
CONTENT_JOURNAL_SCHEMA = "guildbridge.content-apply-journal.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read {label}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object.")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _matching_plan_result(plan_data: dict[str, Any], *, source: str, target: str) -> dict[str, Any]:
    candidates: list[object]
    if plan_data.get("schema") == BATCH_RESULT_SCHEMA:
        candidates = plan_data.get("results") if isinstance(plan_data.get("results"), list) else []
    else:
        candidates = [plan_data]
    matching = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        plan = candidate.get("plan")
        context = plan.get("context") if isinstance(plan, dict) else None
        if isinstance(context, dict) and context.get("provider") == target and context.get("source_provider") == source:
            matching.append(candidate)
    if len(matching) != 1:
        raise ValueError("Dry-run plan must contain exactly one result for the selected source and target providers.")
    return matching[0]


def _validate_plan(plan_data: dict[str, Any], *, source: str, target: str) -> dict[str, Any]:
    result = _matching_plan_result(plan_data, source=source, target=target)
    if result.get("applied") is not False:
        raise ValueError("Dry-run plan result must have applied=false.")
    metadata = result.get("plan")
    if not isinstance(metadata, dict) or metadata.get("schema") != PLAN_SCHEMA:
        raise ValueError("Dry-run plan is missing GuildBridge stable plan metadata.")
    action_count = metadata.get("action_count")
    action_hash = metadata.get("action_hash")
    if not isinstance(action_count, int) or action_count < 0:
        raise ValueError("Dry-run plan action_count must be a non-negative integer.")
    if not isinstance(action_hash, str) or not SHA256_PATTERN.fullmatch(action_hash):
        raise ValueError("Dry-run plan action_hash must be a lowercase SHA-256 digest.")
    return {"schema": PLAN_SCHEMA, "action_count": action_count, "action_hash": action_hash}


def _validate_journal(
    journal: dict[str, Any], *, kind: str, target: str, label: str, requires_resume: bool
) -> dict[str, str]:
    expected_schema = STRUCTURAL_JOURNAL_SCHEMA if kind == "structural" else CONTENT_JOURNAL_SCHEMA
    if journal.get("schema") != expected_schema:
        raise ValueError(f"{label} must use schema {expected_schema}.")
    if journal.get("status") != "succeeded":
        raise ValueError(f"{label} must have status=succeeded.")
    context = journal.get("context") if kind == "structural" else journal
    if not isinstance(context, dict) or context.get("provider") != target:
        raise ValueError(f"{label} provider must match the selected target provider.")
    if requires_resume and (
        not isinstance(journal.get("resumed_from"), str) or not journal["resumed_from"].strip()
    ):
        raise ValueError(f"{label} must record the failed journal it resumed from.")
    return {"schema": expected_schema, "status": "succeeded"}


def build_receipt(
    *,
    kind: str,
    source: str,
    target: str,
    plan_path: Path,
    apply_journal_path: Path,
    recovery_journal_path: Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, "dry-run plan")
    apply_journal = _read_json(apply_journal_path, "apply journal")
    recovery_journal = _read_json(recovery_journal_path, "recovery journal")
    return {
        "schema": "guildbridge.provider-drill-receipt.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "source_provider": source,
        "target_provider": target,
        "dry_run_plan": {**_validate_plan(plan, source=source, target=target), "sha256": _sha256(plan_path)},
        "apply_journal": {
            **_validate_journal(
                apply_journal, kind=kind, target=target, label="Apply journal", requires_resume=False
            ),
            "sha256": _sha256(apply_journal_path),
        },
        "recovery_journal": {
            **_validate_journal(
                recovery_journal, kind=kind, target=target, label="Recovery journal", requires_resume=True
            ),
            "sha256": _sha256(recovery_journal_path),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("structural", "content"), required=True)
    parser.add_argument("--source", choices=sorted(provider_names()), required=True)
    parser.add_argument("--target", choices=sorted(provider_names()), required=True)
    parser.add_argument("--plan", required=True, type=Path, help="dry-run plan/result JSON")
    parser.add_argument("--apply-journal", required=True, type=Path, help="successful apply journal JSON")
    parser.add_argument("--recovery-journal", required=True, type=Path, help="successful recovery journal JSON")
    parser.add_argument("--out", required=True, type=Path, help="private receipt output path")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing receipt")
    args = parser.parse_args(argv)

    if args.source == args.target:
        parser.error("--source and --target must name different providers.")
    if args.out.exists() and not args.overwrite:
        parser.error(f"{args.out} already exists; pass --overwrite to replace it.")
    try:
        receipt = build_receipt(
            kind=args.kind,
            source=args.source,
            target=args.target,
            plan_path=args.plan,
            apply_journal_path=args.apply_journal,
            recovery_journal_path=args.recovery_journal,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(f"Wrote credential-free provider-drill receipt: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

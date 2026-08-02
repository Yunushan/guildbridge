from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record-provider-drill-receipt.py"
SPEC = importlib.util.spec_from_file_location("record_provider_drill_receipt", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
receipt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipt)


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _plan() -> dict[str, object]:
    return {
        "applied": False,
        "plan": {
            "schema": "guildbridge.apply-plan.v1",
            "context": {"source_provider": "discord", "provider": "stoat"},
            "action_count": 2,
            "action_hash": "a" * 64,
        },
    }


def _structural_journal(*, resumed_from: str | None = None) -> dict[str, object]:
    return {
        "schema": "guildbridge.apply-journal.v1",
        "status": "succeeded",
        "context": {
            "provider": "stoat",
            "source_provider": "discord",
            "reviewed_plan_hash": "a" * 64,
        },
        "resumed_from": resumed_from,
    }


def test_receipt_records_only_route_metadata_and_artifact_digests(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.json", _plan())
    apply = _write(tmp_path / "apply.json", _structural_journal())
    recovery = _write(tmp_path / "recovery.json", _structural_journal(resumed_from="failed.json"))

    result = receipt.build_receipt(
        kind="structural",
        source="discord",
        target="stoat",
        plan_path=plan,
        apply_journal_path=apply,
        recovery_journal_path=recovery,
    )

    assert result["schema"] == "guildbridge.provider-drill-receipt.v1"
    assert result["dry_run_plan"]["action_hash"] == "a" * 64
    assert result["apply_journal"]["sha256"] != result["recovery_journal"]["sha256"]
    assert "target_id" not in json.dumps(result)


def test_receipt_rejects_a_recovery_journal_without_resume_evidence(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.json", _plan())
    apply = _write(tmp_path / "apply.json", _structural_journal())
    recovery = _write(tmp_path / "recovery.json", _structural_journal())

    with pytest.raises(ValueError, match="resumed from"):
        receipt.build_receipt(
            kind="structural",
            source="discord",
            target="stoat",
            plan_path=plan,
            apply_journal_path=apply,
            recovery_journal_path=recovery,
        )


def test_receipt_rejects_a_journal_for_a_different_source_or_plan(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.json", _plan())
    apply_data = _structural_journal()
    apply_context = apply_data["context"]
    assert isinstance(apply_context, dict)
    apply_context["source_provider"] = "fluxer"
    apply = _write(tmp_path / "apply.json", apply_data)
    recovery = _write(tmp_path / "recovery.json", _structural_journal(resumed_from="failed.json"))

    with pytest.raises(ValueError, match="source_provider"):
        receipt.build_receipt(
            kind="structural",
            source="discord",
            target="stoat",
            plan_path=plan,
            apply_journal_path=apply,
            recovery_journal_path=recovery,
        )

    apply_context["source_provider"] = "discord"
    apply_context["reviewed_plan_hash"] = "b" * 64
    apply = _write(tmp_path / "apply.json", apply_data)
    with pytest.raises(ValueError, match="reviewed_plan_hash"):
        receipt.build_receipt(
            kind="structural",
            source="discord",
            target="stoat",
            plan_path=plan,
            apply_journal_path=apply,
            recovery_journal_path=recovery,
        )


def test_content_receipt_requires_the_content_journal_schema(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.json", _plan())
    apply = _write(
        tmp_path / "apply.json",
        {
            "schema": "guildbridge.content-apply-journal.v1",
            "status": "succeeded",
            "provider": "stoat",
            "action_hash": "a" * 64,
        },
    )
    recovery = _write(
        tmp_path / "recovery.json",
        {
            "schema": "guildbridge.content-apply-journal.v1",
            "status": "succeeded",
            "provider": "stoat",
            "action_hash": "a" * 64,
            "resumed_from": "failed-content.json",
        },
    )

    result = receipt.build_receipt(
        kind="content",
        source="discord",
        target="stoat",
        plan_path=plan,
        apply_journal_path=apply,
        recovery_journal_path=recovery,
    )

    assert result["kind"] == "content"
    assert result["apply_journal"]["action_hash"] == "a" * 64


def test_content_receipt_rejects_a_journal_for_a_different_action_set(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.json", _plan())
    apply = _write(
        tmp_path / "apply.json",
        {
            "schema": "guildbridge.content-apply-journal.v1",
            "status": "succeeded",
            "provider": "stoat",
            "action_hash": "b" * 64,
        },
    )
    recovery = _write(
        tmp_path / "recovery.json",
        {
            "schema": "guildbridge.content-apply-journal.v1",
            "status": "succeeded",
            "provider": "stoat",
            "action_hash": "a" * 64,
            "resumed_from": "failed-content.json",
        },
    )

    with pytest.raises(ValueError, match="action_hash"):
        receipt.build_receipt(
            kind="content",
            source="discord",
            target="stoat",
            plan_path=plan,
            apply_journal_path=apply,
            recovery_journal_path=recovery,
        )

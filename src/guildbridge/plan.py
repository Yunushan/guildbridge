from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from guildbridge.journal import template_fingerprint, utc_now
from guildbridge.models import Action, CommunityTemplate, ImportResult

PLAN_SCHEMA = "guildbridge.apply-plan.v1"


@dataclass(frozen=True)
class StablePlanContext:
    command: str
    provider: str
    template_hash: str
    template_name: str
    source_provider: str | None = None
    target_id: str | None = None
    target_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_plan_context(
    *,
    command: str,
    provider: str,
    template: CommunityTemplate,
    source_provider: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
) -> StablePlanContext:
    return StablePlanContext(
        command=command,
        provider=provider,
        source_provider=source_provider,
        template_hash=template_fingerprint(template),
        template_name=template.name,
        target_id=target_id,
        target_name=target_name,
    )


def action_fingerprint(actions: list[Action] | list[dict[str, Any]]) -> str:
    normalized = [asdict(action) if isinstance(action, Action) else action for action in actions]
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_plan_metadata(context: StablePlanContext, result: ImportResult) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "created_at": utc_now(),
        "context": context.to_dict(),
        "action_count": len(result.actions),
        "action_hash": action_fingerprint(result.actions),
    }


def apply_result_plan_metadata(candidate_plan: dict[str, Any], reviewed_plan_path: str | Path) -> dict[str, Any]:
    metadata = dict(candidate_plan)
    metadata["reviewed_plan_path"] = str(reviewed_plan_path)
    metadata["validated_at"] = utc_now()
    return metadata


def result_to_dict(result: ImportResult, *, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    data = result.to_dict()
    if plan is not None:
        data["plan"] = plan
    return data


def load_reviewed_plan(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("applied") is not False:
        raise ValueError("Reviewed plan must be a dry-run result with applied=false.")
    plan = data.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("Reviewed plan is missing stable plan metadata. Recreate it with this GuildBridge version.")
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"Unsupported reviewed plan schema: {plan.get('schema')!r}")
    return data


def validate_reviewed_plan_data(data: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    reviewed_plan = data["plan"]
    reviewed_actions = data.get("actions")
    if not isinstance(reviewed_actions, list):
        raise ValueError("Reviewed plan actions must be a list.")
    reviewed_action_hash = action_fingerprint(reviewed_actions)
    if reviewed_action_hash != reviewed_plan.get("action_hash"):
        raise ValueError("Reviewed plan action hash does not match its actions.")
    expected_context = expected.get("context")
    reviewed_context = reviewed_plan.get("context")
    if not isinstance(expected_context, dict) or not isinstance(reviewed_context, dict):
        raise ValueError("Reviewed plan context is invalid.")
    for key in ("command", "provider", "source_provider", "target_id", "target_name", "template_hash"):
        if reviewed_context.get(key) != expected_context.get(key):
            raise ValueError(
                f"Refusing --apply because reviewed plan has different {key}: "
                f"{reviewed_context.get(key)!r} != {expected_context.get(key)!r}."
            )
    for key in ("action_count", "action_hash"):
        if reviewed_plan.get(key) != expected.get(key):
            raise ValueError(
                f"Refusing --apply because reviewed plan has different {key}: "
                f"{reviewed_plan.get(key)!r} != {expected.get(key)!r}."
            )
    return reviewed_plan


def validate_reviewed_plan(path: str | Path, expected: dict[str, Any]) -> dict[str, Any]:
    return validate_reviewed_plan_data(load_reviewed_plan(path), expected)

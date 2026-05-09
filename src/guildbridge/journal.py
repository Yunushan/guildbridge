from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guildbridge.http import sanitize_text
from guildbridge.models import Action, CommunityTemplate, ImportResult

JOURNAL_SCHEMA = "guildbridge.apply-journal.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def template_fingerprint(template: CommunityTemplate) -> str:
    data = template.to_dict()
    if isinstance(data.get("source"), dict):
        data["source"]["exported_at"] = None
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ApplyJournalContext:
    command: str
    provider: str
    template_hash: str
    template_name: str
    source_provider: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    reviewed_plan_hash: str | None = None
    plan_out: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_journal_path(command: str, provider: str, *, root: str | Path = ".guildbridge/journals") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    safe_command = _safe_path_part(command)
    safe_provider = _safe_path_part(provider)
    return Path(root) / f"{stamp}-{safe_command}-{safe_provider}-{suffix}.json"


def load_journal(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != JOURNAL_SCHEMA:
        raise ValueError(f"Unsupported apply journal schema: {data.get('schema')!r}")
    return data


def validate_resume_journal(path: str | Path, expected: ApplyJournalContext) -> dict[str, Any]:
    data = load_journal(path)
    status = data.get("status")
    if status == "succeeded":
        raise ValueError("Refusing to resume from a journal that already succeeded.")
    context = data.get("context")
    if not isinstance(context, dict):
        raise ValueError("Refusing to resume from a journal without context.")

    expected_context = expected.to_dict()
    for key in ("command", "provider", "source_provider", "target_id", "target_name", "template_hash", "reviewed_plan_hash"):
        if context.get(key) != expected_context.get(key):
            raise ValueError(
                f"Refusing to resume from journal with different {key}: "
                f"{context.get(key)!r} != {expected_context.get(key)!r}."
            )
    return data


class ApplyJournal:
    def __init__(
        self,
        path: str | Path,
        context: ApplyJournalContext,
        *,
        resumed_from: str | Path | None = None,
    ):
        self.path = Path(path)
        self.context = context
        self.resumed_from = str(resumed_from) if resumed_from else None
        self._data: dict[str, Any] = {
            "schema": JOURNAL_SCHEMA,
            "status": "started",
            "started_at": utc_now(),
            "finished_at": None,
            "context": context.to_dict(),
            "resumed_from": self.resumed_from,
            "actions": [],
            "result": None,
            "error": None,
        }

    def start(self) -> None:
        self._write()

    def record_action(self, action: Action) -> int:
        actions = self._actions()
        index = len(actions)
        actions.append(
            {
                "index": index,
                "status": "pending",
                "started_at": utc_now(),
                "finished_at": None,
                "action": asdict(action),
                "error": None,
            }
        )
        self._write()
        return index

    def action_succeeded(self, index: int) -> None:
        entry = self._entry(index)
        entry["status"] = "succeeded"
        entry["finished_at"] = utc_now()
        self._write()

    def action_failed(self, index: int, error: BaseException | str) -> None:
        entry = self._entry(index)
        entry["status"] = "failed"
        entry["finished_at"] = utc_now()
        entry["error"] = sanitize_text(str(error))
        self._write()

    def finish(self, result: ImportResult) -> None:
        self._data["status"] = "succeeded"
        self._data["finished_at"] = utc_now()
        self._data["result"] = result.to_dict()
        self._write()

    def fail(self, error: BaseException | str) -> None:
        self._data["status"] = "failed"
        self._data["finished_at"] = utc_now()
        self._data["error"] = sanitize_text(str(error))
        self._write()

    def _actions(self) -> list[dict[str, Any]]:
        actions = self._data.setdefault("actions", [])
        if not isinstance(actions, list):
            raise TypeError("journal actions must be a list")
        return actions

    def _entry(self, index: int) -> dict[str, Any]:
        actions = self._actions()
        if index < 0 or index >= len(actions):
            raise IndexError(f"journal action index out of range: {index}")
        entry = actions[index]
        if not isinstance(entry, dict):
            raise TypeError("journal action entry must be an object")
        return entry

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)


def _safe_path_part(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "run"

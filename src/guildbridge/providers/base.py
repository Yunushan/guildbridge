from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from guildbridge.config import RuntimeConfig
from guildbridge.content import (
    ContentArchive,
    ContentCapability,
    ContentImportOptions,
    dry_run_content_import,
)
from guildbridge.models import Action, CommunityTemplate, ImportResult


class ApplyJournalRecorder(Protocol):
    def record_action(self, action: Action) -> int:
        raise NotImplementedError

    def action_succeeded(self, index: int) -> None:
        raise NotImplementedError

    def action_failed(self, index: int, error: BaseException | str) -> None:
        raise NotImplementedError


@dataclass
class ExportOptions:
    source_id: str | None = None
    template: str | None = None
    include_user_overwrites: bool = False


@dataclass
class ImportOptions:
    target_id: str | None = None
    target_name: str | None = None
    apply: bool = False
    audit_log_reason: str | None = None
    journal: ApplyJournalRecorder | None = None


class Provider(ABC):
    name: str
    aliases: tuple[str, ...] = ()

    def __init__(self, config: RuntimeConfig):
        self.config = config

    @abstractmethod
    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        raise NotImplementedError

    @abstractmethod
    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        raise NotImplementedError

    def content_capabilities(self) -> ContentCapability:
        return ContentCapability.planned_for_provider(self.name)

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply:
            raise ValueError(f"{self.name} content import is not implemented for live writes yet.")
        return dry_run_content_import(self.name, archive, options)

    @staticmethod
    def supported_warning() -> str:
        return "Messages, members, DMs, and user-specific permission overwrites are intentionally not exported."


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def response_id(value: Mapping[str, Any], *paths: str) -> str | None:
    for path in paths:
        current: Any = value
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current is not None and current != "":
            return str(current)
    return None


def require_response_id(value: Mapping[str, Any], resource: str, *paths: str) -> str:
    found = response_id(value, *paths)
    if found:
        return found
    expected = ", ".join(paths)
    raise ValueError(f"{resource} response did not contain an id at any of: {expected}; response={value!r}")


def plan_or_apply_action(
    options: ImportOptions,
    result: ImportResult,
    action: Action,
    operation: Callable[[], Any] | None = None,
) -> Any:
    result.actions.append(action)
    journal_index = options.journal.record_action(action) if options.apply and options.journal else None
    if not options.apply:
        return None
    if operation is None:
        raise ValueError("Internal error: apply action missing provider operation.")
    try:
        response = operation()
    except Exception as exc:
        if journal_index is not None and options.journal:
            options.journal.action_failed(journal_index, exc)
        raise
    if journal_index is not None and options.journal:
        options.journal.action_succeeded(journal_index)
    return response

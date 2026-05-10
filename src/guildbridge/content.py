from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from guildbridge.http import sanitize_text
from guildbridge.models import Action, ImportResult
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

CONTENT_CAPABILITIES_SCHEMA = "guildbridge.content-capabilities.v1"
CONTENT_ARCHIVE_SCHEMA = "guildbridge.content.v1"
CONTENT_APPLY_JOURNAL_SCHEMA = "guildbridge.content-apply-journal.v1"
CONTENT_DEAD_LETTER_SCHEMA = "guildbridge.content-dead-letter.v1"
CONTENT_IMPORT_REPORT_SCHEMA = "guildbridge.content-import-report.v1"
CONTENT_INCREMENTAL_STATE_SCHEMA = "guildbridge.content-incremental-state.v1"
CONTENT_VERSION = "1.0"
CONTENT_STATUS = Literal["not_implemented", "planned", "supported", "not_applicable"]
CONTENT_FEATURES: tuple[str, ...] = (
    "messages",
    "message_authors",
    "message_timestamps",
    "attachments",
    "custom_emoji",
    "stickers",
    "pins",
    "replies",
    "reactions",
    "embeds",
    "polls",
    "threads",
    "forum_posts",
    "server_banner",
    "role_colors",
    "channel_permissions",
    "nsfw_channels",
    "offline_exports",
    "pre_creation_review",
    "pause_resume",
    "incremental_migration",
    "parallel_sends",
    "dead_letter_queue",
    "message_splitting",
    "migration_report",
    "migration_lock",
    "circuit_breaker",
)
CONTENT_FEATURE_SET = set(CONTENT_FEATURES)
MESSAGE_LIMIT = 1900
CUSTOM_EMOJI_RE = re.compile(r"<(?P<animated>a?):(?P<name>[A-Za-z0-9_.~-]+):(?P<id>\d+)>")


@dataclass(frozen=True)
class ContentCapability:
    provider: str
    export: dict[str, CONTENT_STATUS] = field(default_factory=dict)
    import_: dict[str, CONTENT_STATUS] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def planned_for_provider(cls, provider: str) -> ContentCapability:
        planned: dict[str, CONTENT_STATUS] = {feature: "planned" for feature in CONTENT_FEATURES}
        return cls(
            provider=provider,
            export=planned.copy(),
            import_=planned.copy(),
            notes=[
                "Optional content migration is gated behind --include-content and is not part of privacy-safe templates.",
                "Live provider content import/export is planned but not implemented for this provider yet.",
            ],
        )

    @classmethod
    def text_content_provider(
        cls,
        provider: str,
        *,
        export_supported: bool = False,
        import_supported: bool = True,
        reliability_supported: bool = False,
    ) -> ContentCapability:
        export: dict[str, CONTENT_STATUS] = {feature: "planned" for feature in CONTENT_FEATURES}
        import_: dict[str, CONTENT_STATUS] = {feature: "planned" for feature in CONTENT_FEATURES}
        for feature in (
            "messages",
            "message_authors",
            "message_timestamps",
            "attachments",
            "custom_emoji",
            "stickers",
            "pins",
            "replies",
            "reactions",
            "embeds",
            "polls",
            "threads",
            "forum_posts",
            "offline_exports",
            "pre_creation_review",
            "message_splitting",
        ):
            export[feature] = "supported" if export_supported else "planned"
            import_[feature] = "supported" if import_supported else "planned"
        for feature in (
            "pause_resume",
            "dead_letter_queue",
            "migration_report",
            "migration_lock",
            "incremental_migration",
            "circuit_breaker",
        ):
            import_[feature] = "supported" if reliability_supported and import_supported else "planned"
        import_["parallel_sends"] = "planned"
        return cls(
            provider=provider,
            export=export,
            import_=import_,
            notes=[
                "Content support is optional and requires an explicit channel id map for writes.",
                "Messages are imported as formatted text; platform-native author/timestamp fidelity varies by provider.",
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["import"] = data.pop("import_")
        return data


@dataclass
class ContentSource:
    platform: str
    id_hash: str | None = None
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: str | None = None


@dataclass
class ContentAuthor:
    id_hash: str | None = None
    display_name: str = "Unknown"
    username: str | None = None
    avatar_url: str | None = None
    is_bot: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentEmoji:
    id_hash: str | None = None
    name: str = ""
    url: str | None = None
    local_path: str | None = None
    animated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentAttachment:
    id_hash: str | None = None
    filename: str | None = None
    url: str | None = None
    local_path: str | None = None
    content_type: str | None = None
    size: int | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentReaction:
    emoji: str
    count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentSticker:
    id_hash: str | None = None
    name: str = ""
    url: str | None = None
    format_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentPollAnswer:
    text: str
    vote_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentPoll:
    question: str
    answers: list[ContentPollAnswer] = field(default_factory=list)
    allow_multiselect: bool = False
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentEmbed:
    title: str | None = None
    description: str | None = None
    url: str | None = None
    image_url: str | None = None
    thumbnail_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentChannel:
    id: str
    name: str
    type: str = "text"
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentMessage:
    id: str
    channel_id: str
    author: ContentAuthor = field(default_factory=ContentAuthor)
    content: str = ""
    created_at: str | None = None
    edited_at: str | None = None
    attachments: list[ContentAttachment] = field(default_factory=list)
    reactions: list[ContentReaction] = field(default_factory=list)
    embeds: list[ContentEmbed] = field(default_factory=list)
    stickers: list[ContentSticker] = field(default_factory=list)
    poll: ContentPoll | None = None
    pinned: bool = False
    reply_to_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentArchive:
    name: str
    schema: str = CONTENT_ARCHIVE_SCHEMA
    version: str = CONTENT_VERSION
    source: ContentSource = field(default_factory=lambda: ContentSource(platform="unknown"))
    channels: list[ContentChannel] = field(default_factory=list)
    messages: list[ContentMessage] = field(default_factory=list)
    emoji: list[ContentEmoji] = field(default_factory=list)
    stickers: list[ContentSticker] = field(default_factory=list)
    features: list[str] = field(default_factory=lambda: ["messages"])
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ContentArchive:
        if data.get("schema") != CONTENT_ARCHIVE_SCHEMA:
            raise ValueError(f"Unsupported content archive schema: {data.get('schema')!r}; expected {CONTENT_ARCHIVE_SCHEMA!r}")
        source = ContentSource(**(data.get("source") or {}))
        channels = [ContentChannel(**item) for item in data.get("channels", [])]
        messages: list[ContentMessage] = []
        for item in data.get("messages", []):
            raw = dict(item)
            raw["author"] = ContentAuthor(**(raw.get("author") or {}))
            raw["attachments"] = [ContentAttachment(**attachment) for attachment in raw.get("attachments", [])]
            raw["reactions"] = [ContentReaction(**reaction) for reaction in raw.get("reactions", [])]
            raw["embeds"] = [ContentEmbed(**embed) for embed in raw.get("embeds", [])]
            raw["stickers"] = [ContentSticker(**sticker) for sticker in raw.get("stickers", [])]
            if raw.get("poll"):
                poll = dict(raw["poll"])
                poll["answers"] = [ContentPollAnswer(**answer) for answer in poll.get("answers", [])]
                raw["poll"] = ContentPoll(**poll)
            messages.append(ContentMessage(**raw))
        return ContentArchive(
            schema=data.get("schema", CONTENT_ARCHIVE_SCHEMA),
            version=data.get("version", CONTENT_VERSION),
            name=data.get("name", "Imported content"),
            source=source,
            channels=channels,
            messages=messages,
            emoji=[ContentEmoji(**item) for item in data.get("emoji", [])],
            stickers=[ContentSticker(**item) for item in data.get("stickers", [])],
            features=list(data.get("features", [])),
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.schema != CONTENT_ARCHIVE_SCHEMA:
            problems.append(f"Unsupported content archive schema {self.schema!r}; expected {CONTENT_ARCHIVE_SCHEMA!r}")
        if self.version != CONTENT_VERSION:
            problems.append(f"Unsupported content archive version {self.version!r}; expected {CONTENT_VERSION!r}")
        channel_ids = {channel.id for channel in self.channels}
        message_ids: set[str] = set()
        for channel in self.channels:
            if not channel.id.strip():
                problems.append("Content channel has an empty id")
            if not channel.name.strip():
                problems.append(f"Content channel {channel.id!r} has no name")
        for message in self.messages:
            if not message.id.strip():
                problems.append("Content message has an empty id")
            elif message.id in message_ids:
                problems.append(f"Duplicate content message id {message.id!r}")
            message_ids.add(message.id)
            if message.channel_id not in channel_ids:
                problems.append(f"Content message {message.id!r} references missing channel {message.channel_id!r}")
            if message.reply_to_id and message.reply_to_id not in message_ids:
                # Replies may point forward or to messages outside the export; keep this as a warning-style problem only.
                continue
        return problems


@dataclass
class ContentImportOptions:
    apply: bool = False
    target_id: str | None = None
    target_name: str | None = None
    channel_map: dict[str, str] = field(default_factory=dict)
    preserve_authors: bool = True
    include_attachments: bool = True
    include_reactions: bool = True
    include_embeds: bool = True
    include_stickers: bool = True
    include_polls: bool = True
    include_threads: bool = True
    include_custom_emoji: bool = True
    native_attachments: bool = False
    native_embeds: bool = False
    native_replies: bool = False
    native_reactions: bool = False
    native_pins: bool = False
    native_custom_emoji: bool = False
    native_masquerade: bool = False
    native_stickers: bool = False
    native_content: bool = False
    message_limit: int | None = None
    journal_path: str | None = None
    resume_journal: str | None = None
    dead_letter_path: str | None = None
    report_path: str | None = None
    lock_path: str | None = None
    incremental_state_path: str | None = None
    incremental: bool = False
    continue_on_error: bool = False
    max_failures: int = 1
    parallel_sends: int = 1

    def __post_init__(self) -> None:
        if self.native_content:
            self.native_attachments = True
            self.native_embeds = True
            self.native_replies = True
            self.native_reactions = True
            self.native_pins = True
            self.native_custom_emoji = True
            self.native_masquerade = True
            self.native_stickers = True

    @property
    def uses_native_content(self) -> bool:
        return any(
            (
                self.native_attachments,
                self.native_embeds,
                self.native_replies,
                self.native_reactions,
                self.native_pins,
                self.native_custom_emoji,
                self.native_masquerade,
                self.native_stickers,
            )
        )


def validate_content_features(features: list[str]) -> list[str]:
    invalid = sorted(set(features) - CONTENT_FEATURE_SET)
    if invalid:
        valid = ", ".join(CONTENT_FEATURES)
        raise ValueError(f"Unknown content feature(s): {', '.join(invalid)}. Valid features: {valid}")
    return features


def selected_content_features(*, include_content: bool, requested_features: list[str] | None = None) -> list[str]:
    requested = validate_content_features(requested_features or [])
    if requested:
        return requested
    return list(CONTENT_FEATURES) if include_content else []


def content_capabilities_document(capabilities: list[ContentCapability]) -> dict[str, Any]:
    return {
        "schema": CONTENT_CAPABILITIES_SCHEMA,
        "default_enabled": False,
        "features": list(CONTENT_FEATURES),
        "providers": [capability.to_dict() for capability in capabilities],
        "privacy": {
            "normal_templates_include_content": False,
            "requires_explicit_opt_in": True,
            "stores_tokens": False,
        },
    }


def content_capabilities_table(capabilities: list[ContentCapability]) -> str:
    lines = [
        "Optional content migration is not enabled by default.",
        "Current live content import/export status:",
        "",
    ]
    for capability in capabilities:
        export_supported = sum(1 for status in capability.export.values() if status == "supported")
        import_supported = sum(1 for status in capability.import_.values() if status == "supported")
        lines.append(
            f"- {capability.provider}: export supported {export_supported}/{len(CONTENT_FEATURES)}, "
            f"import supported {import_supported}/{len(CONTENT_FEATURES)}"
        )
        for note in capability.notes:
            lines.append(f"  note: {note}")
    lines.append("")
    lines.append("Feature names: " + ", ".join(CONTENT_FEATURES))
    return "\n".join(lines)


def content_not_implemented_message(*, source_provider: str | None, target_providers: list[str], features: list[str]) -> str:
    provider_text = ", ".join(target_providers) if target_providers else "none"
    if source_provider and target_providers:
        provider_text = f"{source_provider} -> {provider_text}"
    elif source_provider:
        provider_text = source_provider
    return (
        "Optional content migration is not implemented for that live provider path yet. "
        f"Requested provider path: {provider_text}. Requested content feature(s): {', '.join(features)}. "
        "Run `guildbridge content-features --format json` to inspect the current capability gate. "
        "Normal GuildBridge templates remain structure-only and privacy-safe."
    )


def load_content_archive(path: str | Path) -> ContentArchive:
    return ContentArchive.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_content_archive(archive: ContentArchive, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(archive.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_channel_map(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "id_map" in data and isinstance(data["id_map"], dict):
        data = data["id_map"]
    if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
        merged: dict[str, str] = {}
        for result in data["results"]:
            if isinstance(result, dict) and isinstance(result.get("id_map"), dict):
                merged.update({str(k): str(v) for k, v in result["id_map"].items()})
        return merged
    if not isinstance(data, dict):
        raise ValueError("Channel map must be a JSON object, a GuildBridge result with id_map, or a batch result.")
    return {str(k): str(v) for k, v in data.items()}


def content_archive_fingerprint(archive: ContentArchive) -> str:
    payload = json.dumps(archive.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_action_key(action: Action) -> str:
    payload = json.dumps(asdict(action), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_text_from_action(action: Action) -> str:
    payload = action.payload or {}
    content = str(payload.get("content") or "").strip()
    return content or "[empty message]"


def default_content_apply_path(provider: str, kind: str, *, target_id: str | None = None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    safe_provider = _safe_path_part(provider)
    if kind == "locks":
        target = _safe_path_part(target_id or "target")
        return Path(".guildbridge") / "content" / kind / f"{safe_provider}-{target}.lock"
    return Path(".guildbridge") / "content" / kind / f"{stamp}-{safe_provider}-{suffix}.json"


class ContentMigrationLock:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self._created = False

    def __enter__(self) -> ContentMigrationLock:
        if self.path is None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "schema": "guildbridge.content-lock.v1",
                            "created_at": _utc_now(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except FileExistsError as exc:
            raise ValueError(
                f"Content migration lock already exists at {self.path}. "
                "Another migration may be running, or a previous run may need manual recovery."
            ) from exc
        self._created = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self.path is not None and self._created:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class ContentApplyJournal:
    def __init__(self, path: str | Path, *, provider: str, target_id: str | None, target_name: str | None):
        self.path = Path(path)
        self._data: dict[str, Any] = {
            "schema": CONTENT_APPLY_JOURNAL_SCHEMA,
            "status": "started",
            "provider": provider,
            "target_id": target_id,
            "target_name": target_name,
            "started_at": _utc_now(),
            "finished_at": None,
            "events": [],
            "result": None,
            "error": None,
        }

    def start(self) -> None:
        self._write()

    def record_action(self, action: Action) -> int:
        events = self._events()
        index = len(events)
        events.append(
            {
                "index": index,
                "status": "pending",
                "started_at": _utc_now(),
                "finished_at": None,
                "action_key": content_action_key(action),
                "action": asdict(action),
                "response_id": None,
                "error": None,
            }
        )
        self._write()
        return index

    def record_skip(self, action: Action, reason: str) -> None:
        events = self._events()
        events.append(
            {
                "index": len(events),
                "status": "skipped",
                "started_at": _utc_now(),
                "finished_at": _utc_now(),
                "action_key": content_action_key(action),
                "action": asdict(action),
                "response_id": None,
                "error": None,
                "reason": reason,
            }
        )
        self._write()

    def action_succeeded(self, index: int, response_id: str | None) -> None:
        entry = self._entry(index)
        entry["status"] = "succeeded"
        entry["finished_at"] = _utc_now()
        entry["response_id"] = response_id
        self._write()

    def action_failed(self, index: int, error: BaseException | str) -> None:
        entry = self._entry(index)
        entry["status"] = "failed"
        entry["finished_at"] = _utc_now()
        entry["error"] = sanitize_text(str(error))
        self._write()

    def finish(self, result: ImportResult, report: dict[str, Any]) -> None:
        self._data["status"] = "succeeded"
        self._data["finished_at"] = _utc_now()
        self._data["result"] = result.to_dict()
        self._data["report"] = report
        self._write()

    def fail(self, error: BaseException | str, report: dict[str, Any]) -> None:
        self._data["status"] = "failed"
        self._data["finished_at"] = _utc_now()
        self._data["error"] = sanitize_text(str(error))
        self._data["report"] = report
        self._write()

    def _events(self) -> list[dict[str, Any]]:
        events = self._data.setdefault("events", [])
        if not isinstance(events, list):
            raise TypeError("content journal events must be a list")
        return events

    def _entry(self, index: int) -> dict[str, Any]:
        events = self._events()
        if index < 0 or index >= len(events):
            raise IndexError(f"content journal event index out of range: {index}")
        entry = events[index]
        if not isinstance(entry, dict):
            raise TypeError("content journal event must be an object")
        return entry

    def _write(self) -> None:
        _write_json_atomic(self.path, self._data)


def load_completed_content_actions(path: str | Path | None) -> set[str]:
    if not path:
        return set()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = data.get("schema")
    if schema == CONTENT_APPLY_JOURNAL_SCHEMA:
        events = data.get("events") or []
        return {str(event["action_key"]) for event in events if isinstance(event, dict) and event.get("status") == "succeeded" and event.get("action_key")}
    if schema == CONTENT_INCREMENTAL_STATE_SCHEMA:
        completed = data.get("completed_action_keys") or []
        return {str(item) for item in completed}
    raise ValueError(f"Unsupported content resume/incremental schema: {schema!r}")


def write_content_incremental_state(path: str | Path, *, provider: str, target_id: str | None, completed: set[str]) -> None:
    _write_json_atomic(
        Path(path),
        {
            "schema": CONTENT_INCREMENTAL_STATE_SCHEMA,
            "provider": provider,
            "target_id": target_id,
            "updated_at": _utc_now(),
            "completed_action_keys": sorted(completed),
        },
    )


def apply_content_actions(
    provider: str,
    actions: list[Action],
    options: ContentImportOptions,
    send_action: Callable[[Action], Mapping[str, Any] | str | None],
) -> ImportResult:
    result = ImportResult(provider=provider, applied=True)
    if options.parallel_sends and options.parallel_sends > 1:
        result.warnings.append("parallel_sends is accepted for planning, but live writes currently run sequentially to preserve order.")

    journal_path = options.journal_path or str(
        default_content_apply_path(provider, "journals", target_id=options.target_id or options.target_name)
    )
    dead_letter_path = options.dead_letter_path or str(
        default_content_apply_path(provider, "dead-letter", target_id=options.target_id or options.target_name)
    )
    report_path = options.report_path or str(
        default_content_apply_path(provider, "reports", target_id=options.target_id or options.target_name)
    )
    lock_path = options.lock_path or str(
        default_content_apply_path(provider, "locks", target_id=options.target_id or options.target_name)
    )

    journal = ContentApplyJournal(journal_path, provider=provider, target_id=options.target_id, target_name=options.target_name)
    completed = load_completed_content_actions(options.resume_journal)
    if options.incremental and options.incremental_state_path:
        completed.update(load_completed_content_actions(options.incremental_state_path) if Path(options.incremental_state_path).exists() else set())
    newly_completed: set[str] = set()
    skipped = 0
    failures: list[dict[str, Any]] = []
    consecutive_failures = 0
    max_failures = max(1, options.max_failures or 1)

    journal.start()
    try:
        with ContentMigrationLock(lock_path):
            for action in actions:
                action_key = content_action_key(action)
                result.actions.append(action)
                if action_key in completed:
                    skipped += 1
                    journal.record_skip(action, "already completed in resume or incremental state")
                    continue

                journal_index = journal.record_action(action)
                try:
                    response = send_action(action)
                except Exception as exc:
                    consecutive_failures += 1
                    failure = _dead_letter_entry(action, exc, action_key=action_key)
                    failures.append(failure)
                    journal.action_failed(journal_index, exc)
                    result.warnings.append(f"Content action failed for {action.path}: {sanitize_text(str(exc))}")
                    if not options.continue_on_error or consecutive_failures >= max_failures:
                        report = _content_apply_report(
                            provider=provider,
                            actions=actions,
                            applied=len(newly_completed),
                            skipped=skipped,
                            failures=failures,
                            journal_path=journal_path,
                            dead_letter_path=dead_letter_path,
                            report_path=report_path,
                            lock_path=lock_path,
                        )
                        write_content_dead_letters(dead_letter_path, provider=provider, failures=failures)
                        write_content_report(report_path, report)
                        if options.incremental_state_path:
                            write_content_incremental_state(
                                options.incremental_state_path,
                                provider=provider,
                                target_id=options.target_id,
                                completed=completed | newly_completed,
                            )
                        journal.fail(exc, report)
                        raise ValueError(
                            f"Content import stopped after {consecutive_failures} consecutive failure(s). "
                            f"Dead-letter queue: {dead_letter_path}. Report: {report_path}."
                        ) from exc
                    continue

                response_id = _response_id(response)
                source_key = _source_message_key(action)
                if response_id and source_key:
                    result.id_map[source_key] = response_id
                journal.action_succeeded(journal_index, response_id)
                newly_completed.add(action_key)
                consecutive_failures = 0
    except Exception:
        raise
    else:
        report = _content_apply_report(
            provider=provider,
            actions=actions,
            applied=len(newly_completed),
            skipped=skipped,
            failures=failures,
            journal_path=journal_path,
            dead_letter_path=dead_letter_path,
            report_path=report_path,
            lock_path=lock_path,
        )
        write_content_dead_letters(dead_letter_path, provider=provider, failures=failures)
        write_content_report(report_path, report)
        if options.incremental_state_path:
            write_content_incremental_state(
                options.incremental_state_path,
                provider=provider,
                target_id=options.target_id,
                completed=completed | newly_completed,
            )
        journal.finish(result, report)
        result.warnings.append(f"Content apply journal written to {journal_path}")
        result.warnings.append(f"Content import report written to {report_path}")
        if failures:
            result.warnings.append(f"Content dead-letter queue written to {dead_letter_path}")
        return result


def write_content_dead_letters(path: str | Path, *, provider: str, failures: list[dict[str, Any]]) -> None:
    if not failures:
        return
    _write_json_atomic(
        Path(path),
        {
            "schema": CONTENT_DEAD_LETTER_SCHEMA,
            "provider": provider,
            "created_at": _utc_now(),
            "failures": failures,
        },
    )


def write_content_report(path: str | Path, report: dict[str, Any]) -> None:
    _write_json_atomic(Path(path), report)


def _dead_letter_entry(action: Action, error: BaseException | str, *, action_key: str) -> dict[str, Any]:
    return {
        "action_key": action_key,
        "created_at": _utc_now(),
        "action": asdict(action),
        "error": sanitize_text(str(error)),
    }


def _content_apply_report(
    *,
    provider: str,
    actions: list[Action],
    applied: int,
    skipped: int,
    failures: list[dict[str, Any]],
    journal_path: str,
    dead_letter_path: str,
    report_path: str,
    lock_path: str,
) -> dict[str, Any]:
    return {
        "schema": CONTENT_IMPORT_REPORT_SCHEMA,
        "provider": provider,
        "created_at": _utc_now(),
        "action_count": len(actions),
        "applied_count": applied,
        "skipped_count": skipped,
        "failed_count": len(failures),
        "journal_path": journal_path,
        "dead_letter_path": dead_letter_path if failures else None,
        "report_path": report_path,
        "lock_path": lock_path,
        "status": "failed" if failures else "succeeded",
    }


def _response_id(response: Mapping[str, Any] | str | None) -> str | None:
    if response is None:
        return None
    if isinstance(response, str):
        return response
    for path in ("id", "_id", "message.id", "message._id"):
        current: Any = response
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return str(current)
    return None


def _source_message_key(action: Action) -> str | None:
    payload = action.payload or {}
    source_id = payload.get("source_message_id")
    if not source_id:
        return None
    part_index = payload.get("part_index")
    return f"{source_id}:{part_index}" if part_index else str(source_id)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_path_part(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "run"


def load_discord_chat_export(path: str | Path) -> ContentArchive:
    root = Path(path)
    files = sorted(root.glob("*.json")) if root.is_dir() else [root]
    if not files:
        raise ValueError(f"No DiscordChatExporter JSON files found in {root}")

    channels: dict[str, ContentChannel] = {}
    messages: list[ContentMessage] = []
    warnings: list[str] = []
    archive_name = root.stem
    guild_id: str | None = None

    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        guild = data.get("guild") or {}
        channel = data.get("channel") or {}
        if isinstance(guild, dict):
            archive_name = str(guild.get("name") or archive_name)
            if guild.get("id"):
                guild_id = str(guild.get("id"))
        raw_channel_id = str(channel.get("id") or file.stem)
        channel_id = local_id("chan", "discord", raw_channel_id)
        channels[channel_id] = ContentChannel(
            id=channel_id,
            name=normalize_channel_name(channel.get("name") or file.stem),
            type=_dce_channel_type(channel.get("type")),
            parent_id=local_id("cat", "discord", str(channel.get("categoryId"))) if channel.get("categoryId") else None,
            metadata=without_none(
                {
                    "source_file": file.name,
                    "source_channel_hash": hash_id("discord_channel", raw_channel_id),
                    "topic": channel.get("topic"),
                    "nsfw": channel.get("nsfw"),
                    "position": channel.get("position"),
                }
            ),
        )
        for raw_message in data.get("messages", []) or []:
            if not isinstance(raw_message, dict):
                continue
            messages.append(_message_from_dce(raw_message, channel_id))

    messages.sort(key=lambda message: (message.created_at or "", message.id))
    archive_emoji = _archive_custom_emoji(messages)
    archive_stickers = _archive_stickers(messages)
    if len(files) > 1:
        warnings.append(f"Merged {len(files)} DiscordChatExporter channel file(s).")
    return ContentArchive(
        name=normalize_name(archive_name, max_len=100, fallback="Discord content"),
        source=ContentSource(
            platform="discord",
            id_hash=hash_id("discord_guild", guild_id or archive_name),
            note="imported from DiscordChatExporter JSON",
        ),
        channels=list(channels.values()),
        messages=messages,
        emoji=archive_emoji,
        stickers=archive_stickers,
        features=[
            "messages",
            "message_authors",
            "message_timestamps",
            "attachments",
            "custom_emoji",
            "stickers",
            "pins",
            "replies",
            "reactions",
            "embeds",
            "polls",
            "threads",
            "forum_posts",
            "server_banner",
            "role_colors",
            "channel_permissions",
            "nsfw_channels",
            "offline_exports",
        ],
        warnings=warnings,
        metadata=without_none(
            {
                "source_format": "discord_chat_exporter",
                "server_banner_url": guild.get("bannerUrl") if isinstance(guild, dict) else None,
                "server_icon_url": guild.get("iconUrl") if isinstance(guild, dict) else None,
                "emoji_count": len(archive_emoji),
                "sticker_count": len(archive_stickers),
            }
        ),
    )


def _dce_channel_type(raw_type: Any) -> str:
    value = str(raw_type or "text").lower()
    if value in {"0", "text", "guildtextchat"}:
        return "text"
    if value in {"2", "voice", "guildvoicechat"}:
        return "voice"
    if value in {"4", "category", "guildcategory"}:
        return "category"
    if value in {"5", "announcement", "news", "guildannouncement"}:
        return "announcement"
    if value in {"11", "12", "thread", "publicthread", "privatethread", "announcementthread"}:
        return "thread"
    if value in {"13", "stage", "guildstagevoice"}:
        return "stage"
    if value in {"15", "forum", "guildforum"}:
        return "forum"
    return value if value else "unknown"


def _message_from_dce(raw: dict[str, Any], channel_id: str) -> ContentMessage:
    raw_id = str(raw.get("id") or raw.get("timestamp") or len(str(raw)))
    author = raw.get("author") or {}
    reference = raw.get("reference") or {}
    raw_content = str(raw.get("content") or "")
    custom_emoji = _custom_emoji_from_text(raw_content)
    poll_raw = raw.get("poll")
    poll = _poll_from_dce(poll_raw) if isinstance(poll_raw, dict) else None
    thread_id = _message_thread_id(raw)
    return ContentMessage(
        id=local_id("msg", "discord", raw_id),
        channel_id=channel_id,
        author=ContentAuthor(
            id_hash=hash_id("discord_user", author.get("id")) if isinstance(author, dict) and author.get("id") else None,
            display_name=normalize_name(
                (author.get("nickname") or author.get("displayName") or author.get("name") or "Unknown")
                if isinstance(author, dict)
                else "Unknown",
                max_len=100,
                fallback="Unknown",
            ),
            username=str(author.get("name")) if isinstance(author, dict) and author.get("name") else None,
            avatar_url=str(author.get("avatarUrl")) if isinstance(author, dict) and author.get("avatarUrl") else None,
            is_bot=bool(author.get("isBot")) if isinstance(author, dict) else False,
        ),
        content=raw_content,
        created_at=str(raw.get("timestamp")) if raw.get("timestamp") else None,
        edited_at=str(raw.get("timestampEdited")) if raw.get("timestampEdited") else None,
        attachments=[_attachment_from_dce(item) for item in raw.get("attachments", []) if isinstance(item, dict)],
        reactions=[_reaction_from_dce(item) for item in raw.get("reactions", []) if isinstance(item, dict)],
        embeds=[_embed_from_dce(item) for item in raw.get("embeds", []) if isinstance(item, dict)],
        stickers=[
            _sticker_from_dce(item)
            for item in (raw.get("stickers") or raw.get("stickerItems") or [])
            if isinstance(item, dict)
        ],
        poll=poll,
        pinned=bool(raw.get("isPinned")),
        reply_to_id=local_id("msg", "discord", str(reference.get("messageId"))) if isinstance(reference, dict) and reference.get("messageId") else None,
        thread_id=thread_id,
        metadata=without_none(
            {
                "source_message_hash": hash_id("discord_message", raw_id),
                "message_type": raw.get("type"),
                "custom_emoji": [emoji.to_dict() if hasattr(emoji, "to_dict") else asdict(emoji) for emoji in custom_emoji],
            }
        ),
    )


def _attachment_from_dce(raw: dict[str, Any]) -> ContentAttachment:
    raw_id = str(raw.get("id") or raw.get("url") or raw.get("fileName") or raw.get("filename") or "")
    return ContentAttachment(
        id_hash=hash_id("discord_attachment", raw_id) if raw_id else None,
        filename=raw.get("fileName") or raw.get("filename"),
        url=raw.get("url"),
        local_path=raw.get("filePath") or raw.get("path"),
        content_type=raw.get("contentType") or raw.get("content_type"),
        size=raw.get("fileSizeBytes") or raw.get("size"),
        metadata=without_none(
            {
                "width": raw.get("width"),
                "height": raw.get("height"),
                "spoiler": raw.get("isSpoiler") or raw.get("spoiler"),
            }
        ),
    )


def _reaction_from_dce(raw: dict[str, Any]) -> ContentReaction:
    emoji = raw.get("emoji") or {}
    if isinstance(emoji, dict):
        emoji_name = str(emoji.get("name") or emoji.get("code") or "?")
        metadata = without_none(
            {
                "emoji_hash": hash_id("discord_emoji", emoji.get("id")) if emoji.get("id") else None,
                "animated": emoji.get("isAnimated") or emoji.get("animated"),
            }
        )
    else:
        emoji_name = str(emoji or "?")
        metadata = {}
    return ContentReaction(emoji=emoji_name, count=int(raw.get("count") or 1), metadata=metadata)


def _sticker_from_dce(raw: dict[str, Any]) -> ContentSticker:
    raw_id = str(raw.get("id") or raw.get("name") or raw.get("url") or "")
    return ContentSticker(
        id_hash=hash_id("discord_sticker", raw_id) if raw_id else None,
        name=normalize_name(str(raw.get("name") or "sticker"), max_len=100, fallback="sticker"),
        url=raw.get("url") or raw.get("assetUrl") or raw.get("asset_url"),
        format_type=str(raw.get("formatType") or raw.get("format_type") or raw.get("type") or "") or None,
        metadata=without_none(
            {
                "description": raw.get("description"),
                "tags": raw.get("tags"),
            }
        ),
    )


def _poll_from_dce(raw: dict[str, Any]) -> ContentPoll:
    question_raw = raw.get("question") or raw.get("title") or raw.get("prompt") or ""
    question = _poll_text(question_raw) or "Poll"
    answers_raw = raw.get("answers") or raw.get("options") or raw.get("choices") or []
    answers: list[ContentPollAnswer] = []
    for item in answers_raw:
        if isinstance(item, dict):
            text = _poll_text(item.get("text") or item.get("answer") or item.get("pollMedia") or item.get("poll_media"))
            if not text:
                continue
            answers.append(
                ContentPollAnswer(
                    text=text,
                    vote_count=_safe_optional_int(item.get("count") or item.get("votes") or item.get("voteCount")),
                    metadata=without_none({"emoji": item.get("emoji")}),
                )
            )
        elif item:
            answers.append(ContentPollAnswer(text=str(item)))
    return ContentPoll(
        question=question,
        answers=answers,
        allow_multiselect=bool(raw.get("allowMultiselect") or raw.get("allow_multiselect")),
        expires_at=str(raw.get("expiry") or raw.get("expiresAt") or raw.get("expires_at") or "") or None,
        metadata=without_none({"layout_type": raw.get("layoutType") or raw.get("layout_type")}),
    )


def _poll_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("title") or "").strip()
    return str(value or "").strip()


def _safe_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _message_thread_id(raw: dict[str, Any]) -> str | None:
    thread = raw.get("thread")
    raw_thread_id = raw.get("threadId") or raw.get("thread_id")
    if isinstance(thread, dict):
        raw_thread_id = raw_thread_id or thread.get("id")
    return local_id("thread", "discord", str(raw_thread_id)) if raw_thread_id else None


def _custom_emoji_from_text(text: str) -> list[ContentEmoji]:
    found: dict[str, ContentEmoji] = {}
    for match in CUSTOM_EMOJI_RE.finditer(text):
        raw_id = match.group("id")
        key = hash_id("discord_emoji", raw_id)
        found[key] = ContentEmoji(
            id_hash=key,
            name=match.group("name"),
            animated=bool(match.group("animated")),
        )
    return list(found.values())


def _archive_custom_emoji(messages: list[ContentMessage]) -> list[ContentEmoji]:
    found: dict[str, ContentEmoji] = {}
    for message in messages:
        raw_items = message.metadata.get("custom_emoji", []) if isinstance(message.metadata, dict) else []
        for raw in raw_items:
            if isinstance(raw, dict) and raw.get("id_hash"):
                found[str(raw["id_hash"])] = ContentEmoji(**raw)
        for reaction in message.reactions:
            emoji_hash = reaction.metadata.get("emoji_hash") if reaction.metadata else None
            if emoji_hash and reaction.emoji:
                found[str(emoji_hash)] = ContentEmoji(
                    id_hash=str(emoji_hash),
                    name=reaction.emoji,
                    animated=bool(reaction.metadata.get("animated")),
                )
    return list(found.values())


def _archive_stickers(messages: list[ContentMessage]) -> list[ContentSticker]:
    found: dict[str, ContentSticker] = {}
    for message in messages:
        for sticker in message.stickers:
            key = sticker.id_hash or sticker.name
            if key:
                found[key] = sticker
    return list(found.values())


def _embed_from_dce(raw: dict[str, Any]) -> ContentEmbed:
    thumbnail = raw.get("thumbnail") or {}
    image = raw.get("image") or {}
    return ContentEmbed(
        title=raw.get("title"),
        description=raw.get("description"),
        url=raw.get("url"),
        image_url=image.get("url") if isinstance(image, dict) else None,
        thumbnail_url=thumbnail.get("url") if isinstance(thumbnail, dict) else None,
    )


def format_message_for_import(
    message: ContentMessage,
    *,
    preserve_authors: bool = True,
    include_attachments: bool = True,
    include_reactions: bool = True,
    include_embeds: bool = True,
    include_stickers: bool = True,
    include_polls: bool = True,
    include_threads: bool = True,
    include_custom_emoji: bool = True,
) -> str:
    lines: list[str] = []
    header_parts: list[str] = []
    if message.created_at:
        header_parts.append(message.created_at)
    if preserve_authors and message.author.display_name:
        header_parts.append(message.author.display_name)
    if header_parts:
        lines.append("[" + " | ".join(header_parts) + "]")
    if message.reply_to_id:
        lines.append(f"(reply to {message.reply_to_id})")
    if include_threads and message.thread_id:
        lines.append(f"(thread {message.thread_id})")
    if message.pinned:
        lines.append("(pinned)")
    if message.content.strip():
        lines.append(message.content.strip())
    if include_attachments and message.attachments:
        lines.append("Attachments:")
        for attachment in message.attachments:
            label = attachment.filename or "attachment"
            value = attachment.url or attachment.local_path or attachment.sha256 or attachment.id_hash or ""
            lines.append(f"- {label}: {value}".rstrip())
    if include_stickers and message.stickers:
        lines.append("Stickers:")
        for sticker in message.stickers:
            value = " | ".join(part for part in (sticker.name, sticker.url, sticker.format_type) if part)
            if value:
                lines.append(f"- {value}")
    if include_embeds and message.embeds:
        lines.append("Embeds:")
        for embed in message.embeds:
            text = " | ".join(part for part in (embed.title, embed.url, embed.description) if part)
            if text:
                lines.append(f"- {text}")
    if include_polls and message.poll:
        lines.append(f"Poll: {message.poll.question}")
        for answer in message.poll.answers:
            suffix = f" ({answer.vote_count} vote{'s' if answer.vote_count != 1 else ''})" if answer.vote_count is not None else ""
            lines.append(f"- {answer.text}{suffix}")
    if include_reactions and message.reactions:
        reaction_text = ", ".join(f"{reaction.emoji} x{reaction.count}" for reaction in message.reactions)
        lines.append(f"Reactions: {reaction_text}")
    if include_custom_emoji:
        emoji_items = message.metadata.get("custom_emoji", []) if isinstance(message.metadata, dict) else []
        emoji_names = [str(item.get("name")) for item in emoji_items if isinstance(item, dict) and item.get("name")]
        if emoji_names:
            lines.append("Custom emoji: " + ", ".join(sorted(set(emoji_names))))
    return "\n".join(lines).strip() or "[empty message]"


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def dry_run_content_import(
    provider: str,
    archive: ContentArchive,
    options: ContentImportOptions,
    *,
    method: str = "POST",
    path_template: str = "/content/channels/{channel_id}/messages",
    path_builder: Callable[[str, ContentMessage, int], str] | None = None,
) -> ImportResult:
    result = ImportResult(provider=provider, applied=False)
    messages = archive.messages[: options.message_limit] if options.message_limit else archive.messages
    for message in messages:
        target_channel = options.channel_map.get(message.channel_id, message.channel_id)
        text = format_message_for_import(
            message,
            preserve_authors=options.preserve_authors,
            include_attachments=options.include_attachments,
            include_reactions=options.include_reactions,
            include_embeds=options.include_embeds,
            include_stickers=options.include_stickers,
            include_polls=options.include_polls,
            include_threads=options.include_threads,
            include_custom_emoji=options.include_custom_emoji,
        )
        parts = split_message(text)
        for index, part in enumerate(parts, start=1):
            payload = {
                "channel_id": target_channel,
                "content": part,
                "source_message_id": message.id,
                "part_index": index,
                "part_count": len(parts),
                "source_channel_id": message.channel_id,
                "author": asdict(message.author),
                "created_at": message.created_at,
                "edited_at": message.edited_at,
                "attachments": [asdict(item) for item in message.attachments],
                "reactions": [asdict(item) for item in message.reactions],
                "embeds": [asdict(item) for item in message.embeds],
                "stickers": [asdict(item) for item in message.stickers],
                "poll": asdict(message.poll) if message.poll else None,
                "pinned": message.pinned,
                "reply_to_id": message.reply_to_id,
                "thread_id": message.thread_id,
                "metadata": message.metadata,
            }
            path = path_builder(target_channel, message, index) if path_builder else path_template.format(channel_id=target_channel)
            result.actions.append(Action(provider, method, path, payload))
    result.warnings.extend(archive.warnings)
    if not options.channel_map:
        result.warnings.append("No channel map was provided; dry-run uses archive channel ids as target ids.")
    if options.parallel_sends and options.parallel_sends > 1:
        result.warnings.append("parallel_sends is recorded in the plan; live writes are currently ordered and sequential.")
    return result

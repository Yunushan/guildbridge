from __future__ import annotations

import mimetypes
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from guildbridge.config import RuntimeConfig
from guildbridge.content import (
    ContentArchive,
    ContentCapability,
    ContentImportOptions,
    ContentMessage,
    apply_content_actions,
    content_text_from_action,
    dry_run_content_import,
    resolve_content_asset_path,
)
from guildbridge.http import HttpClient, HttpError, sanitize_text
from guildbridge.models import (
    Action,
    Category,
    Channel,
    CommunityTemplate,
    ImportResult,
    Role,
    TemplatePrivacy,
    TemplateSource,
)
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import (
    ExportOptions,
    ImportOptions,
    Provider,
    plan_or_apply_action,
    require_response_id,
    response_id,
)


class MatrixProvider(Provider):
    name = "matrix"
    aliases = ("element", "synapse")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        base = config.matrix_base_url or "https://matrix.org"
        self.http = HttpClient(
            base,
            token=config.matrix_access_token,
            auth_scheme="Bearer",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Matrix/Element export requires --source-id <space_or_room_id>.")
        if not self.config.matrix_access_token:
            raise ValueError("Matrix/Element export requires MATRIX_ACCESS_TOKEN or ELEMENT_ACCESS_TOKEN.")

        # Try space hierarchy first; fallback to a single room state export.
        try:
            hierarchy = self.http.get(f"/_matrix/client/v1/rooms/{self._q(options.source_id)}/hierarchy")
            rooms = hierarchy.get("rooms") or []
            return self._build_from_hierarchy(options.source_id, rooms)
        except HttpError as exc:
            state = self.http.get(f"/_matrix/client/v3/rooms/{self._q(options.source_id)}/state")
            return self._build_from_state(options.source_id, state, warning=f"Hierarchy API was unavailable ({exc.status_code}); exported a single room instead.")

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Matrix room IDs.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import can upload local files to Matrix media, send replies/reactions, and set room pinned-event state when permissions allow it."
        )
        for feature in ("attachments", "replies", "reactions", "pins"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self.config.matrix_access_token:
            raise ValueError("Matrix/Element content import requires MATRIX_ACCESS_TOKEN or ELEMENT_ACCESS_TOKEN when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Matrix/Element content import requires --channel-map for live writes so archive channel IDs map to existing room IDs."
            )
        plan = dry_run_content_import(self.name, archive, options, method="PUT", path_builder=self._content_message_path)
        if not options.apply:
            return plan
        self._prepare_native_content_state(options)
        result = apply_content_actions(self.name, plan.actions, options, self._send_content_action)
        result.warnings[:0] = plan.warnings
        result.warnings.extend(self._content_native_warnings)
        return result

    def _content_message_path(self, target_channel_id: str, message: ContentMessage, part_index: int) -> str:
        txn_id = hash_id("matrix_content_txn", f"{message.id}:{part_index}", 24)
        return f"/_matrix/client/v3/rooms/{self._q(target_channel_id)}/send/m.room.message/{txn_id}"

    def _send_content_action(self, action: Action) -> dict[str, Any] | str | None:
        if not self._content_options.uses_native_content:
            return self.http.put(action.path, json_body={"msgtype": "m.text", "body": content_text_from_action(action)})
        payload = action.payload or {}
        message_payload: dict[str, Any] = {
            "msgtype": "m.text",
            "body": content_text_from_action(action),
        }
        if self._content_options.native_replies:
            reply_id = self._mapped_reply_id(payload)
            if reply_id:
                message_payload["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_id}}
        response = self.http.put(action.path, json_body=message_payload)
        self._record_native_message_response(action, response)
        event_id = response_id(response if isinstance(response, dict) else {}, "event_id", "id")
        if event_id and int(payload.get("part_index") or 1) == 1:
            self._apply_native_followups(payload, event_id)
        return response

    def _prepare_native_content_state(self, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_native_warnings = []

    def _mapped_reply_id(self, payload: dict[str, Any]) -> str | None:
        reply_to = payload.get("reply_to_id")
        if not reply_to:
            return None
        mapped = self._content_message_ids.get(f"{reply_to}:1") or self._content_message_ids.get(str(reply_to))
        if not mapped:
            self._content_native_warnings.append(f"Native reply skipped for {reply_to!r}; referenced event was not mapped yet.")
            return None
        return mapped

    def _record_native_message_response(self, action: Action, response: object) -> None:
        if not isinstance(response, dict):
            return
        event_id = response_id(response, "event_id", "id")
        if not event_id:
            return
        payload = action.payload or {}
        source_message_id = str(payload.get("source_message_id") or "")
        if not source_message_id:
            return
        part_index = int(payload.get("part_index") or 1)
        self._content_message_ids[source_message_id] = event_id
        self._content_message_ids[f"{source_message_id}:{part_index}"] = event_id

    def _apply_native_followups(self, payload: dict[str, Any], event_id: str) -> None:
        room_id = str(payload.get("channel_id") or "")
        if not room_id:
            return
        if self._content_options.native_attachments:
            self._send_native_files(room_id, payload)
        if self._content_options.native_reactions:
            self._apply_native_reactions(room_id, event_id, payload)
        if self._content_options.native_pins and payload.get("pinned"):
            self._safe_native_followup(
                "pin",
                lambda: self.http.put(
                    f"/_matrix/client/v3/rooms/{self._q(room_id)}/state/m.room.pinned_events/",
                    json_body={"pinned": [event_id]},
                ),
            )

    def _send_native_files(self, room_id: str, payload: dict[str, Any]) -> None:
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            return
        for item in attachments[:10]:
            path = self._local_content_path(item, label="attachment")
            if not path:
                continue
            try:
                content_uri = self._upload_matrix_media(path)
            except Exception as exc:  # noqa: BLE001
                self._content_native_warnings.append(f"Native Matrix media upload failed for {path.name}: {sanitize_text(str(exc))}")
                continue
            body = str(item.get("filename") if isinstance(item, dict) and item.get("filename") else path.name)
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            msgtype = "m.image" if mime_type.startswith("image/") else "m.file"
            txn_id = hash_id("matrix_content_file_txn", f"{room_id}:{content_uri}", 24)
            self._safe_native_followup(
                "file message",
                lambda uri=content_uri, label=body, kind=msgtype, tx=txn_id: self.http.put(
                    f"/_matrix/client/v3/rooms/{self._q(room_id)}/send/m.room.message/{tx}",
                    json_body={"msgtype": kind, "body": label, "url": uri},
                ),
            )

    def _upload_matrix_media(self, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        uploaded = self.http.post_raw(
            "/_matrix/media/v3/upload",
            path.read_bytes(),
            params={"filename": path.name},
            headers={"Content-Type": mime_type},
        )
        return require_response_id(uploaded, "Matrix media upload", "content_uri", "uri", "url")

    def _local_content_path(self, item: object, *, label: str) -> Path | None:
        return resolve_content_asset_path(
            item,
            label=label,
            allow_remote_download=self._content_options.download_remote_assets,
            warnings=self._content_native_warnings,
        )

    def _apply_native_reactions(self, room_id: str, event_id: str, payload: dict[str, Any]) -> None:
        reactions = payload.get("reactions")
        if not isinstance(reactions, list):
            return
        for reaction in reactions:
            if not isinstance(reaction, dict) or not reaction.get("emoji"):
                continue
            emoji = str(reaction["emoji"])
            count = int(reaction.get("count") or 1)
            if count > 1:
                self._content_native_warnings.append(
                    f"Native reaction {emoji!r} applied once to {event_id}; original archive count was {count}."
                )
            txn_id = hash_id("matrix_reaction_txn", f"{room_id}:{event_id}:{emoji}", 24)
            self._safe_native_followup(
                "reaction",
                lambda tx=txn_id, key=emoji: self.http.put(
                    f"/_matrix/client/v3/rooms/{self._q(room_id)}/send/m.reaction/{tx}",
                    json_body={"m.relates_to": {"rel_type": "m.annotation", "event_id": event_id, "key": key}},
                ),
            )

    def _safe_native_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.matrix_access_token:
            raise ValueError("Matrix/Element import requires MATRIX_ACCESS_TOKEN or ELEMENT_ACCESS_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        server_name = self.config.matrix_server_name or self._server_name_from_base_url()
        main_space_id = options.target_id
        if not main_space_id:
            payload = {
                "name": normalize_name(options.target_name or template.name, max_len=100),
                "preset": "private_chat",
                "creation_content": {"type": "m.space"},
            }
            action = Action(self.name, "POST", "/_matrix/client/v3/createRoom", payload, note="create target Matrix space")
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/_matrix/client/v3/createRoom", json_body=payload),
            )
            if options.apply:
                main_space_id = require_response_id(created, "Matrix space create", "room_id")
            else:
                main_space_id = "!dryMainSpace:example.org"
        result.id_map["space"] = main_space_id

        category_space_map: dict[str, str] = {}
        for cat in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = {
                "name": normalize_name(cat.name, max_len=100, fallback="category"),
                "preset": "private_chat",
                "creation_content": {"type": "m.space"},
            }
            action = Action(self.name, "POST", "/_matrix/client/v3/createRoom", payload, note="create category as nested Matrix space")
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/_matrix/client/v3/createRoom", json_body=payload),
            )
            if options.apply:
                cat_space_id = require_response_id(created, "Matrix category space create", "room_id")
            else:
                cat_space_id = f"!dryCategory{len(category_space_map)}:example.org"
            category_space_map[cat.id] = cat_space_id
            self._plan_or_apply_space_link(result, main_space_id, cat_space_id, server_name, order=cat.position, options=options)

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type not in {"text", "voice", "announcement", "forum", "stage", "link"}:
                result.warnings.append(f"Skipping unsupported Matrix room source type {channel.type!r} for {channel.name!r}.")
                continue
            room_name = normalize_name(channel.name.replace("-", " "), max_len=100, fallback="room")
            payload = without_none(
                {
                    "name": room_name,
                    "topic": channel.topic,
                    "preset": "private_chat",
                    "power_level_content_override": self._power_levels_for_channel(channel),
                }
            )
            action = Action(self.name, "POST", "/_matrix/client/v3/createRoom", payload, note="create Matrix room")
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/_matrix/client/v3/createRoom", json_body=payload),
            )
            if options.apply:
                room_id = require_response_id(created, "Matrix room create", "room_id")
            else:
                room_id = f"!dryRoom{len(result.id_map)}:example.org"
            result.id_map[channel.id] = room_id
            if channel.parent_id and channel.parent_id not in category_space_map:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; linking to the main space."
                )
            parent = category_space_map.get(channel.parent_id or "") or main_space_id
            self._plan_or_apply_space_link(result, parent, room_id, server_name, order=channel.position, options=options)

        result.warnings.append("Matrix/Element has no Discord-style global server roles; GuildBridge creates rooms/spaces and applies only coarse room defaults.")
        return result

    def _build_from_hierarchy(self, source_id: str, rooms: Iterable[dict[str, Any]]) -> CommunityTemplate:
        out_channels: list[Channel] = []
        out_categories: list[Category] = []
        category_for_rooms = Category(id="cat_matrix_rooms", name="Matrix Rooms", position=0)
        out_categories.append(category_for_rooms)
        source_name = "Matrix space"
        for idx, room in enumerate(rooms or []):
            room_id = str(room.get("room_id") or idx)
            room_type = room.get("room_type")
            room_name = room.get("name")
            name = room_name or room.get("canonical_alias") or f"room-{idx}"
            if room_id == source_id or room_type == "m.space":
                if room_id == source_id and room_name:
                    source_name = str(room_name)
                continue
            out_channels.append(
                Channel(
                    id=local_id("room", self.name, room_id),
                    name=normalize_channel_name(name, max_len=100),
                    type="text",
                    position=idx,
                    parent_id=category_for_rooms.id,
                    topic=room.get("topic"),
                    metadata={"matrix_join_rule": room.get("join_rule"), "matrix_world_readable": room.get("world_readable")},
                )
            )
        return CommunityTemplate(
            name=normalize_name(source_name, max_len=100),
            source=TemplateSource(platform=self.name, id_hash=hash_id(self.name, source_id), note="exported from Matrix/Element space hierarchy"),
            privacy=TemplatePrivacy(),
            roles=[Role(id="everyone", name="@everyone", permissions=[])],
            categories=out_categories if out_channels else [],
            channels=out_channels,
            warnings=[self.supported_warning(), "Matrix message history, members, and per-user power levels were not exported."],
        )

    def _build_from_state(self, room_id: str, state: Iterable[dict[str, Any]], *, warning: str) -> CommunityTemplate:
        name = "Matrix room"
        topic = None
        for event in state or []:
            if event.get("type") == "m.room.name":
                name = event.get("content", {}).get("name") or name
            elif event.get("type") == "m.room.topic":
                topic = event.get("content", {}).get("topic")
        return CommunityTemplate(
            name=normalize_name(name, max_len=100),
            source=TemplateSource(platform=self.name, id_hash=hash_id(self.name, room_id), note="exported from Matrix/Element room state"),
            privacy=TemplatePrivacy(),
            roles=[Role(id="everyone", name="@everyone", permissions=[])],
            channels=[Channel(id=local_id("room", self.name, room_id), name=normalize_channel_name(name), type="text", topic=topic)],
            warnings=[self.supported_warning(), warning, "Matrix message history, members, and per-user power levels were not exported."],
        )

    def _plan_or_apply_space_link(
        self,
        result: ImportResult,
        parent_id: str,
        child_id: str,
        server_name: str,
        *,
        order: int | None,
        options: ImportOptions,
    ) -> None:
        order_str = f"{order:04d}" if isinstance(order, int) else None
        child_payload = without_none({"via": [server_name], "order": order_str, "suggested": True})
        parent_payload = {"via": [server_name], "canonical": True}
        child_path = f"/_matrix/client/v3/rooms/{self._q(parent_id)}/state/m.space.child/{self._q(child_id)}"
        parent_path = f"/_matrix/client/v3/rooms/{self._q(child_id)}/state/m.space.parent/{self._q(parent_id)}"
        child_action = Action(self.name, "PUT", child_path, child_payload, note="link child into parent space")
        plan_or_apply_action(options, result, child_action, partial(self.http.put, child_path, json_body=child_payload))
        parent_action = Action(self.name, "PUT", parent_path, parent_payload, note="set parent on child room")
        plan_or_apply_action(options, result, parent_action, partial(self.http.put, parent_path, json_body=parent_payload))

    @staticmethod
    def _power_levels_for_channel(channel: Channel) -> dict[str, Any]:
        # Conservative defaults: creators/admins keep state power, normal users can chat.
        # Role-specific permissions do not map cleanly to Matrix without user IDs, which
        # GuildBridge intentionally avoids storing.
        if channel.type in {"announcement", "forum", "stage"}:
            return {"events_default": 0, "state_default": 50, "invite": 50, "kick": 50, "ban": 50}
        return {"events_default": 0, "state_default": 50, "invite": 50, "kick": 50, "ban": 50}

    def _server_name_from_base_url(self) -> str:
        if self.config.matrix_base_url:
            parsed = urlparse(self.config.matrix_base_url)
            if parsed.hostname:
                return parsed.hostname
        return "matrix.org"

    @staticmethod
    def _q(value: str) -> str:
        return quote(value, safe="")

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import Any
from urllib.parse import quote, urlparse

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpClient, HttpError
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

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id


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

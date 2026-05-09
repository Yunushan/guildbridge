from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import Any

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpClient
from guildbridge.models import (
    Action,
    Channel,
    CommunityTemplate,
    ImportResult,
    Role,
    TemplatePrivacy,
    TemplateSource,
)
from guildbridge.permissions import rocket_chat_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id


class RocketChatProvider(Provider):
    name = "rocket.chat"
    aliases = ("rocketchat", "rocket-chat", "rocket")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.rocket_chat_api_base,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not self.config.rocket_chat_auth_token or not self.config.rocket_chat_user_id:
            raise ValueError("Rocket.Chat export requires ROCKET_CHAT_AUTH_TOKEN and ROCKET_CHAT_USER_ID.")
        if options.source_id:
            room_data = self.http.get("/rooms.info", params={"roomId": options.source_id}, headers=self._headers())
            rooms = [room_data.get("room", room_data)]
        else:
            rooms = self._rooms_from_response(self.http.get("/rooms.get", headers=self._headers()))
        roles = self._unwrap_list(self.http.get("/roles.list", headers=self._headers()), "roles")
        info = self.http.get("/info", headers=self._headers())
        return self._build_template(info, roles, rooms, options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and (not self.config.rocket_chat_auth_token or not self.config.rocket_chat_user_id):
            raise ValueError("Rocket.Chat import requires ROCKET_CHAT_AUTH_TOKEN and ROCKET_CHAT_USER_ID when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        result.id_map["workspace"] = options.target_id or "rocket_chat_workspace"
        headers = self._headers()

        role_map: dict[str, str] = {"everyone": "everyone"}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.id == "everyone" or role.name == "@everyone":
                continue
            role_name = normalize_channel_name(role.name, max_len=64)
            payload = {
                "name": role_name,
                "description": role.metadata.get("description") or normalize_name(role.name, max_len=120),
                "scope": "Users",
            }
            action = Action(self.name, "POST", "/roles.create", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/roles.create", json_body=payload, headers=headers),
            )
            role_map[role.id] = require_response_id(created, "Rocket.Chat role create", "role._id", "role.id", "_id", "id") if options.apply else f"dry_role_{role.id}"

        team_map: dict[str, str] = {}
        for category in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = {"name": normalize_channel_name(category.name, max_len=64), "type": 0}
            action = Action(self.name, "POST", "/teams.create", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/teams.create", json_body=payload, headers=headers),
            )
            team_map[category.id] = require_response_id(created, "Rocket.Chat team create", "team._id", "team.id", "_id", "id") if options.apply else f"dry_team_{category.id}"

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            endpoint = self._create_endpoint(channel)
            if endpoint is None:
                result.warnings.append(f"Skipping unsupported Rocket.Chat channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "name": normalize_channel_name(channel.name, max_len=64),
                    "members": [],
                    "readOnly": "send_messages" not in self._effective_neutral_permissions(channel, template.roles),
                    "extraData": without_none(
                        {
                            "topic": channel.topic,
                            "teamId": team_map.get(channel.parent_id or "") if channel.parent_id else None,
                            "broadcast": channel.type == "announcement",
                            "encrypted": bool(channel.metadata.get("encrypted", False)),
                        }
                    ),
                }
            )
            action = Action(self.name, "POST", endpoint, payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, endpoint, json_body=payload, headers=headers),
            )
            result.id_map[channel.id] = require_response_id(created, "Rocket.Chat room create", "channel._id", "channel.id", "group._id", "group.id", "room._id", "room.id", "_id", "id") if options.apply else f"dry_room_{channel.id}"
            if channel.permission_overwrites:
                result.warnings.append(
                    f"Rocket.Chat room-specific role permissions for {channel.name!r} require workspace role configuration; stored as template metadata only."
                )

        result.id_map.update(role_map)
        result.id_map.update(team_map)
        return result

    def _build_template(
        self,
        workspace: dict[str, Any],
        roles: Iterable[dict[str, Any]],
        rooms: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        out_roles = [Role(id="everyone", name="@everyone", permissions=["view_channel"])]
        for role in roles or []:
            raw_id = str(role.get("_id") or role.get("id") or role.get("name"))
            name = str(role.get("name") or role.get("description") or "role")
            if name in {"user", "anonymous"}:
                continue
            out_roles.append(
                Role(
                    id=local_id("role", self.name, raw_id),
                    name=normalize_name(name, max_len=64, fallback="role"),
                    permissions=rocket_chat_to_neutral(role.get("permissions", [])),
                    metadata=without_none({"scope": role.get("scope"), "description": role.get("description")}),
                )
            )

        channels: list[Channel] = []
        for room in rooms or []:
            room_type = self._room_type(room)
            if room_type == "unknown":
                continue
            raw_id = str(room.get("_id") or room.get("rid") or room.get("id") or room.get("name"))
            channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(room.get("name") or room.get("fname") or "room", max_len=64),
                    type=room_type,  # type: ignore[arg-type]
                    topic=room.get("topic"),
                    nsfw=bool(room.get("prid") or room.get("private", False)),
                    metadata=without_none(
                        {
                            "rocket_chat_type": room.get("t"),
                            "team_id_hash": hash_id(self.name, room.get("teamId")) if room.get("teamId") else None,
                            "read_only": room.get("ro"),
                            "broadcast": room.get("broadcast"),
                            "encrypted": room.get("encrypted"),
                        }
                    ),
                )
            )

        return CommunityTemplate(
            name=normalize_name(workspace.get("siteName") or workspace.get("name") or "Rocket.Chat workspace", max_len=100),
            description=workspace.get("description"),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, workspace.get("uniqueId") or workspace.get("siteUrl") or options.source_id or "workspace"),
                note="exported from Rocket.Chat workspace",
            ),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            channels=channels,
            warnings=[
                self.supported_warning(),
                "Rocket.Chat exports rooms/channels and workspace roles; messages, users, subscriptions, and direct messages are not exported.",
            ],
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.rocket_chat_auth_token:
            headers["X-Auth-Token"] = self.config.rocket_chat_auth_token
        if self.config.rocket_chat_user_id:
            headers["X-User-Id"] = self.config.rocket_chat_user_id
        return headers

    @staticmethod
    def _unwrap_list(value: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
        return []

    @classmethod
    def _rooms_from_response(cls, value: Any) -> list[dict[str, Any]]:
        rooms = cls._unwrap_list(value, "rooms")
        if rooms:
            return rooms
        if isinstance(value, dict):
            return [room for key in ("channels", "groups") for room in cls._unwrap_list(value, key)]
        return []

    @staticmethod
    def _room_type(room: dict[str, Any]) -> str:
        room_type = str(room.get("t") or room.get("type") or "").lower()
        if room_type in {"c", "channel", "public"}:
            return "text"
        if room_type in {"p", "private", "group"}:
            return "text"
        if room_type in {"l", "livechat"}:
            return "unknown"
        return "text" if room.get("name") else "unknown"

    @staticmethod
    def _create_endpoint(channel: Channel) -> str | None:
        if channel.type in {"text", "announcement", "forum"}:
            return "/channels.create" if not channel.nsfw else "/groups.create"
        return None

    @staticmethod
    def _effective_neutral_permissions(channel: Channel, roles: list[Role]) -> list[str]:
        permissions: list[str] = []
        for role in roles:
            for permission in role.permissions:
                if permission not in permissions:
                    permissions.append(permission)
        for overwrite in channel.permission_overwrites:
            for denied in overwrite.deny:
                if denied in permissions:
                    permissions.remove(denied)
            for allowed in overwrite.allow:
                if allowed not in permissions:
                    permissions.append(allowed)
        if not permissions:
            permissions.append("send_messages")
        return permissions

from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import Any

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpClient
from guildbridge.models import (
    Action,
    Category,
    Channel,
    CommunityTemplate,
    ImportResult,
    PermissionOverwrite,
    Role,
    TemplatePrivacy,
    TemplateSource,
)
from guildbridge.permissions import daccord_to_neutral, neutral_to_daccord
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id, safe_int

DACCORD_CHANNEL_TYPES = {
    "text": "text",
    "voice": "voice",
    "category": "category",
    "announcement": "announcement",
    "forum": "forum",
    "stage": "stage",
}
DACCORD_NUMERIC_CHANNEL_TYPES = {
    0: "text",
    2: "voice",
    4: "category",
    5: "announcement",
    13: "stage",
    15: "forum",
}


class DaccordProvider(Provider):
    name = "daccord"
    aliases = ("accord",)

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.daccord_api_base,
            token=config.daccord_token,
            auth_scheme=config.daccord_auth_scheme,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Daccord export requires --source-id <space_id>.")
        if not self.config.daccord_token:
            raise ValueError("Daccord export requires DACCORD_BOT_TOKEN or DACCORD_TOKEN.")
        space = self._unwrap_object(self.http.get(f"/spaces/{options.source_id}"))
        roles = self._unwrap_list(self.http.get(f"/spaces/{options.source_id}/roles"))
        channels = self._unwrap_list(self.http.get(f"/spaces/{options.source_id}/channels"))
        channels_with_overwrites: list[dict[str, Any]] = []
        for channel in channels:
            raw_id = channel.get("id") or channel.get("_id")
            if raw_id:
                channel = dict(channel)
                channel["permission_overwrites"] = self._unwrap_list(self.http.get(f"/channels/{raw_id}/permissions"))
            channels_with_overwrites.append(channel)
        return self._build_template(space, roles, channels_with_overwrites, options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.daccord_token:
            raise ValueError("Daccord import requires DACCORD_BOT_TOKEN or DACCORD_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        if options.target_id:
            space_id = options.target_id
        else:
            payload = without_none(
                {
                    "name": normalize_name(options.target_name or template.name, max_len=100),
                    "slug": normalize_channel_name(options.target_name or template.name, max_len=64),
                    "description": template.description,
                    "public": False,
                    "allow_guest_access": False,
                }
            )
            action = Action(self.name, "POST", "/spaces", payload)
            created = plan_or_apply_action(options, result, action, partial(self.http.post, "/spaces", json_body=payload))
            space_id = (
                require_response_id(created, "Daccord space create", "data.id", "space.id", "id", "_id")
                if options.apply
                else "dry_daccord_space"
            )
        result.id_map["space"] = space_id

        role_map: dict[str, str] = {"everyone": space_id}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.id == "everyone" or role.name == "@everyone":
                role_map[role.id] = space_id
                continue
            payload = without_none(
                {
                    "name": normalize_name(role.name, max_len=100, fallback="role"),
                    "permissions": neutral_to_daccord(role.permissions),
                    "color": role.color,
                    "hoist": bool(role.hoist),
                    "mentionable": bool(role.mentionable),
                }
            )
            action = Action(self.name, "POST", f"/spaces/{space_id}/roles", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/spaces/{space_id}/roles", json_body=payload),
            )
            role_map[role.id] = (
                require_response_id(created, "Daccord role create", "data.id", "role.id", "id", "_id")
                if options.apply
                else f"dry_role_{role.id}"
            )

        category_map: dict[str, str] = {}
        for category in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = without_none(
                {
                    "name": normalize_name(category.name, max_len=100, fallback="category"),
                    "type": "category",
                    "position": category.position,
                }
            )
            action = Action(self.name, "POST", f"/spaces/{space_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/spaces/{space_id}/channels", json_body=payload),
            )
            category_id = (
                require_response_id(created, "Daccord category create", "data.id", "channel.id", "id", "_id")
                if options.apply
                else f"dry_category_{category.id}"
            )
            category_map[category.id] = category_id
            self._plan_overwrites(options, result, category_id, category.permission_overwrites, role_map)

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            daccord_type = DACCORD_CHANNEL_TYPES.get(channel.type)
            if daccord_type is None:
                result.warnings.append(f"Skipping unsupported Daccord channel type {channel.type!r} for {channel.name!r}.")
                continue
            if channel.parent_id and channel.parent_id not in category_map:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; creating without a parent."
                )
            payload = without_none(
                {
                    "name": normalize_channel_name(channel.name, max_len=100),
                    "type": daccord_type,
                    "topic": channel.topic if channel.type in {"text", "announcement", "forum"} else None,
                    "parent_id": category_map.get(channel.parent_id or "") if channel.parent_id else None,
                    "nsfw": bool(channel.nsfw) if channel.type in {"text", "voice", "announcement", "stage", "forum"} else None,
                    "bitrate": channel.bitrate if channel.type in {"voice", "stage"} else None,
                    "user_limit": channel.user_limit if channel.type in {"voice", "stage"} else None,
                    "position": channel.position,
                }
            )
            action = Action(self.name, "POST", f"/spaces/{space_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/spaces/{space_id}/channels", json_body=payload),
            )
            channel_id = (
                require_response_id(created, "Daccord channel create", "data.id", "channel.id", "id", "_id")
                if options.apply
                else f"dry_channel_{channel.id}"
            )
            result.id_map[channel.id] = channel_id
            self._plan_overwrites(options, result, channel_id, channel.permission_overwrites, role_map)

        result.id_map.update(role_map)
        result.id_map.update(category_map)
        return result

    def _build_template(
        self,
        space: dict[str, Any],
        roles: Iterable[dict[str, Any]],
        channels: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        role_id_map: dict[str, str] = {}
        out_roles: list[Role] = []
        space_id = str(space.get("id") or space.get("_id") or options.source_id or "space")
        for role in roles or []:
            raw_id = str(role.get("id") or role.get("_id") or role.get("name"))
            name = str(role.get("name") or "role")
            if name == "@everyone" or raw_id == space_id:
                local_role_id = "everyone"
            else:
                local_role_id = local_id("role", self.name, raw_id)
            role_id_map[raw_id] = local_role_id
            out_roles.append(
                Role(
                    id=local_role_id,
                    name=normalize_name(name, max_len=100, fallback="role"),
                    permissions=daccord_to_neutral(role.get("permissions")),
                    color=role.get("color"),
                    position=role.get("position"),
                    hoist=bool(role.get("hoist", False)),
                    mentionable=bool(role.get("mentionable", False)),
                )
            )
        if "everyone" not in {role.id for role in out_roles}:
            out_roles.insert(0, Role(id="everyone", name="@everyone", permissions=[]))
            role_id_map[space_id] = "everyone"

        category_id_map: dict[str, str] = {}
        out_categories: list[Category] = []
        out_channels: list[Channel] = []
        raw_channels = list(channels or [])
        for channel in raw_channels:
            raw_id = str(channel.get("id") or channel.get("_id") or channel.get("name"))
            channel_type = self._channel_type(channel)
            if channel_type != "category":
                continue
            category_id = local_id("cat", self.name, raw_id)
            category_id_map[raw_id] = category_id
            out_categories.append(
                Category(
                    id=category_id,
                    name=normalize_name(channel.get("name") or "category", max_len=100, fallback="category"),
                    position=channel.get("position"),
                    permission_overwrites=self._overwrites_from_daccord(channel.get("permission_overwrites", []), role_id_map, options),
                )
            )

        for channel in raw_channels:
            raw_id = str(channel.get("id") or channel.get("_id") or channel.get("name"))
            channel_type = self._channel_type(channel)
            if channel_type == "category":
                continue
            parent_raw = str(channel.get("parent_id")) if channel.get("parent_id") else None
            out_channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(channel.get("name") or "channel", max_len=100),
                    type=channel_type,  # type: ignore[arg-type]
                    position=channel.get("position"),
                    parent_id=category_id_map.get(parent_raw or "") if parent_raw else None,
                    topic=channel.get("topic"),
                    nsfw=bool(channel.get("nsfw", False)),
                    bitrate=channel.get("bitrate"),
                    user_limit=channel.get("user_limit"),
                    permission_overwrites=self._overwrites_from_daccord(channel.get("permission_overwrites", []), role_id_map, options),
                )
            )

        return CommunityTemplate(
            name=normalize_name(space.get("name") or "Daccord space", max_len=100),
            description=space.get("description"),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, space.get("id") or space.get("_id") or options.source_id or space.get("name")),
                note="exported from Daccord space",
            ),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            categories=out_categories,
            channels=out_channels,
            warnings=[
                self.supported_warning(),
                "Daccord exports spaces, roles, channels, and role permission overwrites; messages, members, DMs, and member overwrites are not exported.",
            ],
        )

    def _plan_overwrites(
        self,
        options: ImportOptions,
        result: ImportResult,
        channel_id: str,
        overwrites: Iterable[PermissionOverwrite],
        role_map: dict[str, str],
    ) -> None:
        for overwrite in overwrites or []:
            target_id = role_map.get(overwrite.target_id)
            if not target_id:
                continue
            payload = {
                "type": "role",
                "allow": neutral_to_daccord(overwrite.allow),
                "deny": neutral_to_daccord(overwrite.deny),
            }
            path = f"/channels/{channel_id}/permissions/{target_id}"
            action = Action(self.name, "PUT", path, payload)
            plan_or_apply_action(options, result, action, partial(self.http.put, path, json_body=payload))

    def _overwrites_from_daccord(
        self,
        overwrites: Iterable[dict[str, Any]],
        role_id_map: dict[str, str],
        options: ExportOptions,
    ) -> list[PermissionOverwrite]:
        output: list[PermissionOverwrite] = []
        for overwrite in overwrites or []:
            target_type = str(overwrite.get("type") or overwrite.get("target_type") or "role").lower()
            raw_id = overwrite.get("id") or overwrite.get("role_id") or overwrite.get("target_id") or overwrite.get("overwrite_id")
            if not raw_id:
                continue
            if target_type in {"member", "user"}:
                continue
            raw_id_str = str(raw_id)
            output.append(
                PermissionOverwrite(
                    target_type="everyone" if role_id_map.get(raw_id_str) == "everyone" else "role",
                    target_id=role_id_map.get(raw_id_str, local_id("role", self.name, raw_id_str)),
                    allow=daccord_to_neutral(overwrite.get("allow")),
                    deny=daccord_to_neutral(overwrite.get("deny")),
                )
            )
        if options.include_user_overwrites:
            return output
        return output

    @staticmethod
    def _channel_type(channel: dict[str, Any]) -> str:
        raw_type = channel.get("type")
        if isinstance(raw_type, int) or (isinstance(raw_type, str) and raw_type.isdigit()):
            return DACCORD_NUMERIC_CHANNEL_TYPES.get(safe_int(raw_type), "unknown")
        normalized = str(raw_type or "text").lower()
        return DACCORD_CHANNEL_TYPES.get(normalized, "unknown")

    @staticmethod
    def _unwrap_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            data = value.get("data")
            if isinstance(data, dict):
                return data
            return value
        return {}

    @staticmethod
    def _unwrap_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("data", "roles", "channels", "permissions", "overwrites"):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    return [item for item in candidate if isinstance(item, dict)]
        return []

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
from guildbridge.permissions import mumble_to_neutral, neutral_to_mumble
from guildbridge.utils import hash_id, local_id, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id, safe_int


class MumbleProvider(Provider):
    name = "mumble"
    aliases = ("murmur",)

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.mumble_api_base,
            token=config.mumble_api_token,
            auth_scheme="Bearer",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Mumble export requires --source-id <server_id> for the configured Mumble admin API.")
        if not self.config.mumble_api_token:
            raise ValueError("Mumble export requires MUMBLE_API_TOKEN.")
        server = self.http.get(f"/servers/{options.source_id}")
        groups = self._unwrap_list(self.http.get(f"/servers/{options.source_id}/groups"), "groups")
        channels = self._unwrap_list(self.http.get(f"/servers/{options.source_id}/channels"), "channels")
        return self._build_template(server, groups, channels, options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.mumble_api_token:
            raise ValueError("Mumble import requires MUMBLE_API_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        server_id = options.target_id
        if not server_id:
            payload = {"name": normalize_name(options.target_name or template.name, max_len=100)}
            action = Action(self.name, "POST", "/servers", payload, note="create target Mumble server")
            created = plan_or_apply_action(options, result, action, partial(self.http.post, "/servers", json_body=payload))
            server_id = require_response_id(created, "Mumble server create", "server.id", "server._id", "id", "_id") if options.apply else "dry_mumble_server"
        result.id_map["server"] = server_id

        group_map: dict[str, str] = {"everyone": "all"}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.id == "everyone" or role.name == "@everyone":
                continue
            payload = without_none(
                {
                    "name": normalize_name(role.name, max_len=64, fallback="group"),
                    "permissions": neutral_to_mumble(role.permissions),
                    "metadata": role.metadata or None,
                }
            )
            action = Action(self.name, "POST", f"/servers/{server_id}/groups", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/servers/{server_id}/groups", json_body=payload),
            )
            group_map[role.id] = require_response_id(created, "Mumble group create", "group.id", "group._id", "id", "_id", "name") if options.apply else f"dry_group_{role.id}"

        channel_map: dict[str, str] = {}
        for category in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = without_none(
                {
                    "name": normalize_name(category.name, max_len=100, fallback="category"),
                    "position": category.position,
                    "temporary": False,
                    "acl": self._overwrites_to_mumble(category.permission_overwrites, group_map),
                }
            )
            action = Action(self.name, "POST", f"/servers/{server_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/servers/{server_id}/channels", json_body=payload),
            )
            channel_map[category.id] = require_response_id(created, "Mumble category channel create", "channel.id", "channel._id", "id", "_id") if options.apply else f"dry_channel_{category.id}"

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            if channel.type not in {"voice", "stage", "text", "unknown"}:
                result.warnings.append(f"Skipping unsupported Mumble channel type {channel.type!r} for {channel.name!r}.")
                continue
            if channel.type == "text":
                result.warnings.append(f"Mumble has no persistent text-room equivalent; creating {channel.name!r} as a voice channel.")
            payload = without_none(
                {
                    "name": normalize_name(channel.name, max_len=100, fallback="channel"),
                    "parent_id": channel_map.get(channel.parent_id or "") if channel.parent_id else None,
                    "position": channel.position,
                    "description": channel.topic,
                    "max_users": channel.user_limit,
                    "acl": self._overwrites_to_mumble(channel.permission_overwrites, group_map),
                }
            )
            action = Action(self.name, "POST", f"/servers/{server_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/servers/{server_id}/channels", json_body=payload),
            )
            channel_map[channel.id] = require_response_id(created, "Mumble channel create", "channel.id", "channel._id", "id", "_id") if options.apply else f"dry_channel_{channel.id}"

        result.id_map.update(group_map)
        result.id_map.update(channel_map)
        return result

    def _build_template(
        self,
        server: dict[str, Any],
        groups: Iterable[dict[str, Any]],
        channels: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        group_id_map: dict[str, str] = {"all": "everyone", "everyone": "everyone"}
        roles = [Role(id="everyone", name="@everyone", permissions=["view_channel", "connect", "speak"])]
        for group in groups or []:
            raw_id = str(group.get("id") or group.get("_id") or group.get("name"))
            name = normalize_name(group.get("name") or raw_id, max_len=64, fallback="group")
            if name.lower() in {"all", "everyone"}:
                continue
            lid = local_id("role", self.name, raw_id)
            group_id_map[raw_id] = lid
            group_id_map[name] = lid
            roles.append(
                Role(
                    id=lid,
                    name=name,
                    permissions=mumble_to_neutral(group.get("permissions", [])),
                    metadata=without_none({"inherited": group.get("inherited"), "inheritable": group.get("inheritable")}),
                )
            )

        channel_id_map: dict[str, str] = {}
        categories: list[Category] = []
        out_channels: list[Channel] = []
        raw_channels = list(channels or [])
        for channel in raw_channels:
            raw_id = str(channel.get("id") or channel.get("_id") or channel.get("name"))
            lid = local_id("chan", self.name, raw_id)
            channel_id_map[raw_id] = lid
            if channel.get("is_category") or channel.get("type") == "category":
                categories.append(
                    Category(
                        id=lid,
                        name=normalize_name(channel.get("name") or "category", max_len=100, fallback="category"),
                        position=safe_int(channel.get("position"), 0),
                        permission_overwrites=self._overwrites_from_mumble(channel.get("acl", []), group_id_map),
                    )
                )

        for channel in raw_channels:
            if channel.get("is_category") or channel.get("type") == "category":
                continue
            raw_id = str(channel.get("id") or channel.get("_id") or channel.get("name"))
            parent_raw = str(channel.get("parent_id") or channel.get("parent")) if channel.get("parent_id") or channel.get("parent") else None
            out_channels.append(
                Channel(
                    id=channel_id_map.get(raw_id, local_id("chan", self.name, raw_id)),
                    name=normalize_name(channel.get("name") or "channel", max_len=100, fallback="channel"),
                    type="voice",
                    position=safe_int(channel.get("position"), 0),
                    parent_id=channel_id_map.get(parent_raw or "") if parent_raw else None,
                    topic=channel.get("description") or channel.get("comment"),
                    user_limit=channel.get("max_users") or channel.get("user_limit"),
                    permission_overwrites=self._overwrites_from_mumble(channel.get("acl", []), group_id_map),
                    metadata=without_none({"temporary": channel.get("temporary"), "codec": channel.get("codec")}),
                )
            )

        return CommunityTemplate(
            name=normalize_name(server.get("name") or "Mumble server", max_len=100),
            description=server.get("description") or server.get("welcome_text"),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, server.get("id") or server.get("_id") or options.source_id),
                note="exported from Mumble/Murmur through configured admin API",
            ),
            privacy=TemplatePrivacy(),
            roles=roles,
            categories=categories,
            channels=out_channels,
            warnings=[
                self.supported_warning(),
                "Mumble support requires a configured Mumble/Murmur admin API bridge; the voice protocol itself is not an HTTP management API.",
                "Mumble messages, users, registrations, certificates, and live state are not exported.",
            ],
        )

    @staticmethod
    def _unwrap_list(value: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                return [dict(v, id=k) if isinstance(v, dict) else {"id": k, "value": v} for k, v in candidate.items()]
        return []

    def _overwrites_from_mumble(self, acl: Iterable[dict[str, Any]], group_id_map: dict[str, str]) -> list[PermissionOverwrite]:
        output: list[PermissionOverwrite] = []
        for entry in acl or []:
            group_raw = str(entry.get("group") or entry.get("group_id") or "all")
            target_id = group_id_map.get(group_raw) or group_id_map.get(group_raw.lower())
            if not target_id:
                target_id = local_id("role", self.name, group_raw)
            output.append(
                PermissionOverwrite(
                    target_type="everyone" if target_id == "everyone" else "role",
                    target_id=target_id,
                    allow=mumble_to_neutral(entry.get("allow", [])),
                    deny=mumble_to_neutral(entry.get("deny", [])),
                )
            )
        return output

    @staticmethod
    def _overwrites_to_mumble(overwrites: Iterable[PermissionOverwrite], group_map: dict[str, str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for overwrite in overwrites:
            group = "all" if overwrite.target_type == "everyone" else group_map.get(overwrite.target_id)
            if not group:
                continue
            output.append(
                {
                    "group": group,
                    "allow": neutral_to_mumble(overwrite.allow),
                    "deny": neutral_to_mumble(overwrite.deny),
                }
            )
        return output

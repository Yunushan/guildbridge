from __future__ import annotations

import re
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
from guildbridge.permissions import discord_to_neutral, neutral_to_discord
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id, safe_int

DISCORD_CHANNEL_TYPES = {
    0: "text",
    2: "voice",
    4: "category",
    5: "announcement",
    13: "stage",
    15: "forum",
    16: "space",  # unofficial/placeholder for compatibility; Discord may not return this.
}
NEUTRAL_TO_DISCORD_CHANNEL_TYPES = {
    "text": 0,
    "voice": 2,
    "category": 4,
    "announcement": 5,
    "stage": 13,
    "forum": 15,
}


class DiscordProvider(Provider):
    name = "discord"
    aliases = ("disc",)

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.discord_api_base,
            token=config.discord_token,
            auth_scheme="Bot",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if options.template:
            return self._export_from_template(options.template, options)
        if not options.source_id:
            raise ValueError("Discord export requires --source-id <guild_id> or --template <template_url_or_code>.")
        if not self.config.discord_token:
            raise ValueError("Discord live guild export requires DISCORD_BOT_TOKEN or DISCORD_TOKEN.")
        guild = self.http.get(f"/guilds/{options.source_id}")
        roles = self.http.get(f"/guilds/{options.source_id}/roles")
        channels = self.http.get(f"/guilds/{options.source_id}/channels")
        return self._build_template(guild, roles, channels, source_note="exported from live Discord guild", options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if not options.target_id:
            raise ValueError("Discord import requires --target-id <existing_guild_id>. GuildBridge imports into an existing guild.")
        if options.apply and not self.config.discord_token:
            raise ValueError("Discord import requires DISCORD_BOT_TOKEN or DISCORD_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        role_map: dict[str, str] = {"everyone": options.target_id}
        headers = {"X-Audit-Log-Reason": options.audit_log_reason} if options.audit_log_reason else None

        # Create roles from low to high-ish position. Discord's @everyone role is represented by the guild id.
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.name == "@everyone" or role.id == "everyone":
                role_map[role.id] = options.target_id
                continue
            payload = without_none(
                {
                    "name": normalize_name(role.name, max_len=100, fallback="role"),
                    "permissions": str(neutral_to_discord(role.permissions)),
                    "color": role.color if isinstance(role.color, int) else None,
                    "hoist": bool(role.hoist),
                    "mentionable": bool(role.mentionable),
                }
            )
            action = Action(self.name, "POST", f"/guilds/{options.target_id}/roles", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/guilds/{options.target_id}/roles", json_body=payload, headers=headers),
            )
            if options.apply:
                role_map[role.id] = require_response_id(created, "Discord role create", "id")
            else:
                role_map[role.id] = f"dry_role_{role.id}"

        category_map: dict[str, str] = {}
        for cat in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = without_none(
                {
                    "name": normalize_name(cat.name, max_len=100, fallback="category"),
                    "type": 4,
                    "position": cat.position,
                    "permission_overwrites": self._overwrites_to_discord(cat.permission_overwrites, role_map),
                }
            )
            action = Action(self.name, "POST", f"/guilds/{options.target_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/guilds/{options.target_id}/channels", json_body=payload, headers=headers),
            )
            if options.apply:
                category_map[cat.id] = require_response_id(created, "Discord category create", "id")
            else:
                category_map[cat.id] = f"dry_category_{cat.id}"

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            discord_type = NEUTRAL_TO_DISCORD_CHANNEL_TYPES.get(channel.type)
            if discord_type is None:
                result.warnings.append(f"Skipping unsupported Discord channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "name": normalize_channel_name(channel.name, max_len=100),
                    "type": discord_type,
                    "topic": channel.topic if channel.type in {"text", "announcement", "forum"} else None,
                    "position": channel.position,
                    "parent_id": category_map.get(channel.parent_id or "") if channel.parent_id else None,
                    "nsfw": bool(channel.nsfw) if channel.type in {"text", "voice", "announcement", "stage", "forum"} else None,
                    "bitrate": channel.bitrate if channel.type in {"voice", "stage"} else None,
                    "user_limit": channel.user_limit if channel.type in {"voice", "stage"} else None,
                    "permission_overwrites": self._overwrites_to_discord(channel.permission_overwrites, role_map),
                }
            )
            if channel.parent_id and channel.parent_id not in category_map:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; creating without a parent."
                )
            action = Action(self.name, "POST", f"/guilds/{options.target_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/guilds/{options.target_id}/channels", json_body=payload, headers=headers),
            )
            if options.apply:
                result.id_map[channel.id] = require_response_id(created, "Discord channel create", "id")
            else:
                result.id_map[channel.id] = f"dry_channel_{channel.id}"

        result.id_map.update(role_map)
        result.id_map.update(category_map)
        return result

    def _export_from_template(self, template_code_or_url: str, options: ExportOptions) -> CommunityTemplate:
        code = self._extract_template_code(template_code_or_url)
        data = self.http.get(f"/guilds/templates/{code}")
        guild = data.get("serialized_source_guild") or data.get("source_guild") or data
        guild.setdefault("name", data.get("name") or guild.get("name") or "Discord Template")
        guild.setdefault("description", data.get("description") or guild.get("description"))
        roles = guild.get("roles", [])
        channels = guild.get("channels", [])
        template = self._build_template(guild, roles, channels, source_note="exported from Discord server template", options=options)
        template.warnings.append("Discord server templates may omit some community channel types and runtime-only configuration.")
        return template

    def _build_template(
        self,
        guild: dict[str, Any],
        roles: Iterable[dict[str, Any]],
        channels: Iterable[dict[str, Any]],
        *,
        source_note: str,
        options: ExportOptions,
    ) -> CommunityTemplate:
        role_id_map: dict[str, str] = {}
        out_roles: list[Role] = []
        for role in roles or []:
            raw_id = str(role.get("id") or role.get("_id") or role.get("name"))
            if role.get("name") == "@everyone" or raw_id == str(guild.get("id")):
                lid = "everyone"
            else:
                lid = local_id("role", self.name, raw_id)
            role_id_map[raw_id] = lid
            out_roles.append(
                Role(
                    id=lid,
                    name=normalize_name(role.get("name") or "role", max_len=100, fallback="role"),
                    permissions=discord_to_neutral(role.get("permissions")),
                    color=role.get("color"),
                    position=role.get("position"),
                    hoist=bool(role.get("hoist", False)),
                    mentionable=bool(role.get("mentionable", False)),
                )
            )

        # Ensure everyone is present because overwrites need a neutral target.
        if "everyone" not in {r.id for r in out_roles}:
            out_roles.insert(0, Role(id="everyone", name="@everyone", permissions=[]))
            role_id_map[str(guild.get("id"))] = "everyone"

        category_id_map: dict[str, str] = {}
        out_categories: list[Category] = []
        out_channels: list[Channel] = []
        raw_channels = list(channels or [])

        for ch in raw_channels:
            ch_type = DISCORD_CHANNEL_TYPES.get(safe_int(ch.get("type"), -1), "unknown")
            raw_id = str(ch.get("id") or ch.get("name"))
            if ch_type == "category":
                lid = local_id("cat", self.name, raw_id)
                category_id_map[raw_id] = lid
                out_categories.append(
                    Category(
                        id=lid,
                        name=normalize_name(ch.get("name") or "category", max_len=100, fallback="category"),
                        position=ch.get("position"),
                        permission_overwrites=self._overwrites_from_discord(ch.get("permission_overwrites", []), role_id_map, options),
                    )
                )

        for ch in raw_channels:
            ch_type = DISCORD_CHANNEL_TYPES.get(safe_int(ch.get("type"), -1), "unknown")
            if ch_type == "category":
                continue
            raw_id = str(ch.get("id") or ch.get("name"))
            parent_raw = str(ch.get("parent_id")) if ch.get("parent_id") else None
            out_channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(ch.get("name") or "channel", max_len=100),
                    type=ch_type,  # type: ignore[arg-type]
                    position=ch.get("position"),
                    parent_id=category_id_map.get(parent_raw or "") if parent_raw else None,
                    topic=ch.get("topic"),
                    nsfw=bool(ch.get("nsfw", False)),
                    bitrate=ch.get("bitrate"),
                    user_limit=ch.get("user_limit"),
                    permission_overwrites=self._overwrites_from_discord(ch.get("permission_overwrites", []), role_id_map, options),
                )
            )

        template = CommunityTemplate(
            name=normalize_name(guild.get("name") or "Discord community", max_len=100, fallback="Discord community"),
            description=guild.get("description"),
            source=TemplateSource(platform=self.name, id_hash=hash_id(self.name, guild.get("id") or guild.get("name")), note=source_note),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            categories=out_categories,
            channels=out_channels,
            warnings=[self.supported_warning()],
        )
        if options.include_user_overwrites:
            template.warnings.append("User/member-specific permission overwrites cannot be represented safely and were dropped.")
        else:
            template.warnings.append("User/member-specific permission overwrites were dropped for privacy.")
        return template

    def _overwrites_from_discord(
        self,
        overwrites: Iterable[dict[str, Any]],
        role_id_map: dict[str, str],
        options: ExportOptions,
    ) -> list[PermissionOverwrite]:
        output: list[PermissionOverwrite] = []
        for ow in overwrites or []:
            raw_type = ow.get("type")
            ow_type = safe_int(raw_type)
            raw_value = ow.get("id")
            if raw_value in {None, ""}:
                continue
            raw_id = str(raw_value)
            if ow_type == 1 or str(raw_type).lower() in {"member", "user"}:
                continue
            output.append(
                PermissionOverwrite(
                    target_type="everyone" if role_id_map.get(raw_id) == "everyone" else "role",
                    target_id=role_id_map.get(raw_id, local_id("role", self.name, raw_id)),
                    allow=discord_to_neutral(ow.get("allow")),
                    deny=discord_to_neutral(ow.get("deny")),
                )
            )
        return output

    def _overwrites_to_discord(self, overwrites: Iterable[PermissionOverwrite], role_map: dict[str, str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for ow in overwrites or []:
            target_id = role_map.get(ow.target_id)
            if not target_id:
                continue
            output.append(
                {
                    "id": target_id,
                    "type": 0,
                    "allow": str(neutral_to_discord(ow.allow)),
                    "deny": str(neutral_to_discord(ow.deny)),
                }
            )
        return output

    @staticmethod
    def _extract_template_code(value: str) -> str:
        value = value.strip()
        match = re.search(r"discord(?:\.new|\.com/template|\.gg)/(?:template/)?([A-Za-z0-9_-]+)", value)
        if match:
            return match.group(1)
        return value.rsplit("/", 1)[-1]

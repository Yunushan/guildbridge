from __future__ import annotations

import json
from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

from guildbridge.config import RuntimeConfig
from guildbridge.content import (
    ContentArchive,
    ContentCapability,
    ContentImportOptions,
    apply_content_actions,
    content_text_from_action,
    dry_run_content_import,
    resolve_content_asset_path,
)
from guildbridge.http import HttpClient, sanitize_text
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
from guildbridge.permissions import fluxer_to_neutral, neutral_to_fluxer
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import (
    ExportOptions,
    ImportOptions,
    Provider,
    plan_or_apply_action,
    require_response_id,
    response_id,
    safe_int,
)

FLUXER_CHANNEL_TYPES = {
    0: "text",
    2: "voice",
    3: "unknown",  # group DM - intentionally not exported as community structure
    4: "category",
    998: "link",
}
NEUTRAL_TO_FLUXER_CHANNEL_TYPES = {
    "text": 0,
    "voice": 2,
    "category": 4,
    "link": 998,
}


class FluxerProvider(Provider):
    name = "fluxer"
    aliases = ("flux",)

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.fluxer_api_base,
            token=config.fluxer_token,
            auth_scheme="Bot",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Fluxer export requires --source-id <guild_id>.")
        if not self.config.fluxer_token:
            raise ValueError("Fluxer export requires FLUXER_BOT_TOKEN or FLUXER_TOKEN.")
        guild = self.http.get(f"/guilds/{options.source_id}")
        roles = self._unwrap_list(self.http.get(f"/guilds/{options.source_id}/roles"), "roles")
        channels = self._unwrap_list(self.http.get(f"/guilds/{options.source_id}/channels"), "channels")
        return self._build_template(guild, roles, channels, options=options)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Fluxer channel IDs.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import uses Discord-compatible message routes for local attachments, embeds, replies, pins, and reactions when the Fluxer API supports them."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self.config.fluxer_token:
            raise ValueError("Fluxer content import requires FLUXER_BOT_TOKEN or FLUXER_TOKEN when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Fluxer content import requires --channel-map for live writes so archive channel IDs map to existing Fluxer channel IDs."
            )
        plan = dry_run_content_import(self.name, archive, options, path_template="/channels/{channel_id}/messages")
        if not options.apply:
            return plan
        self._prepare_native_content_state(options)
        result = apply_content_actions(self.name, plan.actions, options, self._send_content_action)
        result.warnings[:0] = plan.warnings
        result.warnings.extend(self._content_native_warnings)
        return result

    def _send_content_action(self, action: Action) -> dict[str, Any] | str | None:
        if not self._content_options.uses_native_content:
            return self.http.post(action.path, json_body={"content": content_text_from_action(action)})
        payload = self._native_message_payload(action)
        files = self._native_file_paths(action.payload or {})
        if files:
            payload["attachments"] = [{"id": index, "filename": path.name} for index, path in enumerate(files)]
            response = self.http.post_files(
                action.path,
                file_paths=files,
                field_prefix="files",
                form_body={"payload_json": json.dumps(payload, ensure_ascii=False)},
                indexed_fields=True,
            )
        else:
            response = self.http.post(action.path, json_body=payload)
        self._record_native_message_response(action, response)
        message_id = response_id(response if isinstance(response, dict) else {}, "id", "message.id")
        payload_data = action.payload or {}
        if message_id and int(payload_data.get("part_index") or 1) == 1:
            self._apply_native_followups(payload_data, message_id)
        return response

    def _prepare_native_content_state(self, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_native_warnings = []

    def _native_message_payload(self, action: Action) -> dict[str, Any]:
        payload_data = action.payload or {}
        payload: dict[str, Any] = {"content": content_text_from_action(action), "allowed_mentions": {"parse": []}}
        if int(payload_data.get("part_index") or 1) != 1:
            return payload
        if self._content_options.native_embeds:
            embeds = self._native_embeds(payload_data)
            if embeds:
                payload["embeds"] = embeds
        if self._content_options.native_replies:
            reply_id = self._mapped_reply_id(payload_data)
            if reply_id:
                payload["message_reference"] = {"message_id": reply_id, "fail_if_not_exists": False}
        return payload

    def _native_embeds(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_embeds = payload.get("embeds")
        if not isinstance(raw_embeds, list):
            return []
        embeds: list[dict[str, Any]] = []
        for raw in raw_embeds[:10]:
            if isinstance(raw, dict):
                embed = without_none(
                    {
                        "title": raw.get("title"),
                        "description": raw.get("description"),
                        "url": raw.get("url"),
                        "thumbnail": {"url": raw.get("thumbnail_url")} if raw.get("thumbnail_url") else None,
                        "image": {"url": raw.get("image_url")} if raw.get("image_url") else None,
                    }
                )
                if embed:
                    embeds.append(embed)
        return embeds

    def _native_file_paths(self, payload: dict[str, Any]) -> list[Path]:
        if not self._content_options.native_attachments:
            return []
        files: list[Path] = []
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            for item in attachments[:10]:
                path = self._local_content_path(item, label="attachment")
                if path:
                    files.append(path)
        return files

    def _local_content_path(self, item: object, *, label: str) -> Path | None:
        return resolve_content_asset_path(
            item,
            label=label,
            allow_remote_download=self._content_options.download_remote_assets,
            warnings=self._content_native_warnings,
        )

    def _mapped_reply_id(self, payload: dict[str, Any]) -> str | None:
        reply_to = payload.get("reply_to_id")
        if not reply_to:
            return None
        mapped = self._content_message_ids.get(f"{reply_to}:1") or self._content_message_ids.get(str(reply_to))
        if not mapped:
            self._content_native_warnings.append(f"Native reply skipped for {reply_to!r}; referenced message was not mapped yet.")
            return None
        return mapped

    def _record_native_message_response(self, action: Action, response: object) -> None:
        if not isinstance(response, dict):
            return
        message_id = response_id(response, "id", "message.id")
        if not message_id:
            return
        payload = action.payload or {}
        source_message_id = str(payload.get("source_message_id") or "")
        if not source_message_id:
            return
        part_index = int(payload.get("part_index") or 1)
        self._content_message_ids[source_message_id] = message_id
        self._content_message_ids[f"{source_message_id}:{part_index}"] = message_id

    def _apply_native_followups(self, payload: dict[str, Any], message_id: str) -> None:
        channel_id = str(payload.get("channel_id") or "")
        if not channel_id:
            return
        if self._content_options.native_pins and payload.get("pinned"):
            self._safe_native_followup("pin", lambda: self.http.put(f"/channels/{channel_id}/messages/pins/{message_id}"))
        if self._content_options.native_reactions:
            self._apply_native_reactions(channel_id, message_id, payload)

    def _apply_native_reactions(self, channel_id: str, message_id: str, payload: dict[str, Any]) -> None:
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
                    f"Native reaction {emoji!r} applied once to {message_id}; original archive count was {count}."
                )
            encoded_emoji = quote(emoji, safe="")
            self._safe_native_followup(
                "reaction",
                lambda encoded=encoded_emoji: self.http.put(
                    f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me"
                ),
            )

    def _safe_native_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.fluxer_token:
            raise ValueError("Fluxer import requires FLUXER_BOT_TOKEN or FLUXER_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        guild_id = options.target_id
        if not guild_id:
            payload = {"name": normalize_name(options.target_name or template.name, max_len=100), "empty_features": True}
            action = Action(self.name, "POST", "/guilds", payload, note="create target Fluxer guild")
            created = plan_or_apply_action(options, result, action, lambda: self.http.post("/guilds", json_body=payload))
            if options.apply:
                guild_id = require_response_id(created, "Fluxer guild create", "id", "guild.id", "guild._id")
            else:
                guild_id = "dry_fluxer_guild"
        result.id_map["guild"] = guild_id

        role_map: dict[str, str] = {"everyone": guild_id}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.name == "@everyone" or role.id == "everyone":
                role_map[role.id] = guild_id
                continue
            payload = without_none(
                {
                    "name": normalize_name(role.name, max_len=100, fallback="role"),
                    "permissions": neutral_to_fluxer(role.permissions),
                    "color": role.color if isinstance(role.color, int) else None,
                    "hoist": bool(role.hoist),
                    "mentionable": bool(role.mentionable),
                }
            )
            action = Action(self.name, "POST", f"/guilds/{guild_id}/roles", payload)
            created = plan_or_apply_action(options, result, action, partial(self.http.post, f"/guilds/{guild_id}/roles", json_body=payload))
            if options.apply:
                role_map[role.id] = require_response_id(created, "Fluxer role create", "id", "role.id", "role._id", "role_id")
            else:
                role_map[role.id] = f"dry_role_{role.id}"

        category_map: dict[str, str] = {}
        for cat in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = without_none(
                {
                    "name": normalize_name(cat.name, max_len=100, fallback="category"),
                    "type": 4,
                    "permission_overwrites": self._overwrites_to_fluxer(cat.permission_overwrites, role_map),
                }
            )
            action = Action(self.name, "POST", f"/guilds/{guild_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/guilds/{guild_id}/channels", json_body=payload),
            )
            if options.apply:
                category_map[cat.id] = require_response_id(created, "Fluxer category create", "id", "channel.id", "channel._id", "channel_id")
            else:
                category_map[cat.id] = f"dry_category_{cat.id}"

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            ftype = NEUTRAL_TO_FLUXER_CHANNEL_TYPES.get(channel.type)
            if ftype is None or channel.type == "category":
                result.warnings.append(f"Skipping unsupported Fluxer channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "name": normalize_channel_name(channel.name, max_len=100),
                    "type": ftype,
                    "topic": channel.topic,
                    "parent_id": category_map.get(channel.parent_id or "") if channel.parent_id else None,
                    "nsfw": bool(channel.nsfw),
                    "bitrate": channel.bitrate if channel.type == "voice" else None,
                    "user_limit": channel.user_limit if channel.type == "voice" else None,
                    "permission_overwrites": self._overwrites_to_fluxer(channel.permission_overwrites, role_map),
                }
            )
            if channel.parent_id and channel.parent_id not in category_map:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; creating without a parent."
                )
            action = Action(self.name, "POST", f"/guilds/{guild_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/guilds/{guild_id}/channels", json_body=payload),
            )
            if options.apply:
                result.id_map[channel.id] = require_response_id(created, "Fluxer channel create", "id", "channel.id", "channel._id", "channel_id")
            else:
                result.id_map[channel.id] = f"dry_channel_{channel.id}"

        result.id_map.update(role_map)
        result.id_map.update(category_map)
        return result

    def _build_template(self, guild: dict[str, Any], roles: Iterable[dict[str, Any]], channels: Iterable[dict[str, Any]], *, options: ExportOptions) -> CommunityTemplate:
        role_id_map: dict[str, str] = {}
        out_roles: list[Role] = []
        guild_id = str(guild.get("id") or guild.get("guild_id") or options.source_id)
        for role in roles or []:
            raw_id = str(role.get("id") or role.get("role_id") or role.get("name"))
            lid = "everyone" if role.get("name") == "@everyone" or raw_id == guild_id else local_id("role", self.name, raw_id)
            role_id_map[raw_id] = lid
            out_roles.append(
                Role(
                    id=lid,
                    name=normalize_name(role.get("name") or "role", max_len=100, fallback="role"),
                    permissions=fluxer_to_neutral(role.get("permissions")),
                    color=role.get("color"),
                    position=role.get("position"),
                    hoist=bool(role.get("hoist", False)),
                    mentionable=bool(role.get("mentionable", False)),
                )
            )
        if "everyone" not in {r.id for r in out_roles}:
            out_roles.insert(0, Role(id="everyone", name="@everyone", permissions=[]))
            role_id_map[guild_id] = "everyone"

        category_id_map: dict[str, str] = {}
        out_categories: list[Category] = []
        out_channels: list[Channel] = []
        raw_channels = list(channels or [])
        for ch in raw_channels:
            ctype = FLUXER_CHANNEL_TYPES.get(safe_int(ch.get("type"), -1), "unknown")
            raw_id = str(ch.get("id") or ch.get("channel_id") or ch.get("name"))
            if ctype == "category":
                lid = local_id("cat", self.name, raw_id)
                category_id_map[raw_id] = lid
                out_categories.append(
                    Category(
                        id=lid,
                        name=normalize_name(ch.get("name") or "category", max_len=100, fallback="category"),
                        position=ch.get("position"),
                        permission_overwrites=self._overwrites_from_fluxer(ch.get("permission_overwrites", []), role_id_map, options),
                    )
                )
        for ch in raw_channels:
            ctype = FLUXER_CHANNEL_TYPES.get(safe_int(ch.get("type"), -1), "unknown")
            if ctype in {"category", "unknown"}:
                continue
            raw_id = str(ch.get("id") or ch.get("channel_id") or ch.get("name"))
            parent_raw = str(ch.get("parent_id")) if ch.get("parent_id") else None
            out_channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(ch.get("name") or "channel", max_len=100),
                    type=ctype,  # type: ignore[arg-type]
                    position=ch.get("position"),
                    parent_id=category_id_map.get(parent_raw or "") if parent_raw else None,
                    topic=ch.get("topic"),
                    nsfw=bool(ch.get("nsfw", False)),
                    bitrate=ch.get("bitrate"),
                    user_limit=ch.get("user_limit"),
                    permission_overwrites=self._overwrites_from_fluxer(ch.get("permission_overwrites", []), role_id_map, options),
                )
            )
        warnings = [self.supported_warning(), "Fluxer DM/group-DM channels are not exported as server structure."]
        if options.include_user_overwrites:
            warnings.append("User/member-specific permission overwrites cannot be represented safely and were dropped.")
        else:
            warnings.append("User/member-specific permission overwrites were dropped for privacy.")
        return CommunityTemplate(
            name=normalize_name(guild.get("name") or "Fluxer community", max_len=100),
            description=guild.get("description"),
            source=TemplateSource(platform=self.name, id_hash=hash_id(self.name, guild_id), note="exported from Fluxer guild"),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            categories=out_categories,
            channels=out_channels,
            warnings=warnings,
        )

    def _overwrites_from_fluxer(self, overwrites: Iterable[dict[str, Any]], role_id_map: dict[str, str], options: ExportOptions) -> list[PermissionOverwrite]:
        output: list[PermissionOverwrite] = []
        for ow in overwrites or []:
            raw_type = ow.get("type")
            ow_type = safe_int(raw_type)
            raw_value = ow.get("id") or ow.get("role_id") or ow.get("target_id")
            if raw_value in {None, ""}:
                continue
            raw_id = str(raw_value)
            if ow_type == 1 or str(raw_type).lower() in {"member", "user"}:
                continue
            output.append(
                PermissionOverwrite(
                    target_type="everyone" if role_id_map.get(raw_id) == "everyone" else "role",
                    target_id=role_id_map.get(raw_id, local_id("role", self.name, raw_id)),
                    allow=fluxer_to_neutral(ow.get("allow")),
                    deny=fluxer_to_neutral(ow.get("deny")),
                )
            )
        return output

    def _overwrites_to_fluxer(self, overwrites: Iterable[PermissionOverwrite], role_map: dict[str, str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for ow in overwrites or []:
            target_id = role_map.get(ow.target_id)
            if not target_id:
                continue
            output.append({"id": target_id, "type": 0, "allow": neutral_to_fluxer(ow.allow), "deny": neutral_to_fluxer(ow.deny)})
        return output

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

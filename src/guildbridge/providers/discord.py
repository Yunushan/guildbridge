from __future__ import annotations

import base64
import json
import mimetypes
import re
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
    metadata_first,
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
from guildbridge.permissions import discord_to_neutral, neutral_to_discord
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
DISCORD_SUPPRESS_NOTIFICATIONS = 1 << 12
DISCORD_EMOJI_SIZE_LIMIT = 256 * 1024
DISCORD_SERVER_ASSET_SIZE_LIMIT = 10 * 1024 * 1024


class DiscordProvider(Provider):
    name = "discord"
    aliases: tuple[str, ...] = ("disc",)
    provider_label = "Discord"
    token_env_hint = "DISCORD_BOT_TOKEN or DISCORD_TOKEN"

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
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []
        self._content_emoji_ids: dict[str, str] = {}

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if options.template:
            return self._export_from_template(options.template, options)
        if not options.source_id:
            raise ValueError(f"{self.provider_label} export requires --source-id <guild_id> or --template <template_url_or_code>.")
        if not self._token_configured():
            raise ValueError(f"{self.provider_label} live guild export requires {self.token_env_hint}.")
        guild = self.http.get(f"/guilds/{options.source_id}")
        roles = self.http.get(f"/guilds/{options.source_id}/roles")
        channels = self.http.get(f"/guilds/{options.source_id}/channels")
        return self._build_template(
            guild,
            roles,
            channels,
            source_note=f"exported from live {self.provider_label} guild",
            options=options,
        )

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if not options.target_id:
            raise ValueError(
                f"{self.provider_label} import requires --target-id <existing_guild_id>. GuildBridge imports into an existing guild."
            )
        if options.apply and not self._token_configured():
            raise ValueError(f"{self.provider_label} import requires {self.token_env_hint} when --apply is used.")

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
                role_map[role.id] = require_response_id(created, f"{self.provider_label} role create", "id")
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
                category_map[cat.id] = require_response_id(created, f"{self.provider_label} category create", "id")
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
                result.id_map[channel.id] = require_response_id(created, f"{self.provider_label} channel create", "id")
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

    def _token_configured(self) -> bool:
        return bool(self.config.discord_token)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(
            self.name,
            export_supported=self.name == "discord",
            import_supported=True,
            reliability_supported=True,
        )
        capability.notes.append(
            f"Live content import sends formatted archived messages to mapped {self.provider_label} channel IDs."
        )
        if self.name == "discord":
            capability.notes.append(
                "Offline Discord content export is supported through existing DiscordChatExporter JSON, a locally installed DiscordChatExporter CLI, or an explicit managed DCE download."
            )
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import can upload local attachments, send embeds/replies, apply pins/reactions, and create custom emoji when the target API and bot permissions support those operations."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins", "custom_emoji", "server_banner"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self._token_configured():
            raise ValueError(f"{self.provider_label} content import requires {self.token_env_hint} when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                f"{self.provider_label} content import requires --channel-map for live writes so archive channel IDs map to existing channel IDs."
            )
        plan = dry_run_content_import(self.name, archive, options, path_template="/channels/{channel_id}/messages")
        if not options.apply:
            return plan
        self._prepare_native_content_state(archive, options)
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
        action_payload = action.payload or {}
        if message_id and int(action_payload.get("part_index") or 1) == 1:
            self._apply_native_followups(action, message_id)
        return response

    def _prepare_native_content_state(self, archive: ContentArchive, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_native_warnings = []
        self._content_emoji_ids = {}
        if options.native_content:
            self._apply_native_server_assets(archive, options)
        if options.native_custom_emoji:
            self._create_native_custom_emoji(archive, options)

    def _native_message_payload(self, action: Action) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": content_text_from_action(action),
            "allowed_mentions": {"parse": []},
            "flags": DISCORD_SUPPRESS_NOTIFICATIONS,
            "nonce": hash_id("discord_content_nonce", json.dumps(action.payload or {}, sort_keys=True), 25),
            "enforce_nonce": True,
        }
        action_payload = action.payload or {}
        if int(action_payload.get("part_index") or 1) != 1:
            return payload
        if self._content_options.native_embeds:
            embeds = self._native_embeds(action_payload)
            if embeds:
                payload["embeds"] = embeds
        if self._content_options.native_replies:
            reply_id = self._mapped_reply_id(action_payload)
            if reply_id:
                payload["message_reference"] = {"message_id": reply_id, "fail_if_not_exists": False}
        return payload

    def _native_embeds(self, action_payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_embeds = action_payload.get("embeds")
        if not isinstance(raw_embeds, list):
            return []
        embeds: list[dict[str, Any]] = []
        for raw in raw_embeds[:10]:
            if not isinstance(raw, dict):
                continue
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

    def _native_file_paths(self, action_payload: dict[str, Any]) -> list[Path]:
        if not self._content_options.native_attachments:
            return []
        files: list[Path] = []
        attachments = action_payload.get("attachments")
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

    def _mapped_reply_id(self, action_payload: dict[str, Any]) -> str | None:
        reply_to = action_payload.get("reply_to_id")
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
        action_payload = action.payload or {}
        source_message_id = str(action_payload.get("source_message_id") or "")
        if not source_message_id:
            return
        part_index = int(action_payload.get("part_index") or 1)
        self._content_message_ids[source_message_id] = message_id
        self._content_message_ids[f"{source_message_id}:{part_index}"] = message_id

    def _apply_native_followups(self, action: Action, message_id: str) -> None:
        payload = action.payload or {}
        channel_id = str(payload.get("channel_id") or "").strip()
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
            if not isinstance(reaction, dict):
                continue
            emoji = self._native_reaction_emoji(reaction)
            if not emoji:
                continue
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

    def _native_reaction_emoji(self, reaction: dict[str, Any]) -> str | None:
        metadata = reaction.get("metadata") if isinstance(reaction.get("metadata"), dict) else {}
        emoji_hash = metadata.get("emoji_hash") if isinstance(metadata, dict) else None
        if emoji_hash and str(emoji_hash) in self._content_emoji_ids:
            return self._content_emoji_ids[str(emoji_hash)]
        emoji = reaction.get("emoji")
        return str(emoji) if emoji else None

    def _create_native_custom_emoji(self, archive: ContentArchive, options: ContentImportOptions) -> None:
        if not options.target_id:
            self._content_native_warnings.append("Native custom emoji skipped because --target-id was not provided.")
            return
        for emoji in archive.emoji:
            if not emoji.id_hash:
                continue
            path = self._local_content_path(
                {
                    "local_path": emoji.local_path,
                    "url": emoji.url,
                    "metadata": emoji.metadata,
                },
                label="custom emoji",
            )
            if not path:
                continue
            if path.stat().st_size > DISCORD_EMOJI_SIZE_LIMIT:
                self._content_native_warnings.append(
                    f"Native custom emoji upload skipped for {emoji.name!r}; file exceeds {DISCORD_EMOJI_SIZE_LIMIT} bytes."
                )
                continue
            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            payload = {"name": normalize_channel_name(emoji.name or "emoji", max_len=32), "image": f"data:{mime_type};base64,{encoded}"}
            try:
                created = self.http.post(f"/guilds/{options.target_id}/emojis", json_body=payload)
            except Exception as exc:  # noqa: BLE001
                self._content_native_warnings.append(f"Native custom emoji follow-up failed: {sanitize_text(str(exc))}")
                continue
            created_id = response_id(created if isinstance(created, dict) else {}, "id", "emoji.id")
            if created_id:
                self._content_emoji_ids[emoji.id_hash] = f"{payload['name']}:{created_id}"

    def _apply_native_server_assets(self, archive: ContentArchive, options: ContentImportOptions) -> None:
        metadata = archive.metadata or {}
        icon_item = {
            "local_path": metadata_first(metadata, "server_icon_path", "server_icon_local_path", "icon_path", "icon_local_path"),
            "url": metadata_first(metadata, "server_icon_url", "icon_url"),
            "name": "server-icon",
            "metadata": metadata,
        }
        banner_item = {
            "local_path": metadata_first(
                metadata,
                "server_banner_path",
                "server_banner_local_path",
                "banner_path",
                "banner_local_path",
            ),
            "url": metadata_first(metadata, "server_banner_url", "banner_url"),
            "name": "server-banner",
            "metadata": metadata,
        }
        if not any((icon_item["local_path"], icon_item["url"], banner_item["local_path"], banner_item["url"])):
            return
        if not options.target_id:
            self._content_native_warnings.append("Native server icon/banner skipped because --target-id was not provided.")
            return
        patch = without_none(
            {
                "icon": self._server_asset_data_uri(icon_item, label="server icon"),
                "banner": self._server_asset_data_uri(banner_item, label="server banner"),
            }
        )
        if not patch:
            return
        self._safe_native_followup(
            "server icon/banner",
            lambda: self.http.patch(f"/guilds/{options.target_id}", json_body=patch),
        )

    def _server_asset_data_uri(self, item: dict[str, Any], *, label: str) -> str | None:
        if not item.get("local_path") and not item.get("url"):
            return None
        path = resolve_content_asset_path(
            item,
            label=label,
            allow_remote_download=self._content_options.download_remote_assets,
            warnings=self._content_native_warnings,
            max_bytes=DISCORD_SERVER_ASSET_SIZE_LIMIT,
        )
        if not path:
            return None
        if path.stat().st_size > DISCORD_SERVER_ASSET_SIZE_LIMIT:
            self._content_native_warnings.append(
                f"Native {label} upload skipped; {path.stat().st_size} bytes exceeds the {DISCORD_SERVER_ASSET_SIZE_LIMIT} byte limit."
            )
            return None
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _safe_native_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

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
        dropped_missing_role_overwrites: set[str] = set()

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
                        permission_overwrites=self._overwrites_from_discord(
                            ch.get("permission_overwrites", []),
                            role_id_map,
                            options,
                            dropped_missing_role_overwrites,
                        ),
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
                    permission_overwrites=self._overwrites_from_discord(
                        ch.get("permission_overwrites", []),
                        role_id_map,
                        options,
                        dropped_missing_role_overwrites,
                    ),
                )
            )

        template = CommunityTemplate(
            name=normalize_name(
                guild.get("name") or f"{self.provider_label} community",
                max_len=100,
                fallback=f"{self.provider_label} community",
            ),
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
        if dropped_missing_role_overwrites:
            template.warnings.append(
                f"Dropped {len(dropped_missing_role_overwrites)} role permission overwrite target(s) "
                "that were not present in the Discord template roles."
            )
        return template

    def _overwrites_from_discord(
        self,
        overwrites: Iterable[dict[str, Any]],
        role_id_map: dict[str, str],
        options: ExportOptions,
        dropped_missing_role_overwrites: set[str] | None = None,
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
            target_id = role_id_map.get(raw_id)
            if target_id is None:
                if dropped_missing_role_overwrites is not None:
                    dropped_missing_role_overwrites.add(raw_id)
                continue
            output.append(
                PermissionOverwrite(
                    target_type="everyone" if target_id == "everyone" else "role",
                    target_id=target_id,
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

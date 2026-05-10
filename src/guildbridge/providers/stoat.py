from __future__ import annotations

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
    content_action_key,
    content_text_from_action,
    dry_run_content_import,
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
from guildbridge.permissions import neutral_to_stoat, stoat_to_neutral
from guildbridge.utils import (
    hash_id,
    local_id,
    normalize_channel_name,
    normalize_name,
    without_none,
)

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id

STOAT_NAME_MAX = 32
STOAT_EMOJI_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")
STOAT_MAX_MESSAGE_ATTACHMENTS = 5
AUTUMN_TAG_LIMITS = {
    "attachments": 20 * 1024 * 1024,
    "avatars": 4 * 1024 * 1024,
    "icons": 2560 * 1024,
    "banners": 6 * 1024 * 1024,
    "emojis": 500 * 1024,
}


class StoatProvider(Provider):
    """Stoat/Revolt-style adapter.

    Stoat has been evolving quickly after the Revolt rename. The route layout
    here follows the public Revolt/Stoat OpenAPI style and keeps base URL and
    auth configurable through environment variables.
    """

    name = "stoat"
    aliases = ("revolt", "rvlt")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.stoat_api_base,
            token=None,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self.autumn = HttpClient(
            config.stoat_autumn_base,
            token=None,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_upload_cache: dict[tuple[str, str], str] = {}
        self._content_emoji_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []

    def _headers(self) -> dict[str, str]:
        if self.config.stoat_session_token:
            return {"X-Session-Token": self.config.stoat_session_token}
        if not self.config.stoat_token:
            return {}
        return {"X-Bot-Token": self.config.stoat_token}

    def _has_token(self) -> bool:
        return bool(self.config.stoat_session_token or self.config.stoat_token)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append(
            "Live content import sends formatted archived messages to mapped Stoat channel IDs through the message API."
        )
        capability.notes.append(
            "Opt-in native content import can upload local attachments/stickers to Autumn, send embeds and replies, apply pins/reactions, create custom emoji, and use Stoat masquerade. Text fallbacks remain the default."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins", "custom_emoji", "stickers"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self._has_token():
            raise ValueError(
                "Stoat content import requires STOAT_SESSION_TOKEN, STOAT_BOT_TOKEN, STOAT_TOKEN, or REVOLT_TOKEN when --apply is used."
            )
        if options.apply and not options.channel_map:
            raise ValueError(
                "Stoat content import requires --channel-map for live writes so archive channel IDs map to existing Stoat channel IDs."
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
        payload = self._content_message_payload(action)
        headers = self._headers()
        headers["Idempotency-Key"] = content_action_key(action)
        response = self.http.post(action.path, json_body=payload, headers=headers)
        response_id = self._response_id(response)
        action_payload = action.payload or {}
        source_message_id = str(action_payload.get("source_message_id") or "")
        part_index = int(action_payload.get("part_index") or 1)
        if response_id and source_message_id:
            self._content_message_ids[source_message_id] = response_id
            self._content_message_ids[f"{source_message_id}:{part_index}"] = response_id
            if part_index == 1:
                self._apply_native_followups(action, response_id)
        return response

    def _prepare_native_content_state(self, archive: ContentArchive, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_upload_cache = {}
        self._content_emoji_ids = {}
        self._content_native_warnings = []
        if options.uses_native_content and not self.config.stoat_session_token:
            self._content_native_warnings.append(
                "Stoat native content features work best with STOAT_SESSION_TOKEN. Bot tokens may lack upload, masquerade, reaction, pin, or custom emoji permissions."
            )
        if options.native_custom_emoji:
            self._create_native_custom_emoji(archive, options)

    def _content_message_payload(self, action: Action) -> dict[str, Any]:
        options = self._content_options
        action_payload = action.payload or {}
        payload: dict[str, Any] = {"content": content_text_from_action(action)}
        part_index = int(action_payload.get("part_index") or 1)

        if options.native_masquerade:
            masquerade = self._native_masquerade(action_payload)
            if masquerade:
                payload["masquerade"] = masquerade

        if part_index == 1:
            attachments = self._native_attachment_ids(action_payload)
            if attachments:
                payload["attachments"] = attachments
            embeds = self._native_embeds(action_payload)
            if embeds:
                payload["embeds"] = embeds
            replies = self._native_replies(action_payload)
            if replies:
                payload["replies"] = replies

        payload["silent"] = True
        return payload

    def _native_masquerade(self, action_payload: dict[str, Any]) -> dict[str, str]:
        author = action_payload.get("author")
        if not isinstance(author, dict):
            return {}
        display = author.get("display_name") or author.get("username") or "Unknown"
        masquerade = {"name": normalize_name(str(display), max_len=STOAT_NAME_MAX, fallback="Unknown")}
        avatar_url = author.get("avatar_url")
        if isinstance(avatar_url, str) and avatar_url.startswith(("http://", "https://")):
            masquerade["avatar"] = avatar_url
        return masquerade

    def _native_attachment_ids(self, action_payload: dict[str, Any]) -> list[str]:
        options = self._content_options
        if not options.native_attachments and not options.native_stickers:
            return []
        uploaded: list[str] = []
        if options.native_attachments:
            attachments = action_payload.get("attachments")
            if isinstance(attachments, list):
                for item in attachments[:STOAT_MAX_MESSAGE_ATTACHMENTS]:
                    if isinstance(item, dict):
                        file_id = self._upload_autumn_dict("attachments", item, label=item.get("filename") or "attachment")
                        if file_id:
                            uploaded.append(file_id)
        if options.native_stickers and len(uploaded) < STOAT_MAX_MESSAGE_ATTACHMENTS:
            stickers = action_payload.get("stickers")
            if isinstance(stickers, list):
                for item in stickers[: STOAT_MAX_MESSAGE_ATTACHMENTS - len(uploaded)]:
                    if isinstance(item, dict):
                        file_id = self._upload_autumn_dict("attachments", item, label=item.get("name") or "sticker")
                        if file_id:
                            uploaded.append(file_id)
        return uploaded

    def _native_embeds(self, action_payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._content_options.native_embeds:
            return []
        raw_embeds = action_payload.get("embeds")
        if not isinstance(raw_embeds, list):
            return []
        embeds: list[dict[str, Any]] = []
        for raw in raw_embeds[:5]:
            if not isinstance(raw, dict):
                continue
            embed = without_none(
                {
                    "title": raw.get("title"),
                    "description": raw.get("description"),
                    "url": raw.get("url"),
                    "icon_url": raw.get("thumbnail_url"),
                }
            )
            if embed:
                embeds.append(embed)
        return embeds

    def _native_replies(self, action_payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._content_options.native_replies:
            return []
        reply_to = action_payload.get("reply_to_id")
        if not reply_to:
            return []
        mapped = self._content_message_ids.get(f"{reply_to}:1") or self._content_message_ids.get(str(reply_to))
        if not mapped:
            self._content_native_warnings.append(f"Native reply skipped for {reply_to!r}; referenced message was not mapped yet.")
            return []
        return [{"id": mapped, "mention": False}]

    def _apply_native_followups(self, action: Action, message_id: str) -> None:
        payload = action.payload or {}
        channel_id = str(payload.get("channel_id") or "").strip()
        if not channel_id:
            return
        if self._content_options.native_pins and payload.get("pinned"):
            self._safe_followup(
                "pin",
                lambda: self.http.put(f"/channels/{channel_id}/messages/{message_id}/pin", headers=self._headers()),
            )
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
            self._safe_followup(
                "reaction",
                lambda encoded=encoded_emoji: self.http.put(
                    f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}",
                    headers=self._headers(),
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
            file_id = self._upload_autumn_dict(
                "emojis",
                {
                    "local_path": emoji.local_path,
                    "url": emoji.url,
                    "metadata": emoji.metadata,
                },
                label=emoji.name or "emoji",
            )
            if not file_id:
                continue
            emoji_name = _stoat_emoji_name(emoji.name)
            try:
                self.http.put(
                    f"/custom/emoji/{file_id}",
                    json_body={"name": emoji_name, "parent": {"type": "Server", "id": options.target_id}},
                    headers=self._headers(),
                )
            except Exception as exc:  # noqa: BLE001
                self._content_native_warnings.append(f"Native custom emoji follow-up failed: {sanitize_text(str(exc))}")
            else:
                self._content_emoji_ids[emoji.id_hash] = file_id

    def _upload_autumn_dict(self, tag: str, item: dict[str, Any], *, label: object) -> str | None:
        local_path = item.get("local_path")
        metadata = item.get("metadata")
        if not local_path and isinstance(metadata, dict):
            local_path = metadata.get("local_path") or metadata.get("source_path")
        if not local_path:
            self._content_native_warnings.append(f"Native {tag} upload skipped for {label!r}; no local file path was available.")
            return None
        path = Path(str(local_path)).expanduser()
        if not path.exists() or not path.is_file():
            self._content_native_warnings.append(f"Native {tag} upload skipped for {label!r}; file was not found at {path}.")
            return None
        limit = AUTUMN_TAG_LIMITS.get(tag)
        if limit is not None and path.stat().st_size > limit:
            self._content_native_warnings.append(
                f"Native {tag} upload skipped for {label!r}; {path.stat().st_size} bytes exceeds the {limit} byte limit."
            )
            return None
        cache_key = (tag, str(path.resolve()))
        if cache_key in self._content_upload_cache:
            return self._content_upload_cache[cache_key]
        response = self.autumn.post_file(f"/{tag}", file_path=path, headers=self._headers())
        file_id = require_response_id(response, f"Autumn {tag} upload", "id", "_id", "file.id", "file._id")
        self._content_upload_cache[cache_key] = file_id
        return file_id

    def _safe_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

    def _response_id(self, response: dict[str, Any] | str | None) -> str | None:
        if not isinstance(response, dict):
            return None
        for key in ("_id", "id", "message_id"):
            value = response.get(key)
            if value:
                return str(value)
        message = response.get("message")
        if isinstance(message, dict):
            for key in ("_id", "id"):
                value = message.get(key)
                if value:
                    return str(value)
        return None

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Stoat export requires --source-id <server_id>.")
        if not self._has_token():
            raise ValueError("Stoat export requires STOAT_SESSION_TOKEN, STOAT_BOT_TOKEN, STOAT_TOKEN, or REVOLT_TOKEN.")
        server = self.http.get(f"/servers/{options.source_id}", headers=self._headers())
        role_items = self._roles_from_server(server)
        channels = self._channels_from_server(server)
        return self._build_template(server, role_items, channels, options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self._has_token():
            raise ValueError(
                "Stoat import requires STOAT_SESSION_TOKEN, STOAT_BOT_TOKEN, STOAT_TOKEN, or REVOLT_TOKEN when --apply is used."
            )

        result = ImportResult(provider=self.name, applied=options.apply)
        server_id = options.target_id
        if not server_id:
            payload = {"name": normalize_name(options.target_name or template.name, max_len=STOAT_NAME_MAX)}
            action = Action(self.name, "POST", "/servers/create", payload, note="create target Stoat server")
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/servers/create", json_body=payload, headers=self._headers()),
            )
            if options.apply:
                server_id = require_response_id(created, "Stoat server create", "_id", "id")
            else:
                server_id = "dry_stoat_server"
        result.id_map["server"] = server_id

        role_map: dict[str, str] = {"everyone": "default"}
        # Stoat's default/everyone permissions are server-level. Avoid modifying them automatically.
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.name == "@everyone" or role.id == "everyone":
                role_map[role.id] = "default"
                continue
            create_payload = {"name": normalize_name(role.name, max_len=STOAT_NAME_MAX, fallback="role")}
            create_action = Action(self.name, "POST", f"/servers/{server_id}/roles", create_payload)
            created = plan_or_apply_action(
                options,
                result,
                create_action,
                partial(self.http.post, f"/servers/{server_id}/roles", json_body=create_payload, headers=self._headers()),
            )
            if options.apply:
                role_id = require_response_id(created, "Stoat role create", "id", "_id", "role_id", "role.id", "role._id")
            else:
                role_id = f"dry_role_{role.id}"
            role_map[role.id] = role_id

            patch_payload = without_none(
                {
                    "name": normalize_name(role.name, max_len=STOAT_NAME_MAX, fallback="role"),
                    "permissions": {"a": neutral_to_stoat(role.permissions), "d": 0},
                    "colour": role.color if isinstance(role.color, str) else None,
                    "color": role.color if isinstance(role.color, int) else None,
                    "hoist": bool(role.hoist),
                    "rank": role.position,
                }
            )
            patch_action = Action(self.name, "PATCH", f"/servers/{server_id}/roles/{role_id}", patch_payload)
            plan_or_apply_action(
                options,
                result,
                patch_action,
                partial(self.http.patch, f"/servers/{server_id}/roles/{role_id}", json_body=patch_payload, headers=self._headers()),
            )

        channel_map: dict[str, str] = {}
        valid_category_ids = {cat.id for cat in template.categories}
        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type not in {"text", "voice"}:
                result.warnings.append(f"Skipping unsupported Stoat channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "type": "Text" if channel.type == "text" else "Voice",
                    "name": normalize_channel_name(channel.name, max_len=STOAT_NAME_MAX),
                    "description": channel.topic[:1024] if channel.topic else None,
                    "nsfw": bool(channel.nsfw),
                }
            )
            action = Action(self.name, "POST", f"/servers/{server_id}/channels", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, f"/servers/{server_id}/channels", json_body=payload, headers=self._headers()),
            )
            if options.apply:
                channel_id = require_response_id(created, "Stoat channel create", "_id", "id", "channel._id", "channel.id")
            else:
                channel_id = f"dry_channel_{channel.id}"
            channel_map[channel.id] = channel_id
            if channel.parent_id and channel.parent_id not in valid_category_ids:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; leaving it uncategorized."
                )

            # Role permission patches are channel-local in Stoat/Revolt-style APIs.
            role_perms: dict[str, dict[str, int]] = {}
            for ow in channel.permission_overwrites:
                target = role_map.get(ow.target_id)
                if not target or target == "default":
                    continue
                role_perms[target] = {"a": neutral_to_stoat(ow.allow), "d": neutral_to_stoat(ow.deny)}
            if role_perms:
                patch_payload = {"role_permissions": role_perms}
                action = Action(self.name, "PATCH", f"/channels/{channel_id}", patch_payload)
                plan_or_apply_action(
                    options,
                    result,
                    action,
                    partial(self.http.patch, f"/channels/{channel_id}", json_body=patch_payload, headers=self._headers()),
                )

        # Stoat/Revolt categories are a server layout property. They are updated after channels exist.
        if template.categories:
            categories_payload: list[dict[str, Any]] = []
            for cat in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
                child_ids = [channel_map[ch.id] for ch in template.channels if ch.parent_id == cat.id and ch.id in channel_map]
                categories_payload.append(
                    {
                        "id": local_id("stoat_cat", self.name, cat.id),
                        "title": normalize_name(cat.name, max_len=STOAT_NAME_MAX),
                        "channels": child_ids,
                    }
                )
            categories_patch: dict[str, Any] = {"categories": categories_payload}
            action = Action(self.name, "PATCH", f"/servers/{server_id}", categories_patch, note="set Stoat category layout")
            plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.patch, f"/servers/{server_id}", json_body=categories_patch, headers=self._headers()),
            )

        result.id_map.update(role_map)
        result.id_map.update(channel_map)
        return result

    def _roles_from_server(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        roles = server.get("roles") or {}
        if isinstance(roles, list):
            return roles
        if isinstance(roles, dict):
            output = []
            for rid, role in roles.items():
                if isinstance(role, dict):
                    output.append(dict(role, id=rid))
            return output
        return []

    def _channels_from_server(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        channels = server.get("channels") or []
        output: list[dict[str, Any]] = []
        for item in channels:
            if isinstance(item, dict):
                output.append(item)
            else:
                try:
                    output.append(self.http.get(f"/channels/{item}", headers=self._headers()))
                except Exception as exc:
                    output.append({"_id": str(item), "name": f"unfetched-{item}", "channel_type": "Unknown", "_warning": str(exc)})
        return output

    def _build_template(self, server: dict[str, Any], roles: Iterable[dict[str, Any]], channels: Iterable[dict[str, Any]], *, options: ExportOptions) -> CommunityTemplate:
        server_id = str(server.get("_id") or server.get("id") or options.source_id)
        role_id_map: dict[str, str] = {"default": "everyone"}
        out_roles: list[Role] = [Role(id="everyone", name="@everyone", permissions=stoat_to_neutral(server.get("default_permissions")))]
        for role in roles or []:
            raw_id = str(role.get("id") or role.get("_id") or role.get("name"))
            lid = local_id("role", self.name, raw_id)
            role_id_map[raw_id] = lid
            permissions = role.get("permissions") or {}
            if isinstance(permissions, dict):
                perm_value = permissions.get("a") or permissions.get("allow") or 0
            else:
                perm_value = permissions
            out_roles.append(
                Role(
                    id=lid,
                    name=normalize_name(role.get("name") or "role", max_len=STOAT_NAME_MAX, fallback="role"),
                    permissions=stoat_to_neutral(perm_value),
                    color=role.get("colour") or role.get("color"),
                    position=role.get("rank"),
                    hoist=bool(role.get("hoist", False)),
                    mentionable=False,
                )
            )

        category_id_map: dict[str, str] = {}
        channel_parent_map: dict[str, str] = {}
        out_categories: list[Category] = []
        for idx, cat in enumerate(server.get("categories") or []):
            if not isinstance(cat, dict):
                continue
            raw_id = str(cat.get("id") or cat.get("title") or idx)
            lid = local_id("cat", self.name, raw_id)
            category_id_map[raw_id] = lid
            out_categories.append(Category(id=lid, name=normalize_name(cat.get("title") or "category", max_len=STOAT_NAME_MAX), position=idx))
            for ch_id in cat.get("channels") or []:
                channel_parent_map[str(ch_id)] = lid

        out_channels: list[Channel] = []
        for idx, ch in enumerate(channels or []):
            raw_id = str(ch.get("_id") or ch.get("id") or ch.get("name"))
            channel_kind = ch.get("channel_type") or ch.get("type") or "TextChannel"
            ctype = "voice" if "voice" in str(channel_kind).lower() else "text" if "text" in str(channel_kind).lower() else "unknown"
            if ctype == "unknown":
                continue
            out_channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(ch.get("name") or "channel", max_len=STOAT_NAME_MAX),
                    type=ctype,  # type: ignore[arg-type]
                    position=idx,
                    parent_id=channel_parent_map.get(raw_id),
                    topic=ch.get("description"),
                    nsfw=bool(ch.get("nsfw", False)),
                    permission_overwrites=self._role_permissions_from_stoat(ch.get("role_permissions") or {}, role_id_map),
                )
            )
        warnings = [self.supported_warning()]
        for ch in channels or []:
            if ch.get("_warning"):
                warnings.append(f"Could not fetch channel {ch.get('_id')}: {ch.get('_warning')}")
        return CommunityTemplate(
            name=normalize_name(server.get("name") or "Stoat server", max_len=STOAT_NAME_MAX),
            description=server.get("description"),
            source=TemplateSource(platform=self.name, id_hash=hash_id(self.name, server_id), note="exported from Stoat/Revolt-style server"),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            categories=out_categories,
            channels=out_channels,
            warnings=warnings,
        )

    def _role_permissions_from_stoat(self, role_permissions: dict[str, Any], role_id_map: dict[str, str]) -> list[PermissionOverwrite]:
        output: list[PermissionOverwrite] = []
        for raw_id, value in role_permissions.items():
            if not isinstance(value, dict):
                continue
            target = role_id_map.get(str(raw_id))
            if not target:
                continue
            output.append(
                PermissionOverwrite(
                    target_type="role",
                    target_id=target,
                    allow=stoat_to_neutral(value.get("a") or value.get("allow")),
                    deny=stoat_to_neutral(value.get("d") or value.get("deny")),
                )
            )
        return output


def _stoat_emoji_name(value: str) -> str:
    name = STOAT_EMOJI_NAME_RE.sub("_", value.lower()).strip("_")
    if not name:
        name = "emoji"
    if name[0].isdigit():
        name = f"emoji_{name}"
    return name[:STOAT_NAME_MAX]

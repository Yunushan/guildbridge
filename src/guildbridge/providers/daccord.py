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
from guildbridge.permissions import daccord_to_neutral, neutral_to_daccord
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
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []

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

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Daccord channel IDs.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import uses Discord-compatible message routes for local attachments, embeds, replies, pins, and reactions when the Daccord API supports them."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self.config.daccord_token:
            raise ValueError("Daccord content import requires DACCORD_BOT_TOKEN or DACCORD_TOKEN when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Daccord content import requires --channel-map for live writes so archive channel IDs map to existing Daccord channel IDs."
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
        message_id = response_id(response if isinstance(response, dict) else {}, "id", "message.id", "data.id")
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
        message_id = response_id(response, "id", "message.id", "data.id")
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

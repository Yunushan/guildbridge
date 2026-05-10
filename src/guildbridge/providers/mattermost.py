from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from pathlib import Path
from typing import Any

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
    Channel,
    CommunityTemplate,
    ImportResult,
    Role,
    TemplatePrivacy,
    TemplateSource,
)
from guildbridge.permissions import mattermost_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import (
    ExportOptions,
    ImportOptions,
    Provider,
    plan_or_apply_action,
    require_response_id,
    response_id,
)


class MattermostProvider(Provider):
    name = "mattermost"
    aliases = ("mattermost-team", "mattermost-server")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.mattermost_api_base,
            token=config.mattermost_token,
            auth_scheme="Bearer",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []
        self._content_user_id: str | None = None

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Mattermost export requires --source-id <team_id>.")
        if not self.config.mattermost_token:
            raise ValueError("Mattermost export requires MATTERMOST_TOKEN or MATTERMOST_PERSONAL_ACCESS_TOKEN.")
        team = self.http.get(f"/teams/{options.source_id}")
        channels = self._unwrap_list(self.http.get(f"/teams/{options.source_id}/channels"))
        return self._build_template(team, channels, options=options)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Mattermost channel IDs.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import can upload local files, post replies, apply pins/reactions, and carry embed text in Mattermost post props when permissions allow it."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and not self.config.mattermost_token:
            raise ValueError("Mattermost content import requires MATTERMOST_TOKEN or MATTERMOST_PERSONAL_ACCESS_TOKEN when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Mattermost content import requires --channel-map for live writes so archive channel IDs map to existing channel IDs."
            )
        plan = dry_run_content_import(self.name, archive, options, path_template="/posts")
        if not options.apply:
            return plan
        self._prepare_native_content_state(options)
        result = apply_content_actions(self.name, plan.actions, options, self._send_content_action)
        result.warnings[:0] = plan.warnings
        result.warnings.extend(self._content_native_warnings)
        return result

    def _send_content_action(self, action: Action) -> dict[str, Any] | str | None:
        payload = action.payload or {}
        if not self._content_options.uses_native_content:
            return self.http.post(
                action.path,
                json_body={"channel_id": str(payload.get("channel_id") or ""), "message": content_text_from_action(action)},
            )
        message_payload: dict[str, Any] = {
            "channel_id": str(payload.get("channel_id") or ""),
            "message": content_text_from_action(action),
        }
        if self._content_options.native_replies:
            reply_id = self._mapped_reply_id(payload)
            if reply_id:
                message_payload["root_id"] = reply_id
        if self._content_options.native_embeds:
            props = self._native_props(payload)
            if props:
                message_payload["props"] = props
        if self._content_options.native_attachments:
            file_ids = self._upload_native_files(payload)
            if file_ids:
                message_payload["file_ids"] = file_ids
        response = self.http.post(action.path, json_body=message_payload)
        self._record_native_message_response(action, response)
        message_id = response_id(response if isinstance(response, dict) else {}, "id", "post.id")
        if message_id and int(payload.get("part_index") or 1) == 1:
            self._apply_native_followups(payload, message_id)
        return response

    def _prepare_native_content_state(self, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_native_warnings = []
        self._content_user_id = None

    def _native_props(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_embeds = payload.get("embeds")
        if not isinstance(raw_embeds, list):
            return {}
        attachments: list[dict[str, Any]] = []
        for raw in raw_embeds[:10]:
            if not isinstance(raw, dict):
                continue
            attachment = without_none(
                {
                    "title": raw.get("title"),
                    "title_link": raw.get("url"),
                    "text": raw.get("description"),
                    "image_url": raw.get("image_url"),
                    "thumb_url": raw.get("thumbnail_url"),
                }
            )
            if attachment:
                attachments.append(attachment)
        return {"attachments": attachments} if attachments else {}

    def _upload_native_files(self, payload: dict[str, Any]) -> list[str]:
        channel_id = str(payload.get("channel_id") or "")
        if not channel_id:
            return []
        file_ids: list[str] = []
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            for item in attachments[:10]:
                path = self._local_content_path(item, label="attachment")
                if not path:
                    continue
                try:
                    uploaded = self.http.post_file(
                        "/files",
                        file_path=path,
                        field_name="files",
                        form_body={"channel_id": channel_id},
                    )
                except Exception as exc:  # noqa: BLE001
                    self._content_native_warnings.append(f"Native file upload failed for {path.name}: {sanitize_text(str(exc))}")
                    continue
                file_id = self._mattermost_file_id(uploaded)
                if file_id:
                    file_ids.append(file_id)
        return file_ids

    def _local_content_path(self, item: object, *, label: str) -> Path | None:
        return resolve_content_asset_path(
            item,
            label=label,
            allow_remote_download=self._content_options.download_remote_assets,
            warnings=self._content_native_warnings,
        )

    @staticmethod
    def _mattermost_file_id(uploaded: Any) -> str | None:
        if not isinstance(uploaded, dict):
            return None
        file_infos = uploaded.get("file_infos")
        if isinstance(file_infos, list) and file_infos:
            first = file_infos[0]
            if isinstance(first, dict):
                return response_id(first, "id", "_id")
        return response_id(uploaded, "id", "file_id")

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
        message_id = response_id(response, "id", "post.id")
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
        if self._content_options.native_pins and payload.get("pinned"):
            self._safe_native_followup("pin", lambda: self.http.post(f"/posts/{message_id}/pin", json_body={}))
        if self._content_options.native_reactions:
            self._apply_native_reactions(message_id, payload)

    def _apply_native_reactions(self, message_id: str, payload: dict[str, Any]) -> None:
        reactions = payload.get("reactions")
        if not isinstance(reactions, list):
            return
        user_id = self._current_user_id()
        if not user_id:
            self._content_native_warnings.append("Native reactions skipped; Mattermost current user id could not be resolved.")
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
            self._safe_native_followup(
                "reaction",
                lambda emoji_name=emoji: self.http.post(
                    "/reactions",
                    json_body={"user_id": user_id, "post_id": message_id, "emoji_name": emoji_name},
                ),
            )

    def _current_user_id(self) -> str | None:
        if self._content_user_id:
            return self._content_user_id
        try:
            user = self.http.get("/users/me")
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native reaction user lookup failed: {sanitize_text(str(exc))}")
            return None
        self._content_user_id = response_id(user if isinstance(user, dict) else {}, "id", "_id")
        return self._content_user_id

    def _safe_native_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.mattermost_token:
            raise ValueError("Mattermost import requires MATTERMOST_TOKEN or MATTERMOST_PERSONAL_ACCESS_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        if options.target_id:
            team_id = options.target_id
        else:
            team_name = normalize_channel_name(options.target_name or template.name, max_len=64)
            payload = {
                "name": team_name,
                "display_name": normalize_name(options.target_name or template.name, max_len=64),
                "type": "I",
            }
            action = Action(self.name, "POST", "/teams", payload)
            created = plan_or_apply_action(options, result, action, partial(self.http.post, "/teams", json_body=payload))
            team_id = require_response_id(created, "Mattermost team create", "id", "_id", "team.id") if options.apply else "dry_mattermost_team"
        result.id_map["team"] = team_id

        result.id_map["everyone"] = "team_user"
        custom_roles = [role.name for role in template.roles if role.id != "everyone" and role.name != "@everyone"]
        if custom_roles:
            result.warnings.append(
                "Mattermost does not create arbitrary Discord-style roles through team/channel import; "
                f"role names kept as metadata only: {', '.join(custom_roles)}."
            )

        category_names = {category.id: normalize_name(category.name, max_len=64, fallback="category") for category in template.categories}
        if category_names:
            result.warnings.append(
                "Mattermost categories are per-user sidebar state; GuildBridge passes category names as default channel category hints."
            )

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            if channel.type not in {"text", "announcement", "forum"}:
                result.warnings.append(f"Skipping unsupported Mattermost channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "team_id": team_id,
                    "name": normalize_channel_name(channel.name, max_len=64),
                    "display_name": normalize_name(channel.name, max_len=64, fallback="channel"),
                    "type": "P" if channel.nsfw or channel.metadata.get("mattermost_private") else "O",
                    "purpose": normalize_name(channel.topic or "", max_len=250, fallback="") if channel.topic else None,
                    "header": channel.topic[:1024] if channel.topic else None,
                    "default_category_name": category_names.get(channel.parent_id or "") if channel.parent_id else None,
                }
            )
            if channel.parent_id and channel.parent_id not in category_names:
                result.warnings.append(
                    f"Channel {channel.name!r} references missing category {channel.parent_id!r}; creating without a category hint."
                )
            action = Action(self.name, "POST", "/channels", payload)
            created = plan_or_apply_action(options, result, action, partial(self.http.post, "/channels", json_body=payload))
            result.id_map[channel.id] = (
                require_response_id(created, "Mattermost channel create", "id", "_id", "channel.id")
                if options.apply
                else f"dry_channel_{channel.id}"
            )
            if channel.permission_overwrites:
                result.warnings.append(
                    f"Mattermost channel permissions for {channel.name!r} require schemes or membership changes; "
                    "neutral permission overwrites are retained in template metadata only."
                )

        return result

    def _build_template(
        self,
        team: dict[str, Any],
        channels: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        roles = [
            Role(id="everyone", name="@everyone", permissions=["view_channel", "send_messages"]),
            Role(
                id=local_id("role", self.name, "team_admin"),
                name="team_admin",
                permissions=mattermost_to_neutral(["team_admin", "manage_team", "manage_team_roles"]),
                metadata={"mattermost_role": "team_admin"},
            ),
        ]
        out_channels: list[Channel] = []
        for channel in channels or []:
            channel_type = str(channel.get("type") or "").upper()
            if channel_type in {"D", "G"}:
                continue
            if channel_type not in {"O", "P", ""}:
                continue
            raw_id = str(channel.get("id") or channel.get("_id") or channel.get("name") or channel.get("display_name"))
            out_channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(channel.get("name") or channel.get("display_name") or "channel", max_len=64),
                    type="text",
                    topic=channel.get("purpose") or channel.get("header"),
                    nsfw=channel_type == "P",
                    metadata=without_none(
                        {
                            "mattermost_type": channel.get("type"),
                            "display_name": channel.get("display_name"),
                            "team_id_hash": hash_id(self.name, channel.get("team_id")) if channel.get("team_id") else None,
                        }
                    ),
                )
            )
        return CommunityTemplate(
            name=normalize_name(team.get("display_name") or team.get("name") or "Mattermost team", max_len=100),
            description=team.get("description"),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, team.get("id") or team.get("_id") or options.source_id or team.get("name")),
                note="exported from Mattermost team",
            ),
            privacy=TemplatePrivacy(),
            roles=roles,
            channels=out_channels,
            warnings=[
                self.supported_warning(),
                "Mattermost exports team channels and portable team role hints; users, posts, direct messages, and per-user sidebar categories are not exported.",
            ],
        )

    @staticmethod
    def _unwrap_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            for key in ("channels", "data"):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    return [item for item in candidate if isinstance(item, dict)]
        return []

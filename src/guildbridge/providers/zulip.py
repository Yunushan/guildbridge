from __future__ import annotations

import base64
import json
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
from guildbridge.permissions import zulip_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import (
    ExportOptions,
    ImportOptions,
    Provider,
    plan_or_apply_action,
    require_response_id,
    response_id,
)


class ZulipProvider(Provider):
    name = "zulip"
    aliases = ("zulipchat", "zulip.chat")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.zulip_api_base,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_native_warnings: list[str] = []

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not self.config.zulip_email or not self.config.zulip_api_key:
            raise ValueError("Zulip export requires ZULIP_EMAIL and ZULIP_API_KEY.")
        streams = self._unwrap_list(self.http.get("/streams", headers=self._headers()), "streams")
        groups = self._unwrap_list(self.http.get("/user_groups", headers=self._headers()), "user_groups")
        return self._build_template({"name": options.source_id or "Zulip organization"}, groups, streams, options=options)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Zulip stream names.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import can upload local files as Zulip file links and apply reactions when permissions allow it. Discord-style pins and exact message replies do not have a direct Zulip equivalent."
        )
        for feature in ("attachments", "reactions"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and (not self.config.zulip_email or not self.config.zulip_api_key):
            raise ValueError("Zulip content import requires ZULIP_EMAIL and ZULIP_API_KEY when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Zulip content import requires --channel-map for live writes so archive channel IDs map to existing stream names."
            )
        plan = dry_run_content_import(self.name, archive, options, path_template="/messages")
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
            return self.http.post_form(
                action.path,
                form_body={
                    "type": "stream",
                    "to": str(payload.get("channel_id") or ""),
                    "topic": "Imported",
                    "content": content_text_from_action(action),
                },
                headers=self._headers(),
            )
        content = content_text_from_action(action)
        if self._content_options.native_attachments:
            content = self._content_with_file_links(payload, content)
        if self._content_options.native_replies and payload.get("reply_to_id"):
            self._content_native_warnings.append("Native replies skipped for Zulip; use topics/thread context in the imported message text.")
        if self._content_options.native_pins and payload.get("pinned"):
            self._content_native_warnings.append("Native pins skipped for Zulip; pinned-message semantics do not map to a portable Zulip API call.")
        response = self.http.post_form(
            action.path,
            form_body={
                "type": "stream",
                "to": str(payload.get("channel_id") or ""),
                "topic": "Imported",
                "content": content,
            },
            headers=self._headers(),
        )
        message_id = response_id(response if isinstance(response, dict) else {}, "id", "message_id")
        if message_id and self._content_options.native_reactions and int(payload.get("part_index") or 1) == 1:
            self._apply_native_reactions(message_id, payload)
        return response

    def _prepare_native_content_state(self, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_native_warnings = []

    def _content_with_file_links(self, payload: dict[str, Any], content: str) -> str:
        links: list[str] = []
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            for item in attachments[:10]:
                path = self._local_content_path(item, label="attachment")
                if not path:
                    continue
                try:
                    uploaded = self.http.post_file(
                        "/user_uploads",
                        file_path=path,
                        field_name="filename",
                        headers=self._headers(),
                    )
                except Exception as exc:  # noqa: BLE001
                    self._content_native_warnings.append(f"Native file upload failed for {path.name}: {sanitize_text(str(exc))}")
                    continue
                uri = response_id(uploaded if isinstance(uploaded, dict) else {}, "uri", "url")
                if uri:
                    links.append(f"[{path.name}]({uri})")
        if not links:
            return content
        return content + "\n\nUploaded files:\n" + "\n".join(f"- {link}" for link in links)

    def _local_content_path(self, item: object, *, label: str) -> Path | None:
        if not isinstance(item, dict):
            return None
        raw_path = item.get("local_path")
        metadata = item.get("metadata")
        if not raw_path and isinstance(metadata, dict):
            raw_path = metadata.get("local_path") or metadata.get("source_path")
        if not raw_path:
            self._content_native_warnings.append(f"Native {label} upload skipped; no local file path was available.")
            return None
        path = Path(str(raw_path)).expanduser()
        if not path.exists() or not path.is_file():
            self._content_native_warnings.append(f"Native {label} upload skipped; file was not found at {path}.")
            return None
        return path

    def _apply_native_reactions(self, message_id: str, payload: dict[str, Any]) -> None:
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
            try:
                self.http.post_form(
                    f"/messages/{message_id}/reactions",
                    form_body={"emoji_name": emoji},
                    headers=self._headers(),
                )
            except Exception as exc:  # noqa: BLE001
                self._content_native_warnings.append(f"Native reaction follow-up failed: {sanitize_text(str(exc))}")

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and (not self.config.zulip_email or not self.config.zulip_api_key):
            raise ValueError("Zulip import requires ZULIP_EMAIL and ZULIP_API_KEY when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        result.id_map["organization"] = options.target_id or "zulip_organization"
        headers = self._headers()

        group_map: dict[str, str] = {"everyone": "role:everyone"}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.id == "everyone" or role.name == "@everyone":
                continue
            group_payload = {
                "name": normalize_name(role.name, max_len=80, fallback="role"),
                "description": role.metadata.get("description") or f"Imported GuildBridge role: {normalize_name(role.name)}",
                "members": json.dumps([]),
            }
            action = Action(self.name, "POST", "/user_groups/create", group_payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post_form, "/user_groups/create", form_body=group_payload, headers=headers),
            )
            group_map[role.id] = (
                require_response_id(created, "Zulip user group create", "group_id", "id", "user_group.id")
                if options.apply
                else f"dry_group_{role.id}"
            )

        category_names = {category.id: normalize_name(category.name, max_len=80, fallback="category") for category in template.categories}
        if category_names:
            result.warnings.append("Zulip has no Discord-style channel categories; category names are folded into channel descriptions.")

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            if channel.type not in {"text", "announcement", "forum"}:
                result.warnings.append(f"Skipping unsupported Zulip channel type {channel.type!r} for {channel.name!r}.")
                continue
            description_parts = []
            if channel.parent_id and channel.parent_id in category_names:
                description_parts.append(f"Category: {category_names[channel.parent_id]}")
            if channel.topic:
                description_parts.append(channel.topic)
            channel_payload: dict[str, Any] = {
                "subscriptions": json.dumps(
                    [
                        {
                            "name": normalize_name(channel.name, max_len=60, fallback="channel"),
                            "description": "\n\n".join(description_parts) or "Imported by GuildBridge.",
                        }
                    ]
                )
            }
            if channel.nsfw or channel.metadata.get("zulip_private"):
                channel_payload["invite_only"] = json.dumps(True)
            action = Action(self.name, "POST", "/users/me/subscriptions", channel_payload)
            plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post_form, "/users/me/subscriptions", form_body=channel_payload, headers=headers),
            )
            result.id_map[channel.id] = f"zulip_channel:{normalize_name(channel.name, max_len=60, fallback='channel')}"
            if channel.permission_overwrites:
                result.warnings.append(
                    f"Zulip channel permission settings for {channel.name!r} require channel administration groups; "
                    "neutral overwrites are retained in template metadata only."
                )

        result.id_map.update(group_map)
        return result

    def _build_template(
        self,
        realm: dict[str, Any],
        groups: Iterable[dict[str, Any]],
        streams: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        roles = [Role(id="everyone", name="@everyone", permissions=["view_channel", "send_messages"])]
        for group in groups or []:
            if group.get("is_system_group"):
                continue
            raw_id = str(group.get("id") or group.get("name"))
            roles.append(
                Role(
                    id=local_id("role", self.name, raw_id),
                    name=normalize_name(group.get("name") or "group", max_len=80, fallback="group"),
                    permissions=zulip_to_neutral(group.get("permissions", [])),
                    metadata=without_none(
                        {
                            "description": group.get("description"),
                            "member_count": len(group.get("members", [])) if isinstance(group.get("members"), list) else None,
                        }
                    ),
                )
            )

        channels: list[Channel] = []
        for stream in streams or []:
            raw_id = str(stream.get("stream_id") or stream.get("id") or stream.get("name"))
            channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(stream.get("name") or "channel", max_len=60),
                    type="text",
                    topic=stream.get("description"),
                    nsfw=bool(stream.get("invite_only", False)),
                    metadata=without_none(
                        {
                            "zulip_stream_id_hash": hash_id(self.name, raw_id),
                            "is_web_public": stream.get("is_web_public"),
                            "is_default": stream.get("is_default"),
                            "can_send_message_group": stream.get("can_send_message_group"),
                        }
                    ),
                )
            )

        return CommunityTemplate(
            name=normalize_name(realm.get("name") or "Zulip organization", max_len=100),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, options.source_id or self.config.zulip_api_base),
                note="exported from Zulip organization",
            ),
            privacy=TemplatePrivacy(),
            roles=roles,
            channels=channels,
            warnings=[
                self.supported_warning(),
                "Zulip exports channels and user groups; messages, users, topics, subscriptions, and private DMs are not exported.",
            ],
        )

    def _headers(self) -> dict[str, str]:
        if not self.config.zulip_email or not self.config.zulip_api_key:
            return {}
        token = base64.b64encode(f"{self.config.zulip_email}:{self.config.zulip_api_key}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    @staticmethod
    def _unwrap_list(value: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

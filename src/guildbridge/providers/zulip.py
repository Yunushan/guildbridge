from __future__ import annotations

import base64
import json
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
from guildbridge.permissions import zulip_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id


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

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not self.config.zulip_email or not self.config.zulip_api_key:
            raise ValueError("Zulip export requires ZULIP_EMAIL and ZULIP_API_KEY.")
        streams = self._unwrap_list(self.http.get("/streams", headers=self._headers()), "streams")
        groups = self._unwrap_list(self.http.get("/user_groups", headers=self._headers()), "user_groups")
        return self._build_template({"name": options.source_id or "Zulip organization"}, groups, streams, options=options)

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

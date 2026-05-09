from __future__ import annotations

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
from guildbridge.permissions import mattermost_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import ExportOptions, ImportOptions, Provider, plan_or_apply_action, require_response_id


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

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Mattermost export requires --source-id <team_id>.")
        if not self.config.mattermost_token:
            raise ValueError("Mattermost export requires MATTERMOST_TOKEN or MATTERMOST_PERSONAL_ACCESS_TOKEN.")
        team = self.http.get(f"/teams/{options.source_id}")
        channels = self._unwrap_list(self.http.get(f"/teams/{options.source_id}/channels"))
        return self._build_template(team, channels, options=options)

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

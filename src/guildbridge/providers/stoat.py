from __future__ import annotations

from collections.abc import Iterable
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
from guildbridge.permissions import neutral_to_stoat, stoat_to_neutral
from guildbridge.utils import (
    hash_id,
    local_id,
    new_ulid,
    normalize_channel_name,
    normalize_name,
    without_none,
)

from .base import ExportOptions, ImportOptions, Provider

STOAT_NAME_MAX = 32


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
        self.http = HttpClient(config.stoat_api_base, token=None, timeout=config.request_timeout)

    def _headers(self) -> dict[str, str]:
        if not self.config.stoat_token:
            return {}
        return {"X-Bot-Token": self.config.stoat_token}

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not options.source_id:
            raise ValueError("Stoat export requires --source-id <server_id>.")
        if not self.config.stoat_token:
            raise ValueError("Stoat export requires STOAT_BOT_TOKEN, STOAT_TOKEN, or REVOLT_TOKEN.")
        server = self.http.get(f"/servers/{options.source_id}", headers=self._headers())
        role_items = self._roles_from_server(server)
        channels = self._channels_from_server(server)
        return self._build_template(server, role_items, channels, options=options)

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and not self.config.stoat_token:
            raise ValueError("Stoat import requires STOAT_BOT_TOKEN, STOAT_TOKEN, or REVOLT_TOKEN when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        server_id = options.target_id
        if not server_id:
            payload = {"name": normalize_name(options.target_name or template.name, max_len=STOAT_NAME_MAX)}
            result.actions.append(Action(self.name, "POST", "/servers/create", payload, note="create target Stoat server"))
            if options.apply:
                created = self.http.post("/servers/create", json_body=payload, headers=self._headers())
                server_id = str(created.get("_id") or created.get("id"))
                if not server_id:
                    raise ValueError(f"Stoat server create response did not contain an id: {created!r}")
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
            result.actions.append(Action(self.name, "POST", f"/servers/{server_id}/roles", create_payload))
            if options.apply:
                created = self.http.post(f"/servers/{server_id}/roles", json_body=create_payload, headers=self._headers())
                role_id = str(created.get("id") or created.get("_id") or created.get("role_id") or created.get("role", {}).get("id"))
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
            result.actions.append(Action(self.name, "PATCH", f"/servers/{server_id}/roles/{role_id}", patch_payload))
            if options.apply:
                self.http.patch(f"/servers/{server_id}/roles/{role_id}", json_body=patch_payload, headers=self._headers())

        channel_map: dict[str, str] = {}
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
            result.actions.append(Action(self.name, "POST", f"/servers/{server_id}/channels", payload))
            if options.apply:
                created = self.http.post(f"/servers/{server_id}/channels", json_body=payload, headers=self._headers())
                channel_id = str(created.get("_id") or created.get("id"))
            else:
                channel_id = f"dry_channel_{channel.id}"
            channel_map[channel.id] = channel_id

            # Role permission patches are channel-local in Stoat/Revolt-style APIs.
            role_perms: dict[str, dict[str, int]] = {}
            for ow in channel.permission_overwrites:
                target = role_map.get(ow.target_id)
                if not target or target == "default":
                    continue
                role_perms[target] = {"a": neutral_to_stoat(ow.allow), "d": neutral_to_stoat(ow.deny)}
            if role_perms:
                patch_payload = {"role_permissions": role_perms}
                result.actions.append(Action(self.name, "PATCH", f"/channels/{channel_id}", patch_payload))
                if options.apply:
                    self.http.patch(f"/channels/{channel_id}", json_body=patch_payload, headers=self._headers())

        # Stoat/Revolt categories are a server layout property. They are updated after channels exist.
        if template.categories:
            categories_payload: list[dict[str, Any]] = []
            for cat in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
                child_ids = [channel_map[ch.id] for ch in template.channels if ch.parent_id == cat.id and ch.id in channel_map]
                categories_payload.append({"id": new_ulid(), "title": normalize_name(cat.name, max_len=STOAT_NAME_MAX), "channels": child_ids})
            categories_patch: dict[str, Any] = {"categories": categories_payload}
            result.actions.append(Action(self.name, "PATCH", f"/servers/{server_id}", categories_patch, note="set Stoat category layout"))
            if options.apply:
                self.http.patch(f"/servers/{server_id}", json_body=categories_patch, headers=self._headers())

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

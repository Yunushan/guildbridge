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
from guildbridge.permissions import rocket_chat_to_neutral
from guildbridge.utils import hash_id, local_id, normalize_channel_name, normalize_name, without_none

from .base import (
    ExportOptions,
    ImportOptions,
    Provider,
    plan_or_apply_action,
    require_response_id,
    response_id,
)


class RocketChatProvider(Provider):
    name = "rocket.chat"
    aliases = ("rocketchat", "rocket-chat", "rocket")

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.rocket_chat_api_base,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )
        self._content_options = ContentImportOptions()
        self._content_message_ids: dict[str, str] = {}
        self._content_native_warnings: list[str] = []

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        if not self.config.rocket_chat_auth_token or not self.config.rocket_chat_user_id:
            raise ValueError("Rocket.Chat export requires ROCKET_CHAT_AUTH_TOKEN and ROCKET_CHAT_USER_ID.")
        if options.source_id:
            room_data = self.http.get("/rooms.info", params={"roomId": options.source_id}, headers=self._headers())
            rooms = [room_data.get("room", room_data)]
        else:
            rooms = self._rooms_from_response(self.http.get("/rooms.get", headers=self._headers()))
        roles = self._unwrap_list(self.http.get("/roles.list", headers=self._headers()), "roles")
        info = self.http.get("/info", headers=self._headers())
        return self._build_template(info, roles, rooms, options=options)

    def content_capabilities(self) -> ContentCapability:
        capability = ContentCapability.text_content_provider(self.name, import_supported=True, reliability_supported=True)
        capability.notes.append("Live content import sends formatted archived messages to mapped Rocket.Chat room IDs.")
        capability.notes.append(
            "Text fallback preserves attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, threads, and timestamps as formatted text."
        )
        capability.notes.append(
            "Opt-in native content import can post threaded replies, upload local files to rooms, apply reactions/pins, and use alias/avatar fields when permissions allow message impersonation."
        )
        for feature in ("attachments", "embeds", "replies", "reactions", "pins"):
            capability.import_[feature] = "supported"
        return capability

    def import_content(self, archive: ContentArchive, options: ContentImportOptions) -> ImportResult:
        if options.apply and (not self.config.rocket_chat_auth_token or not self.config.rocket_chat_user_id):
            raise ValueError("Rocket.Chat content import requires ROCKET_CHAT_AUTH_TOKEN and ROCKET_CHAT_USER_ID when --apply is used.")
        if options.apply and not options.channel_map:
            raise ValueError(
                "Rocket.Chat content import requires --channel-map for live writes so archive channel IDs map to existing room IDs."
            )
        plan = dry_run_content_import(self.name, archive, options, path_template="/chat.postMessage")
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
                json_body={"roomId": str(payload.get("channel_id") or ""), "text": content_text_from_action(action)},
                headers=self._headers(),
            )
        message_payload = self._native_message_payload(action)
        response = self.http.post(action.path, json_body=message_payload, headers=self._headers())
        self._record_native_message_response(action, response)
        message_id = response_id(response if isinstance(response, dict) else {}, "message._id", "message.id", "_id", "id")
        if message_id and int(payload.get("part_index") or 1) == 1:
            self._apply_native_followups(payload, message_id)
        return response

    def _prepare_native_content_state(self, options: ContentImportOptions) -> None:
        self._content_options = options
        self._content_message_ids = {}
        self._content_native_warnings = []

    def _native_message_payload(self, action: Action) -> dict[str, Any]:
        payload = action.payload or {}
        message_payload: dict[str, Any] = {
            "roomId": str(payload.get("channel_id") or ""),
            "text": content_text_from_action(action),
        }
        if int(payload.get("part_index") or 1) != 1:
            return message_payload
        if self._content_options.native_replies:
            reply_id = self._mapped_reply_id(payload)
            if reply_id:
                message_payload["tmid"] = reply_id
        if self._content_options.native_masquerade:
            author = payload.get("author")
            if isinstance(author, dict):
                display = author.get("display_name") or author.get("username")
                if display:
                    message_payload["alias"] = normalize_name(str(display), max_len=80, fallback="Imported")
                avatar_url = author.get("avatar_url")
                if isinstance(avatar_url, str) and avatar_url.startswith(("http://", "https://")):
                    message_payload["avatar"] = avatar_url
        if self._content_options.native_embeds:
            attachments = self._native_attachments(payload)
            if attachments:
                message_payload["attachments"] = attachments
        return message_payload

    def _native_attachments(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_embeds = payload.get("embeds")
        if not isinstance(raw_embeds, list):
            return []
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
        return attachments

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
        message_id = response_id(response, "message._id", "message.id", "_id", "id")
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
        room_id = str(payload.get("channel_id") or "").strip()
        if self._content_options.native_attachments and room_id:
            self._upload_native_files(room_id, payload)
        if self._content_options.native_pins:
            if payload.get("pinned"):
                self._safe_native_followup("pin", lambda: self.http.post("/chat.pinMessage", json_body={"messageId": message_id}, headers=self._headers()))
        if self._content_options.native_reactions:
            self._apply_native_reactions(message_id, payload)

    def _upload_native_files(self, room_id: str, payload: dict[str, Any]) -> None:
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            return
        for item in attachments[:10]:
            path = self._local_content_path(item, label="attachment")
            if not path:
                continue
            self._safe_native_followup(
                "file upload",
                lambda file_path=path: self.http.post_file(
                    f"/rooms.upload/{room_id}",
                    file_path=file_path,
                    field_name="file",
                    form_body={},
                    headers=self._headers(),
                ),
            )

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
            self._safe_native_followup(
                "reaction",
                lambda emoji_name=emoji: self.http.post(
                    "/chat.react",
                    json_body={"messageId": message_id, "emoji": emoji_name},
                    headers=self._headers(),
                ),
            )

    def _safe_native_followup(self, label: str, operation: Any) -> None:
        try:
            operation()
        except Exception as exc:  # noqa: BLE001
            self._content_native_warnings.append(f"Native {label} follow-up failed: {sanitize_text(str(exc))}")

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        if options.apply and (not self.config.rocket_chat_auth_token or not self.config.rocket_chat_user_id):
            raise ValueError("Rocket.Chat import requires ROCKET_CHAT_AUTH_TOKEN and ROCKET_CHAT_USER_ID when --apply is used.")

        result = ImportResult(provider=self.name, applied=options.apply)
        result.id_map["workspace"] = options.target_id or "rocket_chat_workspace"
        headers = self._headers()

        role_map: dict[str, str] = {"everyone": "everyone"}
        for role in sorted(template.roles, key=lambda r: (r.position is None, r.position or 0)):
            if role.id == "everyone" or role.name == "@everyone":
                continue
            role_name = normalize_channel_name(role.name, max_len=64)
            payload = {
                "name": role_name,
                "description": role.metadata.get("description") or normalize_name(role.name, max_len=120),
                "scope": "Users",
            }
            action = Action(self.name, "POST", "/roles.create", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/roles.create", json_body=payload, headers=headers),
            )
            role_map[role.id] = require_response_id(created, "Rocket.Chat role create", "role._id", "role.id", "_id", "id") if options.apply else f"dry_role_{role.id}"

        team_map: dict[str, str] = {}
        for category in sorted(template.categories, key=lambda c: (c.position is None, c.position or 0)):
            payload = {"name": normalize_channel_name(category.name, max_len=64), "type": 0}
            action = Action(self.name, "POST", "/teams.create", payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, "/teams.create", json_body=payload, headers=headers),
            )
            team_map[category.id] = require_response_id(created, "Rocket.Chat team create", "team._id", "team.id", "_id", "id") if options.apply else f"dry_team_{category.id}"

        for channel in sorted(template.channels, key=lambda c: (c.position is None, c.position or 0)):
            if channel.type == "category":
                continue
            endpoint = self._create_endpoint(channel)
            if endpoint is None:
                result.warnings.append(f"Skipping unsupported Rocket.Chat channel type {channel.type!r} for {channel.name!r}.")
                continue
            payload = without_none(
                {
                    "name": normalize_channel_name(channel.name, max_len=64),
                    "members": [],
                    "readOnly": "send_messages" not in self._effective_neutral_permissions(channel, template.roles),
                    "extraData": without_none(
                        {
                            "topic": channel.topic,
                            "teamId": team_map.get(channel.parent_id or "") if channel.parent_id else None,
                            "broadcast": channel.type == "announcement",
                            "encrypted": bool(channel.metadata.get("encrypted", False)),
                        }
                    ),
                }
            )
            action = Action(self.name, "POST", endpoint, payload)
            created = plan_or_apply_action(
                options,
                result,
                action,
                partial(self.http.post, endpoint, json_body=payload, headers=headers),
            )
            result.id_map[channel.id] = require_response_id(created, "Rocket.Chat room create", "channel._id", "channel.id", "group._id", "group.id", "room._id", "room.id", "_id", "id") if options.apply else f"dry_room_{channel.id}"
            if channel.permission_overwrites:
                result.warnings.append(
                    f"Rocket.Chat room-specific role permissions for {channel.name!r} require workspace role configuration; stored as template metadata only."
                )

        result.id_map.update(role_map)
        result.id_map.update(team_map)
        return result

    def _build_template(
        self,
        workspace: dict[str, Any],
        roles: Iterable[dict[str, Any]],
        rooms: Iterable[dict[str, Any]],
        *,
        options: ExportOptions,
    ) -> CommunityTemplate:
        out_roles = [Role(id="everyone", name="@everyone", permissions=["view_channel"])]
        for role in roles or []:
            raw_id = str(role.get("_id") or role.get("id") or role.get("name"))
            name = str(role.get("name") or role.get("description") or "role")
            if name in {"user", "anonymous"}:
                continue
            out_roles.append(
                Role(
                    id=local_id("role", self.name, raw_id),
                    name=normalize_name(name, max_len=64, fallback="role"),
                    permissions=rocket_chat_to_neutral(role.get("permissions", [])),
                    metadata=without_none({"scope": role.get("scope"), "description": role.get("description")}),
                )
            )

        channels: list[Channel] = []
        for room in rooms or []:
            room_type = self._room_type(room)
            if room_type == "unknown":
                continue
            raw_id = str(room.get("_id") or room.get("rid") or room.get("id") or room.get("name"))
            channels.append(
                Channel(
                    id=local_id("chan", self.name, raw_id),
                    name=normalize_channel_name(room.get("name") or room.get("fname") or "room", max_len=64),
                    type=room_type,  # type: ignore[arg-type]
                    topic=room.get("topic"),
                    nsfw=bool(room.get("prid") or room.get("private", False)),
                    metadata=without_none(
                        {
                            "rocket_chat_type": room.get("t"),
                            "team_id_hash": hash_id(self.name, room.get("teamId")) if room.get("teamId") else None,
                            "read_only": room.get("ro"),
                            "broadcast": room.get("broadcast"),
                            "encrypted": room.get("encrypted"),
                        }
                    ),
                )
            )

        return CommunityTemplate(
            name=normalize_name(workspace.get("siteName") or workspace.get("name") or "Rocket.Chat workspace", max_len=100),
            description=workspace.get("description"),
            source=TemplateSource(
                platform=self.name,
                id_hash=hash_id(self.name, workspace.get("uniqueId") or workspace.get("siteUrl") or options.source_id or "workspace"),
                note="exported from Rocket.Chat workspace",
            ),
            privacy=TemplatePrivacy(),
            roles=out_roles,
            channels=channels,
            warnings=[
                self.supported_warning(),
                "Rocket.Chat exports rooms/channels and workspace roles; messages, users, subscriptions, and direct messages are not exported.",
            ],
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.rocket_chat_auth_token:
            headers["X-Auth-Token"] = self.config.rocket_chat_auth_token
        if self.config.rocket_chat_user_id:
            headers["X-User-Id"] = self.config.rocket_chat_user_id
        return headers

    @staticmethod
    def _unwrap_list(value: Any, key: str) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
        return []

    @classmethod
    def _rooms_from_response(cls, value: Any) -> list[dict[str, Any]]:
        rooms = cls._unwrap_list(value, "rooms")
        if rooms:
            return rooms
        if isinstance(value, dict):
            return [room for key in ("channels", "groups") for room in cls._unwrap_list(value, key)]
        return []

    @staticmethod
    def _room_type(room: dict[str, Any]) -> str:
        room_type = str(room.get("t") or room.get("type") or "").lower()
        if room_type in {"c", "channel", "public"}:
            return "text"
        if room_type in {"p", "private", "group"}:
            return "text"
        if room_type in {"l", "livechat"}:
            return "unknown"
        return "text" if room.get("name") else "unknown"

    @staticmethod
    def _create_endpoint(channel: Channel) -> str | None:
        if channel.type in {"text", "announcement", "forum"}:
            return "/channels.create" if not channel.nsfw else "/groups.create"
        return None

    @staticmethod
    def _effective_neutral_permissions(channel: Channel, roles: list[Role]) -> list[str]:
        permissions: list[str] = []
        for role in roles:
            for permission in role.permissions:
                if permission not in permissions:
                    permissions.append(permission)
        for overwrite in channel.permission_overwrites:
            for denied in overwrite.deny:
                if denied in permissions:
                    permissions.remove(denied)
            for allowed in overwrite.allow:
                if allowed not in permissions:
                    permissions.append(allowed)
        if not permissions:
            permissions.append("send_messages")
        return permissions

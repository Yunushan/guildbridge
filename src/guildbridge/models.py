from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, get_args

from guildbridge.permissions import NEUTRAL_PERMISSIONS

SCHEMA_ID = "guildbridge.community.v1"
TEMPLATE_VERSION = "1.0"

ChannelType = Literal[
    "text",
    "voice",
    "category",
    "forum",
    "announcement",
    "stage",
    "link",
    "space",
    "unknown",
]
TargetType = Literal["role", "everyone"]
CHANNEL_TYPES = set(get_args(ChannelType))
TARGET_TYPES = set(get_args(TargetType))


@dataclass
class PermissionOverwrite:
    """Privacy-safe permission overwrite.

    User/member-specific overwrites are intentionally not represented in the
    neutral schema. Adapters should drop them unless they are converted to a
    role/everyone target.
    """

    target_type: TargetType
    target_id: str
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Role:
    id: str
    name: str
    permissions: list[str] = field(default_factory=list)
    color: int | str | None = None
    position: int | None = None
    hoist: bool = False
    mentionable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Category:
    id: str
    name: str
    position: int | None = None
    permission_overwrites: list[PermissionOverwrite] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Channel:
    id: str
    name: str
    type: ChannelType = "text"
    position: int | None = None
    parent_id: str | None = None
    topic: str | None = None
    nsfw: bool = False
    bitrate: int | None = None
    user_limit: int | None = None
    permission_overwrites: list[PermissionOverwrite] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateSource:
    platform: str
    id_hash: str | None = None
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: str | None = None


@dataclass
class TemplatePrivacy:
    redaction: str = "safe"
    exports_members: bool = False
    exports_messages: bool = False
    exports_dm_channels: bool = False
    exports_user_overwrites: bool = False
    stores_tokens: bool = False


@dataclass
class CommunityTemplate:
    name: str
    description: str | None = None
    schema: str = SCHEMA_ID
    version: str = TEMPLATE_VERSION
    source: TemplateSource = field(default_factory=lambda: TemplateSource(platform="unknown"))
    privacy: TemplatePrivacy = field(default_factory=TemplatePrivacy)
    roles: list[Role] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> CommunityTemplate:
        if data.get("schema") != SCHEMA_ID:
            raise ValueError(f"Unsupported schema: {data.get('schema')!r}; expected {SCHEMA_ID!r}")
        source_raw = data.get("source", {}) or {}
        privacy_raw = data.get("privacy", {}) or {}
        roles = [Role(**r) for r in data.get("roles", [])]
        categories = []
        for c in data.get("categories", []):
            c = dict(c)
            c["permission_overwrites"] = [PermissionOverwrite(**po) for po in c.get("permission_overwrites", [])]
            categories.append(Category(**c))
        channels = []
        for ch in data.get("channels", []):
            ch = dict(ch)
            ch["permission_overwrites"] = [PermissionOverwrite(**po) for po in ch.get("permission_overwrites", [])]
            channels.append(Channel(**ch))
        return CommunityTemplate(
            schema=data.get("schema", SCHEMA_ID),
            version=data.get("version", TEMPLATE_VERSION),
            name=data.get("name", "Imported community"),
            description=data.get("description"),
            source=TemplateSource(**source_raw),
            privacy=TemplatePrivacy(**privacy_raw),
            roles=roles,
            categories=categories,
            channels=channels,
            warnings=list(data.get("warnings", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.schema != SCHEMA_ID:
            problems.append(f"Unsupported schema {self.schema!r}; expected {SCHEMA_ID!r}")
        if self.version != TEMPLATE_VERSION:
            problems.append(f"Unsupported template version {self.version!r}; expected {TEMPLATE_VERSION!r}")
        if not isinstance(self.name, str) or not self.name.strip():
            problems.append("Template has no name")

        seen: set[str] = set()
        for collection_name, collection in (
            ("roles", self.roles),
            ("categories", self.categories),
            ("channels", self.channels),
        ):
            for item in collection:
                if not isinstance(item.id, str) or not item.id.strip():
                    problems.append(f"{collection_name[:-1].capitalize()} has an empty local id")
                    continue
                if item.id in seen:
                    problems.append(f"Duplicate local id {item.id!r} in {collection_name}")
                seen.add(item.id)
                if not isinstance(getattr(item, "name", ""), str) or not getattr(item, "name", "").strip():
                    problems.append(f"{collection_name[:-1].capitalize()} {item.id!r} has no name")

        role_ids = {role.id for role in self.roles}
        if "everyone" not in role_ids:
            problems.append("Template must include an @everyone role with id 'everyone'")

        for role in self.roles:
            self._validate_permissions(problems, f"Role {role.id!r}", role.permissions)
            if not isinstance(role.hoist, bool):
                problems.append(f"Role {role.id!r} hoist must be a boolean")
            if not isinstance(role.mentionable, bool):
                problems.append(f"Role {role.id!r} mentionable must be a boolean")
            if role.position is not None and not isinstance(role.position, int):
                problems.append(f"Role {role.id!r} position must be an integer or null")

        valid_category_ids = {cat.id for cat in self.categories}
        for cat in self.categories:
            if cat.position is not None and not isinstance(cat.position, int):
                problems.append(f"Category {cat.id!r} position must be an integer or null")
            self._validate_overwrites(problems, f"Category {cat.id!r}", cat.permission_overwrites, role_ids)

        for ch in self.channels:
            if ch.type not in CHANNEL_TYPES:
                problems.append(f"Channel {ch.name!r} has unsupported type {ch.type!r}")
            if ch.position is not None and not isinstance(ch.position, int):
                problems.append(f"Channel {ch.id!r} position must be an integer or null")
            if ch.parent_id and ch.parent_id not in valid_category_ids:
                problems.append(f"Channel {ch.name!r} references missing parent category {ch.parent_id!r}")
            if not isinstance(ch.nsfw, bool):
                problems.append(f"Channel {ch.id!r} nsfw must be a boolean")
            if ch.bitrate is not None and not isinstance(ch.bitrate, int):
                problems.append(f"Channel {ch.id!r} bitrate must be an integer or null")
            if ch.user_limit is not None and not isinstance(ch.user_limit, int):
                problems.append(f"Channel {ch.id!r} user_limit must be an integer or null")
            self._validate_overwrites(problems, f"Channel {ch.id!r}", ch.permission_overwrites, role_ids)

        if (
            self.privacy.exports_members
            or self.privacy.exports_messages
            or self.privacy.exports_dm_channels
            or self.privacy.exports_user_overwrites
            or self.privacy.stores_tokens
        ):
            problems.append("Template privacy flags indicate it may contain private user data or tokens")
        return problems

    @staticmethod
    def _validate_permissions(problems: list[str], location: str, permissions: list[str]) -> None:
        if not isinstance(permissions, list):
            problems.append(f"{location} permissions must be a list")
            return
        for permission in permissions:
            if not isinstance(permission, str) or not permission.strip():
                problems.append(f"{location} has an empty or non-string permission")
            elif permission not in NEUTRAL_PERMISSIONS:
                problems.append(f"{location} uses unknown permission {permission!r}")

    @classmethod
    def _validate_overwrites(
        cls,
        problems: list[str],
        location: str,
        overwrites: list[PermissionOverwrite],
        role_ids: set[str],
    ) -> None:
        if not isinstance(overwrites, list):
            problems.append(f"{location} permission_overwrites must be a list")
            return
        for index, overwrite in enumerate(overwrites):
            prefix = f"{location} overwrite {index}"
            if overwrite.target_type not in TARGET_TYPES:
                problems.append(f"{prefix} has unsupported target_type {overwrite.target_type!r}")
            if not isinstance(overwrite.target_id, str) or not overwrite.target_id.strip():
                problems.append(f"{prefix} has an empty target_id")
            elif overwrite.target_type == "everyone" and overwrite.target_id != "everyone":
                problems.append(f"{prefix} targets everyone but target_id is not 'everyone'")
            elif overwrite.target_type == "role" and overwrite.target_id not in role_ids:
                problems.append(f"{prefix} references missing role {overwrite.target_id!r}")
            cls._validate_permissions(problems, f"{prefix} allow", overwrite.allow)
            cls._validate_permissions(problems, f"{prefix} deny", overwrite.deny)


@dataclass
class Action:
    provider: str
    method: str
    path: str
    payload: dict[str, Any] | None = None
    note: str | None = None


@dataclass
class ImportResult:
    provider: str
    applied: bool
    actions: list[Action] = field(default_factory=list)
    id_map: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

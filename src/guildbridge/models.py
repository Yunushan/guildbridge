from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional

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


@dataclass
class PermissionOverwrite:
    """Privacy-safe permission overwrite.

    User/member-specific overwrites are intentionally not represented in the
    neutral schema. Adapters should drop them unless they are converted to a
    role/everyone target.
    """

    target_type: TargetType
    target_id: str
    allow: List[str] = field(default_factory=list)
    deny: List[str] = field(default_factory=list)


@dataclass
class Role:
    id: str
    name: str
    permissions: List[str] = field(default_factory=list)
    color: Optional[int | str] = None
    position: Optional[int] = None
    hoist: bool = False
    mentionable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Category:
    id: str
    name: str
    position: Optional[int] = None
    permission_overwrites: List[PermissionOverwrite] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Channel:
    id: str
    name: str
    type: ChannelType = "text"
    position: Optional[int] = None
    parent_id: Optional[str] = None
    topic: Optional[str] = None
    nsfw: bool = False
    bitrate: Optional[int] = None
    user_limit: Optional[int] = None
    permission_overwrites: List[PermissionOverwrite] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TemplateSource:
    platform: str
    id_hash: Optional[str] = None
    exported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    note: Optional[str] = None


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
    description: Optional[str] = None
    schema: str = SCHEMA_ID
    version: str = TEMPLATE_VERSION
    source: TemplateSource = field(default_factory=lambda: TemplateSource(platform="unknown"))
    privacy: TemplatePrivacy = field(default_factory=TemplatePrivacy)
    roles: List[Role] = field(default_factory=list)
    categories: List[Category] = field(default_factory=list)
    channels: List[Channel] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CommunityTemplate":
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

    def validate(self) -> List[str]:
        problems: List[str] = []
        seen = set()
        for collection_name, collection in (
            ("roles", self.roles),
            ("categories", self.categories),
            ("channels", self.channels),
        ):
            for item in collection:
                if item.id in seen:
                    problems.append(f"Duplicate local id {item.id!r} in {collection_name}")
                seen.add(item.id)
                if not getattr(item, "name", ""):
                    problems.append(f"{collection_name[:-1].capitalize()} {item.id!r} has no name")
        valid_category_ids = {cat.id for cat in self.categories}
        for ch in self.channels:
            if ch.parent_id and ch.parent_id not in valid_category_ids:
                problems.append(f"Channel {ch.name!r} references missing parent category {ch.parent_id!r}")
        if self.privacy.exports_members or self.privacy.exports_messages or self.privacy.stores_tokens:
            problems.append("Template privacy flags indicate it may contain private user data or tokens")
        return problems


@dataclass
class Action:
    provider: str
    method: str
    path: str
    payload: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


@dataclass
class ImportResult:
    provider: str
    applied: bool
    actions: List[Action] = field(default_factory=list)
    id_map: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

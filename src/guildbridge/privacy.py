from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from guildbridge.models import CommunityTemplate, TemplatePrivacy
from guildbridge.utils import hash_id

REDACTED_VALUE = "[redacted]"
REDACTION_WARNING = "Redacted with GuildBridge privacy-safe mode."

PRIVATE_METADATA_KEYS = frozenset(
    {
        "ownerid",
        "userid",
        "creatorid",
        "inviter",
        "inviterid",
        "members",
        "memberids",
        "membercount",
        "presencecount",
        "messages",
        "messageids",
        "lastmessageid",
        "recipients",
        "recipientids",
        "rawid",
        "rawproviderid",
        "providerid",
        "sourceid",
        "guildid",
        "serverid",
        "spaceid",
        "roomid",
        "channelid",
        "roleid",
        "invite",
        "invitecode",
    }
)
PRIVATE_KEY_FRAGMENTS = frozenset(
    {
        "accesstoken",
        "apikey",
        "authorization",
        "bottoken",
        "clientsecret",
        "cookie",
        "credential",
        "password",
        "passwd",
        "refreshtoken",
        "secret",
        "session",
        "token",
    }
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"(Authorization\s*[:=]\s*(?:Bot|Bearer)?\s*)[^\s,;&]+", re.IGNORECASE),
    re.compile(
        r"((?:access[_-]?token|api[_-]?key|bot[_-]?token|client[_-]?secret|cookie|password|passwd|refresh[_-]?token|secret|session|token)[\"'=:\s]+)[^\"'\s,;&}]+",
        re.IGNORECASE,
    ),
    re.compile(r"((?:Bot|Bearer)\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
)


def normalize_metadata_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).lower())


def is_private_metadata_key(key: object) -> bool:
    normalized = normalize_metadata_key(key)
    return normalized in PRIVATE_METADATA_KEYS or any(fragment in normalized for fragment in PRIVATE_KEY_FRAGMENTS)


def sanitize_secret_text(value: str) -> str:
    sanitized = value
    for pattern in SECRET_VALUE_PATTERNS:
        sanitized = pattern.sub(rf"\1{REDACTED_VALUE}", sanitized)
    return sanitized


def _clean_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean_metadata(v) for k, v in value.items() if not is_private_metadata_key(k)}
    if isinstance(value, list):
        return [_clean_metadata(v) for v in value]
    if isinstance(value, str):
        return sanitize_secret_text(value)
    return value


def _redact_source_id_hash(platform: str, value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{12,64}", normalized) and not normalized.isdigit():
        return normalized
    return hash_id(platform or "unknown", value)


def redact_template(template: CommunityTemplate) -> CommunityTemplate:
    """Return a privacy-safe copy of a template.

    This never exports messages, members, DMs, tokens, raw source IDs, or user
    overwrites. The neutral model already avoids those fields; this is a final
    defense for hand-edited templates.
    """

    redacted = deepcopy(template)
    if redacted.description:
        redacted.description = sanitize_secret_text(redacted.description)
    redacted.source.id_hash = _redact_source_id_hash(redacted.source.platform, redacted.source.id_hash)
    if redacted.source.note:
        redacted.source.note = sanitize_secret_text(redacted.source.note)
    redacted.privacy = TemplatePrivacy(
        redaction="safe",
        exports_members=False,
        exports_messages=False,
        exports_dm_channels=False,
        exports_user_overwrites=False,
        stores_tokens=False,
    )
    redacted.metadata = _clean_metadata(redacted.metadata or {})
    redacted.warnings = [sanitize_secret_text(str(warning)) for warning in redacted.warnings]
    for role in redacted.roles:
        role.metadata = _clean_metadata(role.metadata or {})
    for cat in redacted.categories:
        cat.metadata = _clean_metadata(cat.metadata or {})
        cat.permission_overwrites = [ow for ow in cat.permission_overwrites if not ow.target_id.startswith("user_overwrite_")]
    for ch in redacted.channels:
        if ch.topic:
            ch.topic = sanitize_secret_text(ch.topic)
        ch.metadata = _clean_metadata(ch.metadata or {})
        ch.permission_overwrites = [ow for ow in ch.permission_overwrites if not ow.target_id.startswith("user_overwrite_")]
    if REDACTION_WARNING not in redacted.warnings:
        redacted.warnings.append(REDACTION_WARNING)
    return redacted

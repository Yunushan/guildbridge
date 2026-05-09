from __future__ import annotations

from copy import deepcopy
from typing import Any

from guildbridge.models import CommunityTemplate, TemplatePrivacy

PRIVATE_METADATA_KEYS = {
    "owner_id",
    "user_id",
    "creator_id",
    "inviter",
    "members",
    "member_count",
    "presence_count",
    "messages",
    "last_message_id",
    "recipients",
    "recipient_ids",
    "token",
    "access_token",
    "bot_token",
    "session",
}


def _clean_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean_metadata(v) for k, v in value.items() if k.lower() not in PRIVATE_METADATA_KEYS}
    if isinstance(value, list):
        return [_clean_metadata(v) for v in value]
    return value


def redact_template(template: CommunityTemplate) -> CommunityTemplate:
    """Return a privacy-safe copy of a template.

    This never exports messages, members, DMs, tokens, raw source IDs, or user
    overwrites. The neutral model already avoids those fields; this is a final
    defense for hand-edited templates.
    """

    redacted = deepcopy(template)
    redacted.privacy = TemplatePrivacy(
        redaction="safe",
        exports_members=False,
        exports_messages=False,
        exports_dm_channels=False,
        exports_user_overwrites=False,
        stores_tokens=False,
    )
    redacted.metadata = _clean_metadata(redacted.metadata or {})
    for role in redacted.roles:
        role.metadata = _clean_metadata(role.metadata or {})
    for cat in redacted.categories:
        cat.metadata = _clean_metadata(cat.metadata or {})
        cat.permission_overwrites = [ow for ow in cat.permission_overwrites if not ow.target_id.startswith("user_overwrite_")]
    for ch in redacted.channels:
        ch.metadata = _clean_metadata(ch.metadata or {})
        ch.permission_overwrites = [ow for ow in ch.permission_overwrites if not ow.target_id.startswith("user_overwrite_")]
    if "Redacted with GuildBridge privacy-safe mode." not in redacted.warnings:
        redacted.warnings.append("Redacted with GuildBridge privacy-safe mode.")
    return redacted

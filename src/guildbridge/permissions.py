from __future__ import annotations

from typing import Dict, Iterable, List, Set

# Neutral permissions intentionally cover only structure-level template work.
# They are not a legal/security substitute for reviewing target permissions.
NEUTRAL_PERMISSIONS: Set[str] = {
    "administrator",
    "manage_server",
    "manage_channels",
    "manage_roles",
    "manage_permissions",
    "kick_members",
    "ban_members",
    "timeout_members",
    "view_channel",
    "send_messages",
    "read_history",
    "manage_messages",
    "mention_everyone",
    "attach_files",
    "connect",
    "speak",
    "stream",
    "video",
    "create_invite",
    "manage_webhooks",
}

DISCORD_TO_NEUTRAL: Dict[int, str] = {
    1 << 0: "create_invite",
    1 << 1: "kick_members",
    1 << 2: "ban_members",
    1 << 3: "administrator",
    1 << 4: "manage_channels",
    1 << 5: "manage_server",
    1 << 10: "view_channel",
    1 << 11: "send_messages",
    1 << 13: "manage_messages",
    1 << 15: "attach_files",
    1 << 16: "read_history",
    1 << 17: "mention_everyone",
    1 << 20: "connect",
    1 << 21: "speak",
    1 << 28: "manage_roles",
    1 << 29: "manage_webhooks",
    1 << 40: "timeout_members",
}
NEUTRAL_TO_DISCORD: Dict[str, int] = {v: k for k, v in DISCORD_TO_NEUTRAL.items()}

# Fluxer deliberately mirrors much of Discord's API surface for guilds/channels.
# Keep a separate mapping for easy edits if Fluxer changes a permission flag.
FLUXER_TO_NEUTRAL: Dict[int, str] = dict(DISCORD_TO_NEUTRAL)
NEUTRAL_TO_FLUXER: Dict[str, int] = dict(NEUTRAL_TO_DISCORD)

# Stoat/Revolt style permission flags observed in developer docs and SDKs.
STOAT_TO_NEUTRAL: Dict[int, str] = {
    1 << 0: "manage_channels",      # ManageChannel
    1 << 1: "manage_server",        # ManageServer
    1 << 2: "manage_permissions",   # ManagePermissions
    1 << 3: "manage_roles",         # ManageRole
    1 << 6: "kick_members",
    1 << 7: "ban_members",
    1 << 8: "timeout_members",
    1 << 20: "view_channel",
    1 << 21: "read_history",
    1 << 22: "send_messages",
    1 << 23: "manage_messages",
    1 << 24: "manage_webhooks",
    1 << 26: "connect",
    1 << 27: "speak",
    1 << 28: "video",
}
NEUTRAL_TO_STOAT: Dict[str, int] = {v: k for k, v in STOAT_TO_NEUTRAL.items()}


def bitset_to_names(value: int | str | None, mapping: Dict[int, str]) -> List[str]:
    try:
        bitset = int(value or 0)
    except (TypeError, ValueError):
        bitset = 0
    names: List[str] = []
    for bit, name in sorted(mapping.items(), key=lambda x: x[0]):
        if bitset & bit:
            names.append(name)
    return names


def names_to_bitset(names: Iterable[str], mapping: Dict[str, int]) -> int:
    total = 0
    for name in names:
        total |= mapping.get(name, 0)
    return total


def discord_to_neutral(value: int | str | None) -> List[str]:
    return bitset_to_names(value, DISCORD_TO_NEUTRAL)


def neutral_to_discord(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_DISCORD)


def fluxer_to_neutral(value: int | str | None) -> List[str]:
    return bitset_to_names(value, FLUXER_TO_NEUTRAL)


def neutral_to_fluxer(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_FLUXER)


def stoat_to_neutral(value: int | str | None) -> List[str]:
    return bitset_to_names(value, STOAT_TO_NEUTRAL)


def neutral_to_stoat(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_STOAT)

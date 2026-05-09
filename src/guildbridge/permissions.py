from __future__ import annotations

from collections.abc import Iterable

# Neutral permissions intentionally cover only structure-level template work.
# They are not a legal/security substitute for reviewing target permissions.
NEUTRAL_PERMISSIONS: set[str] = {
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

DISCORD_TO_NEUTRAL: dict[int, str] = {
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
NEUTRAL_TO_DISCORD: dict[str, int] = {v: k for k, v in DISCORD_TO_NEUTRAL.items()}

# Fluxer deliberately mirrors much of Discord's API surface for guilds/channels.
# Keep a separate mapping for easy edits if Fluxer changes a permission flag.
FLUXER_TO_NEUTRAL: dict[int, str] = dict(DISCORD_TO_NEUTRAL)
NEUTRAL_TO_FLUXER: dict[str, int] = dict(NEUTRAL_TO_DISCORD)

# Stoat/Revolt style permission flags observed in developer docs and SDKs.
STOAT_TO_NEUTRAL: dict[int, str] = {
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
NEUTRAL_TO_STOAT: dict[str, int] = {v: k for k, v in STOAT_TO_NEUTRAL.items()}

ROCKET_CHAT_TO_NEUTRAL: dict[str, str] = {
    "admin": "administrator",
    "view-room-administration": "manage_server",
    "edit-room": "manage_channels",
    "create-c": "manage_channels",
    "create-p": "manage_channels",
    "manage-roles": "manage_roles",
    "set-permission": "manage_permissions",
    "view-c-room": "view_channel",
    "view-p-room": "view_channel",
    "post-readonly": "send_messages",
    "send-message": "send_messages",
    "delete-message": "manage_messages",
    "mention-all": "mention_everyone",
    "upload-file": "attach_files",
}
NEUTRAL_TO_ROCKET_CHAT: dict[str, str] = {
    "administrator": "admin",
    "manage_server": "view-room-administration",
    "manage_channels": "create-c",
    "manage_roles": "manage-roles",
    "manage_permissions": "set-permission",
    "view_channel": "view-c-room",
    "send_messages": "send-message",
    "manage_messages": "delete-message",
    "mention_everyone": "mention-all",
    "attach_files": "upload-file",
}

MUMBLE_TO_NEUTRAL: dict[str, str] = {
    "write": "manage_permissions",
    "traverse": "view_channel",
    "enter": "connect",
    "speak": "speak",
    "mute-deafen": "manage_roles",
    "move": "manage_channels",
    "make-channel": "manage_channels",
    "link-channel": "manage_channels",
    "register": "manage_server",
    "kick": "kick_members",
    "ban": "ban_members",
    "text-message": "send_messages",
}
NEUTRAL_TO_MUMBLE: dict[str, str] = {v: k for k, v in MUMBLE_TO_NEUTRAL.items()}

DACCORD_TO_NEUTRAL: dict[str, str] = {
    "create_invites": "create_invite",
    "kick_members": "kick_members",
    "ban_members": "ban_members",
    "administrator": "administrator",
    "manage_channels": "manage_channels",
    "manage_space": "manage_server",
    "view_channel": "view_channel",
    "send_messages": "send_messages",
    "manage_messages": "manage_messages",
    "attach_files": "attach_files",
    "read_history": "read_history",
    "mention_everyone": "mention_everyone",
    "connect": "connect",
    "speak": "speak",
    "manage_roles": "manage_roles",
    "manage_webhooks": "manage_webhooks",
    "moderate_members": "timeout_members",
}
NEUTRAL_TO_DACCORD: dict[str, str] = {
    "create_invite": "create_invites",
    "kick_members": "kick_members",
    "ban_members": "ban_members",
    "administrator": "administrator",
    "manage_channels": "manage_channels",
    "manage_server": "manage_space",
    "view_channel": "view_channel",
    "send_messages": "send_messages",
    "manage_messages": "manage_messages",
    "attach_files": "attach_files",
    "read_history": "read_history",
    "mention_everyone": "mention_everyone",
    "connect": "connect",
    "speak": "speak",
    "manage_roles": "manage_roles",
    "manage_webhooks": "manage_webhooks",
    "timeout_members": "moderate_members",
}

MATTERMOST_TO_NEUTRAL: dict[str, str] = {
    "manage_system": "administrator",
    "system_admin": "administrator",
    "team_admin": "manage_server",
    "manage_team": "manage_server",
    "manage_team_roles": "manage_roles",
    "manage_public_channel_members": "manage_roles",
    "manage_private_channel_members": "manage_roles",
    "create_team": "manage_server",
    "create_public_channel": "manage_channels",
    "create_private_channel": "manage_channels",
    "delete_public_channel": "manage_channels",
    "delete_private_channel": "manage_channels",
    "read_channel": "view_channel",
    "create_post": "send_messages",
    "edit_others_posts": "manage_messages",
    "delete_others_posts": "manage_messages",
    "upload_file": "attach_files",
    "manage_webhooks": "manage_webhooks",
    "invite_user": "create_invite",
}
NEUTRAL_TO_MATTERMOST: dict[str, str] = {
    "administrator": "manage_system",
    "manage_server": "manage_team",
    "manage_channels": "create_public_channel",
    "manage_roles": "manage_team_roles",
    "view_channel": "read_channel",
    "send_messages": "create_post",
    "manage_messages": "delete_others_posts",
    "attach_files": "upload_file",
    "manage_webhooks": "manage_webhooks",
    "create_invite": "invite_user",
}

ZULIP_TO_NEUTRAL: dict[str, str] = {
    "role:owners": "administrator",
    "role:administrators": "administrator",
    "role:moderators": "timeout_members",
    "can_create_streams": "manage_channels",
    "can_create_groups": "manage_roles",
    "can_invite_users": "create_invite",
    "can_send_message_group": "send_messages",
}
NEUTRAL_TO_ZULIP: dict[str, str] = {
    "administrator": "role:administrators",
    "timeout_members": "role:moderators",
    "manage_channels": "can_create_streams",
    "manage_roles": "can_create_groups",
    "create_invite": "can_invite_users",
    "send_messages": "can_send_message_group",
}


def bitset_to_names(value: int | str | None, mapping: dict[int, str]) -> list[str]:
    try:
        bitset = int(value or 0)
    except (TypeError, ValueError):
        bitset = 0
    names: list[str] = []
    for bit, name in sorted(mapping.items(), key=lambda x: x[0]):
        if bitset & bit:
            names.append(name)
    return names


def names_to_bitset(names: Iterable[str], mapping: dict[str, int]) -> int:
    total = 0
    for name in names:
        total |= mapping.get(name, 0)
    return total


def discord_to_neutral(value: int | str | None) -> list[str]:
    return bitset_to_names(value, DISCORD_TO_NEUTRAL)


def neutral_to_discord(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_DISCORD)


def fluxer_to_neutral(value: int | str | None) -> list[str]:
    return bitset_to_names(value, FLUXER_TO_NEUTRAL)


def neutral_to_fluxer(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_FLUXER)


def stoat_to_neutral(value: int | str | None) -> list[str]:
    return bitset_to_names(value, STOAT_TO_NEUTRAL)


def neutral_to_stoat(names: Iterable[str]) -> int:
    return names_to_bitset(names, NEUTRAL_TO_STOAT)


def rocket_chat_to_neutral(names: Iterable[str] | str | None) -> list[str]:
    return string_names_to_neutral(names, ROCKET_CHAT_TO_NEUTRAL)


def neutral_to_rocket_chat(names: Iterable[str]) -> list[str]:
    return neutral_to_string_names(names, NEUTRAL_TO_ROCKET_CHAT)


def mumble_to_neutral(names: Iterable[str] | str | None) -> list[str]:
    return string_names_to_neutral(names, MUMBLE_TO_NEUTRAL)


def neutral_to_mumble(names: Iterable[str]) -> list[str]:
    return neutral_to_string_names(names, NEUTRAL_TO_MUMBLE)


def daccord_to_neutral(names: Iterable[str] | str | None) -> list[str]:
    return string_names_to_neutral(names, DACCORD_TO_NEUTRAL)


def neutral_to_daccord(names: Iterable[str]) -> list[str]:
    return neutral_to_string_names(names, NEUTRAL_TO_DACCORD)


def mattermost_to_neutral(names: Iterable[str] | str | None) -> list[str]:
    return string_names_to_neutral(names, MATTERMOST_TO_NEUTRAL)


def neutral_to_mattermost(names: Iterable[str]) -> list[str]:
    return neutral_to_string_names(names, NEUTRAL_TO_MATTERMOST)


def zulip_to_neutral(names: Iterable[str] | str | None) -> list[str]:
    return string_names_to_neutral(names, ZULIP_TO_NEUTRAL)


def neutral_to_zulip(names: Iterable[str]) -> list[str]:
    return neutral_to_string_names(names, NEUTRAL_TO_ZULIP)


def string_names_to_neutral(names: Iterable[str] | str | None, mapping: dict[str, str]) -> list[str]:
    if names is None:
        return []
    raw_names: Iterable[str]
    if isinstance(names, str):
        raw_names = [names]
    else:
        raw_names = names
    output: list[str] = []
    for name in raw_names:
        mapped = mapping.get(str(name))
        if mapped and mapped not in output:
            output.append(mapped)
    return output


def neutral_to_string_names(names: Iterable[str], mapping: dict[str, str]) -> list[str]:
    output: list[str] = []
    for name in names:
        mapped = mapping.get(name)
        if mapped and mapped not in output:
            output.append(mapped)
    return output

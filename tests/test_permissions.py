from __future__ import annotations

from guildbridge.permissions import (
    daccord_to_neutral,
    discord_to_neutral,
    mattermost_to_neutral,
    mumble_to_neutral,
    neutral_to_daccord,
    neutral_to_discord,
    neutral_to_fluxer,
    neutral_to_mattermost,
    neutral_to_mumble,
    neutral_to_rocket_chat,
    neutral_to_stoat,
    neutral_to_zulip,
    rocket_chat_to_neutral,
    stoat_to_neutral,
    zulip_to_neutral,
)


def test_discord_round_trip_subset() -> None:
    names = ["view_channel", "send_messages", "manage_roles"]
    bitset = neutral_to_discord(names)
    assert set(names).issubset(set(discord_to_neutral(bitset)))


def test_fluxer_mapping_is_editable_and_discord_like() -> None:
    assert neutral_to_fluxer(["view_channel"]) == neutral_to_discord(["view_channel"])


def test_stoat_mapping_subset() -> None:
    bitset = neutral_to_stoat(["view_channel", "send_messages"])
    assert set(stoat_to_neutral(bitset)) == {"view_channel", "send_messages"}


def test_rocket_chat_mapping_subset() -> None:
    names = neutral_to_rocket_chat(["view_channel", "send_messages", "manage_roles"])
    assert set(names) == {"view-c-room", "send-message", "manage-roles"}
    assert set(rocket_chat_to_neutral(names)) == {"view_channel", "send_messages", "manage_roles"}


def test_mumble_mapping_subset() -> None:
    names = neutral_to_mumble(["view_channel", "connect", "speak", "kick_members"])
    assert set(names) == {"traverse", "enter", "speak", "kick"}
    assert set(mumble_to_neutral(names)) == {"view_channel", "connect", "speak", "kick_members"}


def test_daccord_mapping_subset() -> None:
    names = neutral_to_daccord(["view_channel", "send_messages", "manage_server"])
    assert set(names) == {"view_channel", "send_messages", "manage_space"}
    assert set(daccord_to_neutral(names)) == {"view_channel", "send_messages", "manage_server"}


def test_mattermost_mapping_subset() -> None:
    names = neutral_to_mattermost(["view_channel", "send_messages", "manage_roles"])
    assert set(names) == {"read_channel", "create_post", "manage_team_roles"}
    assert set(mattermost_to_neutral(names)) == {"view_channel", "send_messages", "manage_roles"}


def test_zulip_mapping_subset() -> None:
    names = neutral_to_zulip(["administrator", "manage_channels", "create_invite"])
    assert set(names) == {"role:administrators", "can_create_streams", "can_invite_users"}
    assert set(zulip_to_neutral(names)) == {"administrator", "manage_channels", "create_invite"}

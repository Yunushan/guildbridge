from __future__ import annotations

from guildbridge.permissions import (
    discord_to_neutral,
    neutral_to_discord,
    neutral_to_fluxer,
    neutral_to_stoat,
    stoat_to_neutral,
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

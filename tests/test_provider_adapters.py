from __future__ import annotations

from typing import Any

import pytest

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpError
from guildbridge.models import Category, Channel, CommunityTemplate, Role
from guildbridge.plan import action_fingerprint
from guildbridge.providers.base import ExportOptions, ImportOptions, require_response_id, safe_int
from guildbridge.providers.daccord import DaccordProvider
from guildbridge.providers.discord import DiscordProvider
from guildbridge.providers.fluxer import FluxerProvider
from guildbridge.providers.matrix import MatrixProvider
from guildbridge.providers.mattermost import MattermostProvider
from guildbridge.providers.mumble import MumbleProvider
from guildbridge.providers.rocket_chat import RocketChatProvider
from guildbridge.providers.spacebar import SpacebarProvider
from guildbridge.providers.stoat import StoatProvider
from guildbridge.providers.zulip import ZulipProvider


class EmptyCreateHttp:
    def post(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        return {}

    def post_form(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        return {}


class DiscordNotFoundHttp:
    def __init__(self, *, channel_guild_id: str | None = None):
        self.channel_guild_id = channel_guild_id

    def get(self, path: str, **_kwargs: object) -> dict[str, Any]:
        if path.startswith("/channels/") and self.channel_guild_id:
            return {"id": path.rsplit("/", 1)[-1], "guild_id": self.channel_guild_id}
        raise HttpError("GET", f"https://discord.example.test{path}", 404, '{"message":"Unknown Guild"}')


def _template_with_role() -> CommunityTemplate:
    return CommunityTemplate(
        name="Example",
        roles=[
            Role(id="everyone", name="@everyone"),
            Role(id="role_admin", name="Admin", permissions=["manage_roles"]),
        ],
    )


def test_provider_helpers_parse_ints_and_require_ids() -> None:
    assert safe_int("4") == 4
    assert safe_int(None, 99) == 99
    assert require_response_id({"guild": {"id": 123}}, "guild create", "id", "guild.id") == "123"
    with pytest.raises(ValueError, match="guild create response did not contain an id"):
        require_response_id({"guild": {}}, "guild create", "id", "guild.id")


def test_discord_export_drops_user_overwrites_even_when_requested() -> None:
    provider = DiscordProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "guild1", "name": "Guild"},
        [{"id": "guild1", "name": "@everyone", "permissions": "0"}],
        [
            {
                "id": "channel1",
                "name": "General",
                "type": "not-an-int",
                "permission_overwrites": [
                    {"id": "user1", "type": 1, "allow": "2048", "deny": "0"},
                    {"id": "guild1", "type": 0, "allow": "1024", "deny": "0"},
                ],
            }
        ],
        source_note="test",
        options=ExportOptions(include_user_overwrites=True),
    )

    assert template.channels[0].type == "unknown"
    assert [ow.target_id for ow in template.channels[0].permission_overwrites] == ["everyone"]
    assert template.validate() == []
    assert any("cannot be represented safely" in warning for warning in template.warnings)


def test_discord_export_drops_role_overwrites_missing_from_template_roles() -> None:
    provider = DiscordProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "guild1", "name": "Guild"},
        [{"id": "guild1", "name": "@everyone", "permissions": "0"}],
        [
            {
                "id": "channel1",
                "name": "General",
                "type": 0,
                "permission_overwrites": [
                    {"id": "missing-role", "type": 0, "allow": "2048", "deny": "0"},
                    {"id": "guild1", "type": 0, "allow": "1024", "deny": "0"},
                ],
            }
        ],
        source_note="test",
        options=ExportOptions(),
    )

    assert [ow.target_id for ow in template.channels[0].permission_overwrites] == ["everyone"]
    assert template.validate() == []
    assert any("not present in the Discord template roles" in warning for warning in template.warnings)


def test_discord_live_export_reports_channel_id_instead_of_unknown_guild() -> None:
    provider = DiscordProvider(RuntimeConfig(discord_token="token"))
    provider.http = DiscordNotFoundHttp(channel_guild_id="guild123")  # type: ignore[assignment]

    with pytest.raises(ValueError, match="looks like a channel ID.*guild123"):
        provider.export_template(ExportOptions(source_id="channel123"))


def test_discord_live_export_reports_missing_bot_membership() -> None:
    provider = DiscordProvider(RuntimeConfig(discord_token="token"))
    provider.http = DiscordNotFoundHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Bot is not in this Discord server"):
        provider.export_template(ExportOptions(source_id="guild123"))


def test_fluxer_export_drops_user_overwrites_even_when_requested() -> None:
    provider = FluxerProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "guild1", "name": "Flux"},
        [{"id": "guild1", "name": "@everyone", "permissions": 0}],
        [
            {
                "id": "channel1",
                "name": "General",
                "type": 0,
                "permission_overwrites": [
                    {"id": "user1", "type": "member", "allow": 2048, "deny": 0},
                    {"id": "guild1", "type": "role", "allow": 1024, "deny": 0},
                ],
            }
        ],
        options=ExportOptions(include_user_overwrites=True),
    )

    assert [ow.target_id for ow in template.channels[0].permission_overwrites] == ["everyone"]
    assert template.validate() == []
    assert any("cannot be represented safely" in warning for warning in template.warnings)


def test_rocket_chat_build_template_exports_rooms_and_roles() -> None:
    provider = RocketChatProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"siteName": "Rocket Workspace", "uniqueId": "workspace1"},
        [{"_id": "admin", "name": "admin", "permissions": ["admin", "send-message"]}],
        [{"_id": "room1", "name": "general", "t": "c", "topic": "General chat"}],
        options=ExportOptions(),
    )

    assert template.source.platform == "rocket.chat"
    assert any(role.name == "admin" for role in template.roles)
    assert template.channels[0].name == "general"
    assert template.channels[0].type == "text"
    assert template.validate() == []


def test_mumble_build_template_exports_voice_channels_and_groups() -> None:
    provider = MumbleProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "server1", "name": "Mumble Server"},
        [{"id": "moderators", "name": "Moderators", "permissions": ["kick", "ban"]}],
        [
            {"id": "cat1", "name": "Team Rooms", "type": "category"},
            {
                "id": "chan1",
                "name": "Blue Team",
                "parent_id": "cat1",
                "acl": [{"group": "moderators", "allow": ["enter", "speak"], "deny": []}],
            },
        ],
        options=ExportOptions(),
    )

    assert template.source.platform == "mumble"
    assert template.categories[0].name == "Team Rooms"
    assert template.channels[0].type == "voice"
    assert template.channels[0].parent_id == template.categories[0].id
    assert template.validate() == []


def test_spacebar_uses_discord_like_template_shape() -> None:
    provider = SpacebarProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "guild1", "name": "Spacebar Guild"},
        [{"id": "guild1", "name": "@everyone", "permissions": "1024"}],
        [{"id": "channel1", "name": "general", "type": 0}],
        source_note="test",
        options=ExportOptions(),
    )

    assert template.source.platform == "spacebar"
    assert template.channels[0].type == "text"
    assert template.validate() == []


def test_daccord_build_template_exports_space_roles_channels_and_overwrites() -> None:
    provider = DaccordProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "space1", "name": "Daccord Space"},
        [{"id": "role1", "name": "Mods", "permissions": ["manage_channels", "manage_roles"]}],
        [
            {"id": "cat1", "name": "Main", "type": "category"},
            {
                "id": "chan1",
                "name": "General",
                "type": "text",
                "parent_id": "cat1",
                "permission_overwrites": [{"id": "role1", "type": "role", "allow": ["send_messages"], "deny": []}],
            },
        ],
        options=ExportOptions(),
    )

    assert template.source.platform == "daccord"
    assert template.categories[0].name == "Main"
    assert template.channels[0].parent_id == template.categories[0].id
    assert template.channels[0].permission_overwrites[0].allow == ["send_messages"]
    assert template.validate() == []


def test_mattermost_build_template_exports_team_channels() -> None:
    provider = MattermostProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"id": "team1", "name": "team", "display_name": "Mattermost Team"},
        [
            {"id": "chan1", "name": "town-square", "display_name": "Town Square", "type": "O", "purpose": "General"},
            {"id": "dm1", "name": "dm", "type": "D"},
        ],
        options=ExportOptions(),
    )

    assert template.source.platform == "mattermost"
    assert template.channels[0].name == "town-square"
    assert template.channels[0].topic == "General"
    assert len(template.channels) == 1
    assert template.validate() == []


def test_zulip_build_template_exports_channels_and_groups() -> None:
    provider = ZulipProvider(RuntimeConfig())
    template = provider._build_template(  # noqa: SLF001
        {"name": "Zulip Org"},
        [{"id": 12, "name": "Developers", "description": "Engineering", "members": [1, 2]}],
        [{"stream_id": 99, "name": "general", "description": "General chat", "invite_only": False}],
        options=ExportOptions(source_id="zulip.example.test"),
    )

    assert template.source.platform == "zulip"
    assert any(role.name == "Developers" for role in template.roles)
    assert template.channels[0].name == "general"
    assert template.channels[0].topic == "General chat"
    assert template.validate() == []


def test_discord_apply_requires_role_create_id() -> None:
    provider = DiscordProvider(RuntimeConfig(discord_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Discord role create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(target_id="guild1", apply=True))


def test_fluxer_apply_requires_role_create_id() -> None:
    provider = FluxerProvider(RuntimeConfig(fluxer_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Fluxer role create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(target_id="guild1", apply=True))


def test_matrix_apply_requires_room_id() -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Matrix space create response did not contain an id"):
        provider.import_template(CommunityTemplate(name="Example"), ImportOptions(apply=True))


def test_stoat_apply_requires_server_id() -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Stoat server create response did not contain an id"):
        provider.import_template(CommunityTemplate(name="Example"), ImportOptions(apply=True))


def test_stoat_dry_run_category_layout_is_deterministic() -> None:
    provider = StoatProvider(RuntimeConfig())
    template = CommunityTemplate(
        name="Example",
        roles=[Role(id="everyone", name="@everyone")],
        categories=[Category(id="cat_general", name="General")],
        channels=[Channel(id="chan_general", name="general", parent_id="cat_general")],
    )

    first = provider.import_template(template, ImportOptions(target_id="server1"))
    second = provider.import_template(template, ImportOptions(target_id="server1"))

    assert action_fingerprint(first.actions) == action_fingerprint(second.actions)
    assert first.actions[-1].payload == second.actions[-1].payload


def test_spacebar_apply_requires_role_create_id() -> None:
    provider = SpacebarProvider(RuntimeConfig(spacebar_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Spacebar role create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(target_id="guild1", apply=True))


def test_daccord_apply_requires_space_create_id() -> None:
    provider = DaccordProvider(RuntimeConfig(daccord_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Daccord space create response did not contain an id"):
        provider.import_template(CommunityTemplate(name="Example"), ImportOptions(apply=True))


def test_rocket_chat_apply_requires_role_create_id() -> None:
    provider = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Rocket.Chat role create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(apply=True))


def test_mumble_apply_requires_group_create_id() -> None:
    provider = MumbleProvider(RuntimeConfig(mumble_api_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Mumble group create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(target_id="server1", apply=True))


def test_mattermost_apply_requires_team_create_id() -> None:
    provider = MattermostProvider(RuntimeConfig(mattermost_token="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Mattermost team create response did not contain an id"):
        provider.import_template(CommunityTemplate(name="Example"), ImportOptions(apply=True))


def test_zulip_apply_requires_group_create_id() -> None:
    provider = ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="token"))
    provider.http = EmptyCreateHttp()  # type: ignore[assignment]

    with pytest.raises(ValueError, match="Zulip user group create response did not contain an id"):
        provider.import_template(_template_with_role(), ImportOptions(apply=True))


def test_missing_parent_category_is_reported_in_dry_runs() -> None:
    provider = DiscordProvider(RuntimeConfig())
    template = CommunityTemplate(
        name="Example",
        roles=[Role(id="everyone", name="@everyone")],
        channels=[Channel(id="chan1", name="General", parent_id="missing-category")],
    )

    result = provider.import_template(template, ImportOptions(target_id="guild1"))

    assert any("references missing category" in warning for warning in result.warnings)

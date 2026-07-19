from __future__ import annotations

from typing import Any

import pytest

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpError
from guildbridge.models import Category, Channel, CommunityTemplate, Role
from guildbridge.plan import action_fingerprint
from guildbridge.providers import get_provider, provider_names
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


class RecordingCreateHttp:
    """Offline provider responses for successful template-write contract tests."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object] | None, dict[str, str] | None]] = []
        self.post_forms: list[tuple[str, dict[str, object] | None, dict[str, str] | None]] = []
        self.puts: list[tuple[str, dict[str, object] | None, dict[str, str] | None]] = []

    def post(
        self,
        path: str,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.posts.append((path, json_body, headers))
        index = len(self.posts)
        if path == "/roles.create":
            return {"role": {"_id": f"role-{index}"}}
        if path == "/teams.create":
            return {"team": {"_id": f"team-{index}"}}
        if path == "/teams":
            return {"id": f"team-{index}"}
        if path == "/guilds":
            return {"id": f"guild-{index}"}
        if path == "/spaces":
            return {"data": {"id": f"space-{index}"}}
        if path in {"/channels.create", "/groups.create"}:
            return {"channel": {"_id": f"room-{index}"}}
        if path == "/channels":
            return {"id": f"channel-{index}"}
        if path.endswith("/roles"):
            if path.startswith("/spaces/"):
                return {"data": {"id": f"role-{index}"}}
            return {"id": f"role-{index}"}
        if path.endswith("/channels"):
            if path.startswith("/spaces/"):
                return {"data": {"id": f"channel-{index}"}}
            return {"id": f"channel-{index}"}
        if path == "/_matrix/client/v3/createRoom":
            return {"room_id": f"!room-{index}:example.org"}
        return {"id": f"id-{index}"}

    def post_form(
        self,
        path: str,
        form_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.post_forms.append((path, form_body, headers))
        if path == "/user_groups/create":
            return {"group_id": f"group-{len(self.post_forms)}"}
        return {"result": "success"}

    def put(
        self,
        path: str,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        self.puts.append((path, json_body, headers))
        return {"event_id": f"event-{len(self.puts)}"}


class DiscordNotFoundHttp:
    def __init__(self, *, channel_guild_id: str | None = None):
        self.channel_guild_id = channel_guild_id

    def get(self, path: str, **_kwargs: object) -> dict[str, Any]:
        if path.startswith("/channels/") and self.channel_guild_id:
            return {"id": path.rsplit("/", 1)[-1], "guild_id": self.channel_guild_id}
        raise HttpError("GET", f"https://discord.example.test{path}", 404, '{"message":"Unknown Guild"}')


class ExportHttp:
    """Recorded provider responses for authenticated export-path tests."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, path: str, **_kwargs: object) -> object:
        self.calls.append(path)
        return self.responses[path]


class MatrixHierarchyFallbackHttp:
    """Simulate an older Matrix server without the space hierarchy endpoint."""

    def __init__(self, state: list[dict[str, Any]]) -> None:
        self.state = state
        self.calls: list[str] = []

    def get(self, path: str, **_kwargs: object) -> object:
        self.calls.append(path)
        if path.endswith("/hierarchy"):
            raise HttpError("GET", f"https://matrix.example.test{path}", 404, "{}")
        return self.state


def _template_with_role() -> CommunityTemplate:
    return CommunityTemplate(
        name="Example",
        roles=[
            Role(id="everyone", name="@everyone"),
            Role(id="role_admin", name="Admin", permissions=["manage_roles"]),
        ],
    )


def _template_with_category_and_channel() -> CommunityTemplate:
    return CommunityTemplate(
        name="Example",
        roles=[
            Role(id="everyone", name="@everyone"),
            Role(id="role_admin", name="Admin", permissions=["manage_roles"], position=1),
        ],
        categories=[Category(id="cat_general", name="General", position=0)],
        channels=[
            Channel(
                id="chan_general",
                name="general",
                type="text",
                position=0,
                parent_id="cat_general",
                topic="General discussion",
            )
        ],
    )


def test_every_provider_export_fails_closed_without_configured_credentials() -> None:
    for provider_name in provider_names():
        provider = get_provider(provider_name, RuntimeConfig())
        with pytest.raises(ValueError):
            provider.export_template(ExportOptions(source_id="contract-source"))


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


def test_fluxer_live_export_uses_guild_role_and_channel_routes() -> None:
    provider = FluxerProvider(RuntimeConfig(fluxer_token="token"))
    http = ExportHttp(
        {
            "/guilds/guild1": {"id": "guild1", "name": "Fluxer Guild"},
            "/guilds/guild1/roles": {"roles": [{"id": "guild1", "name": "@everyone", "permissions": 0}]},
            "/guilds/guild1/channels": {"channels": [{"id": "chan1", "name": "general", "type": 0}]},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="guild1"))

    assert http.calls == ["/guilds/guild1", "/guilds/guild1/roles", "/guilds/guild1/channels"]
    assert template.name == "Fluxer Guild"
    assert template.channels[0].name == "general"


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


def test_mumble_live_export_reads_server_group_and_channel_routes() -> None:
    provider = MumbleProvider(RuntimeConfig(mumble_api_token="token"))
    http = ExportHttp(
        {
            "/servers/server1": {"id": "server1", "name": "Mumble Server"},
            "/servers/server1/groups": {"groups": [{"id": "mods", "name": "Moderators", "permissions": []}]},
            "/servers/server1/channels": {"channels": [{"id": "chan1", "name": "Lobby", "type": "voice"}]},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="server1"))

    assert http.calls == ["/servers/server1", "/servers/server1/groups", "/servers/server1/channels"]
    assert template.name == "Mumble Server"
    assert template.channels[0].name == "Lobby"


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


def test_daccord_live_export_reads_space_resources_and_channel_permissions() -> None:
    provider = DaccordProvider(RuntimeConfig(daccord_token="token"))
    http = ExportHttp(
        {
            "/spaces/space1": {"data": {"id": "space1", "name": "Daccord Space"}},
            "/spaces/space1/roles": {"data": [{"id": "space1", "name": "@everyone", "permissions": []}]},
            "/spaces/space1/channels": {"data": [{"id": "chan1", "name": "general", "type": "text"}]},
            "/channels/chan1/permissions": {"data": []},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="space1"))

    assert http.calls == [
        "/spaces/space1",
        "/spaces/space1/roles",
        "/spaces/space1/channels",
        "/channels/chan1/permissions",
    ]
    assert template.name == "Daccord Space"
    assert template.channels[0].type == "text"


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


def test_mattermost_live_export_reads_team_and_channel_routes() -> None:
    provider = MattermostProvider(RuntimeConfig(mattermost_token="token"))
    http = ExportHttp(
        {
            "/teams/team1": {"id": "team1", "name": "engineering", "display_name": "Engineering"},
            "/teams/team1/channels": [{"id": "chan1", "name": "town-square", "display_name": "Town Square", "type": "O"}],
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="team1"))

    assert http.calls == ["/teams/team1", "/teams/team1/channels"]
    assert template.name == "Engineering"
    assert template.channels[0].name == "town-square"


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


def test_zulip_live_export_reads_stream_and_group_routes() -> None:
    provider = ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="token"))
    http = ExportHttp(
        {
            "/streams": {"streams": [{"stream_id": 1, "name": "general", "description": "General"}]},
            "/user_groups": {"user_groups": [{"id": 2, "name": "Admins", "description": "Operators"}]},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="zulip.example.test"))

    assert http.calls == ["/streams", "/user_groups"]
    assert template.channels[0].name == "general"
    assert any(role.name == "Admins" for role in template.roles)


def test_matrix_live_export_reads_space_hierarchy() -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    http = ExportHttp(
        {
            "/_matrix/client/v1/rooms/%21space%3Aexample.org/hierarchy": {
                "rooms": [
                    {"room_id": "!space:example.org", "room_type": "m.space", "name": "Engineering"},
                    {"room_id": "!general:example.org", "name": "General", "topic": "Announcements"},
                ]
            }
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="!space:example.org"))

    assert http.calls == ["/_matrix/client/v1/rooms/%21space%3Aexample.org/hierarchy"]
    assert template.name == "Engineering"
    assert template.channels[0].topic == "Announcements"


def test_matrix_live_export_falls_back_to_room_state_when_hierarchy_is_unavailable() -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    http = MatrixHierarchyFallbackHttp(
        [
            {"type": "m.room.name", "content": {"name": "Incident room"}},
            {"type": "m.room.topic", "content": {"topic": "Operational updates"}},
        ]
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="!incident:example.org"))

    assert http.calls == [
        "/_matrix/client/v1/rooms/%21incident%3Aexample.org/hierarchy",
        "/_matrix/client/v3/rooms/%21incident%3Aexample.org/state",
    ]
    assert template.name == "Incident room"
    assert template.categories == []
    assert template.channels[0].topic == "Operational updates"
    assert any("Hierarchy API was unavailable (404)" in warning for warning in template.warnings)


def test_matrix_url_helpers_preserve_host_and_escape_room_ids() -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_base_url="https://matrix.example.test:8448"))

    assert provider._server_name_from_base_url() == "matrix.example.test"  # noqa: SLF001
    assert provider._q("!space:example.org") == "%21space%3Aexample.org"  # noqa: SLF001


def test_stoat_live_export_reads_embedded_server_roles_categories_and_channels() -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="token"))
    http = ExportHttp(
        {
            "/servers/server1": {
                "_id": "server1",
                "name": "Stoat Server",
                "default_permissions": 0,
                "roles": {"mods": {"name": "Moderators", "permissions": {"a": 0}, "rank": 1}},
                "categories": [{"id": "cat1", "title": "General", "channels": ["chan1"]}],
                "channels": [{"_id": "chan1", "name": "general", "channel_type": "TextChannel"}],
            }
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="server1"))

    assert http.calls == ["/servers/server1"]
    assert template.name == "Stoat Server"
    assert template.categories[0].name == "General"
    assert template.channels[0].parent_id == template.categories[0].id
    assert any(role.name == "Moderators" for role in template.roles)


def test_rocket_chat_live_export_reads_selected_room_roles_and_workspace_info() -> None:
    provider = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    http = ExportHttp(
        {
            "/rooms.info": {"room": {"_id": "room1", "name": "general", "t": "c"}},
            "/roles.list": {"roles": [{"_id": "admin", "name": "admin", "permissions": ["admin"]}]},
            "/info": {"siteName": "Rocket Workspace", "uniqueId": "workspace1"},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions(source_id="room1"))

    assert http.calls == ["/rooms.info", "/roles.list", "/info"]
    assert template.name == "Rocket Workspace"
    assert template.channels[0].name == "general"


def test_rocket_chat_live_export_normalizes_channels_and_groups_and_skips_livechat() -> None:
    provider = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    http = ExportHttp(
        {
            "/rooms.get": {
                "channels": [{"_id": "public", "name": "general", "t": "c"}],
                "groups": [
                    {"_id": "private", "name": "operators", "t": "p"},
                    {"_id": "livechat", "name": "support", "t": "l"},
                ],
            },
            "/roles.list": {"roles": [{"_id": "user", "name": "user"}, {"_id": "owner", "name": "owner"}]},
            "/info": {"siteName": "Rocket Workspace", "uniqueId": "workspace1"},
        }
    )
    provider.http = http  # type: ignore[assignment]

    template = provider.export_template(ExportOptions())

    assert http.calls == ["/rooms.get", "/roles.list", "/info"]
    assert [channel.name for channel in template.channels] == ["general", "operators"]
    assert [role.name for role in template.roles] == ["@everyone", "owner"]


def test_matrix_template_dry_run_plans_space_category_room_and_links() -> None:
    provider = MatrixProvider(RuntimeConfig())

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_name="Example space"))

    assert result.applied is False
    assert result.id_map["space"] == "!dryMainSpace:example.org"
    assert result.id_map["chan_general"].startswith("!dryRoom")
    assert [action.method for action in result.actions] == ["POST", "POST", "PUT", "PUT", "POST", "PUT", "PUT"]
    assert result.actions[0].path == "/_matrix/client/v3/createRoom"
    assert any("global server roles" in warning for warning in result.warnings)


def test_matrix_template_apply_uses_room_creation_and_space_link_contracts() -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_name="Example space", apply=True))

    assert result.applied is True
    assert result.id_map["space"] == "!room-1:example.org"
    assert result.id_map["chan_general"] == "!room-3:example.org"
    assert [path for path, _body, _headers in http.posts] == [
        "/_matrix/client/v3/createRoom",
        "/_matrix/client/v3/createRoom",
        "/_matrix/client/v3/createRoom",
    ]
    assert len(http.puts) == 4
    assert all("/state/m.space." in path for path, _body, _headers in http.puts)


def test_rocket_chat_template_dry_run_plans_roles_teams_and_rooms() -> None:
    provider = RocketChatProvider(RuntimeConfig())

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_id="workspace1"))

    assert result.applied is False
    assert result.id_map["role_admin"] == "dry_role_role_admin"
    assert result.id_map["cat_general"] == "dry_team_cat_general"
    assert result.id_map["chan_general"] == "dry_room_chan_general"
    assert [action.path for action in result.actions] == ["/roles.create", "/teams.create", "/channels.create"]


def test_rocket_chat_template_apply_uses_role_team_and_room_contracts() -> None:
    provider = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_id="workspace1", apply=True))

    assert result.applied is True
    assert result.id_map["role_admin"] == "role-1"
    assert result.id_map["cat_general"] == "team-2"
    assert result.id_map["chan_general"] == "room-3"
    assert [path for path, _body, _headers in http.posts] == ["/roles.create", "/teams.create", "/channels.create"]
    channel_payload = http.posts[-1][1]
    assert channel_payload is not None
    assert channel_payload["extraData"] == {"topic": "General discussion", "teamId": "team-2", "broadcast": False, "encrypted": False}


def test_fluxer_template_apply_uses_guild_role_and_channel_contracts() -> None:
    provider = FluxerProvider(RuntimeConfig(fluxer_token="token"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_name="Example", apply=True))

    assert result.applied is True
    assert result.id_map["guild"] == "guild-1"
    assert result.id_map["role_admin"] == "role-2"
    assert result.id_map["cat_general"] == "channel-3"
    assert result.id_map["chan_general"] == "channel-4"
    assert [path for path, _body, _headers in http.posts] == [
        "/guilds",
        "/guilds/guild-1/roles",
        "/guilds/guild-1/channels",
        "/guilds/guild-1/channels",
    ]


def test_daccord_template_apply_uses_space_role_and_channel_contracts() -> None:
    provider = DaccordProvider(RuntimeConfig(daccord_token="token"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_name="Example", apply=True))

    assert result.applied is True
    assert result.id_map["space"] == "space-1"
    assert result.id_map["role_admin"] == "role-2"
    assert result.id_map["cat_general"] == "channel-3"
    assert result.id_map["chan_general"] == "channel-4"
    assert [path for path, _body, _headers in http.posts] == [
        "/spaces",
        "/spaces/space-1/roles",
        "/spaces/space-1/channels",
        "/spaces/space-1/channels",
    ]


def test_zulip_template_apply_uses_group_and_subscription_contracts() -> None:
    provider = ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="token"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_id="organization", apply=True))

    assert result.applied is True
    assert result.id_map["role_admin"] == "group-1"
    assert result.id_map["chan_general"] == "zulip_channel:general"
    assert [path for path, _body, _headers in http.post_forms] == ["/user_groups/create", "/users/me/subscriptions"]


def test_mattermost_template_apply_uses_team_and_channel_contracts() -> None:
    provider = MattermostProvider(RuntimeConfig(mattermost_token="token"))
    http = RecordingCreateHttp()
    provider.http = http  # type: ignore[assignment]

    result = provider.import_template(_template_with_category_and_channel(), ImportOptions(target_name="Example", apply=True))

    assert result.applied is True
    assert result.id_map["team"] == "team-1"
    assert result.id_map["chan_general"] == "channel-2"
    assert [path for path, _body, _headers in http.posts] == ["/teams", "/channels"]


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

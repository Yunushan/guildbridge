from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from guildbridge.config import RuntimeConfig
from guildbridge.models import Category, Channel, CommunityTemplate, PermissionOverwrite, Role
from guildbridge.providers.base import ImportOptions, Provider
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


def contract_template() -> CommunityTemplate:
    return CommunityTemplate(
        name="Contract Example",
        roles=[
            Role(id="everyone", name="@everyone", permissions=["view_channel"]),
            Role(id="role_admin", name="Admins", permissions=["manage_channels", "manage_roles"], position=1),
        ],
        categories=[
            Category(
                id="cat_general",
                name="General",
                position=1,
                permission_overwrites=[
                    PermissionOverwrite(
                        target_type="role",
                        target_id="role_admin",
                        allow=["view_channel"],
                    )
                ],
            )
        ],
        channels=[
            Channel(
                id="chan_general",
                name="general",
                type="text",
                position=1,
                parent_id="cat_general",
                topic="Announcements and chat",
                permission_overwrites=[
                    PermissionOverwrite(
                        target_type="role",
                        target_id="role_admin",
                        allow=["send_messages"],
                    )
                ],
            ),
            Channel(id="chan_voice", name="Voice", type="voice", position=2, parent_id="cat_general"),
        ],
    )


class RecordingHttp:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.counter = 0

    def post(self, path: str, *, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append({"method": "POST", "path": path, "payload": json_body, "headers": headers})
        return self._response(path)

    def post_form(self, path: str, *, form_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append({"method": "POST", "path": path, "payload": form_body, "headers": headers})
        return self._response(path)

    def patch(self, path: str, *, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append({"method": "PATCH", "path": path, "payload": json_body, "headers": headers})
        return self._response(path)

    def put(self, path: str, *, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append({"method": "PUT", "path": path, "payload": json_body, "headers": headers})
        return self._response(path)

    def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "GET", "path": path, "payload": None, "headers": kwargs.get("headers")})
        return self._response(path)

    def _response(self, path: str) -> dict[str, Any]:
        self.counter += 1
        resource_id = f"id_{self.counter}"
        if "createRoom" in path:
            return {"room_id": f"!room{self.counter}:example.org"}
        if "/servers/create" in path:
            return {"_id": resource_id}
        if "/channels" in path:
            return {"id": resource_id, "_id": resource_id, "channel": {"id": resource_id, "_id": resource_id}}
        if "/roles" in path:
            return {"id": resource_id, "_id": resource_id, "role": {"id": resource_id, "_id": resource_id}}
        if path == "/guilds":
            return {"id": resource_id, "guild": {"id": resource_id, "_id": resource_id}}
        return {"id": resource_id, "_id": resource_id}


class ExplodingHttp(RecordingHttp):
    def post(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run attempted HTTP POST")

    def post_form(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run attempted HTTP POST")

    def patch(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run attempted HTTP PATCH")

    def put(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("dry-run attempted HTTP PUT")


class FailAfterWriteHttp(RecordingHttp):
    def __init__(self, fail_on_write: int) -> None:
        super().__init__()
        self.fail_on_write = fail_on_write
        self.write_attempts = 0

    def _fail_if_needed(self) -> None:
        self.write_attempts += 1
        if self.write_attempts == self.fail_on_write:
            raise RuntimeError("simulated provider write failure")

    def post(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._fail_if_needed()
        return super().post(*args, **kwargs)

    def post_form(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._fail_if_needed()
        return super().post_form(*args, **kwargs)

    def patch(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._fail_if_needed()
        return super().patch(*args, **kwargs)

    def put(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._fail_if_needed()
        return super().put(*args, **kwargs)


@dataclass(frozen=True)
class ProviderCase:
    label: str
    factory: Callable[[], Provider]
    dry_options: ImportOptions
    apply_options: ImportOptions
    token: str


PROVIDER_CASES = (
    ProviderCase(
        "discord",
        lambda: DiscordProvider(RuntimeConfig(discord_token="discord-secret-token")),
        ImportOptions(target_id="guild1"),
        ImportOptions(target_id="guild1", apply=True),
        "discord-secret-token",
    ),
    ProviderCase(
        "fluxer",
        lambda: FluxerProvider(RuntimeConfig(fluxer_token="fluxer-secret-token")),
        ImportOptions(target_name="Flux Copy"),
        ImportOptions(target_name="Flux Copy", apply=True),
        "fluxer-secret-token",
    ),
    ProviderCase(
        "matrix",
        lambda: MatrixProvider(RuntimeConfig(matrix_access_token="matrix-secret-token", matrix_server_name="example.org")),
        ImportOptions(target_name="Matrix Copy"),
        ImportOptions(target_name="Matrix Copy", apply=True),
        "matrix-secret-token",
    ),
    ProviderCase(
        "stoat",
        lambda: StoatProvider(RuntimeConfig(stoat_token="stoat-secret-token")),
        ImportOptions(target_name="Stoat Copy"),
        ImportOptions(target_name="Stoat Copy", apply=True),
        "stoat-secret-token",
    ),
    ProviderCase(
        "spacebar",
        lambda: SpacebarProvider(RuntimeConfig(spacebar_token="spacebar-secret-token")),
        ImportOptions(target_id="guild1"),
        ImportOptions(target_id="guild1", apply=True),
        "spacebar-secret-token",
    ),
    ProviderCase(
        "daccord",
        lambda: DaccordProvider(RuntimeConfig(daccord_token="daccord-secret-token")),
        ImportOptions(target_name="Daccord Copy"),
        ImportOptions(target_name="Daccord Copy", apply=True),
        "daccord-secret-token",
    ),
    ProviderCase(
        "rocket.chat",
        lambda: RocketChatProvider(
            RuntimeConfig(rocket_chat_auth_token="rocket-secret-token", rocket_chat_user_id="rocket-user")
        ),
        ImportOptions(target_name="Rocket Copy"),
        ImportOptions(target_name="Rocket Copy", apply=True),
        "rocket-secret-token",
    ),
    ProviderCase(
        "mumble",
        lambda: MumbleProvider(RuntimeConfig(mumble_api_token="mumble-secret-token")),
        ImportOptions(target_name="Mumble Copy"),
        ImportOptions(target_name="Mumble Copy", apply=True),
        "mumble-secret-token",
    ),
    ProviderCase(
        "mattermost",
        lambda: MattermostProvider(RuntimeConfig(mattermost_token="mattermost-secret-token")),
        ImportOptions(target_name="Mattermost Copy"),
        ImportOptions(target_name="Mattermost Copy", apply=True),
        "mattermost-secret-token",
    ),
    ProviderCase(
        "zulip",
        lambda: ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="zulip-secret-token")),
        ImportOptions(target_name="Zulip Copy"),
        ImportOptions(target_name="Zulip Copy", apply=True),
        "zulip-secret-token",
    ),
)


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.label)
def test_provider_dry_run_never_calls_http_and_hides_tokens(case: ProviderCase) -> None:
    provider = case.factory()
    provider.http = ExplodingHttp()  # type: ignore[attr-defined]

    result = provider.import_template(contract_template(), case.dry_options)

    assert result.provider == case.label
    assert result.applied is False
    assert result.actions
    serialized = json.dumps(result.to_dict())
    assert case.token not in serialized


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.label)
def test_provider_apply_actions_match_http_writes(case: ProviderCase) -> None:
    provider = case.factory()
    http = RecordingHttp()
    provider.http = http  # type: ignore[attr-defined]

    result = provider.import_template(contract_template(), case.apply_options)

    write_actions = [action for action in result.actions if action.method in {"POST", "PATCH", "PUT", "DELETE"}]
    assert result.applied is True
    assert len(http.calls) == len(write_actions)
    assert http.calls
    for call, action in zip(http.calls, write_actions, strict=True):
        assert call["method"] == action.method
        assert call["path"] == action.path
        assert call["payload"] == action.payload


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.label)
def test_provider_apply_records_journal_for_each_write(case: ProviderCase) -> None:
    provider = case.factory()
    provider.http = RecordingHttp()  # type: ignore[attr-defined]
    journal = MemoryJournal()
    options = ImportOptions(
        target_id=case.apply_options.target_id,
        target_name=case.apply_options.target_name,
        apply=True,
        audit_log_reason=case.apply_options.audit_log_reason,
        journal=journal,
    )

    result = provider.import_template(contract_template(), options)

    assert journal.recorded == len(result.actions)
    assert journal.succeeded == list(range(len(result.actions)))
    assert journal.failed == []


@pytest.mark.parametrize("case", PROVIDER_CASES, ids=lambda case: case.label)
def test_provider_apply_records_failed_write_in_journal(case: ProviderCase) -> None:
    provider = case.factory()
    provider.http = FailAfterWriteHttp(fail_on_write=2)  # type: ignore[attr-defined]
    journal = MemoryJournal()
    options = ImportOptions(
        target_id=case.apply_options.target_id,
        target_name=case.apply_options.target_name,
        apply=True,
        audit_log_reason=case.apply_options.audit_log_reason,
        journal=journal,
    )

    with pytest.raises(RuntimeError, match="simulated provider write failure"):
        provider.import_template(contract_template(), options)

    assert journal.recorded == 2
    assert journal.succeeded == [0]
    assert journal.failed == [(1, "simulated provider write failure")]


@dataclass
class MemoryJournal:
    recorded: int = 0
    succeeded: list[int] | None = None
    failed: list[tuple[int, str]] | None = None

    def __post_init__(self) -> None:
        self.succeeded = []
        self.failed = []

    def record_action(self, _action: object) -> int:
        index = self.recorded
        self.recorded += 1
        return index

    def action_succeeded(self, index: int) -> None:
        if self.succeeded is None:
            raise AssertionError("journal not initialized")
        self.succeeded.append(index)

    def action_failed(self, index: int, error: BaseException | str) -> None:
        if self.failed is None:
            raise AssertionError("journal not initialized")
        self.failed.append((index, str(error)))

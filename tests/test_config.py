from __future__ import annotations

import pytest

from guildbridge.config import RuntimeConfig, parse_positive_int


def test_parse_positive_int_defaults_and_bounds() -> None:
    assert parse_positive_int(None, default=30) == 30
    assert parse_positive_int("5", default=30) == 5
    assert parse_positive_int("0", default=5, allow_zero=True) == 0
    with pytest.raises(ValueError):
        parse_positive_int("0", default=30)
    with pytest.raises(ValueError):
        parse_positive_int("nope", default=30)


def test_runtime_config_reads_retry_and_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUILDBRIDGE_REQUEST_TIMEOUT", "12")
    monkeypatch.setenv("GUILDBRIDGE_MAX_RETRIES", "2")
    monkeypatch.setenv("GUILDBRIDGE_USER_AGENT", "GuildBridge/Test")
    monkeypatch.setenv("ROCKET_CHAT_API_BASE", "https://chat.example.test/api/v1")
    monkeypatch.setenv("ROCKET_CHAT_AUTH_TOKEN", "rocket-token")
    monkeypatch.setenv("ROCKET_CHAT_USER_ID", "rocket-user")
    monkeypatch.setenv("MUMBLE_API_BASE", "https://mumble.example.test/api/v1")
    monkeypatch.setenv("MUMBLE_API_TOKEN", "mumble-token")

    config = RuntimeConfig.from_env()

    assert config.request_timeout == 12
    assert config.max_retries == 2
    assert config.user_agent == "GuildBridge/Test"
    assert config.rocket_chat_api_base == "https://chat.example.test/api/v1"
    assert config.rocket_chat_auth_token == "rocket-token"
    assert config.rocket_chat_user_id == "rocket-user"
    assert config.mumble_api_base == "https://mumble.example.test/api/v1"
    assert config.mumble_api_token == "mumble-token"

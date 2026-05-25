from __future__ import annotations

import os
from pathlib import Path

import pytest

from guildbridge.config import (
    RuntimeConfig,
    load_env_files,
    parse_positive_int,
    user_env_file,
    write_env_values,
)


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
    monkeypatch.setenv("SPACEBAR_API_BASE", "https://spacebar.example.test/api/v9")
    monkeypatch.setenv("SPACEBAR_BOT_TOKEN", "spacebar-token")
    monkeypatch.setenv("DACCORD_API_BASE", "https://daccord.example.test/api/v1")
    monkeypatch.setenv("DACCORD_TOKEN", "daccord-token")
    monkeypatch.setenv("DACCORD_AUTH_SCHEME", "Bearer")
    monkeypatch.setenv("MATTERMOST_API_BASE", "https://mattermost.example.test/api/v4")
    monkeypatch.setenv("MATTERMOST_TOKEN", "mattermost-token")
    monkeypatch.setenv("ZULIP_API_BASE", "https://zulip.example.test/api/v1")
    monkeypatch.setenv("ZULIP_EMAIL", "bot@example.test")
    monkeypatch.setenv("ZULIP_API_KEY", "zulip-token")

    config = RuntimeConfig.from_env()

    assert config.request_timeout == 12
    assert config.max_retries == 2
    assert config.user_agent == "GuildBridge/Test"
    assert config.rocket_chat_api_base == "https://chat.example.test/api/v1"
    assert config.rocket_chat_auth_token == "rocket-token"
    assert config.rocket_chat_user_id == "rocket-user"
    assert config.mumble_api_base == "https://mumble.example.test/api/v1"
    assert config.mumble_api_token == "mumble-token"
    assert config.spacebar_api_base == "https://spacebar.example.test/api/v9"
    assert config.spacebar_token == "spacebar-token"
    assert config.daccord_api_base == "https://daccord.example.test/api/v1"
    assert config.daccord_token == "daccord-token"
    assert config.daccord_auth_scheme == "Bearer"
    assert config.mattermost_api_base == "https://mattermost.example.test/api/v4"
    assert config.mattermost_token == "mattermost-token"
    assert config.zulip_api_base == "https://zulip.example.test/api/v1"
    assert config.zulip_email == "bot@example.test"
    assert config.zulip_api_key == "zulip-token"


def test_load_env_files_reads_explicit_local_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'DISCORD_BOT_TOKEN="discord-from-file"\nSTOAT_BOT_TOKEN=stoat-from-file\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("STOAT_BOT_TOKEN", raising=False)

    loaded = load_env_files((env_file,))
    config = RuntimeConfig.from_env()

    assert loaded == (env_file.resolve(strict=False),)
    assert config.discord_token == "discord-from-file"
    assert config.stoat_token == "stoat-from-file"


def test_load_env_files_allows_user_file_to_fill_blank_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blank_env = tmp_path / "app" / ".env"
    user_env = tmp_path / "home" / ".guildbridge" / ".env"
    blank_env.parent.mkdir()
    user_env.parent.mkdir(parents=True)
    blank_env.write_text("DISCORD_BOT_TOKEN=\n", encoding="utf-8")
    user_env.write_text("DISCORD_BOT_TOKEN=user-file-token\n", encoding="utf-8")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)

    load_env_files((blank_env, user_env))

    assert os.environ["DISCORD_BOT_TOKEN"] == "user-file-token"


def test_write_env_values_updates_private_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = user_env_file(home=tmp_path)
    env_file.parent.mkdir(parents=True)
    env_file.write_text("# local\nDISCORD_BOT_TOKEN=old\nSTOAT_API_BASE=https://api.stoat.chat\n", encoding="utf-8")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("STOAT_BOT_TOKEN", raising=False)

    saved = write_env_values(
        {
            "DISCORD_BOT_TOKEN": "new-discord-token",
            "STOAT_BOT_TOKEN": "new stoat token",
        },
        env_file=env_file,
    )

    text = saved.read_text(encoding="utf-8")
    assert saved == env_file
    assert 'DISCORD_BOT_TOKEN="new-discord-token"' in text
    assert "STOAT_API_BASE=https://api.stoat.chat" in text
    assert 'STOAT_BOT_TOKEN="new stoat token"' in text
    assert os.environ["DISCORD_BOT_TOKEN"] == "new-discord-token"
    assert os.environ["STOAT_BOT_TOKEN"] == "new stoat token"

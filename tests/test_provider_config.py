from __future__ import annotations

from guildbridge.config import RuntimeConfig
from guildbridge.providers.discord import DiscordProvider
from guildbridge.providers.stoat import StoatProvider


def test_provider_passes_http_retry_and_user_agent_config() -> None:
    config = RuntimeConfig(max_retries=7, request_timeout=9, user_agent="GuildBridge/Test")
    provider = DiscordProvider(config)

    assert provider.http.max_retries == 7
    assert provider.http.timeout == 9
    assert provider.http.session.headers["User-Agent"] == "GuildBridge/Test"


def test_stoat_uses_bot_token_header_by_default() -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="bot-token"))

    assert provider._headers() == {"X-Bot-Token": "bot-token"}  # noqa: SLF001


def test_stoat_session_token_uses_session_header() -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="bot-token", stoat_session_token="session-token"))

    assert provider._headers() == {"X-Session-Token": "session-token"}  # noqa: SLF001


def test_runtime_config_reads_stoat_session_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("STOAT_SESSION_TOKEN", "session-token")
    monkeypatch.delenv("STOAT_BOT_TOKEN", raising=False)
    monkeypatch.delenv("STOAT_TOKEN", raising=False)
    monkeypatch.delenv("REVOLT_TOKEN", raising=False)

    config = RuntimeConfig.from_env()

    assert config.stoat_session_token == "session-token"

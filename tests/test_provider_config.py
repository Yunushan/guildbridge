from __future__ import annotations

from guildbridge.config import RuntimeConfig
from guildbridge.providers.discord import DiscordProvider


def test_provider_passes_http_retry_and_user_agent_config() -> None:
    config = RuntimeConfig(max_retries=7, request_timeout=9, user_agent="GuildBridge/Test")
    provider = DiscordProvider(config)

    assert provider.http.max_retries == 7
    assert provider.http.timeout == 9
    assert provider.http.session.headers["User-Agent"] == "GuildBridge/Test"

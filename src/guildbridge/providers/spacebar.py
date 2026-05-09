from __future__ import annotations

from guildbridge.config import RuntimeConfig
from guildbridge.http import HttpClient

from .discord import DiscordProvider


class SpacebarProvider(DiscordProvider):
    name = "spacebar"
    aliases = ("spacebar.chat", "fosscord")
    provider_label = "Spacebar"
    token_env_hint = "SPACEBAR_BOT_TOKEN or SPACEBAR_TOKEN"

    def __init__(self, config: RuntimeConfig):
        super().__init__(config)
        self.http = HttpClient(
            config.spacebar_api_base,
            token=config.spacebar_token,
            auth_scheme="Bot",
            timeout=config.request_timeout,
            max_retries=config.max_retries,
            user_agent=config.user_agent,
        )

    def _token_configured(self) -> bool:
        return bool(self.config.spacebar_token)

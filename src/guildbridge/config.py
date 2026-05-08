from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .utils import env

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RuntimeConfig:
    discord_api_base: str = "https://discord.com/api/v10"
    discord_token: Optional[str] = None

    fluxer_api_base: str = "https://api.fluxer.app/v1"
    fluxer_token: Optional[str] = None

    stoat_api_base: str = "https://api.stoat.chat"
    stoat_token: Optional[str] = None

    matrix_base_url: Optional[str] = None
    matrix_access_token: Optional[str] = None
    matrix_server_name: Optional[str] = None

    request_timeout: int = 30

    @staticmethod
    def from_env() -> "RuntimeConfig":
        if load_dotenv is not None:
            load_dotenv()
        return RuntimeConfig(
            discord_api_base=env("DISCORD_API_BASE", default="https://discord.com/api/v10") or "https://discord.com/api/v10",
            discord_token=env("DISCORD_BOT_TOKEN", "DISCORD_TOKEN"),
            fluxer_api_base=env("FLUXER_API_BASE", default="https://api.fluxer.app/v1") or "https://api.fluxer.app/v1",
            fluxer_token=env("FLUXER_BOT_TOKEN", "FLUXER_TOKEN"),
            stoat_api_base=env("STOAT_API_BASE", "REVOLT_API_BASE", default="https://api.stoat.chat") or "https://api.stoat.chat",
            stoat_token=env("STOAT_BOT_TOKEN", "STOAT_TOKEN", "REVOLT_TOKEN"),
            matrix_base_url=env("MATRIX_BASE_URL", "ELEMENT_MATRIX_BASE_URL"),
            matrix_access_token=env("MATRIX_ACCESS_TOKEN", "ELEMENT_ACCESS_TOKEN"),
            matrix_server_name=env("MATRIX_SERVER_NAME"),
            request_timeout=int(env("GUILDBRIDGE_REQUEST_TIMEOUT", "GUILDBRIDGE_TIMEOUT", default="30") or "30"),
        )

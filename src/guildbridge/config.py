from __future__ import annotations

from dataclasses import dataclass

from .utils import env

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RuntimeConfig:
    discord_api_base: str = "https://discord.com/api/v10"
    discord_token: str | None = None

    fluxer_api_base: str = "https://api.fluxer.app/v1"
    fluxer_token: str | None = None

    stoat_api_base: str = "https://api.stoat.chat"
    stoat_token: str | None = None

    matrix_base_url: str | None = None
    matrix_access_token: str | None = None
    matrix_server_name: str | None = None

    rocket_chat_api_base: str = "http://localhost:3000/api/v1"
    rocket_chat_auth_token: str | None = None
    rocket_chat_user_id: str | None = None

    mumble_api_base: str = "http://localhost:64738/api/v1"
    mumble_api_token: str | None = None

    request_timeout: int = 30
    max_retries: int = 5
    user_agent: str = "GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)"

    @staticmethod
    def from_env() -> RuntimeConfig:
        if load_dotenv is not None:
            load_dotenv()
        request_timeout = parse_positive_int(env("GUILDBRIDGE_REQUEST_TIMEOUT", "GUILDBRIDGE_TIMEOUT"), default=30)
        max_retries = parse_positive_int(env("GUILDBRIDGE_MAX_RETRIES"), default=5, allow_zero=True)
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
            rocket_chat_api_base=env("ROCKET_CHAT_API_BASE", "ROCKETCHAT_API_BASE", default="http://localhost:3000/api/v1")
            or "http://localhost:3000/api/v1",
            rocket_chat_auth_token=env("ROCKET_CHAT_AUTH_TOKEN", "ROCKETCHAT_AUTH_TOKEN"),
            rocket_chat_user_id=env("ROCKET_CHAT_USER_ID", "ROCKETCHAT_USER_ID"),
            mumble_api_base=env("MUMBLE_API_BASE", default="http://localhost:64738/api/v1") or "http://localhost:64738/api/v1",
            mumble_api_token=env("MUMBLE_API_TOKEN"),
            request_timeout=request_timeout,
            max_retries=max_retries,
            user_agent=env("GUILDBRIDGE_USER_AGENT", default="GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)") or "GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)",
        )


def parse_positive_int(value: str | None, *, default: int, allow_zero: bool = False) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"Expected an integer value, got {value!r}") from exc
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        raise ValueError(f"Expected an integer >= {minimum}, got {parsed}")
    return parsed

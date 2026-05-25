from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .utils import env

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None  # type: ignore[assignment]


def env_file_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = [Path.cwd() / ".env"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve(strict=False).parent / ".env")
    if sys.argv and sys.argv[0]:
        candidates.append(Path(sys.argv[0]).resolve(strict=False).parent / ".env")
    candidates.append(user_env_file())
    candidates.append(Path.home() / ".config" / "guildbridge" / ".env")
    return _dedupe_paths(candidates)


def user_env_file(home: Path | None = None) -> Path:
    root = Path.home() if home is None else Path(home)
    return root / ".guildbridge" / ".env"


def load_env_files(candidates: Iterable[Path] | None = None) -> tuple[Path, ...]:
    loaded: list[Path] = []
    for path in _dedupe_paths(candidates or env_file_candidates()):
        if not path.is_file():
            continue
        if load_dotenv is not None:
            load_dotenv(dotenv_path=path, override=False)
        _load_simple_env_file(path)
        loaded.append(path)
    return tuple(loaded)


def write_env_values(values: Mapping[str, str], *, env_file: Path | None = None) -> Path:
    updates = {key: value.strip() for key, value in values.items() if value.strip()}
    if not updates:
        raise ValueError("No environment values were provided.")
    for key in updates:
        if not key.replace("_", "").isalnum() or key.upper() != key:
            raise ValueError(f"Invalid environment key: {key}")

    target = env_file or user_env_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        lines = target.read_text(encoding="utf-8").splitlines()
    else:
        lines = [
            "# GuildBridge local secrets. Do not commit this file.",
            "# Created by the desktop GUI after confirmation.",
        ]

    seen: set[str] = set()
    rewritten: list[str] = []
    for line in lines:
        line_key = _env_line_key(line)
        if line_key in updates:
            rewritten.append(f"{line_key}={_quote_env_value(updates[line_key])}")
            seen.add(line_key)
        else:
            rewritten.append(line)
    for key, value in updates.items():
        if key not in seen:
            rewritten.append(f"{key}={_quote_env_value(value)}")

    target.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value
    return target


def _dedupe_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(resolved)
    return tuple(deduped)


def _env_line_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key = stripped.split("=", 1)[0].strip()
    if key.startswith("export "):
        key = key.removeprefix("export ").strip()
    if not key.replace("_", "").isalnum() or key.upper() != key:
        return None
    return key


def _quote_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _load_simple_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        key = _env_line_key(line)
        if key is None or os.environ.get(key):
            continue
        raw_value = line.split("=", 1)[1].strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            raw_value = raw_value[1:-1]
        if not raw_value:
            continue
        os.environ[key] = raw_value.replace(r"\"", '"').replace(r"\\", "\\")


@dataclass(frozen=True)
class RuntimeConfig:
    discord_api_base: str = "https://discord.com/api/v10"
    discord_token: str | None = None

    fluxer_api_base: str = "https://api.fluxer.app/v1"
    fluxer_token: str | None = None

    stoat_api_base: str = "https://api.stoat.chat"
    stoat_autumn_base: str = "https://autumn.stoat.chat"
    stoat_token: str | None = None
    stoat_session_token: str | None = None

    spacebar_api_base: str = "https://api.spacebar.chat/api/v9"
    spacebar_token: str | None = None

    daccord_api_base: str = "http://localhost:3000/api/v1"
    daccord_token: str | None = None
    daccord_auth_scheme: str = "Bot"

    matrix_base_url: str | None = None
    matrix_access_token: str | None = None
    matrix_server_name: str | None = None

    rocket_chat_api_base: str = "http://localhost:3000/api/v1"
    rocket_chat_auth_token: str | None = None
    rocket_chat_user_id: str | None = None

    mumble_api_base: str = "http://localhost:64738/api/v1"
    mumble_api_token: str | None = None

    mattermost_api_base: str = "http://localhost:8065/api/v4"
    mattermost_token: str | None = None

    zulip_api_base: str = "https://chat.zulip.org/api/v1"
    zulip_email: str | None = None
    zulip_api_key: str | None = None

    request_timeout: int = 30
    max_retries: int = 5
    user_agent: str = "GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)"

    @staticmethod
    def from_env() -> RuntimeConfig:
        load_env_files()
        request_timeout = parse_positive_int(env("GUILDBRIDGE_REQUEST_TIMEOUT", "GUILDBRIDGE_TIMEOUT"), default=30)
        max_retries = parse_positive_int(env("GUILDBRIDGE_MAX_RETRIES"), default=5, allow_zero=True)
        return RuntimeConfig(
            discord_api_base=env("DISCORD_API_BASE", default="https://discord.com/api/v10") or "https://discord.com/api/v10",
            discord_token=env("DISCORD_BOT_TOKEN", "DISCORD_TOKEN"),
            fluxer_api_base=env("FLUXER_API_BASE", default="https://api.fluxer.app/v1") or "https://api.fluxer.app/v1",
            fluxer_token=env("FLUXER_BOT_TOKEN", "FLUXER_TOKEN"),
            stoat_api_base=env("STOAT_API_BASE", "REVOLT_API_BASE", default="https://api.stoat.chat") or "https://api.stoat.chat",
            stoat_autumn_base=env("STOAT_AUTUMN_BASE", "REVOLT_AUTUMN_BASE", default="https://autumn.stoat.chat")
            or "https://autumn.stoat.chat",
            stoat_token=env("STOAT_BOT_TOKEN", "STOAT_TOKEN", "REVOLT_TOKEN"),
            stoat_session_token=env("STOAT_SESSION_TOKEN", "REVOLT_SESSION_TOKEN"),
            spacebar_api_base=env("SPACEBAR_API_BASE", "FOSSCORD_API_BASE", default="https://api.spacebar.chat/api/v9")
            or "https://api.spacebar.chat/api/v9",
            spacebar_token=env("SPACEBAR_BOT_TOKEN", "SPACEBAR_TOKEN", "FOSSCORD_BOT_TOKEN", "FOSSCORD_TOKEN"),
            daccord_api_base=env("DACCORD_API_BASE", default="http://localhost:3000/api/v1") or "http://localhost:3000/api/v1",
            daccord_token=env("DACCORD_BOT_TOKEN", "DACCORD_TOKEN"),
            daccord_auth_scheme=env("DACCORD_AUTH_SCHEME", default="Bot") or "Bot",
            matrix_base_url=env("MATRIX_BASE_URL", "ELEMENT_MATRIX_BASE_URL"),
            matrix_access_token=env("MATRIX_ACCESS_TOKEN", "ELEMENT_ACCESS_TOKEN"),
            matrix_server_name=env("MATRIX_SERVER_NAME"),
            rocket_chat_api_base=env("ROCKET_CHAT_API_BASE", "ROCKETCHAT_API_BASE", default="http://localhost:3000/api/v1")
            or "http://localhost:3000/api/v1",
            rocket_chat_auth_token=env("ROCKET_CHAT_AUTH_TOKEN", "ROCKETCHAT_AUTH_TOKEN"),
            rocket_chat_user_id=env("ROCKET_CHAT_USER_ID", "ROCKETCHAT_USER_ID"),
            mumble_api_base=env("MUMBLE_API_BASE", default="http://localhost:64738/api/v1") or "http://localhost:64738/api/v1",
            mumble_api_token=env("MUMBLE_API_TOKEN"),
            mattermost_api_base=env("MATTERMOST_API_BASE", default="http://localhost:8065/api/v4") or "http://localhost:8065/api/v4",
            mattermost_token=env("MATTERMOST_TOKEN", "MATTERMOST_PERSONAL_ACCESS_TOKEN"),
            zulip_api_base=env("ZULIP_API_BASE", default="https://chat.zulip.org/api/v1") or "https://chat.zulip.org/api/v1",
            zulip_email=env("ZULIP_EMAIL", "ZULIP_BOT_EMAIL"),
            zulip_api_key=env("ZULIP_API_KEY", "ZULIP_BOT_API_KEY"),
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

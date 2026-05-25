from __future__ import annotations

import base64
import re
from pathlib import Path
from urllib.parse import urlencode

DISCORD_MIGRATION_PERMISSION_INTEGER = 66560
DISCORD_CHANNEL_URL_RE = re.compile(
    r"(?:https?://)?(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/(?P<guild_id>\d{15,25}|@me)/(?P<channel_id>\d{15,25})",
    re.IGNORECASE,
)


def discord_bot_invite_url(
    client_id: str = "",
    *,
    token: str | None = None,
    permissions: int = DISCORD_MIGRATION_PERMISSION_INTEGER,
) -> str:
    cleaned = client_id.strip() or discord_client_id_from_token(token or "")
    if not cleaned:
        raise ValueError("Discord app/client ID is required, or set DISCORD_BOT_TOKEN so GuildBridge can derive it.")
    query = urlencode({"client_id": cleaned, "permissions": str(permissions), "scope": "bot"})
    return f"https://discord.com/oauth2/authorize?{query}"


def discord_client_id_from_token(token: str) -> str:
    first_segment = token.strip().split(".", 1)[0]
    if not first_segment:
        return ""
    padded = first_segment + "=" * (-len(first_segment) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except Exception:
        return ""
    return decoded if decoded.isdigit() else ""


def discord_source_id_warning(value: str) -> str | None:
    match = DISCORD_CHANNEL_URL_RE.search(value.strip())
    if not match:
        return None
    guild_id = match.group("guild_id")
    channel_id = match.group("channel_id")
    if guild_id == "@me":
        return "This is a Discord DM/channel URL. Use a server/guild ID, not a DM or channel ID."
    return f"This looks like a Discord channel URL. Use server/guild ID {guild_id}, not channel ID {channel_id}."


def migration_artifact_paths(
    base_dir: str | Path,
    *,
    source_provider: str,
    target_providers: list[str] | tuple[str, ...],
) -> dict[str, str]:
    base = Path(base_dir).expanduser()
    target_part = _target_path_part(target_providers)
    name = f"guildbridge-{_safe_path_part(source_provider)}-to-{target_part}"
    return {
        "template_out": str(base / f"{name}.template.json"),
        "plan_out": str(base / f"{name}.plan.json"),
        "apply_result": str(base / f"{name}.apply-result.json"),
        "journal_out": str(base / f"{name}.journal.json"),
    }


def export_artifact_paths(base_dir: str | Path, *, provider: str) -> dict[str, str]:
    base = Path(base_dir).expanduser()
    name = f"guildbridge-{_safe_path_part(provider)}-export"
    return {
        "out": str(base / f"{name}.template.json"),
    }


def import_artifact_paths(
    base_dir: str | Path,
    *,
    target_providers: list[str] | tuple[str, ...],
) -> dict[str, str]:
    base = Path(base_dir).expanduser()
    name = f"guildbridge-import-to-{_target_path_part(target_providers)}"
    return {
        "plan_out": str(base / f"{name}.plan.json"),
        "apply_result": str(base / f"{name}.apply-result.json"),
        "journal_out": str(base / f"{name}.journal.json"),
    }


def content_artifact_paths(
    base_dir: str | Path,
    *,
    target_providers: list[str] | tuple[str, ...],
) -> dict[str, str]:
    base = Path(base_dir).expanduser() / "content"
    name = f"guildbridge-content-to-{_target_path_part(target_providers)}"
    return {
        "discord_export_out": str(base / f"{name}.discord-export"),
        "archive_out": str(base / f"{name}.content.json"),
        "plan_out": str(base / f"{name}.plan.json"),
        "apply_result": str(base / f"{name}.apply-result.json"),
        "content_journal_out": str(base / f"{name}.journal.json"),
        "content_dead_letter_out": str(base / f"{name}.dead-letter.json"),
        "content_report_out": str(base / f"{name}.report.json"),
        "content_lock_file": str(base / f"{name}.lock"),
        "content_incremental_state": str(base / f"{name}.incremental-state.json"),
        "content_thread_archive_dir": str(base / f"{name}.threads"),
    }


def default_migration_artifact_dir(home: str | Path | None = None) -> Path:
    root = Path(home).expanduser() if home is not None else Path.home()
    return root / ".guildbridge" / "gui"


def _target_path_part(target_providers: list[str] | tuple[str, ...]) -> str:
    target_part = "-".join(_safe_path_part(provider) for provider in target_providers if provider.strip())
    return target_part or "target"


def _safe_path_part(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "provider"

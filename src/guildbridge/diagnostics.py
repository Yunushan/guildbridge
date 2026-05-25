from __future__ import annotations

import json
from collections.abc import Iterable

from guildbridge.http import HttpError, HttpTransportError, sanitize_text


def format_error_report(exc: BaseException) -> str:
    message = sanitize_text(str(exc))
    lines = [f"guildbridge: error: {message}"]
    hints = recovery_hints(exc)
    if hints:
        lines.append("recovery:")
        lines.extend(f"- {hint}" for hint in hints)
    return "\n".join(lines)


def recovery_hints(exc: BaseException) -> list[str]:
    if isinstance(exc, FileNotFoundError):
        return [
            "Check that the template, reviewed plan, or journal path exists from the current working directory.",
            "Use an absolute path when launching GuildBridge from a GUI, service, or different shell.",
        ]
    if isinstance(exc, PermissionError):
        return [
            "Check filesystem permissions for the input or output path.",
            "Write generated templates, plans, and journals to a directory your user account owns.",
        ]
    if isinstance(exc, json.JSONDecodeError):
        return [
            f"Fix the JSON syntax near line {exc.lineno}, column {exc.colno}.",
            "After editing, run `guildbridge validate <template.json>` before importing or applying.",
        ]
    if isinstance(exc, HttpError):
        return _http_error_hints(exc)
    if isinstance(exc, HttpTransportError):
        return [
            "Check network connectivity, DNS, proxy, TLS certificates, and the provider API base URL.",
            "If the provider is slow, increase GUILDBRIDGE_REQUEST_TIMEOUT or lower GUILDBRIDGE_MAX_RETRIES.",
        ]

    text = str(exc)
    lowered = text.lower()
    hints: list[str] = []
    hints.extend(_apply_hints(lowered))
    hints.extend(_plan_hints(lowered))
    hints.extend(_journal_hints(lowered))
    hints.extend(_content_hints(lowered))
    hints.extend(_template_hints(lowered))
    hints.extend(_provider_hints(text, lowered))
    hints.extend(_configuration_hints(lowered))
    return _dedupe(hints)


def _http_error_hints(exc: HttpError) -> list[str]:
    if exc.status_code in {401, 403}:
        if "stoat" in exc.url.lower() or "revolt" in exc.url.lower():
            return [
                "For Stoat/Revolt role or server management routes, set STOAT_SESSION_TOKEN or REVOLT_SESSION_TOKEN in .env when bot auth is rejected.",
                "If the response is 403, confirm the account owns or can manage the target server, roles, and channels.",
                "Do not paste session tokens into templates, plans, journals, screenshots, or issue reports.",
            ]
        return [
            "Check the provider token environment variable and confirm the token has the required scopes or bot permissions.",
            "For Discord targets, confirm the bot is installed in the target guild before applying writes.",
        ]
    if exc.status_code == 404:
        return [
            "Check the source or target ID and provider API base URL.",
            "If you are importing into Discord, GuildBridge requires an existing target guild ID.",
        ]
    if exc.status_code == 429:
        return [
            "The provider is rate limiting requests; wait before retrying.",
            "Keep the reviewed plan and journal so a later retry can be compared to the same intended actions.",
        ]
    if 500 <= exc.status_code <= 599:
        return [
            "The provider returned a server-side error; retry after checking provider status.",
            "If an apply run started, inspect the apply journal before retrying with --resume-journal.",
        ]
    return [
        "Inspect the provider response and verify the requested source or target supports the operation.",
        "Retry as a dry run first when changing command arguments.",
    ]


def _apply_hints(lowered: str) -> list[str]:
    if "--confirm-apply" in lowered or "without typing" in lowered:
        return [
            "Run without --apply first and review the generated plan.",
            "Apply only after rerunning with --plan-in <reviewed-plan.json> --confirm-apply APPLY.",
        ]
    if "without --plan-in" in lowered or "--plan-in is only used with --apply" in lowered:
        return [
            "Create a dry-run plan first, review it, then pass that exact file with --plan-in when using --apply.",
            "Do not pass --plan-in during a dry run.",
        ]
    if "template failed validation" in lowered:
        return [
            "Run `guildbridge validate <template.json>` and fix the reported schema or privacy issues.",
            "Use --force-invalid-template only after manual review and only with a reviewed dry-run plan.",
        ]
    return []


def _plan_hints(lowered: str) -> list[str]:
    if "reviewed plan" not in lowered:
        return []
    return [
        "Regenerate the dry-run plan with the same command, provider, template, target, and GuildBridge version.",
        "Do not hand-edit reviewed plan metadata; GuildBridge compares the action hash before writing.",
    ]


def _journal_hints(lowered: str) -> list[str]:
    if "resume" not in lowered and "journal" not in lowered:
        return []
    return [
        "Inspect the apply journal before retrying so you know which actions started, succeeded, or failed.",
        "Resume with the same command, target, template, and reviewed plan hash that created the failed journal.",
    ]


def _content_hints(lowered: str) -> list[str]:
    if "optional content migration is not implemented" not in lowered:
        return []
    return [
        "Run `guildbridge content-features --format json` to inspect the optional content feature gate.",
        "Use the normal import/export/migrate flow without --include-content for privacy-safe structure migration.",
    ]


def _template_hints(lowered: str) -> list[str]:
    if "unsupported schema" in lowered:
        return [
            "Use a template generated by this GuildBridge version or update the schema field to the supported version.",
            "Compare against examples/template.example.json before importing.",
        ]
    if "template must" in lowered or "validation" in lowered:
        return ["Run `guildbridge validate <template.json>` and fix every reported problem before applying writes."]
    return []


def _provider_hints(text: str, lowered: str) -> list[str]:
    if "unknown provider" in lowered:
        return ["Run `guildbridge providers` to list valid provider names and aliases."]
    if "requires" in lowered and "token" in lowered:
        env_names = _env_names(text)
        token_hint = f"Set {' or '.join(env_names)} in .env or the shell environment." if env_names else "Set the provider token in .env or the shell environment."
        return [
            token_hint,
            "Do not paste tokens into templates, plans, journals, screenshots, or issue reports.",
        ]
    if "requires --source-id" in lowered:
        return ["Pass the source server, guild, space, or room ID with --source-id, or use a supported provider template URL when available."]
    if "requires --target-id" in lowered:
        return ["Pass an existing target ID with --target-id, or choose a provider that can create a target from --target-name."]
    if "bot is not in this discord server" in lowered:
        return [
            "Use Invite Discord Bot from the GUI, or open a Discord OAuth2 bot invite URL for the application.",
            "Use the Discord server/guild ID as Source ID, not a channel ID or channel URL.",
            "Grant View Channels and Read Message History, then retry Check Discord Access.",
        ]
    if "looks like a channel id" in lowered and "discord" in lowered:
        return ["Replace the Discord Source ID with the server/guild ID shown in the error message."]
    if "response did not contain an id" in lowered:
        return [
            "The provider response did not match the expected API contract.",
            "Check provider API compatibility and keep the sanitized command output for a bug report.",
        ]
    return []


def _configuration_hints(lowered: str) -> list[str]:
    if "expected an integer" in lowered:
        return ["Check numeric environment variables such as GUILDBRIDGE_REQUEST_TIMEOUT and GUILDBRIDGE_MAX_RETRIES."]
    if "unable to start command" in lowered:
        return ["Verify Python can run `python -m guildbridge` in this environment."]
    return []


def _env_names(text: str) -> list[str]:
    found: list[str] = []
    for token in text.replace(",", " ").replace(".", " ").split():
        stripped = token.strip("()[]{}'\"")
        if stripped.isupper() and ("TOKEN" in stripped or stripped.endswith("_BASE_URL")):
            found.append(stripped)
    return _dedupe(found)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

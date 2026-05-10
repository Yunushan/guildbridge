from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from guildbridge.diagnostics import format_error_report
from guildbridge.safety import APPLY_CONFIRMATION

DEFAULT_COMMAND_TIMEOUT_SECONDS = 60 * 60


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _add_value(args: list[str], flag: str, value: str | None) -> None:
    cleaned = (value or "").strip()
    if cleaned:
        args.extend([flag, cleaned])


def _add_flag(args: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        args.append(flag)


def _provider_values(value: str | Sequence[str]) -> list[str]:
    values = [value] if isinstance(value, str) else list(value)
    providers: list[str] = []
    for raw_value in values:
        providers.extend(part.strip() for part in raw_value.split(",") if part.strip())
    return providers


def _add_providers(args: list[str], flag: str, values: str | Sequence[str]) -> None:
    for value in _provider_values(values):
        args.extend([flag, value])


def build_export_args(
    provider_from: str,
    *,
    source_id: str = "",
    template: str = "",
    out: str = "community.template.json",
    include_user_overwrites: bool = False,
    include_content: bool = False,
) -> list[str]:
    args = ["export", "--from", provider_from]
    _add_value(args, "--source-id", source_id)
    _add_value(args, "--template", template)
    _add_value(args, "--out", out)
    _add_flag(args, "--include-user-overwrites", include_user_overwrites)
    _add_flag(args, "--include-content", include_content)
    return args


def build_import_args(
    provider_to: str | Sequence[str],
    *,
    file: str,
    target_id: str = "",
    target_name: str = "",
    plan_out: str = "-",
    plan_in: str = "",
    audit_log_reason: str = "",
    redact: bool = False,
    apply: bool = False,
    force_invalid_template: bool = False,
    journal_out: str = "",
    resume_journal: str = "",
    include_content: bool = False,
) -> list[str]:
    args = ["import"]
    _add_providers(args, "--to", provider_to)
    args.extend(["--file", file.strip()])
    _add_value(args, "--target-id", target_id)
    _add_value(args, "--target-name", target_name)
    _add_value(args, "--plan-out", plan_out)
    _add_value(args, "--plan-in", plan_in)
    _add_value(args, "--journal-out", journal_out)
    _add_value(args, "--resume-journal", resume_journal)
    _add_value(args, "--audit-log-reason", audit_log_reason)
    _add_flag(args, "--redact", redact)
    _add_flag(args, "--include-content", include_content)
    _add_flag(args, "--force-invalid-template", force_invalid_template)
    _add_flag(args, "--apply", apply)
    _add_value(args, "--confirm-apply", APPLY_CONFIRMATION if apply else "")
    return args


def build_migrate_args(
    provider_from: str,
    provider_to: str | Sequence[str],
    *,
    source_id: str = "",
    template: str = "",
    target_id: str = "",
    target_name: str = "",
    template_out: str = "",
    plan_out: str = "-",
    plan_in: str = "",
    audit_log_reason: str = "",
    include_user_overwrites: bool = False,
    redact: bool = True,
    apply: bool = False,
    force_invalid_template: bool = False,
    journal_out: str = "",
    resume_journal: str = "",
    include_content: bool = False,
) -> list[str]:
    args = ["migrate", "--from", provider_from]
    _add_providers(args, "--to", provider_to)
    _add_value(args, "--source-id", source_id)
    _add_value(args, "--template", template)
    _add_value(args, "--target-id", target_id)
    _add_value(args, "--target-name", target_name)
    _add_value(args, "--template-out", template_out)
    _add_value(args, "--plan-out", plan_out)
    _add_value(args, "--plan-in", plan_in)
    _add_value(args, "--journal-out", journal_out)
    _add_value(args, "--resume-journal", resume_journal)
    _add_value(args, "--audit-log-reason", audit_log_reason)
    _add_flag(args, "--include-user-overwrites", include_user_overwrites)
    _add_flag(args, "--include-content", include_content)
    _add_flag(args, "--redact", redact)
    _add_flag(args, "--force-invalid-template", force_invalid_template)
    _add_flag(args, "--apply", apply)
    _add_value(args, "--confirm-apply", APPLY_CONFIRMATION if apply else "")
    return args


def build_content_export_args(
    *,
    discord_chat_export: str,
    out: str = "community.content.json",
) -> list[str]:
    args = ["content-export"]
    _add_value(args, "--discord-chat-export", discord_chat_export)
    _add_value(args, "--out", out)
    return args


def _add_content_import_options(
    args: list[str],
    *,
    target_id: str = "",
    target_name: str = "",
    channel_map: str = "",
    plan_out: str = "-",
    plan_in: str = "",
    apply: bool = False,
    force_invalid_archive: bool = False,
    message_limit: str = "",
    no_authors: bool = False,
    no_attachments: bool = False,
    no_reactions: bool = False,
    no_embeds: bool = False,
    no_stickers: bool = False,
    no_polls: bool = False,
    no_threads: bool = False,
    no_custom_emoji: bool = False,
    native_content: bool = False,
    native_attachments: bool = False,
    native_embeds: bool = False,
    native_replies: bool = False,
    native_reactions: bool = False,
    native_pins: bool = False,
    native_custom_emoji: bool = False,
    native_masquerade: bool = False,
    native_stickers: bool = False,
    content_journal_out: str = "",
    resume_content_journal: str = "",
    content_dead_letter_out: str = "",
    content_report_out: str = "",
    content_lock_file: str = "",
    content_incremental_state: str = "",
    content_incremental: bool = False,
    content_continue_on_error: bool = False,
    content_max_failures: str = "",
    content_parallel_sends: str = "",
) -> None:
    _add_value(args, "--target-id", target_id)
    _add_value(args, "--target-name", target_name)
    _add_value(args, "--channel-map", channel_map)
    _add_value(args, "--plan-out", plan_out)
    _add_value(args, "--plan-in", plan_in)
    _add_value(args, "--message-limit", message_limit)
    _add_value(args, "--content-journal-out", content_journal_out)
    _add_value(args, "--resume-content-journal", resume_content_journal)
    _add_value(args, "--content-dead-letter-out", content_dead_letter_out)
    _add_value(args, "--content-report-out", content_report_out)
    _add_value(args, "--content-lock-file", content_lock_file)
    _add_value(args, "--content-incremental-state", content_incremental_state)
    _add_value(args, "--content-max-failures", content_max_failures)
    _add_value(args, "--content-parallel-sends", content_parallel_sends)
    _add_flag(args, "--no-authors", no_authors)
    _add_flag(args, "--no-attachments", no_attachments)
    _add_flag(args, "--no-reactions", no_reactions)
    _add_flag(args, "--no-embeds", no_embeds)
    _add_flag(args, "--no-stickers", no_stickers)
    _add_flag(args, "--no-polls", no_polls)
    _add_flag(args, "--no-threads", no_threads)
    _add_flag(args, "--no-custom-emoji", no_custom_emoji)
    _add_flag(args, "--native-content", native_content)
    _add_flag(args, "--native-attachments", native_attachments)
    _add_flag(args, "--native-embeds", native_embeds)
    _add_flag(args, "--native-replies", native_replies)
    _add_flag(args, "--native-reactions", native_reactions)
    _add_flag(args, "--native-pins", native_pins)
    _add_flag(args, "--native-custom-emoji", native_custom_emoji)
    _add_flag(args, "--native-masquerade", native_masquerade)
    _add_flag(args, "--native-stickers", native_stickers)
    _add_flag(args, "--content-incremental", content_incremental)
    _add_flag(args, "--content-continue-on-error", content_continue_on_error)
    _add_flag(args, "--force-invalid-archive", force_invalid_archive)
    _add_flag(args, "--apply", apply)
    _add_value(args, "--confirm-apply", APPLY_CONFIRMATION if apply else "")


def build_content_import_args(
    provider_to: str | Sequence[str],
    *,
    file: str,
    target_id: str = "",
    target_name: str = "",
    channel_map: str = "",
    plan_out: str = "-",
    plan_in: str = "",
    apply: bool = False,
    force_invalid_archive: bool = False,
    message_limit: str = "",
    no_authors: bool = False,
    no_attachments: bool = False,
    no_reactions: bool = False,
    no_embeds: bool = False,
    no_stickers: bool = False,
    no_polls: bool = False,
    no_threads: bool = False,
    no_custom_emoji: bool = False,
    native_content: bool = False,
    native_attachments: bool = False,
    native_embeds: bool = False,
    native_replies: bool = False,
    native_reactions: bool = False,
    native_pins: bool = False,
    native_custom_emoji: bool = False,
    native_masquerade: bool = False,
    native_stickers: bool = False,
    content_journal_out: str = "",
    resume_content_journal: str = "",
    content_dead_letter_out: str = "",
    content_report_out: str = "",
    content_lock_file: str = "",
    content_incremental_state: str = "",
    content_incremental: bool = False,
    content_continue_on_error: bool = False,
    content_max_failures: str = "",
    content_parallel_sends: str = "",
) -> list[str]:
    args = ["content-import"]
    args.extend(["--file", file.strip()])
    _add_providers(args, "--to", provider_to)
    _add_content_import_options(
        args,
        target_id=target_id,
        target_name=target_name,
        channel_map=channel_map,
        plan_out=plan_out,
        plan_in=plan_in,
        apply=apply,
        force_invalid_archive=force_invalid_archive,
        message_limit=message_limit,
        no_authors=no_authors,
        no_attachments=no_attachments,
        no_reactions=no_reactions,
        no_embeds=no_embeds,
        no_stickers=no_stickers,
        no_polls=no_polls,
        no_threads=no_threads,
        no_custom_emoji=no_custom_emoji,
        native_content=native_content,
        native_attachments=native_attachments,
        native_embeds=native_embeds,
        native_replies=native_replies,
        native_reactions=native_reactions,
        native_pins=native_pins,
        native_custom_emoji=native_custom_emoji,
        native_masquerade=native_masquerade,
        native_stickers=native_stickers,
        content_journal_out=content_journal_out,
        resume_content_journal=resume_content_journal,
        content_dead_letter_out=content_dead_letter_out,
        content_report_out=content_report_out,
        content_lock_file=content_lock_file,
        content_incremental_state=content_incremental_state,
        content_incremental=content_incremental,
        content_continue_on_error=content_continue_on_error,
        content_max_failures=content_max_failures,
        content_parallel_sends=content_parallel_sends,
    )
    return args


def build_content_migrate_args(
    provider_to: str | Sequence[str],
    *,
    discord_chat_export: str,
    target_id: str = "",
    target_name: str = "",
    channel_map: str = "",
    plan_out: str = "-",
    plan_in: str = "",
    apply: bool = False,
    force_invalid_archive: bool = False,
    message_limit: str = "",
    no_authors: bool = False,
    no_attachments: bool = False,
    no_reactions: bool = False,
    no_embeds: bool = False,
    no_stickers: bool = False,
    no_polls: bool = False,
    no_threads: bool = False,
    no_custom_emoji: bool = False,
    native_content: bool = False,
    native_attachments: bool = False,
    native_embeds: bool = False,
    native_replies: bool = False,
    native_reactions: bool = False,
    native_pins: bool = False,
    native_custom_emoji: bool = False,
    native_masquerade: bool = False,
    native_stickers: bool = False,
    content_journal_out: str = "",
    resume_content_journal: str = "",
    content_dead_letter_out: str = "",
    content_report_out: str = "",
    content_lock_file: str = "",
    content_incremental_state: str = "",
    content_incremental: bool = False,
    content_continue_on_error: bool = False,
    content_max_failures: str = "",
    content_parallel_sends: str = "",
) -> list[str]:
    args = ["content-migrate", "--from", "discord"]
    _add_value(args, "--discord-chat-export", discord_chat_export)
    _add_providers(args, "--to", provider_to)
    _add_content_import_options(
        args,
        target_id=target_id,
        target_name=target_name,
        channel_map=channel_map,
        plan_out=plan_out,
        plan_in=plan_in,
        apply=apply,
        force_invalid_archive=force_invalid_archive,
        message_limit=message_limit,
        no_authors=no_authors,
        no_attachments=no_attachments,
        no_reactions=no_reactions,
        no_embeds=no_embeds,
        no_stickers=no_stickers,
        no_polls=no_polls,
        no_threads=no_threads,
        no_custom_emoji=no_custom_emoji,
        native_content=native_content,
        native_attachments=native_attachments,
        native_embeds=native_embeds,
        native_replies=native_replies,
        native_reactions=native_reactions,
        native_pins=native_pins,
        native_custom_emoji=native_custom_emoji,
        native_masquerade=native_masquerade,
        native_stickers=native_stickers,
        content_journal_out=content_journal_out,
        resume_content_journal=resume_content_journal,
        content_dead_letter_out=content_dead_letter_out,
        content_report_out=content_report_out,
        content_lock_file=content_lock_file,
        content_incremental_state=content_incremental_state,
        content_incremental=content_incremental,
        content_continue_on_error=content_continue_on_error,
        content_max_failures=content_max_failures,
        content_parallel_sends=content_parallel_sends,
    )
    return args


def apply_confirmation_error(
    *,
    apply: bool,
    plan_in: str,
    confirmation: str | None,
    plan_out: str = "",
) -> str | None:
    if not apply:
        return None
    if not plan_in.strip():
        return "Actual run requires a reviewed plan JSON path."
    if _same_plan_path(plan_in, plan_out):
        return "Actual run requires Plan/result JSON to be empty, '-', or a different file than Reviewed plan JSON."
    if (confirmation or "").strip() != APPLY_CONFIRMATION:
        return "Actual run was not confirmed."
    return None


def _same_plan_path(plan_in: str, plan_out: str) -> bool:
    plan_in_clean = plan_in.strip()
    plan_out_clean = plan_out.strip()
    if not plan_in_clean or not plan_out_clean or plan_out_clean == "-":
        return False
    try:
        return Path(plan_in_clean).expanduser().resolve() == Path(plan_out_clean).expanduser().resolve()
    except OSError:
        return Path(plan_in_clean).expanduser().absolute() == Path(plan_out_clean).expanduser().absolute()


def build_validate_args(file: str) -> list[str]:
    return ["validate", file.strip()]


def build_redact_args(file: str, *, out: str = "redacted.template.json") -> list[str]:
    return ["redact", file.strip(), "--out", out.strip()]


def command_preview(args: Sequence[str]) -> str:
    return "guildbridge " + " ".join(shlex.quote(part) for part in args)


def _bundled_cli_name() -> str:
    return "guildbridge.exe" if sys.platform == "win32" else "guildbridge"


def subprocess_command(args: Sequence[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        cli_launcher = Path(sys.executable).with_name(_bundled_cli_name())
        return [str(cli_launcher), *args]
    return [sys.executable, "-m", "guildbridge", *args]


def subprocess_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def subprocess_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_cli_args(
    args: Sequence[str],
    *,
    timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    cwd: str | Path | None = None,
) -> CommandResult:
    command = subprocess_command(args)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=subprocess_creationflags(),
            env=subprocess_environment(),
        )
        duration = time.monotonic() - started
        return CommandResult(
            args=tuple(args),
            command=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stderr = _text(exc.stderr)
        if stderr:
            stderr += "\n"
        stderr += f"Command timed out after {timeout_seconds} seconds."
        return CommandResult(
            args=tuple(args),
            command=tuple(command),
            returncode=124,
            stdout=_text(exc.stdout),
            stderr=stderr,
            duration_seconds=duration,
            timed_out=True,
        )
    except OSError as exc:
        duration = time.monotonic() - started
        return CommandResult(
            args=tuple(args),
            command=tuple(command),
            returncode=127,
            stdout="",
            stderr=format_error_report(RuntimeError(f"Unable to start command: {exc}")),
            duration_seconds=duration,
        )

from __future__ import annotations

import json

import pytest

from guildbridge.diagnostics import format_error_report, recovery_hints
from guildbridge.http import HttpError, HttpTransportError


def test_file_not_found_report_includes_recovery() -> None:
    report = format_error_report(FileNotFoundError("missing template.json"))

    assert report.startswith("guildbridge: error:")
    assert "recovery:" in report
    assert "current working directory" in report


def test_json_decode_report_points_to_location() -> None:
    try:
        json.loads("{broken")
    except json.JSONDecodeError as exc:
        report = format_error_report(exc)
    else:
        raise AssertionError("expected JSONDecodeError")

    assert "line 1" in report
    assert "guildbridge validate" in report


def test_http_error_report_has_status_specific_recovery() -> None:
    report = format_error_report(HttpError("GET", "https://provider.example", 401, "unauthorized", 2))

    assert "failed with 401" in report
    assert "provider token environment variable" in report
    assert "required scopes or bot permissions" in report


def test_stoat_http_error_report_mentions_session_token() -> None:
    report = format_error_report(HttpError("POST", "https://api.stoat.chat/servers/target/roles", 401, "unauthorized", 1))

    assert "STOAT_SESSION_TOKEN" in report
    assert "bot auth is rejected" in report
    assert "Do not paste session tokens" in report


def test_transport_error_report_mentions_network_and_timeout() -> None:
    report = format_error_report(HttpTransportError("GET", "https://provider.example", "timed out", 3))

    assert "network connectivity" in report
    assert "GUILDBRIDGE_REQUEST_TIMEOUT" in report


def test_apply_and_plan_recovery_hints_are_specific() -> None:
    hints = recovery_hints(ValueError("Refusing --apply because reviewed plan has different action_hash."))

    assert any("Regenerate the dry-run plan" in hint for hint in hints)
    assert any("action hash" in hint for hint in hints)


def test_token_recovery_hints_name_environment_variables() -> None:
    report = format_error_report(ValueError("Discord live guild export requires DISCORD_BOT_TOKEN or DISCORD_TOKEN."))

    assert "Set DISCORD_BOT_TOKEN or DISCORD_TOKEN" in report
    assert "Do not paste tokens" in report


def test_permission_error_report_explains_safe_output_paths() -> None:
    report = format_error_report(PermissionError("plan.json"))

    assert "filesystem permissions" in report
    assert "directory your user account owns" in report


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, "Check the source or target ID"),
        (429, "rate limiting requests"),
        (503, "server-side error"),
        (418, "Retry as a dry run first"),
    ],
)
def test_http_error_reports_have_status_specific_recovery(status: int, expected: str) -> None:
    report = format_error_report(HttpError("GET", "https://provider.example", status, "failure", 1))

    assert expected in report


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Refusing --apply without typing APPLY in --confirm-apply", "Run without --apply first"),
        ("--plan-in is only used with --apply", "Create a dry-run plan first"),
        ("Template failed validation", "force-invalid-template"),
        ("resume journal required", "Inspect the apply journal"),
        ("optional content migration is not implemented", "guildbridge content-features --format json"),
        ("unsupported schema", "examples/template.example.json"),
        ("unknown provider", "guildbridge providers"),
        ("Discord live export requires DISCORD_BOT_TOKEN.", "Set DISCORD_BOT_TOKEN"),
        ("provider requires --source-id", "Pass the source server"),
        ("provider requires --target-id", "Pass an existing target ID"),
        ("Bot is not in this Discord server", "Invite Discord Bot"),
        ("Discord source looks like a channel ID", "Replace the Discord Source ID"),
        ("response did not contain an id", "expected API contract"),
        ("expected an integer", "GUILDBRIDGE_REQUEST_TIMEOUT"),
        ("unable to start command", "python -m guildbridge"),
    ],
)
def test_value_error_reports_have_actionable_recovery(message: str, expected: str) -> None:
    report = format_error_report(ValueError(message))

    assert expected in report


def test_error_report_redacts_token_values() -> None:
    report = format_error_report(ValueError("DISCORD_BOT_TOKEN=super-secret-token requires attention"))

    assert "super-secret-token" not in report
    assert "[redacted]" in report

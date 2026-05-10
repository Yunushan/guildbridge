from __future__ import annotations

import json

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

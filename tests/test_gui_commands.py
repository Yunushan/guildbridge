from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from guildbridge.gui_commands import (
    apply_confirmation_error,
    build_export_args,
    build_import_args,
    build_migrate_args,
    build_redact_args,
    build_validate_args,
    command_preview,
    run_cli_args,
    subprocess_command,
    subprocess_creationflags,
)


def test_build_export_args() -> None:
    args = build_export_args(
        "discord",
        template="https://discord.new/example",
        out="community.json",
        include_user_overwrites=True,
    )
    assert args == [
        "export",
        "--from",
        "discord",
        "--template",
        "https://discord.new/example",
        "--out",
        "community.json",
        "--include-user-overwrites",
    ]


def test_build_import_args_apply_redact() -> None:
    args = build_import_args(
        "fluxer",
        file="community.json",
        target_name="Imported",
        plan_out="plan.json",
        plan_in="reviewed.plan.json",
        journal_out="journal.json",
        resume_journal="failed-journal.json",
        redact=True,
        apply=True,
        force_invalid_template=True,
    )
    assert "--redact" in args
    assert "--apply" in args
    assert "--force-invalid-template" in args
    assert args[args.index("--plan-in") + 1] == "reviewed.plan.json"
    assert args[args.index("--journal-out") + 1] == "journal.json"
    assert args[args.index("--resume-journal") + 1] == "failed-journal.json"
    assert args[args.index("--confirm-apply") + 1] == "APPLY"
    assert args[:5] == ["import", "--to", "fluxer", "--file", "community.json"]


def test_build_import_args_accepts_multiple_targets() -> None:
    args = build_import_args(["fluxer", "stoat"], file="community.json")

    assert args[:7] == ["import", "--to", "fluxer", "--to", "stoat", "--file", "community.json"]


def test_build_migrate_args_preview() -> None:
    args = build_migrate_args(
        "discord",
        "matrix",
        source_id="123",
        target_name="Matrix Space",
        plan_out="plan.json",
        plan_in="reviewed.plan.json",
        journal_out="journal.json",
        resume_journal="failed-journal.json",
        force_invalid_template=True,
    )
    assert args[:5] == ["migrate", "--from", "discord", "--to", "matrix"]
    assert "--redact" in args
    assert "--force-invalid-template" in args
    assert args[args.index("--plan-in") + 1] == "reviewed.plan.json"
    assert args[args.index("--journal-out") + 1] == "journal.json"
    assert args[args.index("--resume-journal") + 1] == "failed-journal.json"
    assert command_preview(args).startswith("guildbridge migrate")


def test_build_migrate_args_accepts_comma_separated_targets() -> None:
    args = build_migrate_args("discord", "matrix,rocket.chat", source_id="123")

    assert args[:7] == ["migrate", "--from", "discord", "--to", "matrix", "--to", "rocket.chat"]


def test_apply_confirmation_error_requires_reviewed_plan_and_token() -> None:
    assert apply_confirmation_error(apply=False, plan_in="", confirmation=None) is None
    assert apply_confirmation_error(apply=True, plan_in="", confirmation="APPLY") == (
        "Apply writes require a reviewed plan JSON path."
    )
    assert apply_confirmation_error(
        apply=True,
        plan_in="reviewed.plan.json",
        plan_out="reviewed.plan.json",
        confirmation="APPLY",
    ) == "Apply writes require Plan/result JSON to be empty, '-', or a different file than Reviewed plan JSON."
    assert apply_confirmation_error(apply=True, plan_in="plan.json", confirmation="wrong") == (
        "Apply writes require typing 'APPLY'."
    )
    assert apply_confirmation_error(apply=True, plan_in="plan.json", confirmation="APPLY") is None


def test_build_validate_and_redact_args() -> None:
    assert build_validate_args("community.json") == ["validate", "community.json"]
    assert build_redact_args("community.json", out="safe.json") == ["redact", "community.json", "--out", "safe.json"]


def test_subprocess_command_uses_current_python() -> None:
    assert subprocess_command(["providers"]) == [sys.executable, "-m", "guildbridge", "providers"]


def test_subprocess_command_uses_bundled_cli_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launcher_name = "guildbridge.exe" if sys.platform == "win32" else "guildbridge"
    gui_name = "guildbridge-gui.exe" if sys.platform == "win32" else "guildbridge-gui"

    monkeypatch.setattr(sys, "executable", str(tmp_path / gui_name))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert subprocess_command(["providers"]) == [str(tmp_path / launcher_name), "providers"]


def test_subprocess_creationflags_hide_windows_console() -> None:
    expected = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if sys.platform == "win32" else 0
    assert subprocess_creationflags() == expected


def test_run_cli_args_uses_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["command"] = command
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("guildbridge.gui_commands.subprocess.run", fake_run)

    result = run_cli_args(["providers"], timeout_seconds=5, cwd=".")

    assert result.returncode == 0
    assert result.stdout == "ok"
    assert result.command == tuple(subprocess_command(["providers"]))
    assert result.timed_out is False
    assert seen["command"] == subprocess_command(["providers"])
    assert seen["kwargs"] == {
        "cwd": ".",
        "capture_output": True,
        "text": True,
        "timeout": 5,
        "check": False,
        "creationflags": subprocess_creationflags(),
    }


def test_run_cli_args_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=1, output="partial", stderr="late")

    monkeypatch.setattr("guildbridge.gui_commands.subprocess.run", fake_run)

    result = run_cli_args(["providers"], timeout_seconds=1)

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert result.timed_out is True
    assert "timed out" in result.stderr


def test_run_cli_args_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_: list[str], **__: object) -> subprocess.CompletedProcess[str]:
        raise OSError("no python")

    monkeypatch.setattr("guildbridge.gui_commands.subprocess.run", fake_run)

    result = run_cli_args(["providers"])

    assert result.returncode == 127
    assert "Unable to start command" in result.stderr

from __future__ import annotations

import json
import queue
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest

from guildbridge import gui
from guildbridge.gui_commands import CommandResult


class FakeVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeListbox:
    def __init__(self, values: list[str], selected: tuple[int, ...] = ()) -> None:
        self.values = values
        self.selected = list(selected)

    def curselection(self) -> tuple[int, ...]:
        return tuple(self.selected)

    def get(self, index: int) -> str:
        return self.values[index]

    def size(self) -> int:
        return len(self.values)

    def selection_clear(self, _start: int, _end: str) -> None:
        self.selected = []

    def selection_set(self, index: int) -> None:
        self.selected = [index]


class PathHarness:
    def __init__(self) -> None:
        self.created_files: list[str] = []
        self.created_dirs: list[str] = []

    def _ensure_file_parent(self, value: str) -> None:
        self.created_files.append(value)

    def _ensure_directory(self, value: str) -> None:
        self.created_dirs.append(value)

    _select_only_provider = staticmethod(gui.GuildBridgeGUI._select_only_provider)
    _selected_providers = staticmethod(gui.GuildBridgeGUI._selected_providers)
    _fill_migrate_paths = gui.GuildBridgeGUI._fill_migrate_paths


class RunHarness:
    def __init__(self) -> None:
        self.master = object()
        self.calls: list[tuple[str, object]] = []

    def _run_dry_run(self, args: list[str], *, plan_out: str) -> None:
        self.calls.append(("dry-run", (args, plan_out)))

    def _run(self, args: list[str], **kwargs: object) -> None:
        self.calls.append(("run", (args, kwargs)))


class ValueHarness:
    def __init__(self) -> None:
        self.master = object()
        self.calls: list[tuple[object, ...]] = []

    def _check_access(self, provider: str, resource_id: str, title: str) -> None:
        self.calls.append((provider, resource_id, title))

    def _run(self, args: list[str], **kwargs: object) -> None:
        self.calls.append((args, kwargs))

    _selected_providers = staticmethod(gui.GuildBridgeGUI._selected_providers)
    _check_provider_access = gui.GuildBridgeGUI._check_provider_access


class OutputHarness:
    def __init__(self) -> None:
        self.master = object()
        self.appended: list[str] = []

    def _append_output(self, text: str) -> None:
        self.appended.append(text)

    _result_dialog_message = staticmethod(gui.GuildBridgeGUI._result_dialog_message)


class ConfirmHarness:
    def __init__(self) -> None:
        self.master = object()

    _reviewed_plan_preview = staticmethod(gui.GuildBridgeGUI._reviewed_plan_preview)
    _apply_confirmation_message = staticmethod(gui.GuildBridgeGUI._apply_confirmation_message)


class FakeCanvas:
    def __init__(self, master: object | None = None) -> None:
        self.master = master
        self.scrolls: list[tuple[int, str]] = []

    def yview_scroll(self, units: int, mode: str) -> None:
        self.scrolls.append((units, mode))


class MouseHarness:
    def __init__(self, canvas: FakeCanvas) -> None:
        self.master = SimpleNamespace(winfo_containing=lambda _x, _y: canvas)
        self.themed_canvases = [canvas]

    _tab_canvas_for_event = gui.GuildBridgeGUI._tab_canvas_for_event


class PollHarness:
    def __init__(self) -> None:
        self.result_queue: queue.Queue[CommandResult] = queue.Queue()
        self.after_calls: list[tuple[int, object]] = []
        self.results: list[CommandResult] = []

    def after(self, delay: int, callback: object) -> None:
        self.after_calls.append((delay, callback))

    def _show_result(self, result: CommandResult) -> None:
        self.results.append(result)

    _poll = gui.GuildBridgeGUI._poll


def test_gui_builds_full_tk_surface_when_a_desktop_session_is_available() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk desktop session is unavailable: {exc}")

    try:
        root.withdraw()
        application = gui.GuildBridgeGUI(root)
        root.update_idletasks()

        notebooks = [widget for widget in application.winfo_children() if isinstance(widget, gui.ttk.Notebook)]
        assert len(notebooks) == 1
        assert [notebooks[0].tab(tab_id, "text") for tab_id in notebooks[0].tabs()] == [
            "Export",
            "Import",
            "Migrate",
            "Content",
            "Validate / Redact",
            "Platforms",
        ]
        assert len(application.themed_canvases) == 6
        assert application.output.winfo_exists()

        application.theme.set("Dark")
        application._apply_theme()
        assert root.cget("background") == gui.GUI_THEMES["Dark"]["bg"]
    finally:
        root.destroy()


def test_selected_providers_defaults_to_first_and_keeps_multi_selection() -> None:
    providers = FakeListbox(["stoat", "fluxer", "matrix"])

    assert gui.GuildBridgeGUI._selected_providers(providers) == ["stoat"]

    providers.selected = [0, 2]
    assert gui.GuildBridgeGUI._selected_providers(providers) == ["stoat", "matrix"]


def test_select_only_provider_falls_back_to_first() -> None:
    providers = FakeListbox(["stoat", "fluxer"], selected=(1,))

    gui.GuildBridgeGUI._select_only_provider(providers, "fluxer")
    assert providers.selected == [1]

    gui.GuildBridgeGUI._select_only_provider(providers, "missing")
    assert providers.selected == [0]


def test_fill_migrate_paths_resets_reviewed_plan(monkeypatch) -> None:
    harness = PathHarness()
    template_out = FakeVar()
    plan_out = FakeVar()
    reviewed = FakeVar("old-review.json")
    journal_out = FakeVar()
    monkeypatch.setattr(gui, "default_migration_artifact_dir", lambda: Path("artifacts"))
    monkeypatch.setattr(
        gui,
        "migration_artifact_paths",
        lambda *_args, **_kwargs: {
            "template_out": "artifacts/discord-to-stoat.template.json",
            "plan_out": "artifacts/discord-to-stoat.plan.json",
            "journal_out": "artifacts/discord-to-stoat.journal.json",
        },
    )

    gui.GuildBridgeGUI._fill_migrate_paths(
        harness,
        "discord",
        ["stoat"],
        template_out,
        plan_out,
        reviewed,
        journal_out,
    )

    assert template_out.get().endswith(".template.json")
    assert plan_out.get().endswith(".plan.json")
    assert reviewed.get() == ""
    assert journal_out.get().endswith(".journal.json")
    assert harness.created_files == [template_out.get()]


def test_fill_content_paths_creates_all_non_secret_artifact_locations(monkeypatch) -> None:
    harness = PathHarness()
    vars_ = [FakeVar() for _ in range(11)]
    monkeypatch.setattr(gui, "default_migration_artifact_dir", lambda: Path("artifacts"))
    monkeypatch.setattr(
        gui,
        "content_artifact_paths",
        lambda *_args, **_kwargs: {
            "discord_export_out": "artifacts/discord-export",
            "archive_out": "artifacts/archive.json",
            "plan_out": "artifacts/content.plan.json",
            "content_journal_out": "artifacts/content.journal.json",
            "content_dead_letter_out": "artifacts/content.dead-letter.json",
            "content_report_out": "artifacts/content.report.json",
            "content_lock_file": "artifacts/content.lock",
            "content_incremental_state": "artifacts/content.state.json",
            "content_thread_archive_dir": "artifacts/threads",
        },
    )

    gui.GuildBridgeGUI._fill_content_paths(harness, ["stoat"], *vars_)

    discord_export_out, archive_file, archive_out, plan_out, reviewed, journal, dead_letter, report, lock, state, threads = vars_
    assert archive_file.get() == archive_out.get()
    assert plan_out.get().endswith(".plan.json")
    assert reviewed.get() == ""
    assert journal.get().endswith(".journal.json")
    assert harness.created_files == [archive_out.get()]
    assert harness.created_dirs == [discord_export_out.get(), threads.get()]
    assert dead_letter.get().endswith(".json")
    assert report.get().endswith(".json")
    assert lock.get().endswith(".lock")
    assert state.get().endswith(".json")


def test_migrate_guard_blocks_discord_channel_id(monkeypatch) -> None:
    harness = RunHarness()
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui, "discord_source_id_warning", lambda _source_id: "Use a Discord server ID.")
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))

    gui.GuildBridgeGUI._run_migrate_with_source_guard(
        harness,
        ["migrate"],
        provider_from="discord",
        source_id="123",
        plan_out="plan.json",
    )

    assert errors == [("Dry-run Check", "Use a Discord server ID.")]
    assert harness.calls == []


def test_migrate_guard_runs_non_discord_route(monkeypatch) -> None:
    harness = RunHarness()
    monkeypatch.setattr(gui, "discord_source_id_warning", lambda _source_id: "unexpected")

    gui.GuildBridgeGUI._run_migrate_with_source_guard(
        harness,
        ["migrate", "--from", "stoat"],
        provider_from="stoat",
        source_id="server",
        plan_out="plan.json",
    )

    assert harness.calls == [("dry-run", (["migrate", "--from", "stoat"], "plan.json"))]


def test_dry_run_requires_a_file_path_before_launching(monkeypatch) -> None:
    harness = SimpleNamespace(master=object(), calls=[])
    harness._run = lambda args: harness.calls.append(args)
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))

    gui.GuildBridgeGUI._run_dry_run(harness, ["migrate"], plan_out="-")
    assert harness.calls == []
    assert errors[0][0] == "Dry-run Check"

    gui.GuildBridgeGUI._run_dry_run(harness, ["migrate"], plan_out="plan.json")
    assert harness.calls == [["migrate"]]


def test_reviewed_plan_preview_and_confirmation_message(tmp_path: Path) -> None:
    reviewed = tmp_path / "reviewed.plan.json"
    reviewed.write_text(
        json.dumps(
            {
                "plan": {
                    "context": {
                        "source_provider": "discord",
                        "provider": "stoat",
                        "target_id": "target",
                        "target_name": "Target server",
                    },
                    "action_count": 2,
                },
                "actions": [
                    {"provider": "stoat", "method": "POST", "path": "/servers/target/channels"},
                    {"provider": "stoat", "method": "POST", "path": "/servers/target/channels"},
                ],
            }
        ),
        encoding="utf-8",
    )

    preview = gui.GuildBridgeGUI._reviewed_plan_preview(str(reviewed))
    prompt = gui.ApplyPrompt("Migrate", "discord", ("stoat",), "target", "Target server")
    message = gui.GuildBridgeGUI._apply_confirmation_message(prompt, str(reviewed), "result.json", preview)

    assert "Planned write actions: 2" in preview
    assert any("stoat POST /servers/target/channels x2" in line for line in preview)
    assert "Operation: Migrate" in message
    assert "Apply result output: result.json" in message


def test_discord_stoat_wizard_selects_route_and_fills_paths(monkeypatch) -> None:
    harness = PathHarness()
    provider_from = FakeVar("matrix")
    provider_to = FakeListbox(["fluxer", "stoat"])
    template_out = FakeVar()
    plan_out = FakeVar()
    reviewed = FakeVar("old.json")
    journal = FakeVar()
    monkeypatch.setattr(gui, "default_migration_artifact_dir", lambda: Path("artifacts"))
    monkeypatch.setattr(
        gui,
        "migration_artifact_paths",
        lambda *_args, **_kwargs: {
            "template_out": "artifacts/discord-to-stoat.template.json",
            "plan_out": "artifacts/discord-to-stoat.plan.json",
            "journal_out": "artifacts/discord-to-stoat.journal.json",
        },
    )

    gui.GuildBridgeGUI._prepare_discord_stoat_wizard(
        harness, provider_from, provider_to, template_out, plan_out, reviewed, journal
    )

    assert provider_from.get() == "discord"
    assert provider_to.selected == [1]
    assert template_out.get().endswith("discord-to-stoat.template.json")
    assert plan_out.get().endswith("discord-to-stoat.plan.json")
    assert reviewed.get() == ""
    assert journal.get().endswith("discord-to-stoat.journal.json")


def test_prepare_content_target_enables_safe_recovery_defaults(monkeypatch) -> None:
    harness = PathHarness()
    provider_to = FakeListbox(["fluxer", "stoat"], selected=(1,))
    text_vars = [FakeVar() for _ in range(11)]
    download_exporter = FakeVar()  # type: ignore[arg-type]
    incremental = FakeVar()  # type: ignore[arg-type]
    continue_on_error = FakeVar()  # type: ignore[arg-type]
    calls: list[tuple[object, ...]] = []

    def fill(*args: object) -> None:
        calls.append(args)

    monkeypatch.setattr(harness, "_fill_content_paths", fill, raising=False)
    gui.GuildBridgeGUI._prepare_selected_content_target(
        harness,
        provider_to,
        *text_vars,
        download_exporter,
        incremental,
        continue_on_error,
    )

    assert download_exporter.get() is True
    assert incremental.get() is True
    assert continue_on_error.get() is True
    assert calls[0][0] == ["stoat"]


def test_access_helpers_validate_provider_and_target_selection(monkeypatch) -> None:
    harness = ValueHarness()
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    monkeypatch.setattr(gui, "discord_source_id_warning", lambda value: "bad id" if value == "bad" else None)

    gui.GuildBridgeGUI._check_provider_access(harness, "", "server", "Check")
    gui.GuildBridgeGUI._check_provider_access(harness, "discord", "bad", "Check")
    gui.GuildBridgeGUI._check_provider_access(harness, "stoat", "server", "Check")
    gui.GuildBridgeGUI._check_selected_target_access(harness, FakeListbox(["stoat", "fluxer"], selected=(0, 1)), "id")
    gui.GuildBridgeGUI._check_selected_target_access(harness, FakeListbox(["stoat"], selected=(0,)), "id")

    assert errors == [
        ("Check", "Provider is required."),
        ("Check", "bad id"),
        ("Check target access", "Select exactly one target provider."),
    ]
    assert harness.calls == [("stoat", "server", "Check"), ("stoat", "id", "Check target access")]


def test_use_plan_as_reviewed_changes_apply_output_and_rejects_stdout(monkeypatch) -> None:
    harness = ValueHarness()
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    plan_out = FakeVar("-")
    reviewed = FakeVar()

    gui.GuildBridgeGUI._use_plan_as_reviewed(harness, "discord", ["stoat"], plan_out, reviewed)
    assert errors == [("Use Plan as Reviewed", "Plan/result JSON must contain a dry-run plan file path.")]

    plan_out.set("C:/plans/migration.plan.json")
    gui.GuildBridgeGUI._use_plan_as_reviewed(harness, "discord", ["stoat"], plan_out, reviewed)
    assert reviewed.get() == "C:/plans/migration.plan.json"
    assert Path(plan_out.get()).name == "migration.apply-result.json"


def test_apply_guard_blocks_invalid_discord_source_and_forwards_valid_route(monkeypatch) -> None:
    harness = RunHarness()
    errors: list[tuple[object, ...]] = []
    prompt = gui.ApplyPrompt("Migrate", "discord", ("stoat",), "target", "Target")
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    monkeypatch.setattr(gui, "discord_source_id_warning", lambda value: "bad id" if value == "bad" else None)

    gui.GuildBridgeGUI._run_apply_with_source_guard(
        harness,
        ["migrate"],
        provider_from="discord",
        source_id="bad",
        reviewed_plan="reviewed.json",
        plan_out="result.json",
        apply_prompt=prompt,
    )
    gui.GuildBridgeGUI._run_apply_with_source_guard(
        harness,
        ["migrate"],
        provider_from="discord",
        source_id="guild",
        reviewed_plan="reviewed.json",
        plan_out="result.json",
        apply_prompt=prompt,
    )

    assert errors == [("Actual run", "bad id")]
    assert harness.calls == [
        (
            "run",
            (
                ["migrate"],
                {
                    "apply_requested": True,
                    "reviewed_plan": "reviewed.json",
                    "plan_out": "result.json",
                    "apply_prompt": prompt,
                },
            ),
        )
    ]


def test_result_dialog_truncates_details_and_show_result_reports_status(monkeypatch) -> None:
    harness = OutputHarness()
    dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _title, message, **_kwargs: dialogs.append(("error", message)))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda _title, message, **_kwargs: dialogs.append(("info", message)))

    failed = CommandResult(("migrate",), ("python", "-m", "guildbridge"), 1, "", "x" * 2000, 0.25)
    gui.GuildBridgeGUI._show_result(harness, failed)
    successful = CommandResult(("migrate",), ("python", "-m", "guildbridge"), 0, "done", "", 0.5)
    gui.GuildBridgeGUI._show_result(harness, successful)

    assert "Status: failed" in "".join(harness.appended)
    assert "Status: completed successfully" in "".join(harness.appended)
    assert dialogs[0][0] == "error"
    assert dialogs[0][1].endswith("\n...")
    assert dialogs[1][0] == "info"


def test_confirm_apply_validates_plan_then_uses_yes_no_prompt(monkeypatch, tmp_path: Path) -> None:
    harness = ConfirmHarness()
    errors: list[tuple[object, ...]] = []
    prompts: list[str] = []
    reviewed = tmp_path / "reviewed.plan.json"
    reviewed.write_text(json.dumps({"plan": {"context": {}, "action_count": 0}, "actions": []}), encoding="utf-8")

    def confirm(_title: str, message: str, **_kwargs: object) -> bool:
        prompts.append(message)
        return True

    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    monkeypatch.setattr(gui.messagebox, "askyesno", confirm)

    assert gui.GuildBridgeGUI._confirm_apply(harness, "", "result.json", None) is False
    assert gui.GuildBridgeGUI._confirm_apply(harness, str(reviewed), "result.json", None) is True
    assert errors[0][0] == "Actual run"
    assert "Continue with the actual run?" in prompts[0]


def test_export_guard_and_access_check_show_clear_validation_errors(monkeypatch) -> None:
    harness = ValueHarness()
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    monkeypatch.setattr(gui, "discord_source_id_warning", lambda value: "bad id" if value == "bad" else None)

    gui.GuildBridgeGUI._check_access(harness, "stoat", "", "Check source")
    gui.GuildBridgeGUI._run_export_with_source_guard(harness, ["export"], provider_from="discord", source_id="bad")
    gui.GuildBridgeGUI._run_export_with_source_guard(harness, ["export"], provider_from="stoat", source_id="server")

    assert errors == [
        ("Check source", "Server/guild/community ID is required."),
        ("Run Export", "bad id"),
    ]
    assert harness.calls == [(["export"], {})]


def test_discord_invite_reports_invalid_client_id_or_opens_valid_url(monkeypatch) -> None:
    harness = ValueHarness()
    errors: list[tuple[object, ...]] = []
    opened: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *args, **_kwargs: errors.append(args))
    monkeypatch.setattr(gui.RuntimeConfig, "from_env", classmethod(lambda _cls: SimpleNamespace(discord_token="token")))
    monkeypatch.setattr(gui.webbrowser, "open", lambda url: opened.append(url))

    gui.GuildBridgeGUI._open_discord_invite(harness, "")
    gui.GuildBridgeGUI._open_discord_invite(harness, "123456")

    assert errors and errors[0][0] == "Invite Discord Bot"
    assert opened and "client_id=123456" in opened[0]


def test_reviewed_plan_preview_rejects_invalid_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[1, 2, 3]", encoding="utf-8")

    try:
        gui.GuildBridgeGUI._reviewed_plan_preview(str(missing))
    except ValueError as exc:
        assert "Could not read reviewed plan JSON" in str(exc)
    else:
        raise AssertionError("missing reviewed plan should be rejected")

    try:
        gui.GuildBridgeGUI._reviewed_plan_preview(str(invalid))
    except ValueError as exc:
        assert "must contain an object" in str(exc)
    else:
        raise AssertionError("non-object reviewed plan should be rejected")


def test_mousewheel_routes_only_inside_tab_canvas() -> None:
    canvas = FakeCanvas()
    harness = MouseHarness(canvas)
    down = SimpleNamespace(x_root=1, y_root=2, delta=-120, num=None)
    up = SimpleNamespace(x_root=1, y_root=2, delta=120, num=None)

    assert gui.GuildBridgeGUI._on_tab_mousewheel(harness, down) == "break"
    assert gui.GuildBridgeGUI._on_tab_mousewheel(harness, up) == "break"
    assert canvas.scrolls == [(3, "units"), (-3, "units")]


def test_path_helpers_create_parent_and_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "nested" / "file.json"
    folder = tmp_path / "nested" / "folder"

    gui.GuildBridgeGUI._ensure_file_parent(str(file_path))
    gui.GuildBridgeGUI._ensure_directory(str(folder))
    gui.GuildBridgeGUI._ensure_file_parent("-")
    gui.GuildBridgeGUI._ensure_directory("")

    assert file_path.parent.is_dir()
    assert folder.is_dir()


def test_poll_reschedules_when_empty_then_displays_result() -> None:
    harness = PollHarness()
    gui.GuildBridgeGUI._poll(harness)
    assert harness.after_calls == [(100, harness._poll)]

    result = CommandResult(("providers",), ("python",), 0, "ok", "", 0.1)
    harness.result_queue.put(result)
    gui.GuildBridgeGUI._poll(harness)
    assert harness.results == [result]

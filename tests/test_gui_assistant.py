from __future__ import annotations

from pathlib import Path

from guildbridge.gui_assistant import (
    DISCORD_MIGRATION_PERMISSION_INTEGER,
    content_artifact_paths,
    default_migration_artifact_dir,
    discord_bot_invite_url,
    discord_client_id_from_token,
    discord_source_id_warning,
    export_artifact_paths,
    import_artifact_paths,
    migration_artifact_paths,
)


def test_discord_bot_invite_url_uses_least_privilege_permissions() -> None:
    url = discord_bot_invite_url(" 12345 ")

    assert "client_id=12345" in url
    assert f"permissions={DISCORD_MIGRATION_PERMISSION_INTEGER}" in url
    assert "scope=bot" in url


def test_discord_bot_invite_url_can_derive_client_id_from_token() -> None:
    token = "MTIzNDU.foo.bar"

    assert discord_client_id_from_token(token) == "12345"
    assert "client_id=12345" in discord_bot_invite_url(token=token)


def test_discord_source_id_warning_detects_channel_url() -> None:
    warning = discord_source_id_warning("https://discord.com/channels/111111111111111111/222222222222222222")

    assert warning is not None
    assert "server/guild ID 111111111111111111" in warning
    assert "not channel ID 222222222222222222" in warning


def test_migration_artifact_paths_are_provider_named(tmp_path: Path) -> None:
    paths = migration_artifact_paths(tmp_path, source_provider="Discord", target_providers=["Stoat", "Fluxer"])

    assert paths == {
        "template_out": str(tmp_path / "guildbridge-discord-to-stoat-fluxer.template.json"),
        "plan_out": str(tmp_path / "guildbridge-discord-to-stoat-fluxer.plan.json"),
        "apply_result": str(tmp_path / "guildbridge-discord-to-stoat-fluxer.apply-result.json"),
        "journal_out": str(tmp_path / "guildbridge-discord-to-stoat-fluxer.journal.json"),
    }


def test_export_artifact_paths_are_provider_named(tmp_path: Path) -> None:
    assert export_artifact_paths(tmp_path, provider="Rocket.Chat") == {
        "out": str(tmp_path / "guildbridge-rocket-chat-export.template.json")
    }


def test_import_artifact_paths_are_target_named(tmp_path: Path) -> None:
    assert import_artifact_paths(tmp_path, target_providers=["Stoat", "Fluxer"]) == {
        "plan_out": str(tmp_path / "guildbridge-import-to-stoat-fluxer.plan.json"),
        "apply_result": str(tmp_path / "guildbridge-import-to-stoat-fluxer.apply-result.json"),
        "journal_out": str(tmp_path / "guildbridge-import-to-stoat-fluxer.journal.json"),
    }


def test_content_artifact_paths_are_target_named(tmp_path: Path) -> None:
    paths = content_artifact_paths(tmp_path, target_providers=["Stoat"])

    assert paths["discord_export_out"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.discord-export")
    assert paths["archive_out"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.content.json")
    assert paths["plan_out"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.plan.json")
    assert paths["apply_result"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.apply-result.json")
    assert paths["content_journal_out"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.journal.json")
    assert paths["content_dead_letter_out"] == str(
        tmp_path / "content" / "guildbridge-content-discord-to-stoat.dead-letter.json"
    )
    assert paths["content_report_out"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.report.json")
    assert paths["content_lock_file"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.lock")
    assert paths["content_incremental_state"] == str(
        tmp_path / "content" / "guildbridge-content-discord-to-stoat.incremental-state.json"
    )
    assert paths["content_thread_archive_dir"] == str(tmp_path / "content" / "guildbridge-content-discord-to-stoat.threads")

    stoat_paths = content_artifact_paths(tmp_path, source_provider="stoat", target_providers=["Fluxer"])
    assert stoat_paths["archive_out"].endswith("guildbridge-content-stoat-to-fluxer.content.json")


def test_default_migration_artifact_dir_uses_ignored_guildbridge_folder(tmp_path: Path) -> None:
    assert default_migration_artifact_dir(tmp_path) == tmp_path / ".guildbridge" / "gui"

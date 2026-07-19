from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest

from guildbridge.config import RuntimeConfig
from guildbridge.content import (
    CONTENT_CAPABILITIES_SCHEMA,
    CONTENT_FEATURES,
    ContentArchive,
    ContentAttachment,
    ContentAuthor,
    ContentCapability,
    ContentChannel,
    ContentEmbed,
    ContentImportOptions,
    ContentMessage,
    ContentReaction,
    ContentSource,
    DiscordChatExporterBootstrapOptions,
    DiscordChatExporterOptions,
    apply_content_actions,
    content_action_key,
    content_capabilities_document,
    content_not_implemented_message,
    download_discord_chat_exporter,
    dry_run_content_import,
    load_channel_map,
    load_completed_content_actions,
    load_discord_chat_export,
    resolve_content_asset_path,
    run_discord_chat_exporter,
    selected_content_features,
)
from guildbridge.models import Action
from guildbridge.providers.daccord import DaccordProvider
from guildbridge.providers.discord import DiscordProvider
from guildbridge.providers.fluxer import FluxerProvider
from guildbridge.providers.matrix import MatrixProvider
from guildbridge.providers.mattermost import MattermostProvider
from guildbridge.providers.rocket_chat import RocketChatProvider
from guildbridge.providers.stoat import StoatProvider
from guildbridge.providers.zulip import ZulipProvider


class RecordingContentHttp:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, object], dict[str, str]]] = []
        self.puts: list[tuple[str, dict[str, object] | None, dict[str, str]]] = []
        self.patches: list[tuple[str, dict[str, object] | None, dict[str, str]]] = []

    def post(self, path: str, *, json_body: dict[str, object], headers: dict[str, str]) -> dict[str, str]:
        self.posts.append((path, json_body, headers))
        return {"_id": f"message-{len(self.posts)}"}

    def put(
        self,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str],
    ) -> dict[str, str]:
        self.puts.append((path, json_body, headers))
        return {"ok": "true"}

    def patch(
        self,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str],
    ) -> dict[str, str]:
        self.patches.append((path, json_body, headers))
        return {"ok": "true"}


class RecordingAutumnHttp:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, dict[str, str]]] = []

    def post_file(self, path: str, *, file_path: Path, headers: dict[str, str]) -> dict[str, str]:
        self.uploads.append((path, str(file_path), headers))
        return {"id": f"file-{len(self.uploads)}"}


class RecordingNativeHttp:
    def __init__(self) -> None:
        self.posts: list[dict[str, object]] = []
        self.post_files_calls: list[dict[str, object]] = []
        self.post_file_calls: list[dict[str, object]] = []
        self.post_raw_calls: list[dict[str, object]] = []
        self.post_form_calls: list[dict[str, object]] = []
        self.puts: list[dict[str, object]] = []
        self.patches: list[dict[str, object]] = []
        self.gets: list[str] = []

    def post(
        self,
        path: str,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.posts.append({"path": path, "json_body": json_body, "headers": headers})
        if path == "/posts":
            return {"id": f"post-{sum(1 for call in self.posts if call['path'] == '/posts')}"}
        if path == "/chat.postMessage":
            return {"message": {"_id": f"rocket-{sum(1 for call in self.posts if call['path'] == '/chat.postMessage')}"}}
        return {"id": f"message-{len(self.posts) + len(self.post_files_calls)}"}

    def post_files(
        self,
        path: str,
        *,
        file_paths: list[Path],
        field_prefix: str,
        form_body: dict[str, object],
        indexed_fields: bool,
    ) -> dict[str, object]:
        self.post_files_calls.append(
            {
                "path": path,
                "file_paths": [str(path) for path in file_paths],
                "field_prefix": field_prefix,
                "form_body": form_body,
                "indexed_fields": indexed_fields,
            }
        )
        return {"id": f"message-{len(self.post_files_calls)}"}

    def post_file(
        self,
        path: str,
        *,
        file_path: Path,
        field_name: str,
        form_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.post_file_calls.append(
            {"path": path, "file_path": str(file_path), "field_name": field_name, "form_body": form_body, "headers": headers}
        )
        if path == "/files":
            return {"file_infos": [{"id": f"file-{len(self.post_file_calls)}"}]}
        if path == "/user_uploads":
            return {"uri": f"/user_uploads/file-{len(self.post_file_calls)}"}
        return {"id": f"file-{len(self.post_file_calls)}"}

    def post_raw(
        self,
        path: str,
        data_body: bytes,
        params: dict[str, object],
        headers: dict[str, str],
    ) -> dict[str, str]:
        self.post_raw_calls.append({"path": path, "data_body": data_body, "params": params, "headers": headers})
        return {"content_uri": f"mxc://example/file-{len(self.post_raw_calls)}"}

    def post_form(
        self,
        path: str,
        form_body: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.post_form_calls.append({"path": path, "form_body": form_body, "headers": headers})
        return {"id": f"zulip-{len(self.post_form_calls)}"}

    def put(
        self,
        path: str,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.puts.append({"path": path, "json_body": json_body, "headers": headers})
        return {"event_id": f"event-{len(self.puts)}"}

    def patch(
        self,
        path: str,
        json_body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.patches.append({"path": path, "json_body": json_body, "headers": headers})
        return {"ok": True}

    def get(self, path: str, headers: dict[str, str] | None = None) -> dict[str, str]:
        del headers
        self.gets.append(path)
        return {"id": "user-1"}


def test_selected_content_features_are_opt_in() -> None:
    assert selected_content_features(include_content=False) == []
    assert selected_content_features(include_content=True) == list(CONTENT_FEATURES)
    assert selected_content_features(include_content=False, requested_features=["messages"]) == ["messages"]


def test_selected_content_features_reject_unknown_name() -> None:
    with pytest.raises(ValueError, match="Unknown content feature"):
        selected_content_features(include_content=False, requested_features=["history"])


def test_resolve_content_asset_path_downloads_remote_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200
        headers = {"content-length": "11"}

        def iter_content(self, *, chunk_size: int) -> Iterator[bytes]:
            del chunk_size
            yield b"hello "
            yield b"world"

    calls: list[tuple[str, bool, int]] = []

    def fake_get(url: str, *, stream: bool, timeout: int) -> Response:
        calls.append((url, stream, timeout))
        return Response()

    monkeypatch.setattr("guildbridge.content.requests.get", fake_get)
    warnings: list[str] = []

    path = resolve_content_asset_path(
        {"url": "https://cdn.example.invalid/path/file.txt", "filename": "file.txt"},
        label="attachment",
        allow_remote_download=True,
        warnings=warnings,
        cache_dir=tmp_path / "remote-assets",
        max_bytes=100,
    )

    assert path is not None
    assert path.read_bytes() == b"hello world"
    assert calls == [("https://cdn.example.invalid/path/file.txt", True, 60)]
    assert warnings == []


def test_content_capabilities_document_marks_templates_private_by_default() -> None:
    doc = content_capabilities_document([ContentCapability.planned_for_provider("discord")])

    assert doc["schema"] == CONTENT_CAPABILITIES_SCHEMA
    assert doc["default_enabled"] is False
    assert doc["privacy"]["normal_templates_include_content"] is False
    assert doc["providers"][0]["import"]["messages"] == "planned"


def test_content_not_implemented_message_names_provider_path_and_features() -> None:
    message = content_not_implemented_message(
        source_provider="discord",
        target_providers=["stoat", "fluxer"],
        features=["messages", "attachments"],
    )

    assert "discord -> stoat, fluxer" in message
    assert "messages, attachments" in message
    assert "privacy-safe" in message


def test_discord_chat_exporter_json_converts_to_private_content_archive(tmp_path: Path) -> None:
    export_path = tmp_path / "general.json"
    export_path.write_text(
        json.dumps(
            {
                "guild": {"id": "example-guild-id", "name": "Example Server"},
                "channel": {"id": "example-channel-id", "name": "general"},
                "messages": [
                    {
                        "id": "example-message-id",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "author": {"id": "example-user-id", "name": "Alice"},
                        "content": "Hello from Discord <:wave:123456789>",
                        "attachments": [{"fileName": "guide.png", "url": "https://cdn.example/guide.png"}],
                        "reactions": [{"emoji": {"name": "thumbs-up"}, "count": 2}],
                        "embeds": [{"title": "Docs", "url": "https://example.invalid/docs"}],
                        "stickers": [{"id": "sticker-1", "name": "Ship it", "url": "https://cdn.example/sticker.png"}],
                        "poll": {"question": {"text": "Move?"}, "answers": [{"text": "Yes", "count": 3}]},
                        "threadId": "thread-1",
                        "isPinned": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    archive = load_discord_chat_export(export_path)

    assert archive.schema == "guildbridge.content.v1"
    assert archive.name == "Example Server"
    assert archive.source.platform == "discord"
    assert archive.source.id_hash != "example-guild-id"
    assert archive.channels[0].id != "example-channel-id"
    assert any(channel.type == "thread" and channel.parent_id == archive.channels[0].id for channel in archive.channels)
    assert archive.messages[0].id != "example-message-id"
    assert archive.messages[0].author.id_hash != "example-user-id"
    assert archive.messages[0].attachments[0].filename == "guide.png"
    assert archive.messages[0].stickers[0].name == "Ship it"
    assert archive.messages[0].poll is not None
    assert archive.messages[0].poll.question == "Move?"
    assert archive.messages[0].thread_id is not None
    assert archive.emoji[0].name == "wave"
    assert archive.stickers[0].name == "Ship it"
    assert "polls" in archive.features
    assert "stickers" in archive.features
    assert archive.validate() == []
    plan = dry_run_content_import("stoat", archive, ContentImportOptions(channel_map={archive.channels[0].id: "target"}))
    planned_text = str(plan.actions[0].payload["content"])
    assert "Stickers:" in planned_text
    assert "Poll: Move?" in planned_text
    assert "Custom emoji: wave" in planned_text


def test_run_discord_chat_exporter_invokes_local_cli_and_redacts_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_path = tmp_path / "dce"
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(command: list[str], **_kwargs: object) -> Completed:
        calls.append(command)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "general.json").write_text(
            json.dumps({"guild": {"id": "guild-1", "name": "Example"}, "channel": {"id": "chan-1"}, "messages": []}),
            encoding="utf-8",
        )
        return Completed()

    monkeypatch.setenv("DISCORD_TOKEN", "secret-token")
    monkeypatch.setattr("guildbridge.content.subprocess.run", fake_run)

    result_path = run_discord_chat_exporter(
        DiscordChatExporterOptions(exporter_bin="DiscordChatExporter.Cli", guild_id="guild-1", output_path=output_path)
    )

    assert result_path == output_path
    assert calls[0][:2] == ["DiscordChatExporter.Cli", "exportguild"]
    assert calls[0][calls[0].index("-g") + 1] == "guild-1"
    archive = load_discord_chat_export(result_path)
    assert archive.name == "Example"


def test_run_discord_chat_exporter_error_hides_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Completed:
        returncode = 1
        stdout = ""
        stderr = "failed with secret-token"

    monkeypatch.setenv("DISCORD_TOKEN", "secret-token")
    monkeypatch.setattr("guildbridge.content.subprocess.run", lambda *_args, **_kwargs: Completed())

    with pytest.raises(ValueError) as error:
        run_discord_chat_exporter(
            DiscordChatExporterOptions(exporter_bin="DiscordChatExporter.Cli", guild_id="guild-1", output_path=tmp_path)
        )

    assert "[redacted]" in str(error.value)
    assert "secret-token" not in str(error.value)


def test_download_discord_chat_exporter_fetches_matching_release_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("DiscordChatExporter.Cli.exe", "binary")
    archive_bytes = archive.getvalue()
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    calls: list[str] = []

    class Response:
        def __init__(self, *, data: dict[str, object] | None = None, content: bytes = b"") -> None:
            self.status_code = 200
            self._data = data or {}
            self.content = content

        def json(self) -> dict[str, object]:
            return self._data

    def fake_get(url: str, **_kwargs: object) -> Response:
        calls.append(url)
        if url.endswith("/latest"):
            return Response(
                data={
                    "tag_name": "v2.0.0",
                    "assets": [
                        {"name": "DiscordChatExporter.Cli.linux-x64.zip", "browser_download_url": "https://example.invalid/linux.zip", "digest": f"sha256:{archive_sha256}"},
                        {"name": "DiscordChatExporter.Cli.win-x64.zip", "browser_download_url": "https://example.invalid/win.zip", "digest": f"sha256:{archive_sha256}"},
                    ],
                }
            )
        return Response(content=archive_bytes)

    monkeypatch.setattr("guildbridge.content.sys.platform", "win32")
    monkeypatch.setattr("guildbridge.content.platform.machine", lambda: "AMD64")
    monkeypatch.setattr("guildbridge.content.requests.get", fake_get)

    executable = download_discord_chat_exporter(
        DiscordChatExporterBootstrapOptions(install_dir=tmp_path / "tools", timeout_seconds=1)
    )

    assert executable.name == "DiscordChatExporter.Cli.exe"
    assert executable.read_text(encoding="utf-8") == "binary"
    assert calls[-1] == "https://example.invalid/win.zip"


def test_download_discord_chat_exporter_rejects_asset_without_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"assets": [{"name": "DiscordChatExporter.Cli.win-x64.zip", "browser_download_url": "https://example.invalid/win.zip"}]}

    monkeypatch.setattr("guildbridge.content.sys.platform", "win32")
    monkeypatch.setattr("guildbridge.content.platform.machine", lambda: "AMD64")
    monkeypatch.setattr("guildbridge.content.requests.get", lambda *_args, **_kwargs: Response())

    with pytest.raises(ValueError, match="SHA-256"):
        download_discord_chat_exporter(DiscordChatExporterBootstrapOptions(install_dir=tmp_path / "tools"))


def test_load_channel_map_accepts_plain_and_result_shapes(tmp_path: Path) -> None:
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"source": "target"}), encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(json.dumps({"id_map": {"source": "target"}}), encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"results": [{"id_map": {"source": "target"}}]}), encoding="utf-8")

    assert load_channel_map(plain) == {"source": "target"}
    assert load_channel_map(result) == {"source": "target"}
    assert load_channel_map(batch) == {"source": "target"}


def test_dry_run_content_import_maps_channels_and_splits_long_messages() -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", content="x" * 4000)],
    )

    result = dry_run_content_import(
        "stoat",
        archive,
        ContentImportOptions(channel_map={"source-channel": "target-channel"}),
    )

    assert result.applied is False
    assert len(result.actions) > 1
    assert {action.path for action in result.actions} == {"/content/channels/target-channel/messages"}
    assert result.actions[0].payload["part_index"] == 1
    assert result.actions[-1].payload["part_count"] == len(result.actions)
    assert result.actions[0].payload["source_channel_id"] == "source-channel"


def test_dry_run_content_import_thread_channel_mode_routes_to_thread_map() -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[
            ContentChannel(id="source-channel", name="general"),
            ContentChannel(id="thread-1", name="feature-thread", type="thread", parent_id="source-channel"),
        ],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", thread_id="thread-1", content="threaded")],
    )

    result = dry_run_content_import(
        "stoat",
        archive,
        ContentImportOptions(channel_map={"thread-1": "target-thread"}, thread_mode="channel"),
        path_template="/channels/{channel_id}/messages",
    )

    assert result.actions[0].path == "/channels/target-thread/messages"
    assert result.actions[0].payload["source_channel_id"] == "thread-1"
    assert result.actions[0].payload["original_source_channel_id"] == "source-channel"
    assert result.actions[0].payload["thread_mode"] == "channel"


def test_thread_markdown_mode_creates_local_archive_action_and_apply_writes_file(tmp_path: Path) -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[
            ContentChannel(id="source-channel", name="general"),
            ContentChannel(id="thread-1", name="feature-thread", type="thread", parent_id="source-channel"),
        ],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", thread_id="thread-1", content="threaded")],
    )
    plan = dry_run_content_import(
        "stoat",
        archive,
        ContentImportOptions(
            channel_map={"source-channel": "target-channel"},
            thread_mode="markdown",
            thread_archive_dir=str(tmp_path / "threads"),
        ),
    )

    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.method == "WRITE_MARKDOWN"
    assert str(tmp_path / "threads") in action.path
    result = apply_content_actions(
        "stoat",
        plan.actions,
        ContentImportOptions(
            apply=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
        lambda _action: pytest.fail("local markdown actions must not call provider APIs"),
    )

    assert result.applied is True
    markdown = Path(action.path).read_text(encoding="utf-8")
    assert "# Thread Archive: feature-thread" in markdown
    assert "threaded" in markdown


def test_apply_content_actions_writes_journal_report_and_incremental_state(tmp_path: Path) -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", content="hello")],
    )
    plan = dry_run_content_import("stoat", archive, ContentImportOptions(channel_map={"source-channel": "target-channel"}))
    journal = tmp_path / "journal.json"
    report = tmp_path / "report.json"
    dead_letter = tmp_path / "dead-letter.json"
    incremental = tmp_path / "state.json"
    lock = tmp_path / "content.lock"

    result = apply_content_actions(
        "stoat",
        plan.actions,
        ContentImportOptions(
            apply=True,
            journal_path=str(journal),
            report_path=str(report),
            dead_letter_path=str(dead_letter),
            incremental_state_path=str(incremental),
            lock_path=str(lock),
        ),
        lambda _action: {"_id": "posted-message"},
    )

    assert result.applied is True
    assert result.id_map["message-1:1"] == "posted-message"
    assert json.loads(journal.read_text(encoding="utf-8"))["events"][0]["status"] == "succeeded"
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "succeeded"
    assert "Fidelity score" in (tmp_path / "report.md").read_text(encoding="utf-8")
    assert content_action_key(plan.actions[0]) in load_completed_content_actions(incremental)
    assert not dead_letter.exists()


def test_apply_content_actions_parallelizes_across_channels_and_preserves_channel_order(tmp_path: Path) -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="channel-a", name="a"), ContentChannel(id="channel-b", name="b")],
        messages=[
            ContentMessage(id="a1", channel_id="channel-a", content="a1"),
            ContentMessage(id="b1", channel_id="channel-b", content="b1"),
            ContentMessage(id="a2", channel_id="channel-a", content="a2"),
            ContentMessage(id="b2", channel_id="channel-b", content="b2"),
        ],
    )
    plan = dry_run_content_import(
        "stoat",
        archive,
        ContentImportOptions(channel_map={"channel-a": "target-a", "channel-b": "target-b"}, parallel_sends=2),
    )
    first_wave = Barrier(2, timeout=2)
    seen_by_channel: dict[str, list[str]] = {"channel-a": [], "channel-b": []}

    def send(action: Action) -> dict[str, str]:
        payload = action.payload or {}
        source_channel = str(payload["source_channel_id"])
        seen_by_channel[source_channel].append(str(payload["source_message_id"]))
        if payload["source_message_id"] in {"a1", "b1"}:
            first_wave.wait()
        return {"_id": f"posted-{payload['source_message_id']}"}

    result = apply_content_actions(
        "stoat",
        plan.actions,
        ContentImportOptions(
            apply=True,
            parallel_sends=2,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
        send,
    )

    assert seen_by_channel == {"channel-a": ["a1", "a2"], "channel-b": ["b1", "b2"]}
    assert result.id_map["a1:1"] == "posted-a1"
    assert "parallel_sends enabled" in "\n".join(result.warnings)


def test_apply_content_actions_dead_letters_and_continues(tmp_path: Path) -> None:
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(id="message-1", channel_id="source-channel", content="first"),
            ContentMessage(id="message-2", channel_id="source-channel", content="second"),
        ],
    )
    plan = dry_run_content_import("stoat", archive, ContentImportOptions(channel_map={"source-channel": "target-channel"}))
    calls = 0

    def send(_action: object) -> dict[str, str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("token='secret' failed")
        return {"_id": "posted-message"}

    result = apply_content_actions(
        "stoat",
        plan.actions,
        ContentImportOptions(
            apply=True,
            continue_on_error=True,
            max_failures=2,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
        send,
    )

    dead_letter = json.loads((tmp_path / "dead-letter.json").read_text(encoding="utf-8"))
    assert result.id_map["message-2:1"] == "posted-message"
    assert dead_letter["failures"][0]["error"] == "token='[redacted]' failed"


def test_stoat_content_apply_posts_to_mapped_channels(tmp_path: Path) -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="token"))
    recorder = RecordingContentHttp()
    provider.http = recorder  # type: ignore[assignment]
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", content="hello")],
    )

    result = provider.import_content(
        archive,
            ContentImportOptions(
                apply=True,
                channel_map={"source-channel": "target-channel"},
                preserve_authors=False,
                journal_path=str(tmp_path / "journal.json"),
                report_path=str(tmp_path / "report.json"),
                dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert result.applied is True
    assert recorder.posts == [
        (
            "/channels/target-channel/messages",
            {"content": "hello", "silent": True},
            recorder.posts[0][2],
        )
    ]
    assert recorder.posts[0][2]["X-Bot-Token"] == "token"
    assert "Idempotency-Key" in recorder.posts[0][2]


def test_stoat_native_content_uses_uploads_embeds_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="token"))
    recorder = RecordingContentHttp()
    autumn = RecordingAutumnHttp()
    provider.http = recorder  # type: ignore[assignment]
    provider.autumn = autumn  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                author=ContentAuthor(display_name="Alice"),
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                embeds=[ContentEmbed(title="Docs", description="Read this", url="https://example.invalid/docs")],
            ),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                author=ContentAuthor(display_name="Bob"),
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    result = provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert result.applied is True
    assert autumn.uploads == [("/attachments", str(attachment), {"X-Bot-Token": "token"})]
    first_payload = recorder.posts[0][1]
    assert first_payload["attachments"] == ["file-1"]
    assert first_payload["embeds"] == [{"title": "Docs", "description": "Read this", "url": "https://example.invalid/docs"}]
    assert first_payload["masquerade"] == {"name": "Alice"}
    second_payload = recorder.posts[1][1]
    assert second_payload["replies"] == [{"id": "message-1", "mention": False}]
    assert second_payload["masquerade"] == {"name": "Bob"}
    assert recorder.puts == [
        ("/channels/target-channel/messages/message-2/pin", None, {"X-Bot-Token": "token"}),
        ("/channels/target-channel/messages/message-2/reactions/rocket", None, {"X-Bot-Token": "token"}),
    ]


def test_stoat_native_content_uploads_local_server_assets(tmp_path: Path) -> None:
    provider = StoatProvider(RuntimeConfig(stoat_token="token"))
    recorder = RecordingContentHttp()
    autumn = RecordingAutumnHttp()
    provider.http = recorder  # type: ignore[assignment]
    provider.autumn = autumn  # type: ignore[assignment]
    icon = tmp_path / "icon.png"
    banner = tmp_path / "banner.png"
    icon.write_bytes(b"icon")
    banner.write_bytes(b"banner")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", content="hello")],
        metadata={"server_icon_path": str(icon), "server_banner_path": str(banner)},
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            target_id="target-server",
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert autumn.uploads[:2] == [("/icons", str(icon), {"X-Bot-Token": "token"}), ("/banners", str(banner), {"X-Bot-Token": "token"})]
    assert recorder.patches == [("/servers/target-server", {"icon": "file-1", "banner": "file-2"}, {"X-Bot-Token": "token"})]


def test_discord_native_content_uses_files_embeds_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = DiscordProvider(RuntimeConfig(discord_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                embeds=[ContentEmbed(title="Docs", description="Read this", url="https://example.invalid/docs")],
            ),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_files_calls[0]["path"] == "/channels/target-channel/messages"
    first_payload = json.loads(str(recorder.post_files_calls[0]["form_body"]["payload_json"]))
    assert first_payload["attachments"] == [{"id": 0, "filename": "guide.txt"}]
    assert first_payload["embeds"][0]["title"] == "Docs"
    second_payload = recorder.posts[0]["json_body"]
    assert isinstance(second_payload, dict)
    assert second_payload["message_reference"] == {"message_id": "message-1", "fail_if_not_exists": False}
    assert [call["path"] for call in recorder.puts] == [
        "/channels/target-channel/messages/pins/message-2",
        "/channels/target-channel/messages/message-2/reactions/rocket/@me",
    ]


def test_discord_native_content_applies_local_server_assets(tmp_path: Path) -> None:
    provider = DiscordProvider(RuntimeConfig(discord_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    icon = tmp_path / "icon.png"
    banner = tmp_path / "banner.png"
    icon.write_bytes(b"icon")
    banner.write_bytes(b"banner")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[ContentMessage(id="message-1", channel_id="source-channel", content="hello")],
        metadata={"server_icon_path": str(icon), "server_banner_path": str(banner)},
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            target_id="target-guild",
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.patches[0]["path"] == "/guilds/target-guild"
    payload = recorder.patches[0]["json_body"]
    assert isinstance(payload, dict)
    assert str(payload["icon"]).startswith("data:image/png;base64,")
    assert str(payload["banner"]).startswith("data:image/png;base64,")


def test_mattermost_native_content_uses_files_embeds_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = MattermostProvider(RuntimeConfig(mattermost_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                embeds=[ContentEmbed(title="Docs", description="Read this", url="https://example.invalid/docs")],
            ),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_file_calls[0]["path"] == "/files"
    first_post = recorder.posts[0]["json_body"]
    assert isinstance(first_post, dict)
    assert first_post["file_ids"] == ["file-1"]
    assert first_post["props"] == {"attachments": [{"title": "Docs", "title_link": "https://example.invalid/docs", "text": "Read this"}]}
    second_post = recorder.posts[1]["json_body"]
    assert isinstance(second_post, dict)
    assert second_post["root_id"] == "post-1"
    assert [call["path"] for call in recorder.posts[2:]] == ["/posts/post-2/pin", "/reactions"]


def test_fluxer_native_content_uses_files_embeds_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = FluxerProvider(RuntimeConfig(fluxer_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                embeds=[ContentEmbed(title="Docs", description="Read this", url="https://example.invalid/docs")],
            ),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_files_calls[0]["path"] == "/channels/target-channel/messages"
    first_payload = json.loads(str(recorder.post_files_calls[0]["form_body"]["payload_json"]))
    assert first_payload["attachments"] == [{"id": 0, "filename": "guide.txt"}]
    assert first_payload["embeds"][0]["title"] == "Docs"
    second_payload = recorder.posts[0]["json_body"]
    assert isinstance(second_payload, dict)
    assert second_payload["message_reference"] == {"message_id": "message-1", "fail_if_not_exists": False}
    assert [call["path"] for call in recorder.puts] == [
        "/channels/target-channel/messages/pins/message-2",
        "/channels/target-channel/messages/message-2/reactions/rocket/@me",
    ]


def test_daccord_native_content_uses_files_embeds_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = DaccordProvider(RuntimeConfig(daccord_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                embeds=[ContentEmbed(title="Docs", description="Read this", url="https://example.invalid/docs")],
            ),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-channel"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_files_calls[0]["path"] == "/channels/target-channel/messages"
    first_payload = json.loads(str(recorder.post_files_calls[0]["form_body"]["payload_json"]))
    assert first_payload["attachments"] == [{"id": 0, "filename": "guide.txt"}]
    assert first_payload["embeds"][0]["title"] == "Docs"
    second_payload = recorder.posts[0]["json_body"]
    assert isinstance(second_payload, dict)
    assert second_payload["message_reference"] == {"message_id": "message-1", "fail_if_not_exists": False}
    assert [call["path"] for call in recorder.puts] == [
        "/channels/target-channel/messages/pins/message-2",
        "/channels/target-channel/messages/message-2/reactions/rocket/@me",
    ]


def test_matrix_native_content_uses_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(id="message-1", channel_id="source-channel", content="first"),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "!target:example.org"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    second_payload = recorder.puts[1]["json_body"]
    assert isinstance(second_payload, dict)
    assert second_payload["m.relates_to"] == {"m.in_reply_to": {"event_id": "event-1"}}
    assert any("m.room.pinned_events" in str(call["path"]) for call in recorder.puts[2:])
    assert any("m.reaction" in str(call["path"]) for call in recorder.puts[2:])


def test_rocket_chat_native_content_uses_uploads_replies_reactions_and_pins(tmp_path: Path) -> None:
    provider = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(id="message-1", channel_id="source-channel", content="first", attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))]),
            ContentMessage(
                id="message-2",
                channel_id="source-channel",
                content="second",
                reply_to_id="message-1",
                pinned=True,
                reactions=[ContentReaction(emoji="rocket", count=1)],
            ),
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-room"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_file_calls[0]["path"] == "/rooms.upload/target-room"
    first_payload = recorder.posts[0]["json_body"]
    assert isinstance(first_payload, dict)
    assert first_payload["roomId"] == "target-room"
    second_payload = recorder.posts[1]["json_body"]
    assert isinstance(second_payload, dict)
    assert second_payload["tmid"] == "rocket-1"
    assert [call["path"] for call in recorder.posts[2:]] == ["/chat.pinMessage", "/chat.react"]


def test_zulip_native_content_uses_uploads_and_reactions(tmp_path: Path) -> None:
    provider = ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="token"))
    recorder = RecordingNativeHttp()
    provider.http = recorder  # type: ignore[assignment]
    attachment = tmp_path / "guide.txt"
    attachment.write_text("hello", encoding="utf-8")
    archive = ContentArchive(
        name="Archive",
        source=ContentSource(platform="discord"),
        channels=[ContentChannel(id="source-channel", name="general")],
        messages=[
            ContentMessage(
                id="message-1",
                channel_id="source-channel",
                content="first",
                attachments=[ContentAttachment(filename="guide.txt", local_path=str(attachment))],
                reactions=[ContentReaction(emoji="rocket", count=1)],
            )
        ],
    )

    provider.import_content(
        archive,
        ContentImportOptions(
            apply=True,
            channel_map={"source-channel": "target-stream"},
            preserve_authors=False,
            native_content=True,
            journal_path=str(tmp_path / "journal.json"),
            report_path=str(tmp_path / "report.json"),
            dead_letter_path=str(tmp_path / "dead-letter.json"),
            lock_path=str(tmp_path / "content.lock"),
        ),
    )

    assert recorder.post_file_calls[0]["path"] == "/user_uploads"
    message_call = recorder.post_form_calls[0]
    assert message_call["path"] == "/messages"
    assert "Uploaded files:" in str(message_call["form_body"]["content"])
    assert recorder.post_form_calls[1]["path"] == "/messages/zulip-1/reactions"


def test_matrix_zulip_and_rocket_native_capabilities_are_opt_in() -> None:
    matrix = MatrixProvider(RuntimeConfig(matrix_access_token="token"))
    rocket = RocketChatProvider(RuntimeConfig(rocket_chat_auth_token="token", rocket_chat_user_id="user"))
    zulip = ZulipProvider(RuntimeConfig(zulip_email="bot@example.test", zulip_api_key="token"))

    assert matrix.content_capabilities().import_["role_colors"] == "supported"
    assert matrix.content_capabilities().import_["channel_permissions"] == "supported"
    assert matrix.content_capabilities().import_["nsfw_channels"] == "supported"
    assert matrix.content_capabilities().import_["attachments"] == "supported"
    assert matrix.content_capabilities().import_["reactions"] == "supported"
    assert rocket.content_capabilities().import_["pins"] == "supported"
    assert rocket.content_capabilities().import_["replies"] == "supported"
    assert zulip.content_capabilities().import_["attachments"] == "supported"
    assert zulip.content_capabilities().import_["reactions"] == "supported"

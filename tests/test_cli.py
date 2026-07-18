from __future__ import annotations

import json
from itertools import product
from pathlib import Path

from guildbridge.access import AccessCheckResult
from guildbridge.cli import main, write_json
from guildbridge.config import RuntimeConfig
from guildbridge.models import CommunityTemplate, Role
from guildbridge.providers import get_provider, provider_names
from guildbridge.providers.base import ImportOptions
from guildbridge.routes import canonical_provider_names, structure_route_document
from guildbridge.safety import APPLY_CONFIRMATION, validate_apply_safety


def test_providers_command(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "discord" in out
    assert "fluxer" in out
    assert "stoat" in out
    assert "spacebar" in out
    assert "daccord" in out
    assert "matrix" in out
    assert "rocket.chat" in out
    assert "mumble" in out
    assert "mattermost" in out
    assert "zulip" in out


def test_check_access_command_uses_provider_adapter(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    def fake_check_provider_access(provider: str, resource_id: str, _config: object) -> AccessCheckResult:
        assert provider == "stoat"
        assert resource_id == "server-id"
        return AccessCheckResult("stoat", "server-id", "Example", 2, 1, 3, 0)

    monkeypatch.setattr("guildbridge.cli.check_provider_access", fake_check_provider_access)

    assert main(["check-access", "--provider", "stoat", "--id", "server-id"]) == 0
    assert "stoat access ok: 'Example'" in capsys.readouterr().out


def test_content_features_command_json(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["content-features", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["schema"] == "guildbridge.content-capabilities.v1"
    assert data["default_enabled"] is False
    assert "messages" in data["features"]
    assert {provider["provider"] for provider in data["providers"]} >= {"discord", "stoat", "zulip"}


def test_routes_command_json(tmp_path: Path) -> None:
    routes_path = tmp_path / "routes.json"

    assert main(["routes", "--format", "json", "--out", str(routes_path)]) == 0
    data = json.loads(routes_path.read_text(encoding="utf-8"))
    providers = set(data["providers"])
    route_pairs = {(route["from"], route["to"]) for route in data["routes"]}

    assert data["schema"] == "guildbridge.structure-routes.v1"
    assert providers >= {"discord", "stoat", "fluxer", "matrix"}
    assert data["route_count"] == data["provider_count"] * data["provider_count"]
    assert data["multi_target"]["supported"] is True
    assert ("discord", "stoat") in route_pairs
    assert ("discord", "fluxer") in route_pairs
    assert ("discord", "matrix") in route_pairs
    assert ("stoat", "fluxer") in route_pairs
    assert ("fluxer", "discord") in route_pairs


def test_every_registered_provider_pair_has_a_structural_dry_run_contract() -> None:
    providers = canonical_provider_names()
    document = structure_route_document()
    route_pairs = {(route["from"], route["to"]) for route in document["routes"]}

    assert providers == sorted(provider_names())
    assert route_pairs == set(product(providers, repeat=2))
    assert len(route_pairs) == 100
    assert all(route["status"] == "supported" for route in document["routes"])
    assert all(route["route_type"] == "structure-template" for route in document["routes"])
    assert all(route["multi_target"] is True for route in document["routes"])

    template = CommunityTemplate(name="Route contract", roles=[Role(id="everyone", name="@everyone")])
    for target in providers:
        result = get_provider(target, RuntimeConfig()).import_template(
            template,
            ImportOptions(target_id="contract-target", target_name="Route contract"),
        )
        assert result.applied is False


def test_import_dry_run_handles_every_registered_destination_in_one_cli_batch(tmp_path: Path) -> None:
    providers = canonical_provider_names()
    template_path = tmp_path / "all-destinations.template.json"
    plan_path = tmp_path / "all-destinations.plan.json"
    template = CommunityTemplate(name="All destinations", roles=[Role(id="everyone", name="@everyone")])
    template_path.write_text(json.dumps(template.to_dict()), encoding="utf-8")

    arguments = ["import", "--file", str(template_path), "--plan-out", str(plan_path)]
    for provider in providers:
        arguments.extend(["--to", provider, "--target-id", f"{provider}=contract-target"])

    assert main(arguments) == 0

    batch = json.loads(plan_path.read_text(encoding="utf-8"))
    assert batch["command"] == "import"
    assert "source_provider" not in batch
    assert batch["target_providers"] == providers
    assert {result["provider"] for result in batch["results"]} == set(providers)
    assert all(result["applied"] is False for result in batch["results"])


def test_migrate_dry_run_exercises_every_registered_source_target_pair(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    providers = canonical_provider_names()
    template = CommunityTemplate(name="Route contract", roles=[Role(id="everyone", name="@everyone")])

    def offline_provider(name: str, config: RuntimeConfig):
        provider = get_provider(name, config)
        monkeypatch.setattr(provider, "export_template", lambda _options: template)
        return provider

    monkeypatch.setattr("guildbridge.cli.get_provider", offline_provider)

    for index, (source, target) in enumerate(product(providers, repeat=2)):
        plan_path = tmp_path / f"{index}-{source}-to-{target}.plan.json"
        assert (
            main(
                [
                    "migrate",
                    "--from",
                    source,
                    "--to",
                    target,
                    "--source-id",
                    "contract-source",
                    "--target-id",
                    f"{target}=contract-target",
                    "--plan-out",
                    str(plan_path),
                ]
            )
            == 0
        )
        result = json.loads(plan_path.read_text(encoding="utf-8"))
        assert result["provider"] == target
        assert result["applied"] is False
        context = result["plan"]["context"]
        assert context["command"] == "migrate"
        assert context["source_provider"] == source
        assert context["provider"] == target


def test_content_export_and_import_dry_run(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    export_path = tmp_path / "general.json"
    archive_path = tmp_path / "content.json"
    plan_path = tmp_path / "content.plan.json"
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
                        "content": "Hello from Discord",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["content-export", "--discord-chat-export", str(export_path), "--out", str(archive_path)]) == 0
    archive = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive["schema"] == "guildbridge.content.v1"

    assert (
        main(
            [
                "content-import",
                "--file",
                str(archive_path),
                "--to",
                "stoat",
                "--target-id",
                "target-server",
                "--plan-out",
                str(plan_path),
            ]
        )
        == 0
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert plan["provider"] == "stoat"
    assert plan["applied"] is False
    assert plan["plan"]["context"]["command"] == "content-import"
    assert plan["actions"][0]["payload"]["content"].endswith("Hello from Discord")
    assert "Planned 1 content action" in capsys.readouterr().err


def test_content_migrate_dry_run_supports_multiple_targets(tmp_path: Path) -> None:
    export_path = tmp_path / "general.json"
    plan_path = tmp_path / "batch.plan.json"
    export_path.write_text(
        json.dumps(
            {
                "guild": {"id": "example-guild-id", "name": "Example Server"},
                "channel": {"id": "example-channel-id", "name": "general"},
                "messages": [{"id": "example-message-id", "content": "Hello"}],
            }
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "content-migrate",
            "--from",
            "discord",
            "--discord-chat-export",
            str(export_path),
            "--to",
            "stoat,fluxer",
            "--plan-out",
            str(plan_path),
        ]
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert plan["schema"] == "guildbridge.batch-result.v1"
    assert plan["command"] == "content-migrate"
    assert plan["target_providers"] == ["stoat", "fluxer"]
    assert plan["action_count"] == 2


def test_include_content_is_explicitly_gated(capsys) -> None:  # type: ignore[no-untyped-def]
    rc = main(
        [
            "migrate",
            "--from",
            "discord",
            "--to",
            "stoat",
            "--template",
            "https://discord.new/example",
            "--include-content",
            "--content-feature",
            "messages",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "Optional content migration is not implemented" in err
    assert "guildbridge content-features --format json" in err


def test_validate_example() -> None:
    root = Path(__file__).resolve().parents[1]
    assert main(["validate", str(root / "examples" / "template.example.json")]) == 0


def test_redact_command(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "safe.json"
    rc = main(["redact", str(root / "examples" / "template.example.json"), "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["privacy"]["stores_tokens"] is False


def test_write_json_stdout_handles_emoji(capsys) -> None:  # type: ignore[no-untyped-def]
    write_json({"name": "Stats \U0001f4ca"}, "-")

    assert "Stats \U0001f4ca" in capsys.readouterr().out


def test_apply_requires_confirmation(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    template = CommunityTemplate(name="Example", roles=[Role(id="everyone", name="@everyone")])
    template_path.write_text(json.dumps(template.to_dict()), encoding="utf-8")

    rc = main(["import", "--to", "discord", "--file", str(template_path), "--target-id", "guild1", "--apply"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "Refusing --apply without --confirm-apply APPLY" in err
    assert "recovery:" in err
    assert "--plan-in <reviewed-plan.json> --confirm-apply APPLY" in err


def test_validate_invalid_json_prints_recovery(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "broken.json"
    template_path.write_text("{broken", encoding="utf-8")

    rc = main(["validate", str(template_path)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "guildbridge: error:" in err
    assert "Fix the JSON syntax near line 1" in err
    assert "guildbridge validate <template.json>" in err


def test_apply_refuses_invalid_template_without_force() -> None:
    try:
        validate_apply_safety(
            apply=True,
            confirm_apply=APPLY_CONFIRMATION,
            validation_problems=["Template must include an @everyone role with id 'everyone'"],
        )
    except ValueError as exc:
        assert "failed validation" in str(exc)
        assert "@everyone" in str(exc)
    else:
        raise AssertionError("expected invalid template apply to fail")


def test_apply_allows_invalid_template_with_force() -> None:
    validate_apply_safety(
        apply=True,
        confirm_apply=APPLY_CONFIRMATION,
        validation_problems=["Template must include an @everyone role with id 'everyone'"],
        force_invalid_template=True,
    )

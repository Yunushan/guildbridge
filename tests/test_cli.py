from __future__ import annotations

import json
from pathlib import Path

from guildbridge.cli import main
from guildbridge.models import CommunityTemplate, Role
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

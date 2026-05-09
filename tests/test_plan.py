from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guildbridge.cli import main
from guildbridge.models import Action, CommunityTemplate, ImportResult, Role
from guildbridge.providers.base import ImportOptions, plan_or_apply_action
from guildbridge.safety import APPLY_CONFIRMATION


class PlanProvider:
    name = "fake"

    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        result = ImportResult(provider=self.name, applied=options.apply)
        payload = {"name": template.name, "target": options.target_name or options.target_id or "default"}
        response: Any = plan_or_apply_action(
            options,
            result,
            Action(self.name, "POST", "/fake/resources", payload),
            lambda: {"id": "created-id"},
        )
        result.id_map["resource"] = response["id"] if options.apply else "dry-resource"
        return result


def write_template(path: Path, *, name: str = "Example") -> None:
    template = CommunityTemplate(name=name, roles=[Role(id="everyone", name="@everyone")])
    path.write_text(json.dumps(template.to_dict()), encoding="utf-8")


def test_dry_run_writes_stable_plan_metadata(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: PlanProvider())

    assert main(["import", "--to", "fake", "--file", str(template_path), "--target-name", "Target", "--plan-out", str(plan_path)]) == 0

    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["applied"] is False
    assert data["plan"]["schema"] == "guildbridge.apply-plan.v1"
    assert data["plan"]["context"]["provider"] == "fake"
    assert data["plan"]["context"]["target_name"] == "Target"
    assert data["plan"]["action_count"] == 1
    assert data["plan"]["action_hash"]


def test_apply_requires_reviewed_plan(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: PlanProvider())

    rc = main(["import", "--to", "fake", "--file", str(template_path), "--apply", "--confirm-apply", APPLY_CONFIRMATION])

    assert rc == 1
    assert "Refusing --apply without --plan-in" in capsys.readouterr().err


def test_apply_accepts_matching_reviewed_plan(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "result.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: PlanProvider())
    assert main(["import", "--to", "fake", "--file", str(template_path), "--target-name", "Target", "--plan-out", str(plan_path)]) == 0

    rc = main(
        [
            "import",
            "--to",
            "fake",
            "--file",
            str(template_path),
            "--target-name",
            "Target",
            "--apply",
            "--confirm-apply",
            APPLY_CONFIRMATION,
            "--plan-in",
            str(plan_path),
            "--plan-out",
            str(result_path),
        ]
    )

    assert rc == 0
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["applied"] is True
    assert data["id_map"]["resource"] == "created-id"
    assert data["plan"]["reviewed_plan_path"] == str(plan_path)


def test_apply_rejects_tampered_reviewed_plan(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: PlanProvider())
    assert main(["import", "--to", "fake", "--file", str(template_path), "--plan-out", str(plan_path)]) == 0
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    data["actions"][0]["payload"]["name"] = "Tampered"
    plan_path.write_text(json.dumps(data), encoding="utf-8")

    rc = main(
        [
            "import",
            "--to",
            "fake",
            "--file",
            str(template_path),
            "--apply",
            "--confirm-apply",
            APPLY_CONFIRMATION,
            "--plan-in",
            str(plan_path),
        ]
    )

    assert rc == 1
    assert "action hash does not match" in capsys.readouterr().err


def test_apply_rejects_reviewed_plan_context_drift(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: PlanProvider())
    assert main(["import", "--to", "fake", "--file", str(template_path), "--target-name", "Original", "--plan-out", str(plan_path)]) == 0

    rc = main(
        [
            "import",
            "--to",
            "fake",
            "--file",
            str(template_path),
            "--target-name",
            "Changed",
            "--apply",
            "--confirm-apply",
            APPLY_CONFIRMATION,
            "--plan-in",
            str(plan_path),
        ]
    )

    assert rc == 1
    assert "different target_name" in capsys.readouterr().err

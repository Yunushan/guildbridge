from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from guildbridge.cli import main
from guildbridge.models import Action, CommunityTemplate, ImportResult, Role
from guildbridge.providers.base import ImportOptions, plan_or_apply_action
from guildbridge.safety import APPLY_CONFIRMATION


def write_template(path: Path, *, name: str = "Example") -> None:
    template = CommunityTemplate(name=name, roles=[Role(id="everyone", name="@everyone")])
    path.write_text(json.dumps(template.to_dict()), encoding="utf-8")


class SuccessfulProvider:
    name = "fake"

    def import_template(self, _: CommunityTemplate, options: ImportOptions) -> ImportResult:
        result = ImportResult(provider=self.name, applied=options.apply)
        action = Action(self.name, "POST", "/fake/resources", {"name": "created"})
        response: Any = plan_or_apply_action(options, result, action, lambda: {"id": "created-id"})
        result.id_map["resource"] = response["id"] if options.apply else "dry-resource"
        return result


class FailingProvider:
    name = "fake"

    def import_template(self, _: CommunityTemplate, options: ImportOptions) -> ImportResult:
        result = ImportResult(provider=self.name, applied=options.apply)
        action = Action(self.name, "POST", "/fake/resources", {"name": "created"})

        def fail() -> dict[str, str]:
            raise RuntimeError("Authorization: Bot secret-token")

        plan_or_apply_action(options, result, action, fail)
        return result


def test_import_apply_writes_success_journal(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    result_path = tmp_path / "result.json"
    journal_path = tmp_path / "journal.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: SuccessfulProvider())
    assert main(["import", "--to", "fake", "--file", str(template_path), "--plan-out", str(plan_path)]) == 0

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
            "--plan-out",
            str(result_path),
            "--plan-in",
            str(plan_path),
            "--journal-out",
            str(journal_path),
        ]
    )

    assert rc == 0
    data = json.loads(journal_path.read_text(encoding="utf-8"))
    assert data["status"] == "succeeded"
    assert data["context"]["provider"] == "fake"
    assert data["actions"][0]["status"] == "succeeded"
    assert data["result"]["id_map"]["resource"] == "created-id"


def test_import_apply_journal_records_failure(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    template_path = tmp_path / "template.json"
    plan_path = tmp_path / "plan.json"
    journal_path = tmp_path / "journal.json"
    write_template(template_path)
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: FailingProvider())
    assert main(["import", "--to", "fake", "--file", str(template_path), "--plan-out", str(plan_path)]) == 0

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
            "--journal-out",
            str(journal_path),
        ]
    )

    assert rc == 1
    data = json.loads(journal_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["actions"][0]["status"] == "failed"
    assert "secret-token" not in data["error"]
    assert "secret-token" not in data["actions"][0]["error"]


def test_resume_journal_rejects_template_mismatch(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    first_template = tmp_path / "first.json"
    second_template = tmp_path / "second.json"
    first_plan = tmp_path / "first.plan.json"
    second_plan = tmp_path / "second.plan.json"
    journal_path = tmp_path / "failed.json"
    write_template(first_template, name="First")
    write_template(second_template, name="Second")
    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: FailingProvider())
    assert main(["import", "--to", "fake", "--file", str(first_template), "--plan-out", str(first_plan)]) == 0
    assert (
        main(
            [
                "import",
                "--to",
                "fake",
                "--file",
                str(first_template),
                "--apply",
                "--confirm-apply",
                APPLY_CONFIRMATION,
                "--plan-in",
                str(first_plan),
                "--journal-out",
                str(journal_path),
            ]
        )
        == 1
    )

    monkeypatch.setattr("guildbridge.cli.get_provider", lambda _name, _config: SuccessfulProvider())
    assert main(["import", "--to", "fake", "--file", str(second_template), "--plan-out", str(second_plan)]) == 0
    rc = main(
        [
            "import",
            "--to",
            "fake",
            "--file",
            str(second_template),
            "--apply",
            "--confirm-apply",
            APPLY_CONFIRMATION,
            "--plan-in",
            str(second_plan),
            "--resume-journal",
            str(journal_path),
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "different template_hash" in err

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from guildbridge.models import (
    SCHEMA_ID,
    Channel,
    CommunityTemplate,
    PermissionOverwrite,
    Role,
    TemplatePrivacy,
)


def test_template_round_trip() -> None:
    template = CommunityTemplate(
        name="Demo",
        roles=[Role(id="everyone", name="@everyone", permissions=["view_channel"])],
        channels=[Channel(id="chan_general", name="general", type="text")],
    )
    data = template.to_dict()
    loaded = CommunityTemplate.from_dict(data)
    assert loaded.schema == SCHEMA_ID
    assert loaded.name == "Demo"
    assert loaded.roles[0].name == "@everyone"
    assert loaded.channels[0].name == "general"
    assert loaded.validate() == []


def test_example_matches_json_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schema" / "community-template.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "examples" / "template.example.json").read_text(encoding="utf-8"))
    jsonschema.validate(example, schema)
    assert CommunityTemplate.from_dict(example).validate() == []


def test_validate_missing_parent() -> None:
    template = CommunityTemplate(
        name="Bad",
        roles=[Role(id="everyone", name="@everyone")],
        channels=[Channel(id="chan", name="general", parent_id="missing")],
    )
    assert any("missing parent" in warning for warning in template.validate())


def test_unknown_permission_rejected_by_model_and_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schema" / "community-template.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "examples" / "template.example.json").read_text(encoding="utf-8"))
    example["roles"][0]["permissions"] = ["read_message_history"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(example, schema)

    template = CommunityTemplate.from_dict(example)
    assert any("unknown permission 'read_message_history'" in problem for problem in template.validate())


def test_validate_rejects_bad_overwrite_target_and_permissions() -> None:
    template = CommunityTemplate(
        name="Bad overwrites",
        roles=[Role(id="everyone", name="@everyone")],
        channels=[
            Channel(
                id="chan",
                name="general",
                permission_overwrites=[
                    PermissionOverwrite(
                        target_type="role",
                        target_id="missing-role",
                        allow=["view_channel"],
                        deny=["not_a_permission"],
                    )
                ],
            )
        ],
    )

    problems = template.validate()
    assert any("references missing role 'missing-role'" in problem for problem in problems)
    assert any("unknown permission 'not_a_permission'" in problem for problem in problems)


def test_validate_rejects_schema_version_privacy_and_channel_shape() -> None:
    template = CommunityTemplate(
        name="",
        schema="other.schema",
        version="2.0",
        privacy=TemplatePrivacy(exports_user_overwrites=True),
        roles=[],
        channels=[
            Channel(
                id="",
                name="",
                type="bad-kind",  # type: ignore[arg-type]
                nsfw="yes",  # type: ignore[arg-type]
            )
        ],
    )

    problems = template.validate()
    assert any("Unsupported schema" in problem for problem in problems)
    assert any("Unsupported template version" in problem for problem in problems)
    assert any("Template has no name" in problem for problem in problems)
    assert any("must include an @everyone role" in problem for problem in problems)
    assert any("unsupported type 'bad-kind'" in problem for problem in problems)
    assert any("nsfw must be a boolean" in problem for problem in problems)
    assert any("privacy flags" in problem for problem in problems)

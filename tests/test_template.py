from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from guildbridge.models import Channel, CommunityTemplate, Role, SCHEMA_ID


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
    template = CommunityTemplate(name="Bad", channels=[Channel(id="chan", name="general", parent_id="missing")])
    assert any("missing parent" in warning for warning in template.validate())

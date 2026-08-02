from __future__ import annotations

import json
from pathlib import Path

import pytest

from guildbridge.content import (
    ContentApplyJournal,
    content_actions_fingerprint,
    validate_content_resume_journal,
)
from guildbridge.models import Action


def test_content_journal_records_the_resumed_from_path(tmp_path: Path) -> None:
    path = tmp_path / "recovery.json"
    journal = ContentApplyJournal(
        path,
        provider="stoat",
        target_id="target",
        target_name="Target",
        resumed_from=tmp_path / "failed.json",
    )

    journal.start()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["resumed_from"] == str(tmp_path / "failed.json")


def test_content_resume_rejects_a_different_action_set(tmp_path: Path) -> None:
    path = tmp_path / "failed.json"
    original = [Action("stoat", "POST", "/channels/target/messages", {"content": "one"})]
    journal = ContentApplyJournal(
        path,
        provider="stoat",
        target_id="target",
        target_name="Target",
        action_hash=content_actions_fingerprint(original),
    )
    journal.start()

    changed = [Action("stoat", "POST", "/channels/target/messages", {"content": "two"})]
    with pytest.raises(ValueError, match="different action_hash"):
        validate_content_resume_journal(
            path,
            provider="stoat",
            target_id="target",
            target_name="Target",
            action_hash=content_actions_fingerprint(changed),
        )

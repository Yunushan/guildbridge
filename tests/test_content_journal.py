from __future__ import annotations

import json
from pathlib import Path

from guildbridge.content import ContentApplyJournal


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

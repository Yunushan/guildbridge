from __future__ import annotations

import json
from pathlib import Path

from guildbridge.cli import main


def test_providers_command(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "discord" in out
    assert "fluxer" in out
    assert "stoat" in out
    assert "matrix" in out


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

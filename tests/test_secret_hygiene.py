from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_secret_hygiene", ROOT / "scripts" / "check-secret-hygiene.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secret_hygiene_detects_high_confidence_values_without_echoing_them() -> None:
    module = _module()

    findings = module._findings_for_bytes(
        b"DISCORD_BOT_TOKEN=" + b"gh" + b"p_abcdefghijklmnopqrstuvwxyz1234567890",
        "example.env",
    )

    assert findings == ["example.env contains a likely GitHub token"]
    assert "ghp_" not in "\n".join(findings)


def test_secret_hygiene_ignores_ordinary_configuration_names() -> None:
    module = _module()

    assert module._findings_for_bytes(b"DISCORD_BOT_TOKEN=\n", "example.env") == []


def test_secret_hygiene_detects_discord_bot_tokens() -> None:
    module = _module()
    token = b"A" * 24 + b"." + b"B" * 6 + b"." + b"C" * 27

    findings = module._findings_for_bytes(b"DISCORD_BOT_TOKEN=" + token, "example.env")

    assert findings == ["example.env contains a likely Discord bot token"]

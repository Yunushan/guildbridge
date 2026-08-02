from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_operations_readiness", ROOT / "scripts" / "check-operations-readiness.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operations_readiness_check_accepts_current_runbook() -> None:
    assert _module().main() == 0


def test_operations_readiness_check_has_distinct_safety_requirements() -> None:
    required = _module().REQUIRED_TEXT

    assert "disposable-tenant dry run" in required
    assert "--resume-journal" in required
    assert "private security advisory" in required

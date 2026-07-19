from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_content_capability_scope", ROOT / "scripts" / "check-content-capability-scope.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_content_scope_matches_current_provider_capabilities() -> None:
    module = _module()

    matrix = module.capability_matrix()

    assert {name for name, capability in matrix.items() if capability["export_messages"]} == {"discord"}
    assert {name for name, capability in matrix.items() if capability["import_messages"]} == set(matrix) - {"mumble"}


def test_live_content_scope_requires_documentation() -> None:
    module = _module()

    assert module.validate_scope() == []

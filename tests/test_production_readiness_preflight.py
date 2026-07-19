from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_production_readiness", ROOT / "scripts" / "check-production-readiness.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_collects_every_failed_check() -> None:
    module = _module()

    failures = module.run_checks([("passing", lambda: 0), ("failing", lambda: 1), ("also failing", lambda: 2)])

    assert failures == ["failing", "also failing"]


def test_preflight_treats_an_unexpected_check_error_as_a_failure(capsys) -> None:
    module = _module()

    failures = module.run_checks(
        [("passing", lambda: 0), ("raises", lambda: (_ for _ in ()).throw(RuntimeError("secret")))]
    )

    assert failures == ["raises"]
    output = capsys.readouterr().out
    assert "raises failed unexpectedly" in output
    assert "secret" not in output


def test_preflight_builds_private_evidence_check_with_expected_commit(monkeypatch) -> None:
    module = _module()
    captured: dict[str, list[str]] = {}

    class Stub:
        @staticmethod
        def main(arguments=None):
            captured["arguments"] = arguments or []
            return 0

    monkeypatch.setattr(module, "_load_script", lambda _filename: Stub)
    checks = module.build_checks(
        repo="owner/repository",
        evidence=Path("C:/private/evidence.json"),
        tag="v1.0.10",
        expected_commit="a" * 40,
    )

    assert len(checks) == 6
    assert checks[-1][1]() == 0
    assert captured["arguments"] == [
        "--evidence",
        str(Path("C:/private/evidence.json")),
        "--tag",
        "v1.0.10",
        "--expected-commit",
        "a" * 40,
    ]

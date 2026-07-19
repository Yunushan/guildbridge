from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "new-production-evidence-template.py"
SPEC = importlib.util.spec_from_file_location("new_production_evidence_template", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
template = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(template)


def test_template_contains_all_provider_routes() -> None:
    evidence = template.build_template("v1.0.10", "a" * 40)

    assert evidence["release_tag"] == "v1.0.10"
    assert evidence["github_settings_evidence_ref"] == (
        "private://release-evidence/v1.0.10/github-production-settings-audit"
    )
    assert len(evidence["provider_drills"]) == 10
    assert all(len(drill["targets"]) == 9 for drill in evidence["provider_drills"])
    assert all(set(drill["route_evidence_refs"]) == set(drill["targets"]) for drill in evidence["provider_drills"])
    assert all(drill["dry_run"] is False for drill in evidence["provider_drills"])
    assert len(evidence["content_provider_drills"]) == 1
    content_drill = evidence["content_provider_drills"][0]
    assert content_drill["source"] == "discord"
    assert set(content_drill["targets"]) == {
        "daccord", "fluxer", "matrix", "mattermost", "rocket.chat", "spacebar", "stoat", "zulip"
    }
    assert content_drill["archive_export_verified"] is False


def test_template_writer_refuses_an_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "production-evidence-v1.0.10.json"
    output.write_text("existing", encoding="utf-8")

    try:
        template.main(["--tag", "v1.0.10", "--commit", "a" * 40, "--out", str(output)])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected an existing evidence file to require --overwrite")

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "check_production_evidence", ROOT / "scripts" / "check-production-evidence.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> dict[str, object]:
    return json.loads((ROOT / "examples" / "production-evidence.example.json").read_text(encoding="utf-8"))


def _completed_evidence() -> dict[str, object]:
    evidence = _evidence()
    artifacts = evidence["artifact_checksums"]
    assert isinstance(artifacts, dict)
    for index, key in enumerate(sorted(artifacts), start=1):
        artifacts[key] = f"{index:064x}"
    content_drills = evidence["content_provider_drills"]
    assert isinstance(content_drills, list)
    for drill in content_drills:
        assert isinstance(drill, dict)
        for key in ("archive_export_verified", "dry_run", "apply_recovery", "least_privilege_reviewed"):
            drill[key] = True
    return evidence


def test_production_evidence_example_cannot_be_used_as_a_release_record() -> None:
    module = _module()

    errors = module.validate_evidence(_evidence(), "v1.0.9")

    assert "artifact_checksums.wheel must not use the all-zero placeholder digest." in errors
    assert "artifact_checksums must contain distinct digests for every published artifact." in errors


def test_completed_production_evidence_covers_structural_and_live_content_routes() -> None:
    module = _module()

    assert module.validate_evidence(_completed_evidence(), "v1.0.9") == []


def test_production_evidence_requires_provider_recovery_and_signing() -> None:
    module = _module()
    evidence = _completed_evidence()
    evidence["windows_signature_verified"] = False
    evidence["provider_drills"][0]["apply_recovery"] = False

    errors = module.validate_evidence(evidence, "v1.0.9")

    assert "windows_signature_verified must be true." in errors
    assert "provider_drills[1].apply_recovery must be true." in errors


def test_production_evidence_requires_every_provider_source_and_artifact_digest() -> None:
    module = _module()
    evidence = _completed_evidence()
    evidence["provider_drills"] = evidence["provider_drills"][:-1]
    evidence["artifact_checksums"]["wheel"] = "not-a-digest"

    errors = module.validate_evidence(evidence, "v1.0.9")

    assert "artifact_checksums.wheel must be a lowercase SHA-256 digest." in errors
    assert any(error.startswith("provider_drills must cover every supported provider as a source") for error in errors)


def test_production_evidence_binds_to_the_checked_out_release_commit() -> None:
    module = _module()
    evidence = _completed_evidence()

    errors = module.validate_evidence(evidence, "v1.0.9", expected_commit="f" * 40)

    assert "source_commit must exactly match --expected-commit." in errors


def test_production_evidence_rejects_public_or_credential_bearing_evidence_references() -> None:
    module = _module()
    evidence = _completed_evidence()
    evidence["github_settings_evidence_ref"] = "https://example.test/audit?token=secret"
    evidence["tls_evidence_ref"] = "https://example.test/evidence?token=secret"
    evidence["provider_drills"][0]["evidence_bundle_ref"] = "vault://migration/drill"
    evidence["provider_drills"][0]["route_evidence_refs"]["discord"] = "https://example.test/route?token=secret"

    errors = module.validate_evidence(evidence, "v1.0.9")

    assert "github_settings_evidence_ref must be an opaque private:// evidence reference." in errors
    assert "tls_evidence_ref must be an opaque private:// evidence reference." in errors
    assert "provider_drills[1].evidence_bundle_ref must be an opaque private:// evidence reference." in errors
    assert "provider_drills[1].route_evidence_refs.discord must be an opaque private:// evidence reference." in errors


def test_production_evidence_requires_a_distinct_reference_for_each_target_route() -> None:
    module = _module()
    evidence = _completed_evidence()
    del evidence["provider_drills"][0]["route_evidence_refs"]["discord"]

    errors = module.validate_evidence(evidence, "v1.0.9")

    assert "provider_drills[1].route_evidence_refs must contain every target provider exactly once." in errors


def test_production_evidence_requires_live_content_route_evidence() -> None:
    module = _module()
    evidence = _completed_evidence()
    content_drills = evidence["content_provider_drills"]
    assert isinstance(content_drills, list)
    content_drills[0]["archive_export_verified"] = False

    errors = module.validate_evidence(evidence, "v1.0.9")

    assert "content_provider_drills[1].archive_export_verified must be true." in errors

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("check_release_assets", ROOT / "scripts" / "check-release-assets.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recorder_module():
    spec = importlib.util.spec_from_file_location(
        "record_release_asset_checksums", ROOT / "scripts" / "record-release-asset-checksums.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_bundle(tmp_path: Path) -> tuple[Path, Path]:
    assets = tmp_path / "release-assets"
    assets.mkdir()
    files = {
        "wheel": assets / "guildbridge-1.0.9-py3-none-any.whl",
        "sdist": assets / "guildbridge-1.0.9.tar.gz",
        "windows_zip": assets / "GuildBridge-1.0.9-windows-x64.zip",
        "windows_msi": assets / "GuildBridge-1.0.9-windows-x64.msi",
        "sbom": assets / "guildbridge-v1.0.9.spdx.json",
        "dependency_audit": assets / "guildbridge-v1.0.9.dependency-audit.json",
    }
    for key, path in files.items():
        path.write_bytes(key.encode("ascii"))

    python_manifest = assets / "SHA256SUMS"
    python_manifest.write_text(
        "\n".join(
            f"{_sha256(files[key])}  {files[key].name}"
            for key in ("wheel", "sdist", "sbom", "dependency_audit")
        )
        + "\n",
        encoding="utf-8",
    )
    windows_manifest = assets / "SHA256SUMS-windows.txt"
    windows_manifest.write_text(
        "\n".join(f"{_sha256(files[key])}  {files[key].name}" for key in ("windows_zip", "windows_msi"))
        + "\n",
        encoding="utf-8",
    )
    files["sha256s"] = python_manifest
    files["windows_sha256s"] = windows_manifest

    evidence = tmp_path / "production-evidence.json"
    evidence.write_text(
        json.dumps({"artifact_checksums": {key: _sha256(path) for key, path in files.items()}}),
        encoding="utf-8",
    )
    return assets, evidence


def test_release_asset_verifier_accepts_matching_manifests_and_evidence(tmp_path: Path) -> None:
    module = _module()
    assets, evidence = _release_bundle(tmp_path)

    assert module.validate_release_assets(assets, evidence) == []


def test_release_asset_verifier_rejects_tampered_download(tmp_path: Path) -> None:
    module = _module()
    assets, evidence = _release_bundle(tmp_path)
    (assets / "GuildBridge-1.0.9-windows-x64.msi").write_bytes(b"tampered")

    errors = module.validate_release_assets(assets, evidence)

    assert "SHA256SUMS-windows.txt checksum mismatch for GuildBridge-1.0.9-windows-x64.msi" in errors
    assert "evidence checksum does not match downloaded windows_msi asset" in errors


def test_release_asset_verifier_rejects_unexpected_download_or_manifest_entry(tmp_path: Path) -> None:
    module = _module()
    assets, evidence = _release_bundle(tmp_path)
    (assets / "unreviewed-extra.exe").write_bytes(b"not-a-release-asset")
    with (assets / "SHA256SUMS").open("a", encoding="utf-8") as handle:
        handle.write(f"{_sha256(assets / 'unreviewed-extra.exe')}  unreviewed-extra.exe\n")

    errors = module.validate_release_assets(assets, evidence)

    assert "release assets contain unexpected files: unreviewed-extra.exe" in errors
    assert "SHA256SUMS contains unexpected entries: unreviewed-extra.exe" in errors


def test_release_asset_recorder_updates_only_verified_checksums(tmp_path: Path) -> None:
    module = _recorder_module()
    assets, evidence = _release_bundle(tmp_path)
    original = json.loads(evidence.read_text(encoding="utf-8"))

    selected = module.select_assets(assets)
    module.verify_manifests(selected)
    module.record_checksums(evidence, selected)

    updated = json.loads(evidence.read_text(encoding="utf-8"))
    assert updated["artifact_checksums"] == {key: _sha256(path) for key, path in selected.items()}
    assert updated == original


def test_release_asset_recorder_rejects_tampered_assets_before_writing(tmp_path: Path) -> None:
    module = _recorder_module()
    assets, evidence = _release_bundle(tmp_path)
    original = evidence.read_text(encoding="utf-8")
    (assets / "GuildBridge-1.0.9-windows-x64.zip").write_bytes(b"tampered")

    try:
        module.verify_manifests(module.select_assets(assets))
    except ValueError as exc:
        assert "SHA256SUMS-windows.txt checksum mismatch" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered asset should not pass manifest verification")
    assert evidence.read_text(encoding="utf-8") == original

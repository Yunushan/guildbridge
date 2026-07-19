from __future__ import annotations

import base64
import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("verify_dist", ROOT / "scripts" / "verify-dist.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wheel_with_record(path: Path, payload: bytes, *, recorded_payload: bytes | None = None) -> None:
    recorded_payload = payload if recorded_payload is None else recorded_payload
    digest = base64.urlsafe_b64encode(hashlib.sha256(recorded_payload).digest()).decode().rstrip("=")
    record = (
        f"guildbridge/__init__.py,sha256={digest},{len(recorded_payload)}\n"
        "guildbridge-1.0.9.dist-info/RECORD,,\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("guildbridge/__init__.py", payload)
        archive.writestr("guildbridge-1.0.9.dist-info/RECORD", record)


def test_spdx_document_describes_the_wheel_and_uses_immutable_identity() -> None:
    module = _module()
    document = module.build_spdx_document(
        [
            {"name": "GuildBridge", "version": "1.0.9"},
            {"name": "requests", "version": "2.32.5"},
        ],
        "a" * 64,
    )

    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["creationInfo"]["created"] == "1970-01-01T00:00:00Z"
    assert document["relationships"] == [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package-GuildBridge",
        }
    ]
    packages = document["packages"]
    assert packages[0]["checksums"] == [{"algorithm": "SHA256", "checksumValue": "a" * 64}]
    assert packages[1]["externalRefs"][0]["referenceLocator"] == "pkg:pypi/requests@2.32.5"


def test_wheel_record_verifier_accepts_consistent_archive(tmp_path: Path) -> None:
    module = _module()
    wheel = tmp_path / "guildbridge-1.0.9-py3-none-any.whl"
    _write_wheel_with_record(wheel, b"__version__ = '1.0.9'\n")

    with zipfile.ZipFile(wheel) as archive:
        module.verify_wheel_record(archive)


def test_wheel_record_verifier_rejects_tampered_archive(tmp_path: Path) -> None:
    module = _module()
    wheel = tmp_path / "guildbridge-1.0.9-py3-none-any.whl"
    _write_wheel_with_record(wheel, b"tampered", recorded_payload=b"original")

    with zipfile.ZipFile(wheel) as archive, pytest.raises(SystemExit, match="RECORD hash mismatch"):
        module.verify_wheel_record(archive)

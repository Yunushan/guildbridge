"""Single source of truth for the public release-asset contract."""

from __future__ import annotations

ASSET_PATTERNS = {
    "wheel": "guildbridge-*.whl",
    "sdist": "guildbridge-*.tar.gz",
    "windows_zip": "GuildBridge-*-windows-x64.zip",
    "windows_msi": "GuildBridge-*-windows-x64.msi",
    "sha256s": "SHA256SUMS",
    "windows_sha256s": "SHA256SUMS-windows.txt",
    "sbom": "guildbridge-*.spdx.json",
    "dependency_audit": "guildbridge-*.dependency-audit.json",
}

PYTHON_MANIFEST_KEYS = ("wheel", "sdist", "sbom", "dependency_audit")
WINDOWS_MANIFEST_KEYS = ("windows_zip", "windows_msi")
MANIFESTS = {
    "sha256s": PYTHON_MANIFEST_KEYS,
    "windows_sha256s": WINDOWS_MANIFEST_KEYS,
}

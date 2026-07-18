from __future__ import annotations

import argparse
import base64
import csv
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path

REQUIRED_SDIST_SUFFIXES = (
    "LICENSE",
    "README.md",
    "README.tr.md",
    ".env.example",
    "docs/assets/guildbridge-icon.svg",
    "docs/PRIVACY.md",
    "docs/PLATFORMS.md",
    "docs/PRODUCTION_READINESS.md",
    "docs/RELEASE.md",
    "docs/OPERATIONS.md",
    "docs/REPOSITORY_SETTINGS.md",
    "docs/WINDOWS_RELEASE.md",
    "examples/template.example.json",
    "examples/production-evidence.example.json",
    "packaging/windows/GuildBridge.wxs",
    "packaging/windows/guildbridge.ico",
    "packaging/windows/guildbridge-cli.py",
    "packaging/windows/guildbridge-gui.py",
    "packaging/windows/guildbridge-web.py",
    "schema/community-template.schema.json",
    "scripts/build-windows-dist.ps1",
    "scripts/sign-windows-release.ps1",
    "scripts/verify-windows-release.ps1",
    "scripts/check-platform.py",
    "scripts/check-release-assets.py",
    "scripts/check-content-capability-scope.py",
    "scripts/record-release-asset-checksums.py",
    "scripts/check-production-evidence.py",
    "scripts/check-production-readiness.py",
    "scripts/record-provider-drill-receipt.py",
    "scripts/new-production-evidence-template.py",
    "scripts/check-release-controls.py",
    "scripts/check-secret-hygiene.py",
    "scripts/check-security-baseline.py",
    "scripts/check-platform.ps1",
    "scripts/install-system-deps.sh",
    "scripts/migrate.sh",
)

REQUIRED_WHEEL_SUFFIXES = (
    "guildbridge/__init__.py",
    "guildbridge/__main__.py",
    "guildbridge/cli.py",
    "guildbridge/providers/daccord.py",
    "guildbridge/providers/mattermost.py",
    "guildbridge/gui.py",
    "guildbridge/assets/guildbridge-icon.ico",
    "guildbridge/assets/guildbridge-icon.png",
    "guildbridge/assets/guildbridge-icon.svg",
    "guildbridge/providers/mumble.py",
    "guildbridge/providers/rocket_chat.py",
    "guildbridge/providers/spacebar.py",
    "guildbridge/providers/zulip.py",
    "guildbridge/web.py",
)

REQUIRED_ENTRY_POINTS = {
    "guildbridge": "guildbridge.cli:main",
    "guildbridge-gui": "guildbridge.gui:main",
    "guildbridge-web": "guildbridge.web:main",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify GuildBridge source and wheel distributions.")
    parser.add_argument("--dist-dir", default="dist", help="directory containing built distributions")
    parser.add_argument("--sbom-out", help="write an SPDX 2.3 SBOM for the verified wheel to this path")
    args = parser.parse_args(argv)

    dist_dir = Path(args.dist_dir)
    wheel = single_match(dist_dir, "guildbridge-*.whl")
    sdist = single_match(dist_dir, "guildbridge-*.tar.gz")
    verify_sdist(sdist)
    verify_wheel(wheel)
    verify_wheel_install(wheel, sbom_out=Path(args.sbom_out) if args.sbom_out else None)
    print(f"Verified distributions in {dist_dir}")
    return 0


def single_match(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(Path(path) for path in glob.glob(str(dist_dir / pattern)))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one {pattern} in {dist_dir}, found {len(matches)}.")
    return matches[0]


def verify_sdist(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
    missing = [suffix for suffix in REQUIRED_SDIST_SUFFIXES if not any(name.endswith(suffix) for name in names)]
    if missing:
        raise SystemExit(f"{path.name} is missing required files: {', '.join(missing)}")


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    missing = [suffix for suffix in REQUIRED_WHEEL_SUFFIXES if not any(name.endswith(suffix) for name in names)]
    if missing:
        raise SystemExit(f"{path.name} is missing required package files: {', '.join(missing)}")
    with zipfile.ZipFile(path) as archive:
        verify_wheel_record(archive)


def verify_wheel_record(archive: zipfile.ZipFile) -> None:
    """Validate the wheel's RECORD hashes and sizes before installation."""
    record_paths = [name for name in archive.namelist() if name.endswith(".dist-info/RECORD")]
    if len(record_paths) != 1:
        raise SystemExit(f"Wheel must contain exactly one .dist-info/RECORD, found {len(record_paths)}.")

    record_path = record_paths[0]
    names = set(archive.namelist())
    try:
        record_rows = list(csv.reader(archive.read(record_path).decode("utf-8").splitlines()))
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Wheel RECORD is not UTF-8: {exc}") from exc

    recorded: set[str] = set()
    for row in record_rows:
        if len(row) != 3:
            raise SystemExit("Wheel RECORD contains an invalid row.")
        filename, digest, size = row
        if filename in recorded:
            raise SystemExit(f"Wheel RECORD contains duplicate entry: {filename}")
        recorded.add(filename)
        if filename not in names:
            raise SystemExit(f"Wheel RECORD references a missing archive entry: {filename}")
        if filename == record_path:
            if digest or size:
                raise SystemExit("Wheel RECORD entry must not contain its own hash or size.")
            continue
        _verify_record_entry(archive, filename, digest, size)

    unrecorded = names - recorded
    if unrecorded:
        raise SystemExit(f"Wheel archive contains entries missing from RECORD: {', '.join(sorted(unrecorded))}")


def _verify_record_entry(archive: zipfile.ZipFile, filename: str, digest: str, size: str) -> None:
    algorithm, separator, encoded_digest = digest.partition("=")
    if separator != "=" or algorithm not in {"sha256", "sha384", "sha512"} or not encoded_digest:
        raise SystemExit(f"Wheel RECORD has an unsupported digest for {filename}: {digest!r}")
    try:
        expected_digest = base64.urlsafe_b64decode(encoded_digest + "=" * (-len(encoded_digest) % 4))
    except ValueError as exc:
        raise SystemExit(f"Wheel RECORD has an invalid base64 digest for {filename}.") from exc
    data = archive.read(filename)
    actual_digest = hashlib.new(algorithm, data).digest()
    if actual_digest != expected_digest:
        raise SystemExit(f"Wheel RECORD hash mismatch for {filename}.")
    try:
        expected_size = int(size)
    except ValueError as exc:
        raise SystemExit(f"Wheel RECORD has an invalid size for {filename}: {size!r}") from exc
    if len(data) != expected_size:
        raise SystemExit(f"Wheel RECORD size mismatch for {filename}.")


def verify_wheel_install(path: Path, *, sbom_out: Path | None = None) -> None:
    temp_parent = Path("build")
    temp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-wheel-", dir=temp_parent) as tmp:
        tmp_path = Path(tmp)
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(tmp_path)
        python = venv_python(tmp_path)
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", str(path)])
        run([python, "-m", "pip", "check"])
        run([python, "-m", "guildbridge", "--version"])
        entry_check = (
            "import sys;"
            "from importlib.metadata import entry_points;"
            f"expected={REQUIRED_ENTRY_POINTS!r};"
            "found={ep.name: ep.value for ep in entry_points(group='console_scripts')};"
            "missing={name: value for name, value in expected.items() if found.get(name) != value};"
            "sys.exit(f'missing entry points: {missing}') if missing else None"
        )
        run([python, "-c", entry_check])
        if sbom_out is not None:
            write_spdx_sbom(python, path, sbom_out)


def write_spdx_sbom(python: str, wheel: Path, destination: Path) -> None:
    """Write a deterministic SBOM for the runtime dependency closure in *python*."""
    query = (
        "import importlib.metadata as md, json;"
        "skip={'pip','setuptools','wheel'};"
        "items=[];"
        "[(items.append({'name': d.metadata['Name'], 'version': d.version}) if d.metadata.get('Name') "
        "and d.metadata['Name'].lower() not in skip else None) for d in md.distributions()];"
        "print(json.dumps(sorted(items, key=lambda item: item['name'].lower())))"
    )
    # python is the freshly-created isolated venv executable and query is a fixed literal.
    completed = subprocess.run([python, "-c", query], text=True, capture_output=True, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or "Could not enumerate installed distributions for SPDX SBOM.")

    components = json.loads(completed.stdout)
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    document = build_spdx_document(components, wheel_hash)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_spdx_document(components: list[dict[str, str]], wheel_hash: str) -> dict[str, object]:
    package_ids = {
        component["name"].lower(): f"SPDXRef-Package-{_spdx_identifier(component['name'])}"
        for component in components
    }
    packages: list[dict[str, object]] = []
    for component in components:
        name = component["name"]
        package: dict[str, object] = {
            "name": name,
            "SPDXID": package_ids[name.lower()],
            "versionInfo": component["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{name.lower()}@{component['version']}",
                }
            ],
        }
        if name.lower() == "guildbridge":
            package["checksums"] = [{"algorithm": "SHA256", "checksumValue": wheel_hash}]
        packages.append(package)

    guildbridge_id = package_ids.get("guildbridge")
    if guildbridge_id is None:
        raise SystemExit("Installed wheel did not provide a guildbridge distribution for SPDX SBOM generation.")
    guildbridge_version = next(component["version"] for component in components if component["name"].lower() == "guildbridge")
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"GuildBridge-{guildbridge_version}",
        "documentNamespace": f"https://spdx.org/spdxdocs/guildbridge-{guildbridge_version}-{wheel_hash}",
        "creationInfo": {
            "created": "1970-01-01T00:00:00Z",
            "creators": ["Tool: GuildBridge verify-dist.py"],
        },
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": guildbridge_id,
            }
        ],
    }
def _spdx_identifier(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-") or "package"


def venv_python(root: Path) -> str:
    executable = root / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return str(executable)


def run(command: list[str]) -> None:
    # Callers supply explicit argument lists, never a shell command string.
    completed = subprocess.run(command, text=True, capture_output=True, check=False)  # noqa: S603
    if completed.returncode != 0:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

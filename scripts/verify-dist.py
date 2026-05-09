from __future__ import annotations

import argparse
import glob
import os
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
    "docs/PRIVACY.md",
    "docs/PLATFORMS.md",
    "docs/RELEASE.md",
    "docs/WINDOWS_RELEASE.md",
    "examples/template.example.json",
    "packaging/windows/GuildBridge.wxs",
    "packaging/windows/guildbridge-cli.py",
    "packaging/windows/guildbridge-gui.py",
    "packaging/windows/guildbridge-web.py",
    "schema/community-template.schema.json",
    "scripts/build-windows-dist.ps1",
    "scripts/check-platform.py",
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
    args = parser.parse_args(argv)

    dist_dir = Path(args.dist_dir)
    wheel = single_match(dist_dir, "guildbridge-*.whl")
    sdist = single_match(dist_dir, "guildbridge-*.tar.gz")
    verify_sdist(sdist)
    verify_wheel(wheel)
    verify_wheel_install(wheel)
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


def verify_wheel_install(path: Path) -> None:
    temp_parent = Path("build")
    temp_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verify-wheel-", dir=temp_parent) as tmp:
        tmp_path = Path(tmp)
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(tmp_path)
        python = venv_python(tmp_path)
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", str(path)])
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


def venv_python(root: Path) -> str:
    executable = root / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return str(executable)


def run(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

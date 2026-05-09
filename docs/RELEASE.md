# Release Checklist

GuildBridge release artifacts are built only by the release workflow for tags and manual workflow runs. Normal CI builds and verifies packages but does not upload downloadable artifacts. The repository does not publish to PyPI automatically.

## Before Tagging

1. Confirm `pyproject.toml` and `src/guildbridge/__init__.py` have the same version.
2. Run the local release check:

```bash
make release-check
```

If `make` is unavailable, run the equivalent commands:

```bash
python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py
python -m mypy src
python -m pytest -q
python scripts/check-platform.py --require cli --format json
python -m build
python -m twine check dist/*
python scripts/verify-dist.py
```

3. Inspect `dist/` and confirm it contains exactly one wheel and one source archive.
4. Confirm `.env`, journals, generated plans, and local migration artifacts are not staged.
5. Review `README.md`, `README.tr.md`, `docs/PRIVACY.md`, `docs/PLATFORMS.md`, `docs/WINDOWS_RELEASE.md`, and `SECURITY.md` for behavior changes.

## Tag Build

Create a `v*` tag only after the release check passes:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The `Release Artifacts` workflow builds, verifies, and uploads wheel/sdist artifacts plus Windows ZIP/MSI artifacts. Download and inspect those artifacts before publishing anywhere external.

## Windows Artifacts

Windows ZIP and MSI artifacts are built on a Windows runner with PyInstaller and WiX. To reproduce locally:

```powershell
python -m pip install -e ".[dev,windows-build]"
dotnet tool install --global wix
.\scripts\build-windows-dist.ps1
```

Use `-SkipMsi` to build only the portable ZIP when WiX is unavailable. See [docs/WINDOWS_RELEASE.md](WINDOWS_RELEASE.md).

## Rollback Notes

If a release artifact is wrong, delete the tag, fix the repository, rerun the release check, and create a new tag. Do not reuse an already published artifact name outside GitHub/GitLab workflow storage.

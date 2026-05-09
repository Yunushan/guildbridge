# Release Checklist

GuildBridge release artifacts are built by CI for tags and manual workflow runs. The repository does not publish to PyPI automatically.

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
5. Review `README.md`, `README.tr.md`, `docs/PRIVACY.md`, `docs/PLATFORMS.md`, and `SECURITY.md` for behavior changes.

## Tag Build

Create a `v*` tag only after the release check passes:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The `Release Artifacts` workflow builds, verifies, and uploads wheel/sdist artifacts. Download and inspect those artifacts before publishing anywhere external.

## Rollback Notes

If a release artifact is wrong, delete the tag, fix the repository, rerun the release check, and create a new tag. Do not reuse an already published artifact name outside GitHub/GitLab workflow storage.

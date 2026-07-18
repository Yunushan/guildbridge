# Release Checklist

GuildBridge release artifacts are built only by the release workflow for tags and manual workflow runs. Normal CI builds and verifies packages but does not upload downloadable artifacts. The repository does not publish to PyPI automatically.

For a public `v*` tag push, the release workflow verifies that the tag commit is reachable from `origin/main` before it builds artifacts. A tag created from another branch or an unrelated commit fails before any public signing or publication step.

## Before Tagging

The preferred local release-prep path on Windows/PowerShell is:

```powershell
.\scripts\release.ps1 -Version 1.0.0
```

On Linux, BSD, macOS, Android terminal environments, and iOS terminal environments with `sh`, `git`, and Python available:

```bash
scripts/release.sh 1.0.0
```

Both scripts refuse to run on a dirty worktree by default, update `pyproject.toml` and `src/guildbridge/__init__.py`, run the local release checks including the enforced source-coverage floor, verify the live GitHub branch/environment/security controls through an administrator-authenticated `gh` session, clean and rebuild `dist/`, verify the distributions, create a `Release v1.0.0` commit, and create an annotated `v1.0.0` tag. They do not push anything. The hosted-control check fails closed if CodeQL has open alerts, production reviewers or signing/evidence secrets are missing, or branch protection is incomplete.

After reviewing the result, publish with:

```powershell
git push origin main
git push origin v1.0.0
```

Use `-SkipCommit` or `-SkipTag` only when you intentionally want to do those steps manually. `-SkipChecks`/`--skip-checks` may only be used with the corresponding skip-tag option, so it cannot create a releasable tag. Use `-AllowDirty` only when you have already verified unrelated local changes will not be included in the release commit.

For `scripts/release.sh`, the equivalent options are `--skip-commit`, `--skip-tag`, and `--allow-dirty`.

Manual release-prep steps are:

1. Confirm `pyproject.toml` and `src/guildbridge/__init__.py` have the same version.
2. When dependencies changed, regenerate and review the Python 3.14 release lock before tagging:

```bash
make lock-release
python -m pip install --dry-run --ignore-installed --require-hashes -r requirements/release.txt
```

Do not regenerate the lock only to make a release pass. Commit the reviewed lock update with the dependency change that requires it.

3. Run the local release check:

```bash
make release-check
```

If `make` is unavailable, run the equivalent commands:

```bash
python -m pip install --require-hashes -r requirements/release.txt
python -m pip install --no-deps -e ".[dev,windows-build]"
python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py scripts/check-release-version.py scripts/check-release-controls.py scripts/check-secret-hygiene.py scripts/check-security-baseline.py scripts/new-production-evidence-template.py scripts/check-github-production-settings.py scripts/check-production-evidence.py scripts/check-production-readiness.py scripts/record-provider-drill-receipt.py scripts/check-release-assets.py scripts/check-content-capability-scope.py scripts/pip-audit-truststore.py
python -m ruff check --select S src scripts
python -m ruff check --select BLE src scripts
python -m mypy src
python -m coverage run -m pytest -q
python -m coverage report
python scripts/pip-audit-truststore.py --strict
python scripts/check-release-controls.py
python scripts/check-secret-hygiene.py --history
python scripts/check-security-baseline.py
python scripts/check-content-capability-scope.py
python scripts/check-github-production-settings.py --repo Yunushan/guildbridge
python scripts/check-platform.py --require cli --format json
python -m build
python -m twine check dist/*.whl dist/*.tar.gz
python scripts/verify-dist.py
```

4. Inspect `dist/` and confirm it contains exactly one wheel and one source archive.
5. Confirm `.env`, journals, generated plans, and local migration artifacts are not staged.
6. Review `README.md`, `README.tr.md`, `docs/PRIVACY.md`, `docs/PLATFORMS.md`, `docs/WINDOWS_RELEASE.md`, and `SECURITY.md` for behavior changes.

## Tag Build

Create a `v*` tag only after the release check passes:

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

The `Release Artifacts` workflow audits dependencies, verifies immutable workflow controls, builds and verifies wheel/sdist artifacts plus Windows ZIP/MSI artifacts, generates SHA-256 checksum files and an SPDX SBOM, and creates GitHub build provenance attestations. For tag-push builds, it also creates or updates the GitHub Release and attaches those files as release assets. Public tag-push builds fail unless the Windows code-signing secrets are configured. Manual workflow runs upload workflow artifacts only, even when the selected ref is a tag; those artifacts are unsigned internal test artifacts.

## Windows Artifacts

Windows ZIP and MSI artifacts are built on a Windows runner with PyInstaller and WiX. To reproduce locally:

```powershell
python -m pip install --require-hashes -r requirements/release.txt
python -m pip install --no-deps -e ".[dev,windows-build]"
dotnet tool install --global wix
.\scripts\build-windows-dist.ps1
```

Use `-SkipMsi` to build only the portable ZIP when WiX is unavailable. See [docs/WINDOWS_RELEASE.md](WINDOWS_RELEASE.md).

After downloading a signed tag release, verify the ZIP, MSI, and `SHA256SUMS-windows.txt` from a clean Windows host before approving deployment:

```powershell
.\scripts\verify-windows-release.ps1 -ArtifactsDir C:\Downloads\GuildBridge-v1.0.0
```

This requires the Windows SDK signing tools but does not require the private code-signing certificate.

When creating the protected production evidence record, record the seven downloaded release-asset checksums without manually copying digests:

```powershell
python scripts/record-release-asset-checksums.py --assets-dir C:\Downloads\GuildBridge-v1.0.0 --evidence C:\Private\guildbridge-v1.0.0-evidence.json
```

This refuses a missing, duplicate, malformed, or checksum-mismatched asset before it updates the private evidence file.

After the protected release workflow finishes and the private evidence record is complete, use the single production-readiness gate:

```powershell
python scripts/check-production-readiness.py --repo Yunushan/guildbridge --evidence C:\Private\guildbridge-v1.0.0-evidence.json --tag v1.0.0 --expected-commit <40-character-sha>
```

It is read-only and fails unless repository controls, GitHub settings, secret hygiene, security baseline, content-route scope, and the exact release evidence all pass.

## Rollback Notes

If a release artifact is wrong, delete the tag, fix the repository, rerun the release check, and create a new tag. Do not reuse an already published artifact name outside GitHub/GitLab workflow storage.

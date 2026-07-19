# Production Readiness Evidence

This document defines the evidence required to describe a GuildBridge release as production-ready. A passing local test suite is necessary but not sufficient: provider permissions, signing identities, and hostile-network behavior require evidence from the deployment environment.

## Repository controls

The repository currently provides the following controls:

- CI tests the supported hosted OS/Python matrix, runs Ruff, mypy, pytest, package validation, a dependency vulnerability audit, and an executable release-controls policy check.
- CI also constructs the desktop Tk GUI under Xvfb on Ubuntu 24.04 and Python 3.14; package verification cannot start until that GUI smoke job passes.
- CI measures branch coverage for `src/guildbridge` and fails below the current 80% source-coverage baseline. This is a ratchet: it prevents silent regression, but does not replace live provider contract or GUI interaction evidence.
- A zero-dependency static security baseline, Ruff security-rules pass, and explicit exception-boundary lint reject dynamic code execution, unsafe deserialization, shell execution, TLS-verification bypasses, weak digests, insecure temporary-file APIs, unsafe process-invocation patterns, and undocumented broad exception handling in application code and Python release tooling.
- A dedicated CodeQL workflow analyzes Python and GitHub Actions workflows on pushes, pull requests, and a weekly schedule using extended security and quality query suites; it is pinned to immutable action commits and policy-checked alongside release controls.
- `scripts/check-github-production-settings.py` provides a read-only, administrator-authenticated verification of the live branch-protection, release-tag ruleset, secret-scanning, open CodeQL-alert, current-commit CodeQL analysis, release-environment, and required environment-secret configuration before a public tag is created. On success it can write a credential-free private audit receipt for the exact release evidence record.
- GitHub Actions dependencies and the multi-architecture Python container base are pinned to immutable digests, workflows prohibit `pull_request_target`, release runs are serialized, and Dependabot watches Python, Docker, and Actions dependencies.
- Release workflow permissions default to `contents: read`; OIDC and provenance permissions are granted only to the artifact-attestation and protected-signing jobs that require them. Unsigned Windows packaging receives repository-read access only.
- `.dockerignore` excludes Git history, local environment files, migration journals, private production evidence, and build output from the Docker build context.
- Public release builds install their Python 3.14 dependencies from `requirements/release.txt`, a generated requirements file with hashes for the full runtime, release, audit, and Windows-packaging toolchain. The pinned Linux container independently installs `requirements/runtime-linux.txt`, and CI plus tagged releases build the container and run its entry point.
- Tag releases verify the tag version, generate wheel/sdist and Windows ZIP/MSI outputs, publish SHA-256 checksum files, an SPDX 2.3 SBOM, and a machine-readable dependency-audit report, create GitHub build provenance attestations, cryptographically verify those attestations against the exact repository, release workflow, tag, commit, and GitHub-hosted runner, and compare every downloaded release asset to both its manifest and the protected private evidence record before publication.
- Public tag releases fail closed unless a trusted Windows code-signing PFX and password are configured as protected `production-release` environment secrets; the tag-only signing job signs and verifies EXE/MSI artifacts before publication.
- GUI-managed provider credentials are stored in the operating-system credential store; legacy non-secret settings files are atomically replaced and owner-readable only on POSIX. LAN web mode requires TLS, explicit authentication, CSRF protection, and a short-lived secure browser session.
- Managed DiscordChatExporter downloads require a verified SHA-256 digest and refuse unmanaged cached binaries.
- Credential-bearing provider requests require HTTPS for non-loopback endpoints; legacy plain HTTP is an explicit, documented break-glass setting only.
- Release and local verification paths scan tracked files for high-confidence secret signatures without printing their values; a maintainer can also scan reachable Git history before publication.
- Migration writes remain opt-in and require a reviewed plan plus explicit apply confirmation.

## Required external evidence for a 100/100 release

Before assigning a 100/100 production-readiness score to a public release, retain evidence for every item below:

1. A protected release branch requires CI, code review, and signed or verified commits according to the organization policy.
2. The tag workflow completed successfully, including dependency audit, artifact checksum generation, and GitHub provenance attestations.
3. Windows EXE and MSI assets are signed by a currently trusted code-signing certificate and pass `signtool verify /pa /v` on a clean Windows host. Retain the output of `scripts/verify-windows-release.ps1` run against the downloaded ZIP, MSI, and `SHA256SUMS-windows.txt`.
4. A clean consumer machine verifies the published `SHA256SUMS` and reviews the release SPDX SBOM and dependency-audit report before installing the wheel, ZIP, or MSI.
5. Every directed structural-template combination of the supported providers has a live, disposable-tenant dry run and an apply/recovery exercise using least-privilege dedicated migration accounts. Retain one source-provider bundle plus one opaque private evidence reference for each directed destination route. Live content migration has a narrower, guarded matrix: Discord is the source, Mumble is excluded as a target, and each enabled content route needs its own disposable-tenant evidence before it is claimed production-ready. Do not test against production communities first.
6. The exact TLS certificate and DNS/reverse-proxy configuration used for LAN web GUI deployment is independently reviewed. LAN mode must not be exposed directly to the public internet.
7. The organization has a vulnerability disclosure contact, incident owner, backup/retention policy for journals, and a tested rollback or compensating-action procedure.
8. A release owner reviews dependency audit exceptions, provider API breaking changes, and platform-specific installer smoke-test evidence.

The operational retention and recovery procedure is documented in `docs/OPERATIONS.md`, and the required GitHub branch/environment controls are documented in `docs/REPOSITORY_SETTINGS.md`; their execution evidence must be retained outside the repository.

Use `examples/production-evidence.example.json` as a structural reference, or create an exact matrix with `python scripts/new-production-evidence-template.py --tag vX.Y.Z --commit <40-character-sha> --out <private-file.json>`. Both include `provider_drills` for structural-template routes and `content_provider_drills` for the currently enabled live-content routes. Neither file is valid production evidence: the example contains all-zero digests and the generated template has incomplete controls. First run `python scripts/check-github-production-settings.py --repo Yunushan/guildbridge --receipt-out <private-directory>/github-production-settings-audit-vX.Y.Z.json` as an administrator and retain the resulting receipt; set `github_settings_evidence_ref` to its opaque `private://` reference. After downloading the eight published assets, run `python scripts/record-release-asset-checksums.py --assets-dir <downloaded-assets-dir> --evidence <private-file.json>` to verify the public manifests and record their checksums atomically. Replace the remaining placeholder fields with distinct evidence records for the exact release, then run `python scripts/check-production-evidence.py --evidence <private-file.json> --tag vX.Y.Z`. Evidence files are ignored by Git and must never contain credentials.

Evidence references use the opaque `private://` scheme. Do not place public URLs, credentials, query tokens, server IDs, or customer/community names in an evidence record. Production-evidence files, hosted-settings audit receipts, and provider-drill `*.receipt.json` files are excluded from Git and Docker build contexts; retain them only in approved private storage.

For each structural or live-content provider route, create a separate private receipt after its dry run, successful apply, and successful recovery run. The receipt records only the route, stable action metadata, and SHA-256 digests of the three local artifacts; it does not copy provider IDs, journal payloads, messages, or credentials:

```bash
python scripts/record-provider-drill-receipt.py \
  --kind structural \
  --source discord \
  --target stoat \
  --plan <dry-run-plan.json> \
  --apply-journal <successful-apply-journal.json> \
  --recovery-journal <successful-recovery-journal.json> \
  --out <private-directory>/discord-to-stoat.structural.receipt.json
```

Use `--kind content` for an enabled live-content route. A recovery journal must record the failed journal it resumed from; GuildBridge now persists that provenance for both structural and content journals. Store the receipt privately, review it, and then place its opaque `private://` reference in the matching route field of the main evidence record.

After a tag release has published its assets and the private record is complete, run one final fail-closed preflight:

```bash
python scripts/check-production-readiness.py \
  --repo Yunushan/guildbridge \
  --evidence <private-file.json> \
  --tag vX.Y.Z \
  --expected-commit <40-character-sha>
```

This aggregates repository controls, Git-history secret hygiene, the static security baseline, current live-content capability scope, live GitHub settings, and exact private release evidence. It makes no GitHub changes and never prints credential values.

## Scoring rule

Use this conservative rule:

- **Repository readiness** can reach 90/100 when all automated repository controls pass.
- **Production deployment readiness** can reach 100/100 only when all external evidence above is recorded for the exact release tag.

Never claim 100/100 solely because CI is green. That would conceal the externally managed risks of provider access, trusted signing, TLS deployment, and operational response.

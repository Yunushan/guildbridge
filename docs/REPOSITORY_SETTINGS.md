# Production Repository Settings

These GitHub settings are required before treating a GuildBridge tag as a public production release. They are intentionally not stored in Git because they govern the hosted repository, not the source tree.

After configuring them, verify the effective hosted state with an administrator-authenticated GitHub CLI. This command is read-only and reports missing controls without revealing secret values:

```bash
python scripts/check-github-production-settings.py --repo Yunushan/guildbridge --receipt-out <private-directory>/github-production-settings-audit-vX.Y.Z.json
```

For a credential-free, ordered explanation of a failed audit, add `--remediation`. This mode is read-only: it does not change branch rules, environments, rulesets, or secrets.

To hand the required state to a repository administrator without exposing credentials, write a declarative plan locally:

```bash
python scripts/check-github-production-settings.py \
  --repo Yunushan/guildbridge \
  --remediation-plan-out <private-directory>/github-production-remediation-plan.json
```

The plan contains intended control names and policy values only. It does not contain GitHub tokens, signing material, environment-secret values, server identifiers, or fetched settings payloads.

The receipt is written only after every hosted control passes. It contains no token values, secret values, server IDs, or fetched GitHub settings payloads. Keep it in approved private storage and record an opaque `private://` reference to it in the matching production-evidence file.

## Protect the release branch

For `main`, require pull requests, at least one independent approval, and successful completion of the `CI / package` check before merging. Require branches to be up to date before merging, prevent force pushes and branch deletion, and require verified or signed commits when the organization supports them.

## Protect publication

Create an active GitHub tag ruleset targeting `refs/tags/v*`. Restrict tag creation, updates, and deletion; grant bypass only to the narrowly authorized release identity under organization policy. This prevents an unreviewed tag from changing the release workflow that GitHub executes. Create a GitHub Environment named `production-release`, restrict it to protected tags matching `v*`, add at least one required reviewer who is independent of the release author, and store all three release secrets there. The audit defaults the release author to the authenticated `gh` user and rejects an environment where that same account is the only named user reviewer. Use `--release-author <login>` when a different maintainer will create the tag. Team reviewers still require an organization-level independence review. The tag-only `sign Windows installers` job targets this environment before it receives the signing certificate; the `publish GitHub release assets` job also targets it before public assets are published. The earlier packaging job receives no signing secret and produces an internal unsigned artifact only.

## Configure signing

Set `GUILDBRIDGE_CODESIGN_PFX_BASE64` and `GUILDBRIDGE_CODESIGN_PFX_PASSWORD` as `production-release` environment secrets. Use a currently trusted code-signing certificate and rotate it before expiry. Public tag builds fail before signing or publishing if the signing material is absent.

Set `GUILDBRIDGE_PRODUCTION_EVIDENCE_JSON` as a protected environment secret. Its value must be the completed JSON record validated by `scripts/check-production-evidence.py` for the exact release tag and source commit. It contains evidence references and checksums, not credentials. The publish job fails closed when it is absent, invalid, or bound to a different commit.

## Completion order

Complete the hosted controls in this order so a tag cannot publish before the release gates exist:

1. Configure the `main` branch rules above, including the `CI / package`, `CodeQL / Analyze (python)`, and `CodeQL / Analyze (actions)` required checks.
2. Create an active `refs/tags/v*` tag ruleset that restricts creation, updates, and deletion, with only a narrowly authorized release identity allowed to bypass it.
3. Create the `production-release` environment, restrict it to `v*` tags, disable administrator bypass, and require an independent reviewer.
4. Add the three required environment secrets. Do not store their values in repository files, workflow variables, plans, journals, or issue text.
5. Push the workflow hardening changes and wait for fresh `python` and `actions` CodeQL analyses on the resulting `main` commit. Re-run `python scripts/check-github-production-settings.py --repo Yunushan/guildbridge --receipt-out <private-directory>/github-production-settings-audit-vX.Y.Z.json`; it rejects missing or stale analysis results and does not accept an alert dismissal as a substitute for reanalysis.
6. Run the disposable-tenant provider dry-run, apply, and recovery exercises. Generate and validate the private evidence record for the exact tag and commit before creating the tag.

This sequence is intentionally partially manual: branch rules, reviewers, signing keys, and provider credentials are organization-owned controls that must not be mutated by a repository workflow.

## Retain release evidence

For each tag, retain the successful workflow URL, provenance attestation, checksums, SPDX SBOM, Windows signature verification output, provider dry-run/apply/recovery evidence, and the approved operations record in private organization storage.

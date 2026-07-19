# Security Policy

## Reporting a vulnerability

Please open a private GitHub security advisory at `https://github.com/Yunushan/guildbridge/security/advisories/new`. Do not report vulnerabilities in public issues.

Do not paste tokens, server IDs, private template files, or screenshots containing secrets into public issues.

## Secret handling

GuildBridge reads provider credentials from environment variables or the operating-system credential store. Templates and dry-run plans must not contain provider tokens or session cookies.

The desktop GUI stores confirmed provider credentials in the system credential store: Windows Credential Locker, macOS Keychain, or a supported Linux secret-service backend. It does not write newly entered tokens to `~/.guildbridge/.env`; legacy non-secret settings are still written atomically and are owner-readable only on POSIX (`0600`). Manual `.env` use remains available for non-GUI and headless deployments, where an enterprise secret manager or injected environment variables are preferred.

The browser GUI binds to loopback only by default. LAN mode requires HTTPS, an explicit authentication token, and a TLS certificate/key. The one-time authentication URL is exchanged for an HttpOnly, Secure, same-site session cookie and the token is not embedded into rendered HTML or form submissions.

Provider API clients reject non-loopback `http://` endpoints by default, so credentials cannot silently cross a LAN or public network without TLS. `GUILDBRIDGE_ALLOW_INSECURE_HTTP=1` is a deliberate legacy-only override and must not be enabled for a production deployment.

Never commit:

- `.env`
- bot tokens
- access tokens
- session tokens
- Matrix access tokens
- cookies
- private keys

The repository's release gates run `python scripts/check-secret-hygiene.py` against tracked files without printing matched values. Run `python scripts/check-secret-hygiene.py --history` before the first public release or after a suspected disclosure; rotate any credential found in reachable history before publishing.

## Safe migration practice

1. Export to a local template.
2. Run `guildbridge validate`.
3. Run `guildbridge redact` if the template was hand-edited.
4. Run an import without `--apply`.
5. Review the generated plan.
6. Run again with `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>` only after review.
7. Keep the generated apply journal with your migration notes. If a run fails, inspect the journal before retrying and use `--resume-journal` to verify the retry matches the failed run and reviewed plan.

## Scope

GuildBridge is for community structure migration. It is not a backup tool for messages, members, DMs, or user profile data.

## Release integrity

Release workflows audit installed Python dependencies, verify an immutable workflow-policy contract, pin GitHub Actions to reviewed commit IDs, publish SHA-256 checksum files and SPDX SBOMs, and produce GitHub build provenance attestations. Public `v*` releases require a trusted Windows code-signing certificate; see `docs/WINDOWS_RELEASE.md` for the required signing configuration.

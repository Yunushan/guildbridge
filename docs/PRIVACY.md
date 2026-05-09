# Privacy Design

GuildBridge treats templates as public artifacts by default.

## Data intentionally excluded

- message history
- member lists
- direct messages
- email addresses
- profile data
- presences
- Rocket.Chat subscriptions and direct messages
- Mumble live users, registrations, certificates, and voice state
- Mattermost users, posts, direct messages, and per-user sidebar categories
- Zulip users, messages, topics, subscriptions, and private DMs
- raw provider IDs
- bot tokens, session tokens, cookies, and access tokens

## Permission overwrites

Role/everyone overwrites are structural and portable, so they can be exported.

User/member overwrites are not portable without identifying users. They are dropped even when `--include-user-overwrites` is requested because the neutral schema only accepts role/everyone targets.

## Dry-run first

Every import creates a plan. Nothing is written unless the user adds `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>`. GuildBridge recomputes a no-write candidate plan immediately before applying and refuses writes if the command, target, template fingerprint, action count, or action hash differs from the reviewed dry-run file. Actual writes are also refused when template validation fails unless `--force-invalid-template` is supplied after manual review.

Confirmed apply runs also write a local journal before provider writes begin. The journal records structural action payloads, action success/failure status, and the final result or sanitized error. It does not store provider tokens. Use `--resume-journal` on a retry so GuildBridge refuses to continue if the command, provider, target, template fingerprint, or reviewed plan hash no longer matches the failed run.

## Redaction command

```bash
guildbridge redact input.template.json --out safe.template.json
```

The redactor removes unsafe metadata keys, recursively cleans nested copied API responses, redacts token-like values inside otherwise safe strings, hashes suspicious source identifiers, removes unsafe overwrite placeholders, and resets privacy flags.

# Privacy Design

GuildBridge treats templates as public artifacts by default.

## Data intentionally excluded

- message history
- member lists
- direct messages
- email addresses
- profile data
- presences
- raw provider IDs
- bot tokens, session tokens, cookies, and access tokens

## Permission overwrites

Role/everyone overwrites are structural and portable, so they can be exported.

User/member overwrites are not portable without identifying users. They are dropped by default. If `--include-user-overwrites` is used for diagnostics, GuildBridge creates anonymized placeholders and the `redact` command removes them again.

## Dry-run first

Every import creates a plan. Nothing is written unless the user adds `--apply`.

## Redaction command

```bash
guildbridge redact input.template.json --out safe.template.json
```

The redactor removes unsafe metadata keys and resets privacy flags.

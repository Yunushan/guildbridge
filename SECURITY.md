# Security Policy

## Reporting a vulnerability

Please open a private security advisory in your GitHub/GitLab project or contact the repository maintainers through your preferred private channel.

Do not paste tokens, server IDs, private template files, or screenshots containing secrets into public issues.

## Secret handling

GuildBridge reads provider credentials from environment variables only. Templates and dry-run plans must not contain provider tokens or session cookies.

Never commit:

- `.env`
- bot tokens
- access tokens
- session tokens
- Matrix access tokens
- cookies
- private keys

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

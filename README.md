<div align="center">

# GuildBridge

**Privacy-first server/community template importer-exporter for Discord, Stoat, Fluxer, and Matrix/Element.**

Import, export, redact, validate, and migrate community structure without shipping members, messages, DMs, tokens, or raw user IDs in open-source templates.

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-blue) ![build](https://img.shields.io/badge/build-ready-brightgreen) ![privacy](https://img.shields.io/badge/privacy-redacted_by_default-success)

**providers** Discord · Fluxer · Stoat · Matrix/Element  
**actions** export · import · migrate · validate · redact · dry-run · apply

[Quick Start](#quick-start) • [Supported Paths](#supported-paths) • [Privacy Model](#privacy-model) • [Configuration](#configuration) • [Examples](#examples) • [Provider Notes](#provider-notes) • [Contributing](#contributing) • [License](#license)

</div>

---

## What is GuildBridge?

GuildBridge converts community/server layout into a neutral JSON format, then imports that structure into another platform.

It focuses on **portable structure**, not surveillance or data cloning:

- roles and safe role permissions
- categories / channel groups / Matrix spaces
- text, voice, announcement, forum, stage, and link-like channels where the target supports them
- safe channel topics and basic channel settings
- role/everyone permission overwrites where possible
- dry-run plans before any write operation

It intentionally does **not** export:

- messages or message history
- members, member lists, DMs, friend lists, presences, emails, IPs, or personal profiles
- bot tokens, access tokens, session tokens, or cookies
- raw provider IDs in generated templates; source IDs are hashed/localized
- user/member-specific permission overwrites unless explicitly requested, and even then they are anonymized and removed by `redact`

## Best project name

Recommended name: **GuildBridge**.

Why it fits:

- “Guild” is understood by Discord-like communities and gaming/chat platforms.
- “Bridge” makes the import/export purpose obvious.
- It is short enough for a CLI command and package name: `guildbridge`.
- It does not lock the project to only one platform.

Alternative names:

- **ServerPort** — clear, but sounds more infrastructure/network-oriented.
- **CommunityBridge** — broader, but longer.
- **ChanFerry** — memorable, but less professional.
- **SpaceBridge** — good for Matrix/Element, less obvious for Discord/Fluxer/Stoat.

## Quick Start

### 1. Install locally

```bash
git clone https://github.com/YOUR_ORG/guildbridge.git
cd guildbridge
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e .[dev]
```

### 2. Configure tokens without committing secrets

```bash
cp .env.example .env
$EDITOR .env
```

Never commit `.env`. The repository `.gitignore` excludes it.

### 3. See providers

```bash
guildbridge providers
```

### 4. Export a Discord server template to neutral JSON

```bash
guildbridge export \
  --from discord \
  --template "https://discord.new/your-template-code" \
  --out community.template.json
```

### 5. Dry-run import to Fluxer

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.plan.json
```

### 6. Apply after reviewing the plan

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.result.json \
  --apply
```

## Supported Paths

All providers export into the same neutral schema, so the migration path is:

```text
source provider -> neutral community.template.json -> target provider
```

| From | To | Status | Notes |
|---|---|---:|---|
| Discord | Fluxer | ✅ supported | Good structural fit; channel/role permissions are mapped best-effort. |
| Discord | Stoat | ✅ supported | Uses configurable Stoat/Revolt-style API endpoints. |
| Discord | Matrix/Element | ✅ supported | Creates Matrix spaces and rooms; roles do not map 1:1. |
| Fluxer | Discord | ✅ supported | Requires an existing Discord guild target. |
| Fluxer | Stoat | ✅ supported | Best-effort role/channel mapping. |
| Fluxer | Matrix/Element | ✅ supported | Categories become nested spaces. |
| Stoat | Discord | ✅ supported | Best-effort role/channel mapping. |
| Stoat | Fluxer | ✅ supported | Best-effort role/channel mapping. |
| Stoat | Matrix/Element | ✅ supported | Categories become spaces. |
| Matrix/Element | Discord/Fluxer/Stoat | ✅ supported | Exports Matrix space hierarchy as channels; Matrix has no global server roles. |

## Configuration

GuildBridge reads environment variables. Use `.env.example` as the source of truth.

### Discord

```bash
DISCORD_BOT_TOKEN="..."
DISCORD_API_BASE="https://discord.com/api/v10"
```

The Discord bot needs enough permission to read guild roles/channels and to create roles/channels in the target guild when importing.

### Fluxer

```bash
FLUXER_BOT_TOKEN="..."
FLUXER_API_BASE="https://api.fluxer.app/v1"
```

Set `FLUXER_API_BASE` to your self-hosted instance if needed.

### Stoat

```bash
STOAT_BOT_TOKEN="..."
STOAT_API_BASE="https://api.stoat.chat"
```

Stoat-compatible endpoints and authentication can evolve. Keep the base URL and provider implementation editable for your instance.

### Matrix/Element

```bash
MATRIX_ACCESS_TOKEN="..."
MATRIX_BASE_URL="https://matrix.example.org"
MATRIX_SERVER_NAME="example.org"
```

Element is a Matrix client, so GuildBridge uses the Matrix Client-Server API.

## Examples

### Discord template -> Fluxer server

```bash
guildbridge migrate \
  --from discord \
  --to fluxer \
  --template "https://discord.new/abc123" \
  --target-name "Fluxer Copy" \
  --template-out exported.template.json \
  --plan-out fluxer.plan.json

# After reviewing fluxer.plan.json:
guildbridge migrate \
  --from discord \
  --to fluxer \
  --template "https://discord.new/abc123" \
  --target-name "Fluxer Copy" \
  --plan-out fluxer.result.json \
  --apply
```

### Live Discord guild -> existing Discord guild

```bash
guildbridge export --from discord --source-id "SOURCE_GUILD_ID" --out source.template.json

guildbridge import \
  --to discord \
  --file source.template.json \
  --target-id "TARGET_GUILD_ID" \
  --plan-out discord.plan.json
```

### Fluxer -> Stoat

```bash
guildbridge migrate \
  --from fluxer \
  --to stoat \
  --source-id "FLUXER_GUILD_ID" \
  --target-name "Stoat Copy" \
  --plan-out stoat.plan.json
```

### Element/Matrix space -> Discord

```bash
guildbridge export \
  --from element \
  --source-id '!spaceid:matrix.example.org' \
  --out matrix-space.template.json

guildbridge import \
  --to discord \
  --file matrix-space.template.json \
  --target-id "DISCORD_TARGET_GUILD_ID" \
  --plan-out discord.plan.json
```

### Validate and redact

```bash
guildbridge validate community.template.json

guildbridge redact community.template.json --out safe.template.json
```

## Neutral schema

The neutral JSON schema is in:

```text
schema/community-template.schema.json
```

A template contains:

```json
{
  "schema": "guildbridge.community.v1",
  "version": "1.0",
  "name": "Example Community",
  "privacy": {
    "exports_members": false,
    "exports_messages": false,
    "stores_tokens": false
  },
  "roles": [],
  "categories": [],
  "channels": []
}
```

## Privacy Model

GuildBridge is designed so public template files are safe to publish.

### Hard rules

1. **No messages.** Message history is not part of the schema.
2. **No members.** Member lists and user profiles are not part of the schema.
3. **No DMs.** Direct/private conversations are never exported.
4. **No secrets.** Tokens and session values are read from environment variables only.
5. **Dry-run first.** Imports do nothing unless `--apply` is set.
6. **Redaction available.** `guildbridge redact` removes unsafe metadata from hand-edited templates.

### Source IDs

Provider IDs are transformed into local IDs like:

```text
role_discord_2f1a4c...
chan_fluxer_91bb20...
```

This keeps the template stable without revealing original raw IDs.

## Provider Notes

### Discord

- Can export from a live guild with a bot token.
- Can export from a Discord server template URL/code.
- Imports into an existing Discord guild using `--target-id`.
- Discord server templates can clone categories, channels, roles, and permissions, but some community channel types are not included by Discord itself.

### Fluxer

- Uses a Discord-like but separate API surface.
- Can create a target guild/server if `--target-id` is not provided.
- Uses configurable base URLs for self-hosted deployments.

### Stoat

- Uses configurable Stoat/Revolt-style HTTP endpoints.
- Can create a target server if `--target-id` is not provided.
- Permission mapping is best-effort and intentionally easy to edit in `src/guildbridge/permissions.py`.

### Matrix/Element

- Element runs on Matrix, so the provider uses Matrix Client-Server endpoints.
- Categories are imported as nested Matrix spaces.
- Channels are imported as Matrix rooms.
- Discord/Fluxer/Stoat-style global roles cannot be faithfully represented without member IDs, which GuildBridge intentionally avoids.

## Development

```bash
python -m pip install -e .[dev]
ruff check src tests
mypy src
pytest
```

Run the CLI directly:

```bash
python -m guildbridge providers
```

## GitHub and GitLab CI

This repo includes both:

```text
.github/workflows/ci.yml
.gitlab-ci.yml
```

Both pipelines run install, lint, type checks, and tests.

## Project layout

```text
guildbridge/
  src/guildbridge/
    cli.py
    models.py
    permissions.py
    privacy.py
    providers/
      discord.py
      fluxer.py
      stoat.py
      matrix.py
  schema/community-template.schema.json
  examples/template.example.json
  tests/
  docs/
```

## Security

- Do not commit `.env`.
- Do not paste tokens into issue reports.
- Run dry-runs before `--apply`.
- Review generated plans before applying them.
- Prefer a bot/application with minimum required permissions.

See [SECURITY.md](SECURITY.md).

## Contributing

Pull requests are welcome. Keep provider-specific API quirks inside provider adapters and keep the neutral schema privacy-safe.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).

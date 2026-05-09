<div align="center">

# GuildBridge

**Privacy-first server/community template importer-exporter for Discord, Stoat, Fluxer, Matrix/Element, Rocket.Chat, and Mumble.**

Import, export, redact, validate, and migrate community structure without shipping members, messages, DMs, tokens, or raw user IDs in open-source templates.

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-blue) ![build](https://img.shields.io/badge/build-ready-brightgreen) ![privacy](https://img.shields.io/badge/privacy-redacted_by_default-success)

**language** [English](README.md) · [Türkçe](README.tr.md)

**providers** Discord · Fluxer · Stoat · Matrix/Element · Rocket.Chat · Mumble  
**interfaces** CLI · desktop GUI · web/mobile GUI  
**actions** export · import · migrate · validate · redact · dry-run · apply

[Quick Start](#quick-start) • [GUI](#gui) • [Supported Platforms](#supported-platforms) • [Supported Paths](#supported-paths) • [Privacy Model](#privacy-model) • [Recovery Guidance](#recovery-guidance) • [Release Hygiene](#release-hygiene) • [Configuration](#configuration) • [Examples](#examples) • [Provider Notes](#provider-notes) • [Contributing](#contributing) • [License](#license)

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
- user/member-specific permission overwrites; unsafe user targets are dropped even when diagnostics are requested

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
git clone https://github.com/Yunushan/guildbridge.git
cd guildbridge
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
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

### 4. Check platform support

```bash
guildbridge platforms --check
```

### 5. Launch the GUI

```bash
guildbridge-gui
```

For browser and mobile access:

```bash
guildbridge-web
```

### 6. Export a Discord server template to neutral JSON

```bash
guildbridge export \
  --from discord \
  --template "https://discord.new/your-template-code" \
  --out community.template.json
```

### 7. Dry-run import to Fluxer

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.plan.json
```

### 8. Apply after reviewing the plan

```bash
guildbridge import \
  --to fluxer \
  --file community.template.json \
  --target-name "Imported Community" \
  --plan-out fluxer.result.json \
  --plan-in fluxer.plan.json \
  --apply \
  --confirm-apply APPLY
```

Confirmed apply runs require a reviewed dry-run plan through `--plan-in`. GuildBridge recomputes a no-write candidate plan, compares the command, target, template fingerprint, action count, and action hash to the reviewed file, and refuses writes if anything drifted. Apply runs also write a local journal before provider writes start. By default the journal is saved under `.guildbridge/journals/`; use `--journal-out path/to/journal.json` for an explicit path. If a run fails halfway through, inspect the journal before retrying and pass `--resume-journal path/to/journal.json` so GuildBridge verifies the retry uses the same command, target, provider, template fingerprint, and reviewed plan hash.

## GUI

GuildBridge includes two GUI modes that wrap the same export, import, migrate, validate, and redact commands as the CLI.

Desktop GUI:

```bash
guildbridge-gui
```

Browser/mobile GUI:

```bash
guildbridge-web
```

The browser GUI starts at `http://127.0.0.1:8765` by default. It uses a responsive layout with touch-sized controls, anchored navigation, result status panels, and scroll-safe platform tables for phone and tablet browsers. It also uses a per-server CSRF token, limits POST body size, adds basic browser security headers, and requires typing `APPLY` before browser-triggered write operations run with `--apply`.

Both GUI modes expose the same apply-safety controls as the CLI for import and migrate: Reviewed plan input, Journal output, Resume journal, Force invalid template after review, and Apply writes. Apply operations need a reviewed plan path and typed `APPLY`; GuildBridge still validates the reviewed plan before provider writes start.

Use `--host 0.0.0.0 --allow-lan --auth-token "choose-a-long-random-token"` only on trusted networks when you want phones or tablets on the same network to connect. LAN mode requires an auth token on every request; if you omit `--auth-token`, GuildBridge generates one and prints it once at startup.

Alternative launch commands:

```bash
python -m guildbridge.gui
python -m guildbridge.web
```

The desktop GUI runs on platforms with Tkinter installed and a desktop session. Android and iOS are browser-client targets for `guildbridge-web`; on-device CLI use is experimental because mobile Python runtimes vary.

## Supported Platforms

GuildBridge support is tiered so platform claims stay honest:

- CI-tested CLI/runtime: Windows, Ubuntu, macOS, and Debian through the GitLab Python image.
- GitHub Actions tests Python 3.10, 3.11, 3.12, 3.13, and 3.14 on the required hosted matrix.
- Hosted compatibility jobs cover Windows Server 2022 and macOS 26. Exact Windows 10/11, Windows Server 2019/2026, and Ubuntu 26.04 checks use the manual self-hosted workflow because GitHub does not provide normal hosted labels for those targets.
- Install-script supported: Windows Server, Linux Mint, RHEL, AlmaLinux, Rocky Linux, Oracle Linux, Fedora, CentOS, CentOS Stream, Arch Linux, Manjaro Linux, Gentoo, FreeBSD, NetBSD, and OpenBSD.
- Browser-client supported: Android and Apple iOS can use `guildbridge-web` from a mobile browser. On-device CLI support is experimental and depends on the Python runtime.

Desktop GUI support requires Tkinter and a desktop session. Headless servers can use the CLI or browser GUI.

Install or check platform dependencies:

```bash
./scripts/install-system-deps.sh
./scripts/install-system-deps.sh --dry-run --require dev
guildbridge platforms --check
python scripts/check-platform.py --require cli --format json
```

Windows:

```powershell
.\scripts\check-platform.ps1
.\scripts\check-platform.ps1 -Require desktop-gui
```

The default check requires CLI readiness only. Use `--require desktop-gui`, `--require web-gui`, or `--require dev` when you need those capabilities checked as hard requirements.

See [docs/PLATFORMS.md](docs/PLATFORMS.md) for package names and platform-specific notes.

## Supported Paths

All providers export into the same neutral schema, so the migration path is:

```text
source provider -> neutral community.template.json -> target provider
```

| From | To | Status | Notes |
|---|---|---:|---|
| Discord/Fluxer/Stoat | Rocket.Chat | ✅ supported | Creates Rocket.Chat roles and rooms; room-specific permission semantics are best-effort. |
| Rocket.Chat | Discord/Fluxer/Stoat/Matrix | ✅ supported | Exports rooms and workspace roles; messages, users, subscriptions, and DMs are excluded. |
| Discord/Fluxer/Stoat/Matrix/Rocket.Chat | Mumble | ✅ supported with admin bridge | Creates Mumble groups and voice channels through a configured admin API bridge. |
| Mumble | Discord/Fluxer/Stoat/Matrix/Rocket.Chat | ✅ supported with admin bridge | Exports Mumble groups, channels, and ACL-like permissions; live voice state and registrations are excluded. |
| Discord | Fluxer | ✅ supported | Good structural fit; channel/role permissions are mapped best-effort. |
| Discord | Stoat | ✅ supported | Uses configurable Stoat/Revolt-style API endpoints. |
| Discord | Matrix/Element | ✅ supported | Creates Matrix spaces and rooms; roles do not map 1:1. |
| Fluxer | Discord | ✅ supported | Requires an existing Discord guild target. |
| Fluxer | Stoat | ✅ supported | Best-effort role/channel mapping. |
| Fluxer | Matrix/Element | ✅ supported | Categories become nested spaces. |
| Stoat | Discord | ✅ supported | Best-effort role/channel mapping. |
| Stoat | Fluxer | ✅ supported | Best-effort role/channel mapping. |
| Stoat | Matrix/Element | ✅ supported | Categories become spaces. |
| Matrix/Element | Discord/Fluxer/Stoat/Rocket.Chat/Mumble | ✅ supported | Exports Matrix space hierarchy as channels; Matrix has no global server roles. |

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

### Rocket.Chat

```bash
ROCKET_CHAT_API_BASE="https://chat.example.org/api/v1"
ROCKET_CHAT_AUTH_TOKEN="..."
ROCKET_CHAT_USER_ID="..."
```

Rocket.Chat exports rooms/channels and workspace roles. It does not export messages, users, subscriptions, direct messages, or private user metadata.

### Mumble

```bash
MUMBLE_API_BASE="https://mumble-admin.example.org/api/v1"
MUMBLE_API_TOKEN="..."
```

Mumble/Murmur does not provide a universal HTTP management API on the voice port. GuildBridge expects `MUMBLE_API_BASE` to point at an admin API bridge for Murmur/Ice/gRPC management that exposes server, group, channel, and ACL routes.

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
  --plan-in fluxer.plan.json \
  --apply \
  --confirm-apply APPLY
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
5. **Stable reviewed plans.** Imports do nothing unless `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>` is set. GuildBridge refuses writes if the current candidate plan differs from the reviewed dry-run plan.
6. **Apply journals.** Confirmed apply runs write a local journal with started, succeeded, and failed action records so interrupted writes can be audited before retrying.
7. **Redaction available.** `guildbridge redact` removes unsafe metadata keys, token-like values, raw source IDs, and unsafe overwrite placeholders from hand-edited templates.

## Recovery Guidance

Command failures include the original error plus recovery hints for common operator issues: missing files, invalid JSON, missing provider tokens, HTTP authentication/rate-limit/provider failures, reviewed-plan drift, invalid templates, and journal resume mismatches.

For interrupted apply runs, inspect the journal first. Retry only with the same command, target, template, and reviewed plan, then pass `--resume-journal path/to/journal.json` so GuildBridge verifies the retry before writing.

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

### Rocket.Chat

- Uses Rocket.Chat REST API credentials: `ROCKET_CHAT_AUTH_TOKEN` and `ROCKET_CHAT_USER_ID`.
- Exports workspace rooms/channels and roles.
- Imports text-like channels as Rocket.Chat channels or private groups.
- Room-specific role semantics are best-effort because Rocket.Chat permissions are mostly workspace role settings.

### Mumble

- Uses a configured Mumble/Murmur admin API bridge through `MUMBLE_API_BASE`.
- Exports groups, channel tree, and ACL-style allow/deny entries.
- Imports structural channels as Mumble voice channels.
- Does not export live users, registrations, certificates, voice state, or text/chat history.

## Release Hygiene

Release steps are documented in [docs/RELEASE.md](docs/RELEASE.md). The short local check is:

```bash
make release-check
```

The GitHub release workflow builds and uploads artifacts for `v*` tags and manual runs; it does not publish to PyPI automatically. Windows release runs also produce a portable ZIP with `guildbridge.exe`, `guildbridge-gui.exe`, `guildbridge-web.exe`, and an MSI installer when WiX is available.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py
python -m mypy src
python -m pytest -q
python scripts/check-platform.py --require cli --format json
python -m build
python -m twine check dist/*
python scripts/verify-dist.py
```

Run the CLI directly:

```bash
python -m guildbridge providers
```

Run the GUI directly:

```bash
python -m guildbridge.gui
```

## GitHub and GitLab CI

This repo includes both:

```text
.github/workflows/ci.yml
.gitlab-ci.yml
```

Both pipelines run install, lint, type checks, tests, platform checks, package builds, distribution metadata checks, and wheel install verification.

GitHub Actions also has a `Release Artifacts` workflow for `v*` tags and manual runs. It builds the wheel/sdist, Windows ZIP, and Windows MSI, then uploads them as workflow artifacts; it does not publish to PyPI automatically.

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
- Run dry-runs before `--apply --confirm-apply APPLY --plan-in <reviewed-plan.json>`.
- Review generated plans before applying them.
- Prefer a bot/application with minimum required permissions.

See [SECURITY.md](SECURITY.md).

## Contributing

Pull requests are welcome. Keep provider-specific API quirks inside provider adapters and keep the neutral schema privacy-safe.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).

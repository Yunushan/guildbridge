<div align="center">

<img src="docs/assets/guildbridge-icon.svg" alt="GuildBridge icon" width="96" height="96">

# GuildBridge

**Privacy-first server/community template importer-exporter for Discord, Stoat, Fluxer, Spacebar, Daccord, Matrix/Element, Rocket.Chat, Mumble, Mattermost, and Zulip.**

Import, export, redact, validate, and migrate community structure without shipping members, messages, DMs, tokens, or raw user IDs in open-source templates.

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-blue) ![build](https://img.shields.io/badge/build-ready-brightgreen) ![privacy](https://img.shields.io/badge/privacy-redacted_by_default-success)

**language** [English](README.md) · [Türkçe](README.tr.md)

**providers** Discord · Fluxer · Stoat · Spacebar · Daccord · Matrix/Element · Rocket.Chat · Mumble · Mattermost · Zulip  
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

Normal structure templates intentionally do **not** export:

- messages or message history
- members, member lists, DMs, friend lists, presences, emails, IPs, or personal profiles
- bot tokens, access tokens, session tokens, or cookies
- raw provider IDs in generated templates; source IDs are hashed/localized
- user/member-specific permission overwrites; unsafe user targets are dropped even when diagnostics are requested

### Optional content migration

GuildBridge now has an explicit optional content-migration path for features such as messages, authors, timestamps, attachments, emoji, stickers, pins, replies, reactions, embeds, polls, threads, forum posts, server banners, role colors, channel permissions, NSFW flags, offline exports, pre-creation review, pause/resume, incremental migration, dead-letter retry, message splitting, reports, locks, circuit breakers, and channel-ordered parallel sends.

This content path is **off by default** and is separate from privacy-safe structure templates. Normal `export`, `import`, and `migrate` commands stay structure-only. Content is handled through a separate neutral archive:

```bash
guildbridge content-features
guildbridge content-features --format json
guildbridge content-export --discord-chat-export ./DiscordChatExporter --out community.content.json
guildbridge content-import --file community.content.json --to stoat,fluxer --plan-out content.plan.json
```

The first supported source is DiscordChatExporter JSON. GuildBridge can convert an existing offline export, or run a locally installed DiscordChatExporter CLI for you when you provide a Discord guild/server ID and a token environment variable:

Live content migration currently exports from Discord archives only. Structural template export/import remains the cross-provider migration path. Mumble does not currently support live content import.

```bash
set DISCORD_TOKEN=your-discord-token
guildbridge content-export \
  --source-id 123456789012345678 \
  --discord-chat-exporter-bin DiscordChatExporter.Cli \
  --discord-export-out .guildbridge/content/discord-chat-exporter/server \
  --out community.content.json
```

If you do not already have DiscordChatExporter, you can opt into a managed download that is cached under `.guildbridge/tools/discord-chat-exporter`:

```bash
guildbridge content-export \
  --source-id 123456789012345678 \
  --download-discord-chat-exporter \
  --discord-chat-exporter-version latest \
  --discord-export-out .guildbridge/content/discord-chat-exporter/server \
  --out community.content.json
```

GuildBridge only downloads remote exporter binaries when `--download-discord-chat-exporter` is set and does not store Discord tokens in templates, archives, plans, journals, or reports. It converts DiscordChatExporter output into `guildbridge.content.v1`, hashes raw source IDs, and preserves message text, authors, timestamps, attachment URLs/local paths, embeds, replies, pins, reactions, custom emoji markers, stickers, polls, thread/forum metadata, server banner/icon URLs, role-color metadata, channel permission metadata, and NSFW channel flags in the private archive or companion structure flow. It can dry-run a content import plan for every target provider from the CLI, desktop GUI Content tab, or web GUI Content panel. Live formatted-message writes are supported for Discord, Spacebar, Daccord, Fluxer, Stoat/Revolt, Matrix/Element, Rocket.Chat, Mattermost, and Zulip when you provide a reviewed plan, a target channel map, and provider tokens. `--content-parallel-sends N` sends multiple source channels concurrently while preserving message order within each channel. `--content-thread-mode reference|merge|channel|markdown` controls whether thread/forum messages stay as references, merge into parent-channel history, route to mapped thread channels, or write local markdown thread archives. Mumble remains structure/voice-channel only because it has no native text-history import surface.

The default `community.content.json` archive name and common content journals, reports, incremental-state files, dead letters, and thread archives are excluded from Git and Docker build contexts. Keep every content archive in approved private storage.

Apply-side content imports can write journals, reports, lock files, incremental state, and dead-letter files:

```bash
guildbridge content-import \
  --file community.content.json \
  --to stoat \
  --channel-map channel-map.json \
  --plan-out content.plan.json

guildbridge content-import \
  --file community.content.json \
  --to stoat \
  --channel-map channel-map.json \
  --plan-in content.plan.json \
  --apply --confirm-apply APPLY \
  --content-journal-out .guildbridge/content/journals/stoat.json \
  --content-report-out .guildbridge/content/reports/stoat.json \
  --content-dead-letter-out .guildbridge/content/dead-letter/stoat.json \
  --content-incremental-state .guildbridge/content/state/stoat.json \
  --content-incremental
```

For Discord-to-Stoat migrations that should behave like a one-click Ferry-style run, use `--ferry-parity`. It enables native content, cached remote media downloads, thread-channel mode, three parallel channel sends, incremental state, reports, dead letters, lock files, and continue-on-error defaults under `.guildbridge/content/ferry-parity/<provider>/<target>/`.

Attachments, embeds, replies, reactions, pins, stickers, polls, custom emoji, authors, timestamps, and thread/forum references are preserved as formatted text by default. Provider-native content behavior is opt-in with `--native-content` or narrower flags such as `--native-attachments`, `--native-embeds`, `--native-replies`, `--native-reactions`, `--native-pins`, `--native-custom-emoji`, `--native-masquerade`, and `--native-stickers`. Stoat/Revolt uses Ferry-style Autumn uploads plus native embeds, replies, reactions, pins, custom emoji, server icon/banner uploads from local archive paths or downloaded server asset URLs, and masquerade. Discord and Spacebar can apply local or downloaded server icon/banner assets through Discord-compatible guild patch routes. Discord, Spacebar, Daccord, and Fluxer use Discord-compatible native message routes where supported. Matrix can upload local or downloaded media and apply replies/reactions/pins. Mattermost and Rocket.Chat can upload local or downloaded files and apply native replies/reactions/pins. Zulip can upload local or downloaded files as message links and apply reactions. Remote CDN/media URLs are downloaded only when `--download-remote-assets` or `--ferry-parity` is set; cached files live under `.guildbridge/content/remote-assets/`, which should remain untracked. JSON apply reports are accompanied by a markdown migration report with a fidelity score and feature counts. Use `--no-attachments`, `--no-embeds`, `--no-reactions`, `--no-stickers`, `--no-polls`, `--no-threads`, or `--no-custom-emoji` to omit optional fidelity items from formatted messages. GuildBridge refuses unsafe structure-template content flags.

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

Import and migrate can target more than one destination in a single reviewed plan. Repeat `--to` or comma-separate targets; use `provider=value` when target IDs or names differ per destination:

```bash
guildbridge migrate \
  --from discord \
  --to stoat \
  --to fluxer \
  --template "https://discord.new/your-template-code" \
  --target-name stoat="Stoat Copy" \
  --target-name fluxer="Fluxer Copy" \
  --plan-out multi-target.plan.json
```

The multi-target dry run writes a `guildbridge.batch-result.v1` plan with one validated provider result per destination. Applying it uses the same command shape plus `--plan-in multi-target.plan.json --apply --confirm-apply APPLY`. If `--journal-out journal.json` is used with multiple destinations, GuildBridge writes provider-specific journals such as `journal.stoat.json` and `journal.fluxer.json`.

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

On Windows release builds, users can run the same interfaces without installing Python:

```text
guildbridge-gui.exe
guildbridge-web.exe
```

### Desktop GUI workflow

1. Configure provider tokens through injected environment variables, or use **Configure Tokens** in the GUI assistant. The GUI saves confirmed credentials in the operating-system credential store after a Yes/No confirmation; it cannot read already-open Discord or Stoat browser sessions.
2. Open `guildbridge-gui` or `guildbridge-gui.exe`.
3. Use the **Platforms** tab first to confirm CLI, desktop GUI, and web GUI readiness.
4. Use **Export** to create a neutral template from a source provider. Provide either a source ID or a provider template URL/code, then choose an output JSON path.
5. Use **Import** to import an existing template into one or more target providers, or **Migrate** to export once and import into one or more destinations in one flow.
6. In **Export**, **Import**, **Migrate**, or **Content**, use the assistant buttons to generate ignored local artifact paths under `.guildbridge/gui`.
7. In **Migrate**, select any supported source and one or more targets, then use **Prepare Selected Route**. **Discord -> Stoat Preset** remains available as a shortcut for that route.
8. Use **Invite Discord Bot** when a Discord source or target needs the bot installed. If **Discord app/client ID** is empty, GuildBridge tries to derive it from `DISCORD_BOT_TOKEN`.
9. Use **Check Source Access** and **Check Target Access** to verify that the configured tokens can read the selected source and target before making a plan. If access fails because a token is missing, use **Configure Tokens** and retry without restarting the app.
10. Use the **Theme** selector to switch between light and dark mode.
11. Click **Dry-run Check** first. This creates a dry-run plan in **Plan/result JSON** without writing to the provider.
12. Review the generated plan JSON, then click **Use Plan as Reviewed** to move that plan into **Reviewed plan JSON** and switch **Plan/result JSON** to an apply-result file.
13. To perform real writes, click **Actual Run**. The desktop GUI shows the target platform/server and incoming changes, then asks a Yes/No confirmation before writes start.
14. Use **Journal output JSON** for apply runs so interrupted writes can be audited. Use **Resume journal JSON** only when retrying an interrupted apply with the same command, target, template, and reviewed plan.
15. Use **Validate / Redact** before sharing templates.

The output panel shows the exact `guildbridge ...` command that the GUI ran, stdout/stderr, exit code, and duration.

The browser GUI starts at `http://127.0.0.1:8765` by default. It uses a responsive layout with touch-sized controls, anchored navigation, light/dark theme selection, result status panels, and scroll-safe platform tables for phone and tablet browsers. It also uses a per-server CSRF token, limits POST body size, adds basic browser security headers, and requires typing `APPLY` before browser-triggered write operations run with `--apply`.

The desktop GUI exposes separate **Dry-run Check** and **Actual Run** buttons for import and migrate. Actual runs need a reviewed plan path and a Yes/No confirmation that previews the target provider, target server, action count, and incoming changes; GuildBridge still validates the reviewed plan before provider writes start. The browser GUI keeps the typed `APPLY` confirmation for web-triggered write operations.

If Discord returns a raw `404 Unknown Guild`, GuildBridge reports whether the bot is missing from the server or whether the Source ID looks like a channel ID. Use the server/guild ID for **Source ID**; channel URLs and channel IDs are rejected before writing.

The same access check is available from the CLI:

```bash
guildbridge check-access --provider discord --id "SOURCE_GUILD_ID"
guildbridge check-access --provider stoat --id "TARGET_SERVER_ID"
```

Use `--host 0.0.0.0 --allow-lan --auth-token "choose-a-long-random-token"` only on trusted networks when you want phones or tablets on the same network to connect. LAN mode requires a configured auth token and a TLS certificate/key; it creates an HttpOnly, Secure, same-site session cookie after the one-time authenticated URL is opened. The token is never rendered into forms or pages.

### Browser and mobile workflow

1. Start the local web GUI:

```bash
guildbridge-web
```

2. Open `http://127.0.0.1:8765` in a browser.
3. Use the same **Migrate**, **Export**, **Import**, **Validate**, **Redact**, **Runtime**, and **Platforms** sections as the desktop GUI.
4. For phone or tablet access on the same trusted network, start the server with LAN mode:

```bash
guildbridge-web --host 0.0.0.0 --port 8765 --allow-lan --auth-token "choose-a-long-random-token" --tls-cert /secure/guildbridge-cert.pem --tls-key /secure/guildbridge-key.pem
```

5. Open the HTTPS URL with `?auth_token=<token>` once from the mobile browser. GuildBridge immediately redirects to a token-free URL and retains only a secure browser session. Keep this token private because the web GUI can run provider write operations after confirmation.

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

Structural migration supports every registered provider as a source and every
registered provider as one or more destinations: Discord, Fluxer, Stoat,
Spacebar, Daccord, Matrix/Element, Rocket.Chat, Mumble, Mattermost, and Zulip.
That means routes such as `discord -> stoat, fluxer, matrix`,
`stoat -> fluxer`, and `fluxer -> discord` use the same dry-run, review, and
apply flow. Provider APIs can still require the correct token, an existing
target ID, or an admin bridge before writes are allowed.

List the current route matrix with:

```bash
guildbridge routes
guildbridge routes --format json
```

Optional content/message migration is separate from structural migration.
`content-migrate` currently uses a DiscordChatExporter source archive, while
`content-import` can import a GuildBridge content archive into one or more
targets.

### Enterprise chat and voice paths

- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix -> Rocket.Chat**: supported. Creates Rocket.Chat roles and rooms; room-specific permission semantics are best-effort.
- **Rocket.Chat -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix**: supported. Exports rooms and workspace roles; messages, users, subscriptions, and DMs are excluded.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mattermost/Zulip -> Mumble**: supported with an admin bridge. Creates Mumble groups and voice channels through a configured admin API bridge.
- **Mumble -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mattermost/Zulip**: supported with an admin bridge. Exports Mumble groups, channels, and ACL-like permissions; live voice state and registrations are excluded.
- **Mattermost -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Zulip**: supported. Exports team channels and portable role hints; posts, users, DMs, and per-user sidebar categories are excluded.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Zulip -> Mattermost**: supported. Creates teams and text-like channels; arbitrary role creation and permission schemes remain best-effort Mattermost administration work.
- **Zulip -> Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Mattermost**: supported. Exports Zulip channels and user groups; topics, messages, subscriptions, users, and DMs are excluded.
- **Discord/Fluxer/Stoat/Spacebar/Daccord/Matrix/Rocket.Chat/Mumble/Mattermost -> Zulip**: supported. Creates channels through subscriptions and maps roles to user groups; category and overwrite semantics are best-effort.

### Core provider paths

- **Discord -> Fluxer**: supported. Good structural fit; channel/role permissions are mapped best-effort.
- **Discord -> Stoat**: supported. Uses configurable Stoat/Revolt-style API endpoints.
- **Discord -> Spacebar**: supported. Spacebar is Discord-compatible, so GuildBridge uses Discord-style guild, role, channel, and permission payloads.
- **Discord -> Daccord**: supported. Creates Daccord spaces/channels/roles and applies role permission overwrites through Daccord's admin API.
- **Discord -> Matrix/Element**: supported. Creates Matrix spaces and rooms; roles do not map 1:1.
- **Fluxer -> Discord**: supported. Requires an existing Discord guild target.
- **Fluxer -> Stoat**: supported. Best-effort role/channel mapping.
- **Fluxer/Stoat/Spacebar/Daccord cross-migration**: supported. Discord-like structures map well; provider-specific flags remain best-effort.
- **Fluxer -> Matrix/Element**: supported. Categories become nested spaces.
- **Stoat -> Discord**: supported. Best-effort role/channel mapping.
- **Stoat -> Fluxer**: supported. Best-effort role/channel mapping.
- **Stoat -> Matrix/Element**: supported. Categories become spaces.
- **Matrix/Element -> Discord/Fluxer/Stoat/Spacebar/Daccord/Rocket.Chat/Mumble/Mattermost/Zulip**: supported. Exports Matrix space hierarchy as channels; Matrix has no global server roles.

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
# Use STOAT_SESSION_TOKEN instead when Stoat role-management routes require user/session auth.
# Keep session tokens private and use a dedicated migration/admin account when possible.
# STOAT_SESSION_TOKEN="..."
STOAT_API_BASE="https://api.stoat.chat"
```

Stoat-compatible endpoints and authentication can evolve. GuildBridge sends `STOAT_BOT_TOKEN` as `X-Bot-Token` and `STOAT_SESSION_TOKEN` as `X-Session-Token`; use the session-token path only when the target route requires user authentication.

### Spacebar

```bash
SPACEBAR_BOT_TOKEN="..."
SPACEBAR_API_BASE="https://api.spacebar.chat/api/v9"
```

Spacebar is Discord-compatible. GuildBridge uses Discord-style guild, role, channel, and permission endpoints against the configured Spacebar instance.

### Daccord

```bash
DACCORD_API_BASE="https://daccord.example.org/api/v1"
DACCORD_BOT_TOKEN="..."
DACCORD_AUTH_SCHEME="Bot"
```

Daccord supports `Bot` and `Bearer` authorization schemes. Use `DACCORD_AUTH_SCHEME=Bearer` when your instance gives you a user bearer token instead of a bot token.

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

### Mattermost

```bash
MATTERMOST_API_BASE="https://mattermost.example.org/api/v4"
MATTERMOST_TOKEN="..."
```

Mattermost imports create teams and text-like channels. Mattermost roles and permission schemes are not arbitrary Discord-style roles, so GuildBridge preserves non-portable role and overwrite intent as warnings/metadata.

### Zulip

```bash
ZULIP_API_BASE="https://zulip.example.org/api/v1"
ZULIP_EMAIL="bot@example.org"
ZULIP_API_KEY="..."
```

Zulip imports create channels via subscriptions and map non-everyone roles to user groups. Zulip topics, message history, subscriptions, users, and private DMs are intentionally not exported.

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

### One source -> multiple destinations

```bash
guildbridge migrate \
  --from discord \
  --to stoat,fluxer \
  --template "https://discord.new/abc123" \
  --target-name stoat="Stoat Copy" \
  --target-name fluxer="Fluxer Copy" \
  --plan-out discord-to-many.plan.json
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
4. **No secrets in migration artifacts.** Templates, archives, plans, journals, and reports never store tokens or session values. CLI and headless runs read credentials from injected environment variables or a local `.env`; confirmed desktop-GUI credentials are stored in the operating-system credential store after explicit user confirmation.
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

### Spacebar

- Uses Spacebar's Discord-compatible HTTP API under `SPACEBAR_API_BASE`.
- Imports into an existing guild/server using `--target-id`.
- Uses Discord-style permission bitsets because Spacebar targets Discord API compatibility.

### Daccord

- Uses Daccord `/api/v1` space, role, channel, and permission routes.
- Can create a target space if `--target-id` is not provided.
- Supports Daccord role permission names such as `manage_space`, `view_channel`, and `send_messages`.

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

### Mattermost

- Uses Mattermost API v4 with bearer tokens.
- Exports team channels and portable team role hints.
- Imports teams and public/private text-like channels.
- Arbitrary Discord-style roles, channel schemes, and per-user sidebar categories are not created automatically.

### Zulip

- Uses Zulip API v1 with Basic authentication from `ZULIP_EMAIL` and `ZULIP_API_KEY`.
- Exports channels and user groups.
- Imports channels through `users/me/subscriptions` and roles through user groups.
- Topics, messages, subscriptions, users, and private DMs are intentionally excluded.

## Release Hygiene

Release steps are documented in [docs/RELEASE.md](docs/RELEASE.md). The short local check is:

```bash
make release-check
```

The GitHub release workflow builds and uploads artifacts for `v*` tags and manual runs; it does not publish to PyPI automatically. Windows release runs also produce a portable ZIP with `guildbridge.exe`, `guildbridge-gui.exe`, `guildbridge-web.exe`, and an MSI installer when WiX is available.

Release artifact creation happens only in the `Release Artifacts` workflow, not on every normal push. Trigger it manually from GitHub Actions or push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Expected workflow artifacts:

- `guildbridge-dist`: Python wheel and source distribution.
- `guildbridge-windows`: Windows portable ZIP and MSI installer.

Windows artifact build details are documented in [docs/WINDOWS_RELEASE.md](docs/WINDOWS_RELEASE.md).

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests scripts/check-platform.py scripts/verify-dist.py
python -m ruff check --select S src scripts
python -m ruff check --select BLE src scripts
python -m mypy src
python -m pytest -q
python scripts/check-platform.py --require cli --format json
python -m build
python -m twine check dist/*.whl dist/*.tar.gz
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

GitHub Actions also has a `Release Artifacts` workflow for `v*` tags and manual runs. Normal CI builds and verifies wheel/sdist packages but does not upload downloadable artifacts. The release workflow rebuilds the wheel/sdist, Windows ZIP, and Windows MSI, uploads them as workflow artifacts, and attaches them to the GitHub Release for tag builds; it does not publish to PyPI automatically.

For a local release prep that bumps the version, runs checks, builds/verifies `dist/`, commits, and creates an annotated tag without pushing:

```powershell
.\scripts\release.ps1 -Version 1.0.0
```

On Linux, BSD, macOS, Android terminal environments, and iOS terminal environments with `sh`, `git`, and Python:

```bash
scripts/release.sh 1.0.0
```

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
      spacebar.py
      daccord.py
      matrix.py
      rocket_chat.py
      mumble.py
      mattermost.py
      zulip.py
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

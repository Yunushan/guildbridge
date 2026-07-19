# Supported Platforms

GuildBridge is a Python 3.10+ application with a CLI, a Tkinter desktop GUI, and a browser-based web/mobile GUI. The core migration logic is platform-neutral; platform support mainly depends on Python, pip, TLS certificates, Git, and either Tkinter or a browser for GUI usage.

## Support Tiers

GuildBridge separates platform support into explicit tiers:

- `CI tested`: install, lint, type checking, tests, and runtime platform checks run in project CI.
- `Install-script supported`: the project ships package-manager guidance and runtime checks, but CI does not boot that operating system.
- `Experimental`: the core Python code may run when a suitable Python runtime exists, but the platform has strong runtime limitations.
- `Browser client supported`: the device can use the browser GUI against `guildbridge-web`, usually running on a trusted desktop or server.

## Support Matrix

| Platform | Family | CLI tier | Desktop GUI tier | Web/mobile GUI tier | CI coverage | System packages |
|---|---|---|---|---|---|---|
| Windows | Windows | CI tested | Tk desktop supported | local/LAN browser supported | GitHub Actions `windows-2025-vs2026`; self-hosted `windows-10`, `windows-11` | Python 3.10+, Git |
| Windows Server | Windows | install documented plus CI compatibility | Desktop Experience only | local/LAN browser supported | GitHub Actions `windows-2022`; self-hosted `windows-server-2019`, `windows-server-2026` | Python 3.10+, Git |
| Debian | Debian | CI tested | `python3-tk` desktop supported | local/LAN browser supported | GitLab digest-pinned Python 3.14 Debian image | `python3 python3-pip python3-venv python3-tk git ca-certificates` |
| Ubuntu | Debian | CI tested | `python3-tk` desktop supported | local/LAN browser supported | GitHub Actions `ubuntu-24.04`; self-hosted `ubuntu-26.04` | `python3 python3-pip python3-venv python3-tk git ca-certificates` |
| Linux Mint | Debian | install-script supported | `python3-tk` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-venv python3-tk git ca-certificates` |
| RHEL | RHEL | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| AlmaLinux | RHEL | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| Rocky Linux | RHEL | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| Oracle Linux | RHEL | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| Fedora | Fedora | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| CentOS | RHEL | install-script supported when Python 3.10+ is available | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| CentOS Stream | RHEL | install-script supported | `python3-tkinter` desktop supported | local/LAN browser supported | no project CI | `python3 python3-pip python3-tkinter git ca-certificates` |
| Arch Linux | Arch | install-script supported | `tk` desktop supported | local/LAN browser supported | no project CI | `python python-pip tk git ca-certificates` |
| Manjaro Linux | Arch | install-script supported | `tk` desktop supported | local/LAN browser supported | no project CI | `python python-pip tk git ca-certificates` |
| Gentoo | Gentoo | install-script supported | Tk USE support required | local/LAN browser supported | no project CI | `dev-lang/python dev-python/pip dev-lang/tk dev-vcs/git app-misc/ca-certificates` |
| FreeBSD | BSD | install-script supported | Tk desktop supported | local/LAN browser supported | no project CI | `python py312-pip py312-tkinter git ca_root_nss` |
| NetBSD | BSD | install-script supported | Tk desktop supported | local/LAN browser supported | no project CI | `python312 py312-pip py312-tkinter git mozilla-rootcerts` |
| OpenBSD | BSD | install-script supported | Tk desktop supported | local/LAN browser supported | no project CI | `python%3.12 py3-pip python-tkinter git` |
| macOS | Darwin | CI tested | Tk desktop supported | local/LAN browser supported | GitHub Actions `macos-15`, `macos-26` | Python 3.10+ from python.org, Homebrew, or MacPorts |
| Android | Mobile | experimental on-device Python | not supported | browser client supported | no project CI | Termux or another Python-capable Android environment |
| Apple iOS | Mobile | experimental on-device Python | not supported | browser client supported | no project CI | Pyto, a-Shell, Pythonista-style environment, or remote GuildBridge web server |

## CI Coverage

GitHub Actions required CI tests Python `3.10`, `3.11`, `3.12`, `3.13`, and `3.14` on `ubuntu-24.04`, `windows-2025-vs2026`, and `macos-15`.

The same CI workflow also runs hosted compatibility checks on `windows-2022` and `macos-26` with Python `3.14`.

GitHub does not currently provide normal hosted x64 runner labels for `ubuntu-26.04`, Windows 10, Windows 11, Windows Server 2019, or Windows Server 2026. Exact checks for those targets are available through the manual `.github/workflows/self-hosted-platforms.yml` workflow. Configure self-hosted runners with these labels before running it:

```text
windows-10
windows-11
windows-server-2019
windows-server-2026
ubuntu-26.04
```

## Install System Dependencies

Linux, BSD, macOS, and Termux/Android:

```bash
./scripts/install-system-deps.sh
```

Preview package-manager commands before installing:

```bash
./scripts/install-system-deps.sh --dry-run --require dev
```

Windows:

```powershell
.\scripts\check-platform.ps1
```

To let the Windows script install missing Python/Git packages through winget:

```powershell
.\scripts\check-platform.ps1 -InstallPackage
```

Windows can also require a specific capability:

```powershell
.\scripts\check-platform.ps1 -Require desktop-gui
```

## Install GuildBridge

```bash
python -m pip install -e .[dev]
```

Use this on Windows:

```powershell
python -m pip install -e ".[dev]"
```

## Runtime Check

```bash
guildbridge platforms --check
python scripts/check-platform.py
```

The default runtime check requires CLI readiness. It treats missing Tkinter and missing Git as warnings because the CLI can run without a desktop GUI or clone/development workflow.

Require a specific capability when needed:

```bash
guildbridge platforms --check --require desktop-gui
guildbridge platforms --check --require web-gui
python scripts/check-platform.py --require dev
python scripts/check-platform.py --require cli --format json
```

The desktop GUI needs a desktop session and Tkinter. Headless servers can still use the CLI and web GUI without Tkinter display access.
Android and iOS are browser-client targets first. iOS does not provide Tkinter for normal app workflows; run `guildbridge-web` on a trusted desktop/server and open it from Safari, or use an iOS Python runtime that can run a local HTTP server.

## Live Content Migration Scope

Structural template migration supports every documented provider direction. Live message-content migration accepts a private GuildBridge content archive tagged with any registered source provider, then plans or applies it to the supported content-import targets. Discord is the only provider with built-in direct offline export conversion, through an existing DiscordChatExporter archive or a locally executed DiscordChatExporter CLI. Live imports are supported for Discord, Fluxer, Stoat, Spacebar, Daccord, Matrix/Element, Rocket.Chat, Mattermost, and Zulip. Mumble live-content import is not implemented.

Run the guard below before a release when content capabilities change:

```bash
python scripts/check-content-capability-scope.py
```

## GUI

Launch the desktop GUI with:

```bash
guildbridge-gui
```

Or:

```bash
python -m guildbridge.gui
```

Launch the browser/mobile GUI with:

```bash
guildbridge-web
```

Or:

```bash
python -m guildbridge.web
```

The web GUI listens on `127.0.0.1:8765` by default. It uses a responsive layout with touch-sized controls, anchored navigation, result status panels, and scroll-safe platform tables for phone and tablet browsers. It also uses a per-server CSRF token, limits POST body size, adds basic browser security headers, and requires typing `APPLY` before browser-triggered write operations run with `--apply`.

The desktop GUI exposes separate **Dry-run Check** and **Actual Run** buttons for import and migrate. Actual runs need a reviewed dry-run plan path and a Yes/No confirmation that previews the target provider, target server, action count, and incoming changes; GuildBridge still verifies the current candidate plan before writing. The browser GUI keeps typed `APPLY` confirmation for web-triggered write operations.

To allow another device on the same trusted network to connect:

```bash
guildbridge-web --host 0.0.0.0 --port 8765 --allow-lan --auth-token "choose-a-long-random-token" --tls-cert /secure/guildbridge-cert.pem --tls-key /secure/guildbridge-key.pem
```

LAN mode requires `--auth-token` (or `GUILDBRIDGE_WEB_AUTH_TOKEN`) and a TLS certificate/key. Open the one-time authenticated URL only over HTTPS; GuildBridge then redirects to a token-free URL and uses an HttpOnly, Secure, same-site session cookie. Share the token only out-of-band with devices that should control the migration UI.

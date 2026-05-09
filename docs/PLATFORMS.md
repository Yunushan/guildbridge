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
| Windows | Windows | CI tested | Tk desktop supported | local/LAN browser supported | GitHub Actions `windows-latest` | Python 3.10+, Git |
| Windows Server | Windows | install documented | Desktop Experience only | local/LAN browser supported | no project CI | Python 3.10+, Git |
| Debian | Debian | CI tested | `python3-tk` desktop supported | local/LAN browser supported | GitLab `python:3.12` Debian image | `python3 python3-pip python3-venv python3-tk git ca-certificates` |
| Ubuntu | Debian | CI tested | `python3-tk` desktop supported | local/LAN browser supported | GitHub Actions `ubuntu-latest` | `python3 python3-pip python3-venv python3-tk git ca-certificates` |
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
| macOS | Darwin | CI tested | Tk desktop supported | local/LAN browser supported | GitHub Actions `macos-latest` | Python 3.10+ from python.org, Homebrew, or MacPorts |
| Android | Mobile | experimental on-device Python | not supported | browser client supported | no project CI | Termux or another Python-capable Android environment |
| Apple iOS | Mobile | experimental on-device Python | not supported | browser client supported | no project CI | Pyto, a-Shell, Pythonista-style environment, or remote GuildBridge web server |

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

Both GUI modes expose the same apply-safety controls as the CLI for import and migrate: Reviewed plan input, Journal output, Resume journal, Force invalid template after review, and Apply writes. Apply operations need a reviewed dry-run plan path and typed `APPLY`; GuildBridge still verifies the current candidate plan before writing.

To allow another device on the same trusted network to connect:

```bash
guildbridge-web --host 0.0.0.0 --port 8765 --allow-lan --auth-token "choose-a-long-random-token"
```

If `--allow-lan` is used without `--auth-token`, GuildBridge generates a token and prints it once at startup. Request logs do not include the token; share it out-of-band only with devices that should control the migration UI.

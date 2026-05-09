# Windows Release Artifacts

GuildBridge can ship Windows-friendly artifacts in addition to the Python wheel and source distribution:

- `GuildBridge-<version>-windows-x64.zip`: portable folder containing `guildbridge.exe`, `guildbridge-gui.exe`, and `guildbridge-web.exe`.
- `GuildBridge-<version>-windows-x64.msi`: Windows Installer package with Start Menu shortcuts and uninstall support.

The ZIP is the safest first distribution target because users can extract it anywhere and run the executables without admin rights. The MSI is useful for normal Windows installs, enterprise deployment, and uninstall integration.

## Build Locally

Run these commands on Windows:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev,windows-build]"
dotnet tool install --global wix
.\scripts\build-windows-dist.ps1
```

If WiX is not installed or you only want the portable ZIP:

```powershell
.\scripts\build-windows-dist.ps1 -SkipMsi
```

Outputs are written under `dist/`.

## Release Workflow

The GitHub `Release Artifacts` workflow builds Windows artifacts on a Windows runner. It uploads:

- `guildbridge-dist`: Python wheel and source distribution.
- `guildbridge-windows`: Windows ZIP and MSI artifacts.

The Windows job uses PyInstaller for the executable launchers and WiX for the MSI.

## Code Signing

Unsigned Windows executables and MSI packages can trigger Microsoft Defender SmartScreen or antivirus warnings. Public releases should be signed with a trusted code-signing certificate before publishing outside GitHub Actions artifacts.

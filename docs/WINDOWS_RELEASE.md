# Windows Release Artifacts

GuildBridge can ship Windows-friendly artifacts in addition to the Python wheel and source distribution:

- `GuildBridge-<version>-windows-x64.zip`: portable folder containing `guildbridge.exe`, `guildbridge-gui.exe`, and `guildbridge-web.exe`.
- `GuildBridge-<version>-windows-x64.msi`: Windows Installer package with Start Menu shortcuts and uninstall support.

The ZIP is the safest first distribution target because users can extract it anywhere and run the executables without admin rights. The MSI is useful for normal Windows installs, enterprise deployment, and uninstall integration.

## Build Locally

Run these commands on Windows:

```powershell
python -m pip install --require-hashes -r requirements/release.txt
python -m pip install --no-deps -e ".[dev,windows-build]"
dotnet tool install --global wix --version 7.0.0
.\scripts\build-windows-dist.ps1
```

If WiX is not installed or you only want the portable ZIP:

```powershell
.\scripts\build-windows-dist.ps1 -SkipMsi
```

Outputs are written under `dist/`.

## Release Workflow

The GitHub `Release Artifacts` workflow builds Windows artifacts on a Windows runner. Normal push/PR CI does not upload downloadable artifacts. Release runs upload:

- `guildbridge-dist`: Python wheel and source distribution.
- `guildbridge-windows`: Windows ZIP and MSI artifacts.

The Windows job uses PyInstaller for the executable launchers and WiX for the MSI.

The workflow pins WiX Toolset v7 and passes `-acceptEula wix7` to `wix build` through `scripts/build-windows-dist.ps1`. WiX v7 requires this explicit EULA acceptance in build scripts and CI/CD. The local build script also supports WiX v5 and v6, which do not accept that flag; it detects the installed major version and omits the flag for those local builds. If you do not want to build an MSI locally, use `-SkipMsi` and publish only the portable ZIP.

## Code Signing

Unsigned Windows executables and MSI packages can trigger Microsoft Defender SmartScreen or antivirus warnings. Public releases should be signed with a trusted code-signing certificate before publishing outside GitHub Actions artifacts.

`scripts/build-windows-dist.ps1` supports signing the three executables and MSI after they are built. It signs with SHA-256, timestamps the signature, and verifies it with the Windows trust policy:

```powershell
$env:GUILDBRIDGE_CODESIGN_PFX_PASSWORD = "<certificate-password>"
.\scripts\build-windows-dist.ps1 -CodeSigningCertificatePath C:\secure\guildbridge.pfx
```

For GitHub Actions releases, configure repository secrets named `GUILDBRIDGE_CODESIGN_PFX_BASE64` and `GUILDBRIDGE_CODESIGN_PFX_PASSWORD`. The workflow writes the PFX only into the ephemeral runner temp directory. Public `v*` tag-push releases fail closed when either secret is absent, so GitHub Releases cannot receive unsigned Windows installers. `workflow_dispatch` remains available for unsigned internal test artifacts only, including when manually dispatched from a tag. Do not commit certificates, passwords, private keys, or signing output to the repository.

## Verify A Downloaded Release

Verify a release after downloading its Windows ZIP, MSI, and `SHA256SUMS-windows.txt` into the same directory. This does not need the private signing certificate or its password. It verifies the checksum manifest, the MSI Authenticode signature, and each executable embedded in the portable ZIP against the local Windows trust policy:

```powershell
.\scripts\verify-windows-release.ps1 -ArtifactsDir C:\Downloads\GuildBridge-v1.0.9
```

Run this on a clean Windows machine with the Windows SDK signing tools installed so the trust decision is independent of the release builder. A valid verification result means the released files match their published Windows checksum manifest and their signatures are trusted by that machine.

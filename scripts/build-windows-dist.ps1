[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$OutputDir = "dist",
    [string]$Version = "",
    [switch]$SkipMsi,
    [switch]$SkipZip,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RepoRootPath = [System.IO.Path]::GetFullPath($RepoRoot.Path)
$PyInstallerWork = Join-Path $RepoRootPath "build\pyinstaller"
$PyInstallerSpecs = Join-Path $PyInstallerWork "spec"
$OutputRoot = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
    [System.IO.Path]::GetFullPath($OutputDir)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $RepoRootPath $OutputDir))
}

function Get-ProjectVersion {
    $pyproject = Get-Content -LiteralPath (Join-Path $RepoRootPath "pyproject.toml") -Raw
    $match = [regex]::Match($pyproject, '(?m)^version = "([^"]+)"\r?$')
    if (-not $match.Success) {
        throw "Could not read project version from pyproject.toml."
    }
    return $match.Groups[1].Value
}

function Assert-PathUnderRepo {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($RepoRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside repository: $fullPath"
    }
    return $fullPath
}

function Remove-BuildPath {
    param([string]$Path)

    $safePath = Assert-PathUnderRepo -Path $Path
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host "> $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath"
    }
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-ProjectVersion
}

$WindowsRoot = Join-Path $OutputRoot "windows"
$BundleRoot = Join-Path $WindowsRoot "GuildBridge-$Version-windows-x64"
$ZipPath = Join-Path $OutputRoot "GuildBridge-$Version-windows-x64.zip"
$MsiPath = Join-Path $OutputRoot "GuildBridge-$Version-windows-x64.msi"

if ($Clean) {
    Remove-BuildPath -Path $PyInstallerWork
}
Remove-BuildPath -Path $BundleRoot
New-Item -ItemType Directory -Force -Path $BundleRoot | Out-Null
New-Item -ItemType Directory -Force -Path $PyInstallerWork | Out-Null
New-Item -ItemType Directory -Force -Path $PyInstallerSpecs | Out-Null

Set-Location $RepoRootPath

Invoke-Checked -FilePath $Python -Arguments @("-m", "PyInstaller", "--version")

$launchers = @(
    @{ Name = "guildbridge"; Script = "packaging\windows\guildbridge-cli.py"; Windowed = $false },
    @{ Name = "guildbridge-gui"; Script = "packaging\windows\guildbridge-gui.py"; Windowed = $true },
    @{ Name = "guildbridge-web"; Script = "packaging\windows\guildbridge-web.py"; Windowed = $false }
)

foreach ($launcher in $launchers) {
    $modeArg = if ($launcher.Windowed) { "--windowed" } else { "--console" }
    $scriptPath = Join-Path $RepoRootPath $launcher.Script
    Invoke-Checked -FilePath $Python -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--distpath", $BundleRoot,
        "--workpath", $PyInstallerWork,
        "--specpath", $PyInstallerSpecs,
        "--name", $launcher.Name,
        $modeArg,
        $scriptPath
    )
}

foreach ($file in @("README.md", "README.tr.md", "LICENSE", ".env.example", "docs\WINDOWS_RELEASE.md")) {
    Copy-Item -LiteralPath (Join-Path $RepoRootPath $file) -Destination $BundleRoot -Force
}

$expectedExecutables = @("guildbridge.exe", "guildbridge-gui.exe", "guildbridge-web.exe")
foreach ($exe in $expectedExecutables) {
    $exePath = Join-Path $BundleRoot $exe
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Missing expected executable: $exePath"
    }
}

Invoke-Checked -FilePath (Join-Path $BundleRoot "guildbridge.exe") -Arguments @("--version")

if (-not $SkipZip) {
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Compress-Archive -LiteralPath $BundleRoot -DestinationPath $ZipPath -Force
    Write-Host "Created $ZipPath"
}

if (-not $SkipMsi) {
    $wix = Get-Command wix -ErrorAction SilentlyContinue
    if ($null -eq $wix) {
        Write-Warning "WiX Toolset command 'wix' was not found. Skipping MSI. Install it with: dotnet tool install --global wix"
    } else {
        if (Test-Path -LiteralPath $MsiPath) {
            Remove-Item -LiteralPath $MsiPath -Force
        }
        Invoke-Checked -FilePath $wix.Source -Arguments @(
            "build",
            (Join-Path $RepoRootPath "packaging\windows\GuildBridge.wxs"),
            "-arch", "x64",
            "-d", "SourceDir=$BundleRoot",
            "-d", "ProductVersion=$Version",
            "-out", $MsiPath
        )
        Write-Host "Created $MsiPath"
    }
}

Write-Host "Windows artifacts are ready in $OutputRoot"

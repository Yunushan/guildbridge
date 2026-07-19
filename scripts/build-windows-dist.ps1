[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$OutputDir = "dist",
    [string]$Version = "",
    [string]$WixEulaId = "wix7",
    [string]$CodeSigningCertificatePath = "",
    [string]$CodeSigningCertificatePasswordEnv = "GUILDBRIDGE_CODESIGN_PFX_PASSWORD",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$SkipMsi,
    [switch]$SkipZip,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RepoRootPath = [System.IO.Path]::GetFullPath($RepoRoot.Path)
$PyInstallerWork = Join-Path $RepoRootPath "build\pyinstaller"
$PyInstallerSpecs = Join-Path $PyInstallerWork "spec"
$IconPath = Join-Path $RepoRootPath "packaging\windows\guildbridge.ico"
$AssetDataPath = "$(Join-Path $RepoRootPath 'src\guildbridge\assets');guildbridge/assets"
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

function Invoke-CodeSign {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($CodeSigningCertificatePath)) {
        return
    }
    $signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($null -eq $signTool) {
        throw "Code signing certificate was supplied but signtool.exe was not found. Install the Windows SDK signing tools."
    }
    if (-not (Test-Path -LiteralPath $CodeSigningCertificatePath)) {
        throw "Code signing certificate was not found: $CodeSigningCertificatePath"
    }
    $password = [Environment]::GetEnvironmentVariable($CodeSigningCertificatePasswordEnv)
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw "Code signing certificate password is missing from environment variable $CodeSigningCertificatePasswordEnv."
    }
    Write-Host "> signtool sign $Path (certificate password hidden)"
    & $signTool.Source sign /fd SHA256 /f $CodeSigningCertificatePath /p $password /tr $TimestampUrl /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Code signing failed with exit code ${LASTEXITCODE}: $Path"
    }
    Invoke-Checked -FilePath $signTool.Source -Arguments @("verify", "/pa", "/v", $Path)
}

function Get-WixMajorVersion {
    param([string]$WixPath)

    $versionOutput = & $WixPath "--version"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not determine the WiX Toolset version: $WixPath"
    }
    $versionText = ($versionOutput -join "`n").Trim()
    $match = [regex]::Match($versionText, '^(\d+)\.')
    if (-not $match.Success) {
        throw "Could not parse the WiX Toolset version '$versionText'."
    }
    return [int]$match.Groups[1].Value
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
        "--icon", $IconPath,
        "--add-data", $AssetDataPath,
        "--name", $launcher.Name,
        $modeArg,
        $scriptPath
    )
}

foreach ($file in @("README.md", "README.tr.md", "LICENSE", ".env.example", "docs\WINDOWS_RELEASE.md", "packaging\windows\guildbridge.ico")) {
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
Invoke-Checked -FilePath (Join-Path $BundleRoot "guildbridge-web.exe") -Arguments @("--version")

foreach ($exe in $expectedExecutables) {
    Invoke-CodeSign -Path (Join-Path $BundleRoot $exe)
}

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
        $wixMajor = Get-WixMajorVersion -WixPath $wix.Source
        if ($wixMajor -lt 5) {
            throw "WiX Toolset v$wixMajor is unsupported. Install WiX Toolset v5 or later."
        }
        if (Test-Path -LiteralPath $MsiPath) {
            Remove-Item -LiteralPath $MsiPath -Force
        }
        $wixArguments = @("build")
        if ($wixMajor -ge 7) {
            if ([string]::IsNullOrWhiteSpace($WixEulaId)) {
                throw "WiX Toolset v$wixMajor requires an explicit EULA identifier. Pass -WixEulaId wix7."
            }
            $wixArguments += @("-acceptEula", $WixEulaId)
        } elseif (-not [string]::IsNullOrWhiteSpace($WixEulaId)) {
            Write-Verbose "WiX Toolset v$wixMajor does not require -acceptEula; omitting it for this local build."
        }
        $wixArguments += @(
            (Join-Path $RepoRootPath "packaging\windows\GuildBridge.wxs"),
            "-arch", "x64",
            "-d", "SourceDir=$BundleRoot",
            "-d", "ProductVersion=$Version",
            "-out", $MsiPath
        )
        Invoke-Checked -FilePath $wix.Source -Arguments $wixArguments
        Invoke-CodeSign -Path $MsiPath
        Write-Host "Created $MsiPath"
    }
}

Write-Host "Windows artifacts are ready in $OutputRoot"

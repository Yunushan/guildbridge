[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactsDir,
    [Parameter(Mandatory = $true)]
    [string]$CodeSigningCertificatePath,
    [string]$CodeSigningCertificatePasswordEnv = "GUILDBRIDGE_CODESIGN_PFX_PASSWORD",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath"
    }
}

function Get-SingleFile {
    param(
        [string]$Directory,
        [string]$Filter
    )

    $matches = @(Get-ChildItem -LiteralPath $Directory -File -Filter $Filter)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one '$Filter' file in $Directory, found $($matches.Count)."
    }
    return $matches[0]
}

function Sign-AndVerify {
    param(
        [string]$Path,
        [string]$SignToolPath,
        [string]$CertificatePath,
        [string]$Password
    )

    Write-Host "Signing $(Split-Path -Leaf $Path)"
    Invoke-Checked -FilePath $SignToolPath -Arguments @(
        "sign", "/fd", "SHA256", "/f", $CertificatePath, "/p", $Password,
        "/tr", $TimestampUrl, "/td", "SHA256", $Path
    )
    Invoke-Checked -FilePath $SignToolPath -Arguments @("verify", "/pa", "/v", $Path)
}

$artifactsPath = [System.IO.Path]::GetFullPath($ArtifactsDir)
if (-not (Test-Path -LiteralPath $artifactsPath -PathType Container)) {
    throw "Windows artifact directory does not exist: $artifactsPath"
}
if (-not (Test-Path -LiteralPath $CodeSigningCertificatePath -PathType Leaf)) {
    throw "Code signing certificate was not found: $CodeSigningCertificatePath"
}
$password = [Environment]::GetEnvironmentVariable($CodeSigningCertificatePasswordEnv)
if ([string]::IsNullOrWhiteSpace($password)) {
    throw "Code signing certificate password is missing from environment variable $CodeSigningCertificatePasswordEnv."
}
$signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($null -eq $signTool) {
    throw "signtool.exe was not found. Install the Windows SDK signing tools."
}

$zip = Get-SingleFile -Directory $artifactsPath -Filter "GuildBridge-*-windows-x64.zip"
$msi = Get-SingleFile -Directory $artifactsPath -Filter "GuildBridge-*-windows-x64.msi"
$temporaryRoot = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
    [System.IO.Path]::GetTempPath()
} else {
    $env:RUNNER_TEMP
}
$extractRoot = Join-Path $temporaryRoot ("guildbridge-sign-" + [guid]::NewGuid().ToString("N"))
$expectedExecutables = @("guildbridge.exe", "guildbridge-gui.exe", "guildbridge-web.exe")

try {
    Expand-Archive -LiteralPath $zip.FullName -DestinationPath $extractRoot -Force
    $bundleDirectories = @(Get-ChildItem -LiteralPath $extractRoot -Directory)
    if ($bundleDirectories.Count -ne 1) {
        throw "Expected exactly one bundle directory in signed ZIP staging, found $($bundleDirectories.Count)."
    }
    $bundleRoot = $bundleDirectories[0].FullName
    $actualExecutableNames = @(Get-ChildItem -LiteralPath $bundleRoot -File -Filter "*.exe" | ForEach-Object Name | Sort-Object)
    if ([string]::Join("|", $actualExecutableNames) -ne [string]::Join("|", ($expectedExecutables | Sort-Object))) {
        throw "Windows ZIP must contain exactly the expected executable launchers."
    }
    foreach ($executableName in $expectedExecutables) {
        Sign-AndVerify -Path (Join-Path $bundleRoot $executableName) -SignToolPath $signTool.Source -CertificatePath $CodeSigningCertificatePath -Password $password
    }
    Remove-Item -LiteralPath $zip.FullName -Force
    Compress-Archive -LiteralPath $bundleRoot -DestinationPath $zip.FullName -Force
    Sign-AndVerify -Path $msi.FullName -SignToolPath $signTool.Source -CertificatePath $CodeSigningCertificatePath -Password $password
    Get-FileHash -LiteralPath $zip.FullName, $msi.FullName -Algorithm SHA256 |
        ForEach-Object { "$($_.Hash.ToLowerInvariant())  $($_.Path | Split-Path -Leaf)" } |
        Set-Content -LiteralPath (Join-Path $artifactsPath "SHA256SUMS-windows.txt")
} finally {
    if (Test-Path -LiteralPath $extractRoot) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
}

Write-Host "Windows ZIP and MSI were signed and verified."

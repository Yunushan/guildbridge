[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactsDir
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

function Assert-WindowsChecksumManifest {
    param(
        [string]$ManifestPath,
        [System.IO.FileInfo[]]$ExpectedFiles
    )

    $expected = @{}
    foreach ($file in $ExpectedFiles) {
        $expected[$file.Name] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    $entries = @{}
    $lineNumber = 0
    foreach ($line in Get-Content -LiteralPath $ManifestPath -Encoding UTF8) {
        $lineNumber++
        if ($line -notmatch '^(?<hash>[a-f0-9]{64})  (?<name>[^\\/]+)$') {
            throw "Invalid SHA256SUMS-windows.txt entry at line $lineNumber."
        }
        $name = $Matches.name
        if ($entries.ContainsKey($name)) {
            throw "SHA256SUMS-windows.txt contains duplicate entry: $name"
        }
        $entries[$name] = $Matches.hash
    }

    if ($entries.Count -ne $expected.Count) {
        throw "SHA256SUMS-windows.txt must contain exactly the Windows ZIP and MSI entries."
    }
    foreach ($name in $expected.Keys) {
        if (-not $entries.ContainsKey($name)) {
            throw "SHA256SUMS-windows.txt is missing $name."
        }
        if ($entries[$name] -ne $expected[$name]) {
            throw "SHA256SUMS-windows.txt checksum mismatch for $name."
        }
    }
}

function Assert-SafeZipEntries {
    param([string]$ZipPath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace("\\", "/")
            if ([System.IO.Path]::IsPathRooted($name) -or $name.Split("/") -contains "..") {
                throw "Windows ZIP contains an unsafe archive path: $($entry.FullName)"
            }
        }
    } finally {
        $archive.Dispose()
    }
}

$artifactsPath = [System.IO.Path]::GetFullPath($ArtifactsDir)
if (-not (Test-Path -LiteralPath $artifactsPath -PathType Container)) {
    throw "Windows artifact directory does not exist: $artifactsPath"
}

$signTool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if ($null -eq $signTool) {
    throw "signtool.exe was not found. Install the Windows SDK signing tools before verifying a release."
}

$zip = Get-SingleFile -Directory $artifactsPath -Filter "GuildBridge-*-windows-x64.zip"
$msi = Get-SingleFile -Directory $artifactsPath -Filter "GuildBridge-*-windows-x64.msi"
$manifest = Get-SingleFile -Directory $artifactsPath -Filter "SHA256SUMS-windows.txt"
$expectedExecutables = @("guildbridge.exe", "guildbridge-gui.exe", "guildbridge-web.exe")
$extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("guildbridge-verify-" + [guid]::NewGuid().ToString("N"))

try {
    Assert-WindowsChecksumManifest -ManifestPath $manifest.FullName -ExpectedFiles @($zip, $msi)
    Invoke-Checked -FilePath $signTool.Source -Arguments @("verify", "/pa", "/v", $msi.FullName)

    Assert-SafeZipEntries -ZipPath $zip.FullName
    Expand-Archive -LiteralPath $zip.FullName -DestinationPath $extractRoot -Force
    $bundleDirectories = @(Get-ChildItem -LiteralPath $extractRoot -Directory)
    if ($bundleDirectories.Count -ne 1) {
        throw "Expected exactly one bundle directory in the Windows ZIP, found $($bundleDirectories.Count)."
    }
    $bundleRoot = $bundleDirectories[0].FullName
    $actualExecutableNames = @(Get-ChildItem -LiteralPath $bundleRoot -File -Filter "*.exe" | ForEach-Object Name | Sort-Object)
    if ([string]::Join("|", $actualExecutableNames) -ne [string]::Join("|", ($expectedExecutables | Sort-Object))) {
        throw "Windows ZIP must contain exactly the expected executable launchers."
    }
    foreach ($executableName in $expectedExecutables) {
        Invoke-Checked -FilePath $signTool.Source -Arguments @("verify", "/pa", "/v", (Join-Path $bundleRoot $executableName))
    }
} finally {
    if (Test-Path -LiteralPath $extractRoot) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
}

Write-Host "Windows ZIP, MSI, checksums, and Authenticode signatures verified."

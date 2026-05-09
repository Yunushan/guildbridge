[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+([a-zA-Z0-9.-]+)?$')]
    [string]$Version,
    [string]$Python = "python",
    [string]$ReleaseBranch = "main",
    [switch]$SkipChecks,
    [switch]$SkipBuild,
    [switch]$SkipCommit,
    [switch]$SkipTag,
    [switch]$AllowDirty,
    [switch]$NoCleanDist
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RepoRootPath = [System.IO.Path]::GetFullPath($RepoRoot.Path)
$PyprojectPath = Join-Path $RepoRootPath "pyproject.toml"
$InitPath = Join-Path $RepoRootPath "src\guildbridge\__init__.py"
$TagName = "v$Version"

function Assert-Command {
    param([string]$Name)

    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command was not found on PATH: $Name"
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

function Get-CheckedOutput {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    $output = & $FilePath @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')`n$output"
    }
    return ($output -join "`n").Trim()
}

function Assert-PathUnderRepo {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($RepoRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the repository: $fullPath"
    }
    return $fullPath
}

function Remove-RepoPath {
    param([string]$Path)

    $safePath = Assert-PathUnderRepo -Path $Path
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
}

function Get-GitStatus {
    return Get-CheckedOutput -FilePath "git" -Arguments @("status", "--porcelain")
}

function Assert-CleanWorktree {
    param([string]$Reason)

    $status = Get-GitStatus
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "Refusing release prep with uncommitted changes $Reason. Commit or stash them first, or rerun with -AllowDirty."
    }
}

function Assert-TagAvailable {
    & git show-ref --tags --verify --quiet "refs/tags/$TagName"
    if ($LASTEXITCODE -eq 0) {
        throw "Tag already exists locally: $TagName"
    }
}

function Get-ProjectVersion {
    $text = Get-Content -LiteralPath $PyprojectPath -Raw
    $match = [regex]::Match($text, '(?m)^version = "([^"]+)"\r?$')
    if (-not $match.Success) {
        throw "Could not read version from pyproject.toml."
    }
    return $match.Groups[1].Value
}

function Get-PackageVersion {
    $text = Get-Content -LiteralPath $InitPath -Raw
    $match = [regex]::Match($text, '(?m)^__version__ = "([^"]+)"\r?$')
    if (-not $match.Success) {
        throw "Could not read __version__ from src\guildbridge\__init__.py."
    }
    return $match.Groups[1].Value
}

function Write-Utf8NoBom {
    param(
        [string]$Path,
        [string]$Content
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Set-Version {
    $pyproject = Get-Content -LiteralPath $PyprojectPath -Raw
    $updatedPyproject = [regex]::Replace($pyproject, '(?m)^version = "[^"]+"\r?$', "version = `"$Version`"")
    if ($updatedPyproject -eq $pyproject -and (Get-ProjectVersion) -ne $Version) {
        throw "Could not update pyproject.toml version."
    }
    Write-Utf8NoBom -Path $PyprojectPath -Content $updatedPyproject

    $init = Get-Content -LiteralPath $InitPath -Raw
    $updatedInit = [regex]::Replace($init, '(?m)^__version__ = "[^"]+"\r?$', "__version__ = `"$Version`"")
    if ($updatedInit -eq $init -and (Get-PackageVersion) -ne $Version) {
        throw "Could not update src\guildbridge\__init__.py version."
    }
    Write-Utf8NoBom -Path $InitPath -Content $updatedInit
}

function Assert-VersionSynced {
    $projectVersion = Get-ProjectVersion
    $packageVersion = Get-PackageVersion
    if ($projectVersion -ne $Version -or $packageVersion -ne $Version) {
        throw "Version mismatch after update: pyproject.toml=$projectVersion, __init__.py=$packageVersion, expected=$Version."
    }
}

function Invoke-ReleaseChecks {
    if ($SkipChecks) {
        Write-Warning "Skipping lint, type checks, tests, and platform check."
        return
    }

    Invoke-Checked -FilePath $Python -Arguments @("-m", "ruff", "check", "src", "tests", "scripts/check-platform.py", "scripts/verify-dist.py")
    Invoke-Checked -FilePath $Python -Arguments @("-m", "mypy", "src")
    Invoke-Checked -FilePath $Python -Arguments @("-m", "pytest", "-q")
    Invoke-Checked -FilePath $Python -Arguments @("scripts/check-platform.py", "--require", "cli", "--format", "json")
}

function Invoke-ReleaseBuild {
    if ($SkipBuild) {
        Write-Warning "Skipping package build and distribution verification."
        return
    }

    if (-not $NoCleanDist) {
        Remove-RepoPath -Path (Join-Path $RepoRootPath "dist")
    }

    Invoke-Checked -FilePath $Python -Arguments @("-m", "build")

    $distFiles = @(Get-ChildItem -LiteralPath (Join-Path $RepoRootPath "dist") -File | ForEach-Object { $_.FullName })
    $wheels = @($distFiles | Where-Object { $_ -like "*.whl" })
    $sdists = @($distFiles | Where-Object { $_ -like "*.tar.gz" })
    if ($wheels.Count -ne 1 -or $sdists.Count -ne 1) {
        throw "Expected exactly one wheel and one source archive in dist/."
    }

    Invoke-Checked -FilePath $Python -Arguments (@("-m", "twine", "check") + $distFiles)
    Invoke-Checked -FilePath $Python -Arguments @("scripts/verify-dist.py")
}

function Commit-Version {
    $versionStatus = Get-CheckedOutput -FilePath "git" -Arguments @(
        "status",
        "--porcelain",
        "--",
        "pyproject.toml",
        "src/guildbridge/__init__.py"
    )

    if ($SkipCommit) {
        if (-not [string]::IsNullOrWhiteSpace($versionStatus) -and -not $SkipTag) {
            throw "Version files changed but -SkipCommit was set. Commit manually before tagging, or rerun without -SkipCommit."
        }
        Write-Warning "Skipping release commit."
        return
    }

    if ([string]::IsNullOrWhiteSpace($versionStatus)) {
        Write-Host "Version files already match $Version; no release commit needed."
        return
    }

    Invoke-Checked -FilePath "git" -Arguments @("add", "pyproject.toml", "src/guildbridge/__init__.py")
    Invoke-Checked -FilePath "git" -Arguments @("commit", "-m", "Release $TagName")
}

function New-ReleaseTag {
    if ($SkipTag) {
        Write-Warning "Skipping release tag."
        return
    }

    if (-not $AllowDirty) {
        Assert-CleanWorktree -Reason "before tagging"
    }

    Assert-TagAvailable
    Invoke-Checked -FilePath "git" -Arguments @("tag", "-a", $TagName, "-m", "Release $TagName")
}

Set-Location $RepoRootPath
Assert-Command -Name "git"
Assert-Command -Name $Python

if (-not $AllowDirty) {
    Assert-CleanWorktree -Reason "before version bump"
}

$currentBranch = Get-CheckedOutput -FilePath "git" -Arguments @("rev-parse", "--abbrev-ref", "HEAD")
if (-not [string]::IsNullOrWhiteSpace($ReleaseBranch) -and $currentBranch -ne $ReleaseBranch) {
    throw "Release prep must run on '$ReleaseBranch'. Current branch is '$currentBranch'. Use -ReleaseBranch '$currentBranch' to override."
}

Assert-TagAvailable
Set-Version
Assert-VersionSynced
Invoke-ReleaseChecks
Invoke-ReleaseBuild
Commit-Version
New-ReleaseTag

Write-Host ""
Write-Host "Release prep complete for $TagName."
Write-Host "Review the result, then publish with:"
Write-Host "  git push origin $currentBranch"
Write-Host "  git push origin $TagName"

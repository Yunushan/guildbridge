[CmdletBinding()]
param(
    [switch]$InstallPackage,
    [ValidateSet("cli", "desktop-gui", "web-gui", "dev")]
    [string]$Require = "cli"
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot

function Test-Command($Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonCommand {
    if (Test-Command python) {
        return "python"
    }
    if (Test-Command py) {
        return "py"
    }
    return $null
}

$PythonCommand = Get-PythonCommand

if (-not $PythonCommand) {
    Write-Host "Python was not found on PATH."
    if ($InstallPackage -and (Test-Command winget)) {
        winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
        $PythonCommand = Get-PythonCommand
        if (-not $PythonCommand) {
            Write-Host "Python install completed but Python is still not on PATH. Open a new terminal and run this script again."
            exit 1
        }
    } else {
        Write-Host "Install Python 3.10+ from python.org, winget, Chocolatey, or Scoop."
        exit 1
    }
}

& $PythonCommand --version
& $PythonCommand -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
& $PythonCommand -c "import importlib.util; print('tkinter_available:', importlib.util.find_spec('tkinter') is not None)"

if (-not (Test-Command git)) {
    Write-Host "Git was not found on PATH."
    if ($InstallPackage -and (Test-Command winget)) {
        winget install --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
    } else {
        Write-Host "Install Git for Windows from git-scm.com or winget for clone/development workflows."
    }
}

& $PythonCommand (Join-Path $ScriptRoot "check-platform.py") --require $Require

# ASCII-only for compatibility with Windows PowerShell 5.1 (which reads
# UTF-8 without BOM as a legacy code page on some Windows installations).
# Example:
# powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -Mode OneFile
[CmdletBinding()]
param(
    [ValidateSet('OneFile', 'OneDir')]
    [string] $Mode = 'OneFile',
    [switch] $Console,
    [switch] $SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$AppName = 'CementMill'
$Main = Join-Path $Root 'main.py'
$Project = Join-Path $Root 'project'
$Dist = Join-Path $Root 'dist'
$Build = Join-Path $Root 'build'

if (-not (Test-Path -LiteralPath $Main -PathType Leaf)) {
    throw "Entry point not found: $Main"
}
if (-not (Test-Path -LiteralPath $Project -PathType Container)) {
    throw "Source directory not found: $Project"
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    Write-Host 'Creating Python 3.11 virtual environment...'
    $PyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($null -eq $PyLauncher) {
        throw 'Python launcher py.exe was not found. Install Python 3.11 x64, or create .venv manually.'
    }
    & py.exe -3.11 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed (exit code $LASTEXITCODE)."
    }
}

Push-Location -LiteralPath $Root
try {
    if (-not $SkipInstall) {
        Write-Host 'Installing application and build dependencies...'
        & $Python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements.txt') -r (Join-Path $Root 'requirements-build.txt')
        if ($LASTEXITCODE -ne 0) {
            throw "Dependency installation failed (exit code $LASTEXITCODE)."
        }
    }

    Write-Host "Building $AppName (mode: $Mode)..."
    $PyInstallerArgs = @(
        '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--noupx',
        '--name', $AppName,
        '--paths', $Project,
        '--distpath', $Dist,
        '--workpath', $Build,
        '--specpath', $Build,
        '--collect-all', 'matplotlib',
        '--hidden-import', 'matplotlib.backends.backend_qtagg',
        '--hidden-import', 'matplotlib.backends.backend_agg',
        '--hidden-import', 'PySide6.QtWidgets',
        '--hidden-import', 'PySide6.QtGui',
        '--hidden-import', 'PySide6.QtCore'
    )
    if ($Mode -eq 'OneFile') {
        $PyInstallerArgs += '--onefile'
    } else {
        $PyInstallerArgs += '--onedir'
    }
    if ($Console) {
        $PyInstallerArgs += '--console'
    } else {
        $PyInstallerArgs += '--windowed'
    }
    $PyInstallerArgs += $Main

    & $Python @PyInstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed (exit code $LASTEXITCODE)."
    }

    if ($Mode -eq 'OneFile') {
        $Executable = Join-Path $Dist "$AppName.exe"
    } else {
        $Executable = Join-Path (Join-Path $Dist $AppName) "$AppName.exe"
    }
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Output executable not found: $Executable"
    }
    $SizeMB = [math]::Round((Get-Item -LiteralPath $Executable).Length / 1MB, 1)
    Write-Host "Build succeeded: $Executable ($SizeMB MB)" -ForegroundColor Green
    if ($Mode -eq 'OneDir') {
        Write-Host 'Distribute the entire dist\CementMill directory (you may ZIP it).'
    } else {
        Write-Host 'Distribute dist\CementMill.exe. Test it on a separate Windows PC.'
    }
} finally {
    Pop-Location
}

# Build a redistributable Windows executable from the repo checkout.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 [-Mode OneFile|OneDir] [-Console] [-SkipInstall]
[CmdletBinding()]
param(
    [ValidateSet('OneFile','OneDir')]
    [string]$Mode = 'OneFile',
    [switch]$Console,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$AppName = 'CementMill'
$Main = Join-Path $Root 'main.py'
$Project = Join-Path $Root 'project'
$Dist = Join-Path $Root 'dist'
$Work = Join-Path $Root 'build'

if (-not (Test-Path $Python)) {
    Write-Host 'Создаю виртуальное окружение Python 3.11…'
    & py -3.11 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать .venv. Установите Python 3.11 x64.' }
}
if (-not (Test-Path $Main)) { throw "Не найден $Main" }

Push-Location $Root
try {
    if (-not $SkipInstall) {
        Write-Host 'Устанавливаю зависимости приложения и сборки…'
        & $Python -m pip install -r (Join-Path $Root 'requirements.txt') -r (Join-Path $Root 'requirements-build.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки зависимостей.' }
    }

    Write-Host "Собираю $AppName ($Mode)..."
    $ArgsForPython = @(
        '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--noupx',
        '--name', $AppName,
        '--paths', $Project,
        '--distpath', $Dist,
        '--workpath', $Work,
        '--specpath', $Work,
        '--collect-all', 'matplotlib',
        '--hidden-import', 'matplotlib.backends.backend_qtagg',
        '--hidden-import', 'matplotlib.backends.backend_agg',
        '--hidden-import', 'PySide6.QtWidgets',
        '--hidden-import', 'PySide6.QtGui',
        '--hidden-import', 'PySide6.QtCore'
    )
    if ($Mode -eq 'OneFile') { $ArgsForPython += '--onefile' }
    else { $ArgsForPython += '--onedir' }
    if ($Console) { $ArgsForPython += '--console' }
    else { $ArgsForPython += '--windowed' }
    $ArgsForPython += $Main
    & $Python @ArgsForPython
    if ($LASTEXITCODE -ne 0) { throw 'Сборка PyInstaller завершилась с ошибкой.' }

    if ($Mode -eq 'OneFile') { $Executable = Join-Path $Dist "$AppName.exe" }
    else { $Executable = Join-Path (Join-Path $Dist $AppName) "$AppName.exe" }
    if (-not (Test-Path $Executable)) { throw "Готовый EXE не найден: $Executable" }
    $Size = [math]::Round((Get-Item $Executable).Length / 1MB, 1)
    Write-Host "Успешно: $Executable ($Size МБ)" -ForegroundColor Green
    if ($Mode -eq 'OneDir') {
        Write-Host 'Передавать папку dist\CementMill целиком либо ZIP этой папки.'
    } else {
        Write-Host 'Передавать файл dist\CementMill.exe. Проверьте его на другом Windows ПК.'
    }
} finally {
    Pop-Location
}

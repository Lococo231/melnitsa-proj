@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1" -Mode OneFile
if errorlevel 1 (
  echo.
  echo Sborка ne udalas. Prover'te soobshcheniya vyshe.
  pause
  exit /b 1
)
echo.
echo Gotovo: dist\CementMill.exe
pause

@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1" -Mode OneFile
if errorlevel 1 (
  echo.
  echo Build failed. Read the error messages above.
  pause
  exit /b 1
)
echo.
echo Build complete: dist\CementMill.exe
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup or start failed. Check the messages above.
  pause
)

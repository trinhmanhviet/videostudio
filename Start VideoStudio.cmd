@echo off
title VideoStudio Startup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_system.ps1"
if errorlevel 1 (
  echo.
  echo Startup needs attention. See the messages above.
  pause
  exit /b 1
)
exit /b 0

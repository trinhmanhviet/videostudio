@echo off
chcp 65001 >nul
title VideoStudio - Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_system.ps1" %*
echo.
pause

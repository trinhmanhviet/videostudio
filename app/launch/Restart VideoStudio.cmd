@echo off
chcp 65001 >nul
title VideoStudio - Restart
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\restart_system.ps1" %*
echo.
pause

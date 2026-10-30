@echo off
chcp 65001 >nul
title VideoStudio Chrome - Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_profile.ps1" -Mode stop
if errorlevel 1 pause

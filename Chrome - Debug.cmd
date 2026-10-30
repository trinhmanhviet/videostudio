@echo off
chcp 65001 >nul
title VideoStudio Chrome - Flow
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_profile.ps1" -Mode debug
if errorlevel 1 pause

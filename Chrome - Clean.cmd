@echo off
chcp 65001 >nul
title VideoStudio Chrome - Login
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open_profile.ps1" -Mode clean
if errorlevel 1 pause

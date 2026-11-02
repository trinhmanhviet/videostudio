@echo off
cd /d "%~dp0"
title VideoStudio Flow Request Lab
echo Open http://localhost:8878/flow-request in Chrome.
if exist "C:\Python312\python.exe" (
  "C:\Python312\python.exe" -m FlowAPI.server
) else (
  python -m FlowAPI.server
)
pause

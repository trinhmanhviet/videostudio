@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 crawl_wikicv.py --rebuild-only
) else (
  python crawl_wikicv.py --rebuild-only
)
pause

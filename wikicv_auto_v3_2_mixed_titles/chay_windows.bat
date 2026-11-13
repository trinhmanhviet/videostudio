@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)
%PY% --version
if errorlevel 1 (
  echo Can cai Python 3.10+ tu python.org, chon Add python.exe to PATH.
  pause
  exit /b 1
)
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
  echo Cai thu vien that bai. Kiem tra Internet va thu lai.
  pause
  exit /b 1
)
%PY% crawl_wikicv.py
pause

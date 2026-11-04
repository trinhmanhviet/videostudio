@echo off
rem VideoStudio: mo app o khay he thong (goc phai thanh tac vu), giong vTransfer.
rem Chay thang ma nguon bang pythonw, khong can build exe. Menu chuot phai bieu tuong co moi thao tac.
cd /d "%~dp0"
set "PY="
if exist "C:\Python312\pythonw.exe" set PY="C:\Python312\pythonw.exe"
if not defined PY (where pyw >nul 2>nul && set PY=pyw -3)
if not defined PY (where pythonw >nul 2>nul && set PY=pythonw)
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Khong tim thay Python 3. Cai Python 3.12 tu https://www.python.org/downloads/
  pause
  exit /b 1
)
start "" %PY% "%~dp0scripts\windows_launcher.py" %*

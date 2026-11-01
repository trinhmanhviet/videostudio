param([switch]$Force)
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
$python = if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}

Write-Host "Dang kiem tra va tat cac tien trinh VideoStudio..." -ForegroundColor Cyan

if(-not $Force){
    try {
        Push-Location $root
        try {
            $active = & $python (Join-Path $PSScriptRoot 'active_jobs.py')
            if($LASTEXITCODE -ne 0 -or "$active" -notmatch '^\d+$'){throw 'Cannot verify active jobs; nothing stopped.'}
        } finally {Pop-Location}
        if([int]$active -gt 0){
            Write-Warning "Co $active tac vu video dang chay! Neu muon cuong che dung, hay chay voi tham so -Force."
            exit 1
        }
    } catch {Write-Error $_; exit 1}
}

# 1. Dung VideoStudio Backend (Port 8877)
$conn8877 = Get-NetTCPConnection -State Listen -LocalPort 8877 -ErrorAction SilentlyContinue
if($conn8877){
    $procId = $conn8877.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if($proc -and $proc.CommandLine -like '*videostudio.api:app*'){
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Da tat VideoStudio Backend (PID $procId, Port 8877)." -ForegroundColor Green
    } else {
        Write-Warning "Port 8877 dang mo boi PID $procId."
    }
} else {
    Write-Host "[--] VideoStudio Backend (Port 8877) hien khong chay." -ForegroundColor Gray
}

# 2. Dung Flow CDP Daemon (Port 8879)
$conn8879 = Get-NetTCPConnection -State Listen -LocalPort 8879 -ErrorAction SilentlyContinue
if($conn8879){
    $procId = $conn8879.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if($proc -and $proc.CommandLine -match '(?i)(videostudio[\\/]cdp_daemon\.py|-m\s+videostudio\.cdp_daemon)'){
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "[OK] Da tat Flow CDP Daemon (PID $procId, Port 8879)." -ForegroundColor Green
    } else {
        Write-Warning "Port 8879 dang mo boi PID $procId."
    }
} else {
    Write-Host "[--] Flow CDP Daemon (Port 8879) hien khong chay." -ForegroundColor Gray
}

# 3. Don dep tien trinh python con neu con sot
$orphans = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*videostudio.api:app*' -or $_.CommandLine -like '*videostudio.cdp_daemon*'
}
foreach($op in $orphans){
    Stop-Process -Id $op.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] Da dung tien trinh ton dong PID $($op.ProcessId)." -ForegroundColor Green
}

Write-Host "Hoan tat! He thong VideoStudio da duoc tat an toan." -ForegroundColor Cyan
exit 0

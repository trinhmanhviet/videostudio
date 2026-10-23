param([string]$EngineeringScope='', [switch]$RestartOwnServer)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
if($EngineeringScope -and $EngineeringScope -notmatch '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'){throw 'Invalid exact engineering scope'}
$existing=Get-NetTCPConnection -State Listen -LocalPort 8877 -ErrorAction SilentlyContinue
if($existing){
 if(-not $RestartOwnServer){throw 'Port 8877 is already in use; nothing changed'}
 $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($existing.OwningProcess)"
 if($process.CommandLine -notlike '*videostudio.api:app*'){throw 'Port is not owned by VideoStudio; refusing to stop it'}
 Push-Location $root
 try{$active=& python (Join-Path $PSScriptRoot 'active_jobs.py')}finally{Pop-Location}
 if($LASTEXITCODE -ne 0 -or [int]$active -gt 0){throw 'Cannot restart while a generation job is active'}
 Stop-Process -Id $existing.OwningProcess
}
if($EngineeringScope){$env:VS_ENGINEERING_SCOPE=$EngineeringScope}else{Remove-Item Env:VS_ENGINEERING_SCOPE -ErrorAction SilentlyContinue}
$env:VS_LLM_TRANSPORT='chrome'
New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null
$process=Start-Process python -ArgumentList '-m','uvicorn','videostudio.api:app','--host','127.0.0.1','--port','8877' -WorkingDirectory $root -RedirectStandardOutput (Join-Path $root 'data/server.out.log') -RedirectStandardError (Join-Path $root 'data/server.err.log') -WindowStyle Hidden -PassThru
Write-Output "VideoStudio local started, PID $($process.Id). Production remains gated; engineering exception is exact-scope only."


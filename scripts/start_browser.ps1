param([switch]$RestartOwnDaemon, [switch]$ServiceOnly)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$python=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}
$existing=Get-NetTCPConnection -State Listen -LocalPort 8879 -ErrorAction SilentlyContinue
if($existing -and $RestartOwnDaemon){
 $proc=Get-CimInstance Win32_Process -Filter "ProcessId=$($existing.OwningProcess)"
 if($proc.CommandLine -notmatch '(?i)(videostudio[\\/]cdp_daemon\.py|-m\s+videostudio\.cdp_daemon)'){
  throw 'Port 8879 is not the owned VideoStudio CDP daemon; nothing stopped.'
 }
 Push-Location $root
 try{$active=& $python (Join-Path $PSScriptRoot 'active_jobs.py')}finally{Pop-Location}
 if($LASTEXITCODE -ne 0 -or [int]$active -gt 0){throw 'Active jobs exist; refusing daemon restart.'}
 Stop-Process -Id $existing.OwningProcess
 $existing=$null
}
if(-not $existing){
 New-Item -ItemType Directory -Force -Path (Join-Path $root 'data') | Out-Null
 Start-Process $python -ArgumentList '-u','-m','videostudio.cdp_daemon' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'data/cdp.out.log') -RedirectStandardError (Join-Path $root 'data/cdp.err.log') | Out-Null
}
$deadline=(Get-Date).AddSeconds(10)
$ready=$false
while((Get-Date) -lt $deadline){
 try{
  $health=Invoke-RestMethod 'http://127.0.0.1:8879/api/status' -TimeoutSec 1
  if($health.service -ne 'videostudio-dedicated-cdp'){throw 'Old daemon or another service owns port 8879. Explicit safe restart required.'}
  $ready=$true;break
 }catch{
  if($existing){throw 'Existing daemon is not the dedicated version; use -RestartOwnDaemon after checking active jobs.'}
  Start-Sleep -Milliseconds 200
 }
}
if(-not $ready){throw 'Dedicated CDP daemon did not start. See data/cdp.err.log.'}
if(-not $ServiceOnly){
 $result=Invoke-RestMethod 'http://127.0.0.1:8879/api/browser/start' -Method Post -ContentType 'application/json' -Headers @{'X-VS-Client'='videostudio'} -Body '{}' -TimeoutSec 35
 Write-Output ('Dedicated Chrome connected: '+$result.connected+'; authentication: '+$result.authentication)
 Write-Output 'Sign in to ChatGPT in the dedicated window. Personal Chrome was not changed.'
}else{Write-Output 'Dedicated browser service ready. Health polling does not open Chrome.'}

$ErrorActionPreference='Stop'
$script:StartupRoot=Split-Path $PSScriptRoot -Parent
$script:StartupPython=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}

function Get-StartupJson([string]$Url){
 try{return Invoke-RestMethod $Url -TimeoutSec 2}catch{return $null}
}
function Test-StartupListener([int]$Port){
 return @((Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)).Count -gt 0
}
function Test-StartupResponse($Response,[string]$Kind){
 if($null -eq $Response){return $false}
 if($Kind -eq 'server'){return $Response.service -eq 'videostudio' -and $Response.status -eq 'ok'}
 if($Kind -eq 'browser'){return $Response.service -eq 'videostudio-dedicated-cdp'}
 if($Kind -eq 'comfy'){return $null -ne $Response.system -and $null -ne $Response.devices}
 return $false
}
function Wait-StartupService([string]$Url,[string]$Kind,[int]$Seconds){
 $deadline=(Get-Date).AddSeconds($Seconds)
 do{
  $response=Get-StartupJson $Url
  if(Test-StartupResponse $response $Kind){return $response}
  Start-Sleep -Milliseconds 500
 }while((Get-Date) -lt $deadline)
 throw "$Kind did not become ready. See data\startup.log and the service logs."
}
function Invoke-StartupScript([string]$Name){
 & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot $Name) | ForEach-Object {Write-Host $_}
 if($LASTEXITCODE -ne 0){throw "$Name failed. See data\server.err.log or data\cdp.err.log."}
}
function Ensure-StartupServer{
 $health=Get-StartupJson 'http://localhost:8877/api/health'
 if(-not (Test-StartupResponse $health 'server')){
  if(Test-StartupListener 8877){throw 'Port 8877 is occupied but VideoStudio is not ready. No process was stopped; wait and run this launcher again.'}
  Invoke-StartupScript 'start_extension.ps1'
  $health=Wait-StartupService 'http://localhost:8877/api/health' 'server' 30
 }
 if($health.text_transport -ne 'extension'){throw 'The running server is not using extension bridge. It was left running; do not restart it while a video is active.'}
 Write-Host '[OK] VideoStudio server (extension bridge).'
}
function Ensure-StartupBrowser{
 $status=Get-StartupJson 'http://127.0.0.1:8879/api/status'
 if((Test-StartupResponse $status 'browser') -and $status.connected){
  Write-Host '[OK] Flow browser is already connected.';return
 }
 Invoke-StartupScript 'start_browser.ps1'
 $status=Wait-StartupService 'http://127.0.0.1:8879/api/status' 'browser' 15
 if(-not $status.connected){throw 'Flow browser is not connected. See data\cdp.err.log.'}
 Write-Host '[OK] Dedicated browser for Flow.'
}
function Get-ComfyStartupState{
 $raw=& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'comfy_host_state.ps1')
 if($LASTEXITCODE -ne 0){throw 'Cannot check existing Comfy process; no duplicate will be started.'}
 return ($raw | ConvertFrom-Json)
}
function Invoke-ComfyStartup{
 & $script:StartupPython (Join-Path $PSScriptRoot 'start_comfy_recovery.py') | ForEach-Object {Write-Host $_}
 return $LASTEXITCODE
}
function Ensure-StartupComfy{
 $url='http://127.0.0.1:8188/system_stats'
 if(Test-StartupResponse (Get-StartupJson $url) 'comfy'){
  Write-Host '[OK] ComfyUI is already running.';return
 }
 $state=Get-ComfyStartupState
 if($state.listening -eq $false -and $null -ne $state.comfy_process_ids -and @($state.comfy_process_ids).Count -eq 0){
  Write-Host '[...] Starting ComfyUI with the existing recovery launcher.'
  $code=Invoke-ComfyStartup
  if($code -ne 0){
   # shell:startup may win the race after our absent-process check.
   $state=Get-ComfyStartupState
   if(-not $state.listening -and @($state.comfy_process_ids).Count -eq 0){throw 'Comfy launcher failed. See data\comfy-recovery\startup.log.'}
  }
 }elseif($state.listening -eq $true -or @($state.comfy_process_ids).Count -gt 0){
  Write-Host '[...] ComfyUI is starting or not ready; waiting without opening another copy.'
 }else{throw 'Comfy process state is unknown; no duplicate will be started.'}
 Wait-StartupService $url 'comfy' 180 | Out-Null
 Write-Host '[OK] ComfyUI is ready.'
}
function Open-StartupStudio{
 $candidates=@("$env:ProgramFiles\Google\Chrome\Application\chrome.exe","${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe","$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe")
 $chrome=$candidates | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
 if(-not $chrome){throw 'Google Chrome was not found. Open http://localhost:8877/ in your ordinary Chrome.'}
 Start-Process -FilePath $chrome -ArgumentList 'http://localhost:8877/'
}
function Start-VideoStudioSystem{
 $mutex=New-Object System.Threading.Mutex($false,'Local\VideoStudio.Startup.8877')
 $locked=$false;$transcript=$false
 try{
  try{$locked=$mutex.WaitOne(0)}catch [System.Threading.AbandonedMutexException]{$locked=$true}
  if(-not $locked){Write-Host 'VideoStudio startup is already in progress. Please wait.';return 0}
  New-Item -ItemType Directory -Force -Path (Join-Path $script:StartupRoot 'data') | Out-Null
  Start-Transcript -Path (Join-Path $script:StartupRoot 'data/startup.log') -Append | Out-Null
  $transcript=$true;$failed=$false;$serverReady=$false
  Write-Host 'Starting VideoStudio. Existing services and video jobs will be preserved.'
  try{Ensure-StartupServer;$serverReady=$true}catch{Write-Host ('[ERROR] '+$_.Exception.Message) -ForegroundColor Red;$failed=$true}
  try{Ensure-StartupBrowser}catch{Write-Host ('[ERROR] '+$_.Exception.Message) -ForegroundColor Red;$failed=$true}
  try{Ensure-StartupComfy}catch{Write-Host ('[ERROR] '+$_.Exception.Message) -ForegroundColor Red;$failed=$true}
  if($serverReady){try{Open-StartupStudio}catch{Write-Host ('[ERROR] '+$_.Exception.Message) -ForegroundColor Red;$failed=$true}}
  Write-Host 'In ordinary Chrome: keep Studio open. If disconnected, press Start in the floating panel, then Test chu.'
  if($failed){Write-Host 'Some components need attention. Log: data\startup.log';return 1}
  Write-Host 'Services ready. Google/ChatGPT sign-in may still need your action.'
  return 0
 }finally{
  if($transcript){Stop-Transcript | Out-Null}
  if($locked){$mutex.ReleaseMutex()}
  $mutex.Dispose()
 }
}
if($MyInvocation.InvocationName -ne '.'){
 try{exit (Start-VideoStudioSystem)}catch{Write-Host ('[ERROR] '+$_.Exception.Message) -ForegroundColor Red;exit 1}
}

param([switch]$Prepare)
$ErrorActionPreference='Stop'
$script:RestartRoot=Split-Path $PSScriptRoot -Parent
function Get-RestartBootId {
 return (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
}
function Get-RestartHealth([string]$Url){
 try{return Invoke-RestMethod $Url -TimeoutSec 3}catch{return $null}
}
function Invoke-RestartCheck([bool]$PrepareCheck){
 $folder=Join-Path $script:RestartRoot 'data'
 New-Item -ItemType Directory -Force -Path $folder | Out-Null
 $baseline=Join-Path $folder 'restart-baseline.json'
 $boot=Get-RestartBootId
 if($PrepareCheck){
  @{boot_id=$boot;prepared_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $baseline -Encoding UTF8
  Write-Output 'Restart check prepared. After reboot, open VideoStudio.exe and click Mo he thong.'
  return
 }
 if(-not(Test-Path -LiteralPath $baseline)){throw 'Prepare restart acceptance first: scripts/check_restart.ps1 -Prepare'}
 $before=Get-Content -LiteralPath $baseline -Raw -Encoding UTF8 | ConvertFrom-Json
 $server=Get-RestartHealth 'http://127.0.0.1:8877/api/health'
 $flow=Get-RestartHealth 'http://127.0.0.1:8879/api/status'
 $comfy=Get-RestartHealth 'http://127.0.0.1:8188/system_stats'
 $checks=@{
  reboot_confirmed=($before.boot_id -ne $boot)
  studio=($null -ne $server -and $server.service -eq 'videostudio' -and $server.status -eq 'ok' -and $server.text_transport -eq 'extension')
  flow=($null -ne $flow -and $flow.service -eq 'videostudio-dedicated-cdp' -and $flow.connected -eq $true)
  comfy=($null -ne $comfy -and $null -ne $comfy.system -and $null -ne $comfy.devices)
 }
 $passed=$checks.reboot_confirmed -and $checks.studio -and $checks.flow -and $checks.comfy
 $record=@{scope='service_startup_only';passed=$passed;checks=$checks;boot_id=$boot;checked_at=[DateTime]::UtcNow.ToString('o');video_acceptance='pending'}
 $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $folder 'restart-acceptance.json') -Encoding UTF8
 if($passed){Write-Output 'PASS restart: Studio, Flow and Comfy ready on a new Windows boot.'}
 elseif(-not $checks.reboot_confirmed){Write-Output 'Restart acceptance pending: Windows has not rebooted yet.'}
 else{Write-Output 'Restart acceptance needs attention. See data/restart-acceptance.json.'}
 return $record
}
if($MyInvocation.InvocationName -ne '.'){
 try{Invoke-RestartCheck ([bool]$Prepare) | Out-String | Write-Output;exit 0}catch{Write-Error $_;exit 1}
}

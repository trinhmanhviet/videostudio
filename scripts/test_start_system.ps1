$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'start_system.ps1')
function Assert-True($Value,$Message){if(-not $Value){throw $Message}}
$script:calls=@();$script:mode='ready'
function Get-StartupJson($Url){
 if($Url -like '*8877*'){
  if($script:mode -eq 'wrong-transport'){return @{service='videostudio';text_transport='cdp';status='ok'}}
  if($script:mode -eq 'server-absent' -and $script:calls -notcontains 'start_extension.ps1'){return $null}
  return @{service='videostudio';text_transport='extension';status='ok'}
 }
 if($Url -like '*8188*'){
  if($script:mode -in @('comfy-booting','comfy-absent')){return $null}
  return @{system=@{};devices=@()}
 }
 return @{service='videostudio-dedicated-cdp';connected=($script:mode -ne 'browser-disconnected' -or $script:calls -contains 'start_browser.ps1')}
}
function Test-StartupListener($Port){return $script:mode -eq 'foreign-port'}
function Invoke-StartupScript($Name){$script:calls+= $Name}
function Wait-StartupService($Url,$Kind,$Seconds){$script:calls+='wait-'+$Kind;return @{service='videostudio';status='ok';text_transport='extension';connected=$true}}
function Get-ComfyStartupState{if($script:mode -eq 'comfy-booting'){return @{listening=$true;comfy_process_ids=@(123)}};return @{listening=$false;comfy_process_ids=@()}}
function Invoke-ComfyStartup{$script:calls+='start-comfy';if($script:mode -eq 'comfy-race'){$script:mode='comfy-booting';return 1};return 0}

Ensure-StartupServer
Ensure-StartupBrowser
Ensure-StartupComfy
Assert-True ($script:calls.Count -eq 0) 'Healthy services must be reused without starting anything'
Write-Output 'PASS reuse running services'
$script:mode='server-absent';Ensure-StartupServer
Assert-True ($script:calls -contains 'start_extension.ps1') 'Missing server must start in extension mode'
Write-Output 'PASS start missing server'
$script:mode='wrong-transport';$blocked=$false
try{Ensure-StartupServer}catch{$blocked=$true}
Assert-True $blocked 'An incompatible live server must not be reused or restarted'
Write-Output 'PASS refuse incompatible live server'
$script:mode='comfy-booting';$script:calls=@();Ensure-StartupComfy
Assert-True ($script:calls.Count -eq 1 -and $script:calls[0] -eq 'wait-comfy') 'Booting Comfy must be awaited, never launched again'
Write-Output 'PASS wait for Startup Comfy'
$script:mode='comfy-absent';$script:calls=@();Ensure-StartupComfy
Assert-True ($script:calls -contains 'start-comfy') 'Absent Comfy must use the existing recovery launcher'
Write-Output 'PASS launch absent Comfy'
$script:mode='browser-disconnected';$script:calls=@();Ensure-StartupBrowser
Assert-True ($script:calls -contains 'start_browser.ps1') 'Disconnected browser must use the existing browser launcher'
Write-Output 'PASS reconnect browser'
$script:mode='comfy-race';$script:calls=@()
# Force the initial HTTP probe to miss a service which starts concurrently.
function Get-StartupJson($Url){return $null}
Ensure-StartupComfy
Assert-True ($script:calls.Count -eq 2 -and $script:calls -contains 'wait-comfy') 'Concurrent Startup Comfy must be awaited after recovery refuses a duplicate'
Write-Output 'PASS concurrent Comfy startup'
$script:mode='foreign-port';$script:calls=@()
$blocked=$false;try{Ensure-StartupServer}catch{$blocked=$true}
Assert-True ($blocked -and $script:calls.Count -eq 0) 'Foreign port must never trigger a server start'
Write-Output 'PASS refuse occupied port'

$originalRoot=$script:StartupRoot
$script:StartupRoot=Join-Path $originalRoot ('data/test-start-system/'+[guid]::NewGuid().ToString())
$script:calls=@()
function Ensure-StartupServer{$script:calls+='server'}
function Ensure-StartupBrowser{$script:calls+='browser'}
function Ensure-StartupComfy{$script:calls+='comfy'}
function Open-StartupStudio{$script:calls+='open-studio'}
$code=Start-VideoStudioSystem
Assert-True ($code -eq 0 -and ($script:calls -join ',') -eq 'server,browser,comfy,open-studio') 'One click must start all components and open Studio'
Write-Output 'PASS one-click orchestration and mutex'
$script:calls=@()
function Ensure-StartupComfy{throw 'Fixture Comfy failure'}
$code=Start-VideoStudioSystem
Assert-True ($code -eq 1 -and $script:calls -contains 'open-studio') 'A Comfy failure must be visible while still opening the working Studio'
Write-Output 'PASS partial failure remains visible'

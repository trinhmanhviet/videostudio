$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '..\check_restart.ps1')
$script:RestartRoot=Join-Path (Split-Path $PSScriptRoot -Parent) ('../../data/test-tmp/restart-check-tests/'+[guid]::NewGuid().ToString()+'/app')
$script:FixtureBoot='boot-one';$script:FlowConnected=$true
function Get-RestartBootId{return $script:FixtureBoot}
function Get-RestartHealth([string]$Url){
 if($Url -like '*8877*'){return @{service='videostudio';status='ok';text_transport='extension'}}
 if($Url -like '*8879*'){return @{service='videostudio-dedicated-cdp';connected=$script:FlowConnected}}
 return @{system=@{};devices=@(@{name='fixture'})}
}
Invoke-RestartCheck $true | Out-Null
$record=Invoke-RestartCheck $false | Select-Object -Last 1
if($record.passed -or $record.checks.reboot_confirmed){throw 'Same boot must never count as reboot acceptance'}
Write-Output 'PASS same boot remains pending'
$script:FixtureBoot='boot-two'
$record=Invoke-RestartCheck $false | Select-Object -Last 1
if(-not $record.passed -or $record.scope -ne 'service_startup_only'){throw 'New boot and ready services should pass service acceptance'}
Write-Output 'PASS new boot with ready services'
$script:FlowConnected=$false
$record=Invoke-RestartCheck $false | Select-Object -Last 1
if($record.passed){throw 'Disconnected Flow must fail acceptance'}
Write-Output 'PASS missing service stays visible'

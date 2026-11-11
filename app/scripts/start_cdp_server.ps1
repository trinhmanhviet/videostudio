param([switch]$RestartOwnServer)
$ErrorActionPreference='Stop'
# ChatGPT text through the dedicated Chrome (CDP daemon on 8879); start_local starts that browser service too.
& (Join-Path $PSScriptRoot 'start_local.ps1') -TextTransport cdp -RestartOwnServer:$RestartOwnServer
Write-Output 'VideoStudio uses ChatGPT in the dedicated Chrome (CDP). Keep that Chrome signed in to ChatGPT.'

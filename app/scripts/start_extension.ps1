param([switch]$RestartOwnServer)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'start_local.ps1') -TextTransport extension -RestartOwnServer:$RestartOwnServer
Write-Output 'Open http://localhost:8877/ in ordinary Chrome with VideoStudio ChatGPT Bridge enabled. The launcher connects and checks ChatGPT automatically.'

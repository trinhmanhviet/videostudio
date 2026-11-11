param([Parameter(Mandatory=$true)][string]$ProfilePath,[Parameter(Mandatory=$true)][string]$ChromeExe,[ValidateSet('inspect','stop')][string]$Action='inspect',[int]$ExpectedProcessId=0,[string]$ExpectedCreated='',[ValidateRange(1024,65535)][int]$DebugPort=19223)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$profileFull=[System.IO.Path]::GetFullPath($ProfilePath).TrimEnd('\')
$exeFull=[System.IO.Path]::GetFullPath($ChromeExe)
$escapedProfile=[regex]::Escape($profileFull)
$profileFlag='(?i)(?:^|\s)(?:"--user-data-dir='+$escapedProfile+'"|--user-data-dir="'+$escapedProfile+'"|--user-data-dir='+$escapedProfile+')(?=\s|$)'
# Failure to inspect sockets must not be treated as proof that a port is free.
$script:listenerRows=@(Get-NetTCPConnection -State Listen -ErrorAction Stop)
function Read-OwnedChrome{
 $found=@()
 foreach($candidateProcess in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $command=$candidateProcess.CommandLine
  if(-not $command -or $command -match '(?i)(?:^|\s)"?--type(?:=|\s)' -or $command -notmatch $profileFlag){continue}
  if(([regex]::Matches($command,'(?i)--user-data-dir(?:=|\s)')).Count -ne 1 -or $candidateProcess.ExecutablePath -ne $exeFull){throw 'Chrome profile ownership is ambiguous; no process changed.'}
  $debugMatches=[regex]::Matches($command,'(?i)(?:^|\s)"?--remote-debugging-port=(\d+)"?(?=\s|$)')
  if($debugMatches.Count -gt 1){throw 'Chrome debug port is ambiguous; no process changed.'}
  $declaredPort=$null;$cdpPort=$null;$listenerOwned=$false
  if($debugMatches.Count -eq 1){
   $declaredPort=[int]$debugMatches[0].Groups[1].Value
   $cdpPort=$declaredPort
   if($declaredPort -eq 0){
    $portFile=Join-Path $profileFull 'DevToolsActivePort'
    if(Test-Path -LiteralPath $portFile){
     $lines=@(Get-Content -LiteralPath $portFile)
     $legacyPort=0
     if($lines.Count -ge 2 -and [int]::TryParse($lines[0],[ref]$legacyPort)){$cdpPort=$legacyPort}
    }
   }
   $listeners=@($script:listenerRows | Where-Object {$_.LocalPort -eq $cdpPort})
   $foreign=@($listeners | Where-Object {$_.OwningProcess -ne $candidateProcess.ProcessId -or $_.LocalAddress -notin @('127.0.0.1','::1')})
   $listenerOwned=$cdpPort -gt 0 -and $cdpPort -le 65535 -and $listeners.Count -gt 0 -and $foreign.Count -eq 0
  }
  $found+=@{pid=[int]$candidateProcess.ProcessId;created=$candidateProcess.CreationDate.ToUniversalTime().ToString('o');mode=$(if($debugMatches.Count -eq 1){'debug'}else{'clean'});debug_port=$declaredPort;cdp_port=$cdpPort;cdp_listener_owned=[bool]$listenerOwned}
 }
 return $found
}
$ownedProcesses=@(Read-OwnedChrome)
if($Action -eq 'stop'){
 if($ownedProcesses.Count -ne 1 -or $ownedProcesses[0].pid -ne $ExpectedProcessId -or $ownedProcesses[0].created -ne $ExpectedCreated){throw 'Owned Chrome process changed; no process stopped.'}
 $targetProcess=Get-Process -Id $ExpectedProcessId
 [void]$targetProcess.CloseMainWindow()
 if(-not $targetProcess.WaitForExit(8000)){
  $confirmed=@(Read-OwnedChrome)
  if($confirmed.Count -ne 1 -or $confirmed[0].pid -ne $ExpectedProcessId -or $confirmed[0].created -ne $ExpectedCreated){throw 'Chrome process identity changed while closing.'}
  Stop-Process -Id $ExpectedProcessId
  if(-not $targetProcess.WaitForExit(5000)){throw 'Owned Chrome did not exit.'}
 }
 $ownedProcesses=@(Read-OwnedChrome)
 if($ownedProcesses.Count){throw 'Chrome profile is still running; no replacement launched.'}
 $script:listenerRows=@(Get-NetTCPConnection -State Listen -ErrorAction Stop)
}
@{processes=@($ownedProcesses);port_in_use=[bool](@($script:listenerRows | Where-Object {$_.LocalPort -eq $DebugPort}).Count -gt 0)} | ConvertTo-Json -Depth 4 -Compress

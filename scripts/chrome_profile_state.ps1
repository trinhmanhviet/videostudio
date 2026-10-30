param([Parameter(Mandatory=$true)][string]$ProfilePath,[Parameter(Mandatory=$true)][string]$ChromeExe,[ValidateSet('inspect','stop')][string]$Action='inspect',[int]$ExpectedProcessId=0,[string]$ExpectedCreated='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$profileFull=[System.IO.Path]::GetFullPath($ProfilePath).TrimEnd('\')
$exeFull=[System.IO.Path]::GetFullPath($ChromeExe)
$escapedProfile=[regex]::Escape($profileFull)
$profileFlag='(?i)(?:^|\s)(?:"--user-data-dir='+$escapedProfile+'"|--user-data-dir="'+$escapedProfile+'"|--user-data-dir='+$escapedProfile+')(?=\s|$)'
function Read-OwnedChrome{
 $found=@()
 foreach($candidateProcess in @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'")){
  $command=$candidateProcess.CommandLine
  if(-not $command -or $command -match '(?i)(?:^|\s)"?--type(?:=|\s)' -or $command -notmatch $profileFlag){continue}
  if(([regex]::Matches($command,'(?i)--user-data-dir(?:=|\s)')).Count -ne 1 -or $candidateProcess.ExecutablePath -ne $exeFull){throw 'Chrome profile ownership is ambiguous; no process changed.'}
  $found+=@{pid=[int]$candidateProcess.ProcessId;created=$candidateProcess.CreationDate.ToUniversalTime().ToString('o');mode=$(if($command -match '(?i)--remote-debugging-port='){'debug'}else{'clean'})}
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
}
@{processes=@($ownedProcesses)} | ConvertTo-Json -Depth 4 -Compress

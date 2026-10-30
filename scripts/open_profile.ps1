param([ValidateSet('clean','debug','stop')][string]$Mode='clean')
$ErrorActionPreference='Stop'
$taskWorkspace=Split-Path $PSScriptRoot -Parent
$taskPython=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}
Push-Location $taskWorkspace
try{& $taskPython -m videostudio.browser_manager $Mode;$taskExit=$LASTEXITCODE}finally{Pop-Location}
exit $taskExit

$ErrorActionPreference='Stop'
$connections=@(Get-NetTCPConnection -State Listen -LocalPort 8188 -ErrorAction SilentlyContinue)
$processes=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {$_.CommandLine -match 'ComfyUI[\\/]main\.py'})
$epoch=[datetime]'1970-01-01'
@{listening=($connections.Count -gt 0);comfy_process_ids=@($processes | ForEach-Object {[int]$_.ProcessId});comfy_started_unix=@($processes | ForEach-Object {[double]($_.CreationDate.ToUniversalTime()-$epoch).TotalSeconds})} | ConvertTo-Json -Compress

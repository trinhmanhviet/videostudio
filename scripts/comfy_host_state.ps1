$ErrorActionPreference='Stop'
$connections=@(Get-NetTCPConnection -State Listen -LocalPort 8188 -ErrorAction SilentlyContinue)
$processes=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {$_.CommandLine -match 'ComfyUI[\\/]main\.py'})
@{listening=($connections.Count -gt 0);comfy_process_ids=@($processes | ForEach-Object {[int]$_.ProcessId})} | ConvertTo-Json -Compress

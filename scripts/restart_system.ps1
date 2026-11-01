param([switch]$Force)
$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Đang dừng các dịch vụ..."
if ($Force) {
    & "$ScriptDir\stop_system.ps1" -Force
} else {
    & "$ScriptDir\stop_system.ps1"
}
if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
Start-Sleep -Seconds 1
Write-Host "Đang khởi động lại dịch vụ..."
& "$ScriptDir\start_system.ps1"

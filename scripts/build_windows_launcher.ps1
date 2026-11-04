$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$python=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}
# A running tray app keeps VideoStudio.exe locked; quit it first (right click the tray icon -> Thoat khay).
$running=Get-Process -Name VideoStudio -ErrorAction SilentlyContinue | Where-Object { $_.Path -and ((Resolve-Path $_.Path).Path -eq (Join-Path $root 'VideoStudio.exe')) }
if($running){throw 'VideoStudio.exe dang chay o khay he thong. Chuot phai bieu tuong -> "Thoat khay" roi build lai (video van chay binh thuong).'}
$assets=Join-Path $PSScriptRoot 'assets'
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name VideoStudio `
  --icon (Join-Path $assets 'videostudio.ico') --add-data ($assets+';assets') `
  --paths $PSScriptRoot --hidden-import tray_app --hidden-import windows_tray --hidden-import windows_integration `
  --distpath $root --workpath (Join-Path $root 'build/launcher') --specpath (Join-Path $root 'build') (Join-Path $PSScriptRoot 'windows_launcher.py')
if($LASTEXITCODE -ne 0){throw 'Windows launcher build failed. Install pyinstaller in the selected Python environment.'}
Write-Output ('Built: '+(Join-Path $root 'VideoStudio.exe'))

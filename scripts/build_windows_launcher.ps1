$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$python=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name VideoStudio --distpath $root --workpath (Join-Path $root 'build/launcher') --specpath (Join-Path $root 'build') (Join-Path $PSScriptRoot 'windows_launcher.py')
if($LASTEXITCODE -ne 0){throw 'Windows launcher build failed. Install pyinstaller in the selected Python environment.'}
Write-Output ('Built: '+(Join-Path $root 'VideoStudio.exe'))

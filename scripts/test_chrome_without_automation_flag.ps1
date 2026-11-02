param([switch]$ShowCommandOnly,[ValidateRange(1024,65535)][int]$DebugPort=19223)
$ErrorActionPreference='Stop'
$taskWorkspace=Split-Path $PSScriptRoot -Parent
$taskPython=if(Test-Path 'C:\Python312\python.exe'){'C:\Python312\python.exe'}else{(Get-Command python).Source}
$taskMode=if($ShowCommandOnly){'preview'}else{'start'}
Push-Location $taskWorkspace
try {
    if(-not $ShowCommandOnly){
        if(Get-NetTCPConnection -State Listen -LocalPort $DebugPort -ErrorAction SilentlyContinue){
            throw "Port $DebugPort is occupied; no browser changed. Use another -DebugPort or close your previous test Chrome."
        }
        Write-Host 'Closing only the VideoStudio Chrome profile. Active video/image jobs prevent this test.'
        & $taskPython -m videostudio.browser_manager stop
        if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    }
    @'
import asyncio, json, subprocess, sys, time, urllib.request
from urllib.parse import urlparse
import websockets
from videostudio.chrome_browser import BrowserConfig

config = BrowserConfig()
original = config.arguments('debug')
port = int(sys.argv[2])
args = [f'--remote-debugging-port={port}' if arg.startswith('--remote-debugging-port=') else arg
        for arg in original if arg != '--enable-automation']
# The previous test already removed enable-automation. Now vary only the CDP port.
assert len(original) - len(args) in (0, 1)
assert '--enable-automation' not in args
assert '--remote-debugging-port=0' not in args
assert f'--remote-debugging-port={port}' in args
if sys.argv[1] == 'preview':
    print(json.dumps(args, ensure_ascii=True))
else:
    if not config.executable.is_file():
        raise RuntimeError('Chrome executable not found')
    config.profile.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
    print(f'Test Chrome opened: same profile, fixed local CDP port {port}, without --enable-automation.', flush=True)
    # Read the browser's actual value. Do not override navigator or inject fingerprint patches.
    async def inspect_webdriver():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=1) as response:
                    pages = json.load(response)
                candidates = [page for page in pages if page.get('type') == 'page'
                              and urlparse(page.get('url', '')).hostname == 'flow.google.com']
                if candidates:
                    ws = candidates[0]['webSocketDebuggerUrl']
                    endpoint = urlparse(ws)
                    if endpoint.scheme != 'ws' or endpoint.hostname not in ('127.0.0.1', 'localhost') or endpoint.port != port:
                        raise RuntimeError('Unexpected diagnostic endpoint')
                    async with websockets.connect(ws, open_timeout=2) as connection:
                        await connection.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                            'params': {'expression': 'navigator.webdriver', 'returnByValue': True}}))
                        while True:
                            reply = json.loads(await asyncio.wait_for(connection.recv(), timeout=3))
                            if reply.get('id') == 1:
                                if 'error' in reply or reply.get('result', {}).get('exceptionDetails'):
                                    raise RuntimeError('Could not inspect browser value')
                                value = reply.get('result', {}).get('result', {}).get('value')
                                print('Observed navigator.webdriver = ' + json.dumps(value), flush=True)
                                return
            except (OSError, ValueError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(.3)
        print('Could not read navigator.webdriver; generation success is not confirmed.', flush=True)
    asyncio.run(inspect_webdriver())
    print('Manually create ONE image in Flow. Do not retry a video job in this test mode.')
    print('To restore normal tool control: run Chrome - Stop.cmd, then Chrome - Debug.cmd.')
'@ | & $taskPython - $taskMode $DebugPort
    $taskExit=$LASTEXITCODE
} finally {Pop-Location}
exit $taskExit

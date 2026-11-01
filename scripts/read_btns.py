import urllib.request, json, asyncio, websockets, sys
sys.stdout.reconfigure(encoding='utf-8')

async def check():
    req = urllib.request.Request('http://127.0.0.1:55935/json/list')
    with urllib.request.urlopen(req) as r: targets = json.loads(r.read().decode())
    page = next(t for t in targets if t.get('type') == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        js = """(()=>{
            const btns = [...document.querySelectorAll('button')].map(b => ({
                text: (b.innerText||'').trim(),
                aria: b.getAttribute('aria-label'),
                disabled: b.disabled
            }));
            return btns;
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
        res = json.loads(await ws.recv())
        print(json.dumps(res.get('result', {}).get('result', {}).get('value'), indent=2, ensure_ascii=False))

asyncio.run(check())

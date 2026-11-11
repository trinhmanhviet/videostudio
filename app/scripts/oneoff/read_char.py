import urllib.request, json, asyncio, websockets, sys
sys.stdout.reconfigure(encoding='utf-8')

async def check():
    req = urllib.request.Request('http://127.0.0.1:55935/json/list')
    with urllib.request.urlopen(req) as r: targets = json.loads(r.read().decode())
    page = next(t for t in targets if t.get('type') == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        js = """(()=>{
            const imgs = [...document.querySelectorAll('img')].map(i => ({src: i.src.slice(0, 50), w: i.naturalWidth, h: i.naturalHeight}));
            const text = (document.querySelector('[role="textbox"]')||{}).innerText || '';
            const inputs = [...document.querySelectorAll('input')].map(i => ({val: i.value, ph: i.placeholder}));
            const spinners = [...document.querySelectorAll('mat-spinner, [role="progressbar"], .loading')];
            return {
                url: location.href,
                imgs: imgs,
                inputs: inputs,
                spinnersCount: spinners.length,
                promptTextLength: text.length
            };
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
        res = json.loads(await ws.recv())
        print(json.dumps(res.get('result', {}).get('result', {}).get('value'), indent=2, ensure_ascii=False))

asyncio.run(check())

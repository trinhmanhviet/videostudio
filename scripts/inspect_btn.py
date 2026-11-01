import urllib.request, json, asyncio, websockets, sys
sys.stdout.reconfigure(encoding='utf-8')

async def check():
    req = urllib.request.Request('http://127.0.0.1:55935/json/list')
    with urllib.request.urlopen(req) as r: targets = json.loads(r.read().decode())
    page = next(t for t in targets if t.get('type') == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        js = """(()=>{
            const btn = document.querySelector('button[aria-label="Bắt đầu tạo"]') || 
                        [...document.querySelectorAll('button')].find(b => (b.innerText||'').trim() === 'arrow_forward');
            if (!btn) return {found: false};
            
            // Check if there are any overlays covering the button
            const r = btn.getBoundingClientRect();
            const cx = r.x + r.width/2, cy = r.y + r.height/2;
            const topEl = document.elementFromPoint(cx, cy);
            
            return {
                found: true,
                disabled: btn.disabled,
                ariaDisabled: btn.getAttribute('aria-disabled'),
                outerHTML: btn.outerHTML,
                rect: {x: r.x, y: r.y, w: r.width, h: r.height},
                center: {cx, cy},
                topElementTag: topEl ? topEl.tagName : null,
                topElementHTML: topEl ? topEl.outerHTML.slice(0, 150) : null,
                isTopDescendant: topEl ? (btn === topEl || btn.contains(topEl)) : false
            };
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
        res = json.loads(await ws.recv())
        print(json.dumps(res.get('result', {}).get('result', {}).get('value'), indent=2, ensure_ascii=False))

asyncio.run(check())

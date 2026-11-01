import urllib.request, json, asyncio, websockets, sys
sys.stdout.reconfigure(encoding='utf-8')

async def check():
    req = urllib.request.Request('http://127.0.0.1:55935/json/list')
    with urllib.request.urlopen(req) as r: targets = json.loads(r.read().decode())
    page = next(t for t in targets if t.get('type') == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        # Move mouse and click
        x, y = 1219, 814
        await ws.send(json.dumps({'id': 1, 'method': 'Input.dispatchMouseEvent', 'params': {'type': 'mouseMoved', 'x': x, 'y': y}}))
        await ws.recv()
        await ws.send(json.dumps({'id': 2, 'method': 'Input.dispatchMouseEvent', 'params': {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1}}))
        await ws.recv()
        await ws.send(json.dumps({'id': 3, 'method': 'Input.dispatchMouseEvent', 'params': {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1}}))
        await ws.recv()
        print('Dispatched mouse click at (1219, 814)')

        # Poll URL and DOM for 10 seconds
        for i in range(10):
            await asyncio.sleep(1)
            await ws.send(json.dumps({'id': 10 + i, 'method': 'Runtime.evaluate', 'params': {'expression': 'location.href', 'returnByValue': True}}))
            res = json.loads(await ws.recv())
            u = res.get('result', {}).get('result', {}).get('value')
            print(f'Second {i+1}: URL = {u}')
            if '/character/' in u and u.rsplit('/', 1)[-1] != 'character':
                break

asyncio.run(check())

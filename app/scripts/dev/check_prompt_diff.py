import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
import urllib.request, json, asyncio, websockets
sys.stdout.reconfigure(encoding='utf-8')

# Read Charles prompt from job script
with open(r'E:\Videos\chuong-1-cai-chet-bi-an-00-00-00-30-canh-1-00-00-00-07-loi-t-20261101-111018\script.json', encoding='utf-8') as f:
    s = json.load(f)
from videostudio.providers import Pipeline
p = Pipeline.__new__(Pipeline)
charles = next(c for c in s['characters'] if c['character_id'] == 'charles')
expected_prompt = p._flow_portrait_prompt(charles).strip()
print('Expected prompt length:', len(expected_prompt))

async def check():
    req = urllib.request.Request('http://127.0.0.1:55935/json/list')
    with urllib.request.urlopen(req) as r: targets = json.loads(r.read().decode())
    page = next(t for t in targets if t.get('type') == 'page')
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        js = """(()=>{
            const el = document.querySelector('[role="textbox"]');
            return (el?.innerText||'').trim();
        })()"""
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
        res = json.loads(await ws.recv())
        actual = res.get('result', {}).get('result', {}).get('value')
        print('Actual in DOM length:', len(actual))
        print('Exact equal:', actual == expected_prompt)
        if actual != expected_prompt:
            import difflib
            print('Diff:', list(difflib.ndiff([actual], [expected_prompt])))

asyncio.run(check())

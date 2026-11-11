import urllib.request, json, asyncio, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from videostudio.cdp_protocol import CDPConnection

sys.stdout.reconfigure(encoding='utf-8')

async def inspect():
    tabs = json.loads(urllib.request.urlopen('http://127.0.0.1:19223/json/list').read())
    fb_tab = next((t for t in tabs if t.get('type') == 'page' and 'facebook.com' in t.get('url', '')), None)
    if not fb_tab:
        print('No FB tab')
        return
    cdp = CDPConnection()
    await cdp.connect(fb_tab['webSocketDebuggerUrl'])
    js = """(() => {
        const msgs = [...document.querySelectorAll('[data-ad-preview="message"]')].map(m => m.innerText.substring(0, 100));
        const el = document.scrollingElement || document.documentElement;
        return {
            scrollY: window.scrollY,
            scrollHeight: el.scrollHeight,
            count: msgs.length,
            samples: msgs.slice(-8)
        };
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': js, 'returnByValue': True})
    print(json.dumps(res.get('result', {}).get('value', {}), ensure_ascii=False, indent=2))
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(inspect())

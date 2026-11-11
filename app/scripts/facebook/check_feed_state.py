import asyncio
import json
import sys
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from videostudio.cdp_protocol import CDPConnection

async def main():
    tabs = json.loads(urllib.request.urlopen('http://127.0.0.1:19223/json/list').read())
    fb = next(t for t in tabs if 'facebook.com' in t.get('url', ''))
    cdp = CDPConnection()
    await cdp.connect(fb['webSocketDebuggerUrl'])

    expr = """(() => {
        const doc = document.scrollingElement || document.documentElement;
        const msgs = [...document.querySelectorAll('[data-ad-preview="message"]')];
        return {
            url: window.location.href,
            scrollY: Math.round(window.scrollY),
            scrollHeight: doc.scrollHeight,
            innerHeight: window.innerHeight,
            postCount: msgs.length,
            firstPost: msgs[0] ? msgs[0].innerText.slice(0, 50).replace(/\\n/g, ' ') : '',
            lastPost: msgs[msgs.length - 1] ? msgs[msgs.length - 1].innerText.slice(0, 50).replace(/\\n/g, ' ') : ''
        };
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    print(json.dumps(res.get('result', {}).get('value'), ensure_ascii=False, indent=2))
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(main())

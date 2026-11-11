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
    print('Current tab URL:', fb.get('url'))
    cdp = CDPConnection()
    await cdp.connect(fb['webSocketDebuggerUrl'])

    # Check theater dialog or photo viewer
    expr = """(() => {
        const theater = document.querySelector('[data-pagelet="MediaViewerRoot"], [data-pagelet="SnowliftRoot"], [aria-label="Close"], [aria-label="Đóng"]');
        const closeBtn = document.querySelector('div[aria-label="Close"], div[aria-label="Đóng"], div[aria-label="Press Esc to close"]');
        const isPhotoUrl = window.location.href.includes('/photo') || window.location.href.includes('theater');
        return {
            url: window.location.href,
            hasTheater: !!theater,
            hasCloseBtn: !!closeBtn,
            closeBtnLabel: closeBtn ? closeBtn.getAttribute('aria-label') : null
        };
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    print(json.dumps(res.get('result', {}).get('value'), ensure_ascii=False, indent=2))
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(main())

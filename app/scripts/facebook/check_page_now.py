import urllib.request, json, asyncio, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from videostudio.cdp_protocol import CDPConnection

async def main():
    tabs = json.loads(urllib.request.urlopen('http://127.0.0.1:19223/json/list').read())
    t = next(t for t in tabs if t.get('type') == 'page' and 'facebook.com' in t.get('url', ''))
    cdp = CDPConnection()
    await cdp.connect(t['webSocketDebuggerUrl'])
    
    expr = """(() => {
        const msgs = [...document.querySelectorAll('[data-ad-preview="message"]')];
        const spinners = document.querySelectorAll('[role="progressbar"], [data-visualcompletion="loading-state"]');
        return {
            scrollY: Math.round(window.scrollY),
            scrollHeight: document.documentElement.scrollHeight,
            innerHeight: window.innerHeight,
            isBottom: (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 60),
            spinnersCount: spinners.length,
            msgsCount: msgs.length,
            titles: msgs.map(m => m.innerText.trim().split('\\n')[0])
        };
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    print(json.dumps(res.get('result', {}).get('value', {}), ensure_ascii=False, indent=2))
    
    # Take screenshot of current view
    shot = await cdp.command('Page.captureScreenshot', {'format': 'png'})
    import base64
    (Path(__file__).resolve().parents[3]/'data/facebook_cases/debug-screens/current_view_after_scroll.png').write_bytes(base64.b64decode(shot['data']))
    
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(main())

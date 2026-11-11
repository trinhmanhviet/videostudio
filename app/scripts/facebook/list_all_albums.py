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
    
    url = "https://www.facebook.com/profile.php?id=61583850062328&sk=photos_albums"
    print(f"[*] Navigating to {url}...")
    await cdp.command('Page.navigate', {'url': url})
    await asyncio.sleep(4.0)
    
    # Scroll down multiple times to make sure all albums load
    for _ in range(5):
        await cdp.command('Page.captureScreenshot', {'format': 'jpeg', 'quality': 5, 'clip': {'x':0,'y':0,'width':8,'height':8,'scale':1}})
        await cdp.command('Runtime.evaluate', {'expression': 'window.scrollTo(0, document.documentElement.scrollHeight);'})
        await asyncio.sleep(1.0)
        
    expr = """(() => {
        const links = [...document.querySelectorAll('a')].filter(a => a.href && (a.href.includes('/media/set/') || a.href.includes('set=a.')));
        const map = new Map();
        for (const a of links) {
            const href = a.href;
            const text = a.innerText.trim().replace(/\\n+/g, ' - ');
            if (!map.has(href) || (text && !map.get(href))) {
                map.set(href, text);
            }
        }
        return [...map.entries()].map(([href, text]) => ({ href, text }));
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    albums = res.get('result', {}).get('value', [])
    print(f"Found {len(albums)} albums:")
    for a in albums:
        print(f" - {a['text']:35} | {a['href']}")
        
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(main())

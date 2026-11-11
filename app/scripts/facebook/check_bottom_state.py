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
        const spinners = document.querySelectorAll('[role="progressbar"], [data-visualcompletion="loading-state"]');
        const endOfResults = [...document.querySelectorAll('span, div')].filter(e => {
            const t = e.innerText.trim();
            return t === 'End of results' || t === 'Đã hết kết quả' || t === 'No more posts' || t.includes('hết bài viết');
        });
        
        return {
            spinnersCount: spinners.length,
            endOfResultsCount: endOfResults.length,
            endText: endOfResults.map(e => e.innerText.trim()),
            scrollY: Math.round(window.scrollY),
            scrollHeight: document.documentElement.scrollHeight
        };
    })()"""
    res = await cdp.command('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    print(json.dumps(res.get('result', {}).get('value', {}), ensure_ascii=False, indent=2))
    await cdp.close()

if __name__ == '__main__':
    asyncio.run(main())

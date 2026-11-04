"""Read-only: describe how ChatGPT currently renders generated images in the dedicated Chrome.

Open one ChatGPT conversation that contains a finished image in the VideoStudio Chrome, then run this.
Writes assets/Meme_Animation_Asset_Pack/new/_probe.json. Clicks nothing, sends nothing.
"""
import asyncio
import json
import os
from pathlib import Path

import aiohttp

PORT = int(os.getenv('VS_CHROME_DEBUG_PORT', '19223'))
OUT = Path(__file__).resolve().parents[1] / 'assets' / 'Meme_Animation_Asset_Pack' / 'new' / '_probe.json'
EXPR = r'''(()=>{
  const short=e=>e?{tag:e.tagName,testid:e.getAttribute('data-testid'),aria:e.getAttribute('aria-label'),role:e.getAttribute('role'),cls:(e.className&&e.className.baseVal===undefined?String(e.className):'').slice(0,80)}:null;
  const turns=[...document.querySelectorAll('[data-talvt-turn-state]')];
  const articles=[...document.querySelectorAll('article,[data-testid^="conversation-turn"]')];
  const imgs=[...document.querySelectorAll('main img')].filter(i=>i.naturalWidth>=256).map(i=>{
    const chain=[];let e=i.parentElement;for(let k=0;k<6&&e;k++,e=e.parentElement)chain.push(short(e));
    return {src:(i.currentSrc||'').slice(0,60),w:i.naturalWidth,h:i.naturalHeight,complete:i.complete,alt:i.alt,
      in_talvt_turn:!!i.closest('[data-talvt-turn-state]'),turn_state:i.closest('[data-talvt-turn-state]')?.getAttribute('data-talvt-turn-state')||null,
      preview_button:!!i.closest('button[data-testid="generated-image-preview"]'),parents:chain};});
  const last=turns[turns.length-1]||articles[articles.length-1];
  return {url:location.href,talvt_turns:turns.length,turn_states:turns.map(t=>t.getAttribute('data-talvt-turn-state')),
    h4:[...document.querySelectorAll('h4,h5,h6')].map(h=>h.textContent.trim().slice(0,40)).slice(-6),
    articles:articles.length,preview_buttons:document.querySelectorAll('button[data-testid="generated-image-preview"]').length,
    images:imgs,last_turn_buttons:last?[...last.querySelectorAll('button')].map(short).slice(0,30):[],
    stop_button:!!document.querySelector('[data-testid="stop-button"]')};
})()'''


async def main():
    async with aiohttp.ClientSession() as http:
        tabs = await (await http.get('http://127.0.0.1:%d/json' % PORT)).json()
        report = []
        for tab in tabs:
            if tab.get('type') != 'page' or 'chatgpt.com' not in tab.get('url', ''):
                continue
            async with http.ws_connect(tab['webSocketDebuggerUrl'], max_msg_size=0) as ws:
                await ws.send_json({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': EXPR, 'returnByValue': True}})
                async for msg in ws:
                    data = json.loads(msg.data)
                    if data.get('id') == 1:
                        report.append(data.get('result', {}).get('result', {}).get('value') or data)
                        break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
    print('Da ghi', OUT, '-', len(report), 'tab ChatGPT')


asyncio.run(main())

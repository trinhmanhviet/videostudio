"""Read-only Gemini DOM diagnostic: what the send control looks like right now."""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from videostudio.cdp_protocol import CDPConnection  # noqa: E402

EXPR = r"""(()=>{
  const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
  const area=document.querySelector('input-area-v2');
  const box=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
  const buttons=area?[...area.querySelectorAll('button')].filter(vis).map(b=>({
    label:b.getAttribute('aria-label'),testid:b.getAttribute('data-testid'),
    disabled:b.disabled,cls:String(b.className).slice(0,60)
  })):[];
  return JSON.stringify({
    url:location.href,
    hasArea:!!area,
    areaTag:area?area.tagName:null,
    draft:box?(box.innerText||box.value||'').trim().slice(0,80):null,
    buttonCount:buttons.length,
    buttons
  });
})()"""


async def main():
    port = pathlib.Path(r'D:\Projects\videostudio\data\chrome-profile\DevToolsActivePort').read_text().splitlines()[0].strip()
    cdp = CDPConnection()
    await cdp.connect(f'ws://127.0.0.1:{port}/devtools/browser/' + pathlib.Path(r'D:\Projects\videostudio\data\chrome-profile\DevToolsActivePort').read_text().splitlines()[1].strip().split('/')[-1])
    try:
        targets = (await cdp.command('Target.getTargets')).get('targetInfos', [])
        gem = [t for t in targets if t.get('type') == 'page' and 'gemini.google.com' in (t.get('url') or '')]
        print('GEMINI_TARGETS', len(gem))
        for t in gem:
            attached = await cdp.command('Target.attachToTarget', {'targetId': t['targetId'], 'flatten': True})
            session = attached['sessionId']
            value = await cdp.command('Runtime.evaluate', {'expression': EXPR, 'returnByValue': True, 'awaitPromise': True}, session=session)
            print(t['targetId'], json.dumps(json.loads(value['result']['value']), indent=1)[:1600])
    finally:
        await cdp.close()


if __name__ == '__main__':
    asyncio.run(main())

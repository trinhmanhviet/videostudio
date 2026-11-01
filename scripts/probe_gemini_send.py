"""Probe: does execCommand insertion enable the Gemini send control?"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from videostudio.cdp_protocol import CDPConnection  # noqa: E402

PROBE = "videostudio-probe-xyz"

INSERT = """(()=>{
  const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
  const box=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
  if(!box)return 'NO_COMPOSER';
  box.focus();
  const ok=document.execCommand('insertText',false,'%s');
  return ok?'INSERTED':'REFUSED';
})()""" % PROBE

REPORT = """(()=>{
  const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
  const area=document.querySelector('input-area-v2');
  const box=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
  const inArea=area?[...area.querySelectorAll('button')].map(b=>({
    label:b.getAttribute('aria-label'),testid:b.getAttribute('data-testid'),
    disabled:b.disabled===true,visible:vis(b),
    head:b.outerHTML.slice(0,140)
  })):[];
  return JSON.stringify({draft:(box&&(box.innerText||box.value||'')).slice(0,40), buttons:inArea});
})()"""

CLEAR = """(()=>{
  const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
  const box=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
  if(!box)return 'NO_COMPOSER';
  box.focus();
  const sel=getSelection();const r=document.createRange();r.selectNodeContents(box);sel.removeAllRanges();sel.addRange(r);
  document.execCommand('delete');
  return (box.innerText||'').trim()===''?'CLEARED':'NOT_CLEAR';
})()"""


async def evaluate(cdp, session, expression):
    value = await cdp.command('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True}, session=session)
    return value['result'].get('value')


async def main():
    port = pathlib.Path(r'D:\Projects\videostudio\data\chrome-profile\DevToolsActivePort').read_text().splitlines()[0].strip()
    browser = pathlib.Path(r'D:\Projects\videostudio\data\chrome-profile\DevToolsActivePort').read_text().splitlines()[1].strip().split('/')[-1]
    cdp = CDPConnection()
    await cdp.connect(f'ws://127.0.0.1:{port}/devtools/browser/{browser}')
    try:
        targets = (await cdp.command('Target.getTargets')).get('targetInfos', [])
        gem = [t for t in targets if t.get('type') == 'page' and 'gemini.google.com' in (t.get('url') or '')]
        for t in gem:
            await cdp.command('Target.activateTarget', {'targetId': t['targetId']})
            attached = await cdp.command('Target.attachToTarget', {'targetId': t['targetId'], 'flatten': True})
            session = attached['sessionId']
            print('INSERT execCommand', await evaluate(cdp, session, INSERT))
            await asyncio.sleep(1.0)
            print('AFTER', json.dumps(json.loads(await evaluate(cdp, session, REPORT)), indent=1)[:1200])
            print('CLEAR', await evaluate(cdp, session, CLEAR))
    finally:
        await cdp.close()


if __name__ == '__main__':
    asyncio.run(main())

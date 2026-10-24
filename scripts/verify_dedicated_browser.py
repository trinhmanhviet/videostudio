"""Live browser plumbing test on tool-owned about:blank tabs. No ChatGPT requests."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from videostudio.chrome_browser import DedicatedChrome, ROOT
from videostudio.cdp_protocol import CDPConnection


async def main():
    launcher=DedicatedChrome()
    endpoint=await asyncio.to_thread(launcher.ensure_started)
    cdp=CDPConnection()
    results={'profile':str(launcher.config.profile.resolve()),'chatgpt_requests_sent':0}
    targets=[]
    try:
        await cdp.connect(endpoint)
        args=(await cdp.command('Browser.getBrowserCommandLine'))['arguments']
        assert '--user-data-dir='+results['profile'] in args
        assert not any('remote-allow-origins' in a for a in args)
        results['dedicated_profile_attested']=True
        target=(await cdp.command('Target.createTarget',{'url':'about:blank'}))['targetId'];targets.append(target)
        sid=(await cdp.command('Target.attachToTarget',{'targetId':target,'flatten':True}))['sessionId']
        await cdp.command('Page.enable',session=sid)
        frame=(await cdp.command('Page.getFrameTree',session=sid))['frameTree']['frame']['id']
        await cdp.command('Page.setDocumentContent',{'frameId':frame,'html':'<html><body><textarea id="input"></textarea><button id="send" onclick="document.body.dataset.result=document.querySelector(\'#input\').value">Send</button></body></html>'},session=sid)
        await cdp.command('Runtime.evaluate',{'expression':"document.querySelector('#input').focus()"},session=sid)
        await cdp.command('Input.insertText',{'text':'VideoStudio unicode: tiếng Việt'},session=sid)
        rect=(await cdp.command('Runtime.evaluate',{'expression':"(()=>{const r=document.querySelector('#send').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()",'returnByValue':True},session=sid))['result']['value']
        for kind in ('mousePressed','mouseReleased'):
            await cdp.command('Input.dispatchMouseEvent',{'type':kind,**rect,'button':'left','clickCount':1},session=sid)
        value=(await cdp.command('Runtime.evaluate',{'expression':'document.body.dataset.result','returnByValue':True},session=sid))['result']['value']
        assert value=='VideoStudio unicode: tiếng Việt'
        results['trusted_input_and_click_fixture']=True
        await cdp.command('Target.closeTarget',{'targetId':target});targets.remove(target)
        current=(await cdp.command('Target.getTargets'))['targetInfos']
        assert not any(t['targetId']==target for t in current)
        results['owned_tab_close_detected']=True
        await cdp.close()
        assert await asyncio.to_thread(launcher.ensure_started)==endpoint
        await cdp.connect(endpoint)
        await cdp.command('Browser.getVersion')
        results['reconnect_existing_owned_browser']=True
        results['limitations']=['Fixture only, not live ChatGPT DOM or login acceptance.','No Memory Saver/discard test performed.']
        out=ROOT/'data'/'dedicated-browser-live.json'
        out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(results,ensure_ascii=True))
    finally:
        if cdp.connected:
            for t in targets:
                await cdp.command('Target.closeTarget',{'targetId':t})
        await cdp.close()

if __name__=='__main__':asyncio.run(main())

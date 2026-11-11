import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,r'D:\Projects\videostudio\app')
from videostudio.chrome_browser import DedicatedChrome
from videostudio.cdp_protocol import CDPConnection

async def main():
    d=DedicatedChrome()
    ep=await asyncio.to_thread(d.discover)
    ALL_EVENTS=[]
    def catch_all(e):
        ALL_EVENTS.append(e)
        m=e.get('method','')
        if 'ownload' in m or 'Browser.' in m:
            print('EVENT:',m,json.dumps(e.get('params',{}))[:200])
    c=CDPConnection(on_event=catch_all)
    await c.connect(ep)
    await c.command('Target.setDiscoverTargets',{'discover':True})
    targets=(await c.command('Target.getTargets'))['targetInfos']
    image_tab=[t for t in targets if '6addc75b' in t.get('url','')]
    if not image_tab:print('No tab');await c.close();return
    tid=image_tab[0]['targetId']
    sid=(await c.command('Target.attachToTarget',{'targetId':tid,'flatten':True}))['sessionId']
    ft=await c.command('Page.getFrameTree',session=sid)
    fid=ft['frameTree']['frame']['id']
    print('frameId:',fid)
    await c.command('Page.enable',session=sid)
    await c.command('Runtime.enable',session=sid)

    folder=Path(r'D:\Projects\videostudio\data\chatgpt-images\downloads\frame-test')
    folder.mkdir(parents=True,exist_ok=True)
    print('Setting download behavior at BROWSER level...')
    await c.command('Browser.setDownloadBehavior',{'behavior':'allowAndName','downloadPath':str(folder.resolve()),'eventsEnabled':True})
    print('Also setting at PAGE session level...')
    try:
        await c.command('Browser.setDownloadBehavior',{'behavior':'allowAndName','downloadPath':str(folder.resolve()),'eventsEnabled':True},session=sid)
        print('Page-session setDownloadBehavior OK')
    except Exception as e:
        print('Page-session setDownloadBehavior failed:',e)

    await c.command('Target.activateTarget',{'targetId':tid})
    expr='(()=>{const bs=[...document.querySelectorAll("button")].filter(b=>(b.getAttribute("aria-label")||"").match(/Download|Save/i) && b.getBoundingClientRect().width);return bs.map(b=>{const r=b.getBoundingClientRect();return {label:b.getAttribute("aria-label"),x:r.x+r.width/2,y:r.y+r.height/2,w:r.width}})})()'
    res=await c.command('Runtime.evaluate',{'expression':expr,'returnByValue':True},session=sid)
    btns=res.get('result',{}).get('value',[])
    print('Download buttons:',json.dumps(btns))
    if btns:
        b=btns[0]
        print(f'Clicking download at ({b["x"]},{b["y"]})...')
        for k in ('mousePressed','mouseReleased'):
            await c.command('Input.dispatchMouseEvent',{'type':k,'x':b['x'],'y':b['y'],'button':'left','clickCount':1},session=sid)
        for i in range(30):
            await asyncio.sleep(.5)
            dl=[e for e in ALL_EVENTS if 'ownload' in str(e.get('method',''))]
            if dl:
                print(f'Got {len(dl)} download events after {(i+1)*0.5}s')
                for de in dl:
                    print('  ',de['method'],json.dumps(de.get('params',{}))[:400])
                break
        else:
            print(f'NO download events after 15s. Total events: {len(ALL_EVENTS)}')
            methods=sorted(set(e.get('method') for e in ALL_EVENTS))
            print('Methods:',methods[:40])
    await c.command('Browser.setDownloadBehavior',{'behavior':'default','eventsEnabled':False})
    await c.close()
asyncio.run(main())

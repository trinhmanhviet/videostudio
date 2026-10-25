"""Read/download-only transport verification against an already generated probe.
No prompt is sent. Never creates/changes a production scene or exports video.
"""
import asyncio,json,sqlite3,sys,uuid
from pathlib import Path
from videostudio.cdp_daemon import ChromeChatGPTBridge
from videostudio.cdp_images import image_snapshot,match_image
from videostudio.core import digest

async def verify(probe_file,out):
    probe=json.loads(Path(probe_file).read_text(encoding='utf8'));out=Path(out);out.mkdir(parents=True,exist_ok=True)
    db=Path(__file__).resolve().parents[1]/'data/jobs.sqlite3'
    with sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True) as c:
        if c.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','retrying')").fetchone()[0]:raise RuntimeError('Production active; postpone read/download probe')
    bridge=ChromeChatGPTBridge();await bridge.connect()
    try:
        target=probe['target'];session=await bridge.session(target);marker='[VideoStudio image probe 20261025]'
        state=await bridge.evaluate(session,image_snapshot(marker));image=match_image(state,marker)
        if not image:raise RuntimeError('Existing probe image unavailable; do not send another prompt')
        bridge.images.root=out
        result=await bridge.images._download(str(uuid.uuid4()),target,session,marker,image,state['url'])
        result.update(new_generation_requests=0,verification='live implemented _download against existing image, not full product UI generation')
        (out/'download-verification.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
    finally:
        (out/'download-events.json').write_text(json.dumps({'events':bridge.images.events,'active_frame':bridge.images.active_frame,'guid':bridge.images.download_guid},indent=2),encoding='utf8')
        await bridge.close()
if __name__=='__main__':asyncio.run(verify(sys.argv[1],sys.argv[2]))

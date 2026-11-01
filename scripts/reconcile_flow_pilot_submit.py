"""Recover only the pilot's visibly unsent second prompt after the Enter regression."""
import asyncio,json,time
from pathlib import Path
from videostudio.cdp_daemon import ChromeChatGPTBridge

async def main():
    root=Path(__file__).resolve().parents[1]
    payload=json.loads((root/'data/flow-batch-pilot-2026-10-30/request.json').read_text())
    first,task=payload['tasks'][:2];bridge=ChromeChatGPTBridge()
    if not bridge.launcher.discover():raise RuntimeError('Owned Chrome is absent')
    await bridge.connect();flow=bridge.flow_images
    try:
        receipt=flow._read_receipt(task['task_id'])
        if receipt['stage']=='waiting_result':print('Already reconciled; no click');return
        if receipt['stage']!='submitting' or receipt['job_id']!=payload['job_id']:raise RuntimeError('Unexpected pilot receipt')
        target=await flow._target();session=await flow._session(target)
        state=await flow._snapshot(session,task['prompt'])
        if state['url'].rstrip('/')!=receipt['project_url'].rstrip('/') or not state['draftMatches'] or state['generateDisabled'] or state['agentOn'] is not False:raise RuntimeError('Cannot prove the exact pilot draft is still unsent')
        tiles=state.get('assetTiles',[])
        if len(tiles)!=1 or not tiles[0].get('complete') or not tiles[0].get('media_id'):raise RuntimeError('Pilot has another pending/new image; do not click')
        tile=tiles[0]
        await flow._click_media_control(session,tile['media_id'],tile['aria_label'])
        full=await flow._eval(session,"(()=>[...document.querySelectorAll('flow-info-panel .prompt-text')].map(e=>e.innerText.trim()).filter(Boolean))()")
        await flow._dismiss_flow_popups(session)
        if full!=[first['prompt']]:raise RuntimeError('Existing media is not the first pilot task')
        state=await flow._snapshot(session,task['prompt'])
        if not state['draftMatches'] or state['generateDisabled']:raise RuntimeError('Pilot draft changed')
        receipt['baseline_media_ids']=[tile['media_id']]
        receipt['pilot_recovery']={'reason':'Enter left exact draft unsent; first image full-prompt verified','at':time.time(),'method':'single_native_click'}
        flow._write_receipt(task['task_id'],receipt)
        await flow._click_named(session,'Bắt đầu tạo',exact=True,native_only=True)
        await flow._wait_page(session,lambda s:s.get('draftEmpty'),timeout=12,prompt='')
        receipt.update(stage='waiting_result',updated_at=time.time());flow._write_receipt(task['task_id'],receipt)
        print(json.dumps({'reconciled_task':task['task_id'],'stage':'waiting_result','new_task_created':False}),flush=True)
    finally:await bridge.cdp.close()

if __name__=='__main__':asyncio.run(main())

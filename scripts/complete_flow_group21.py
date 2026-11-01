"""Finish the verified partial cohort without cancelling or replacing its video job."""
import asyncio,hashlib,json,shutil,sqlite3,time,uuid
from pathlib import Path
from videostudio.cdp_daemon import ChromeChatGPTBridge
ROOT=Path(__file__).resolve().parents[1];JOB='67b0c73c-4008-4083-954d-5a9e9dc8d851';FOLDER=ROOT/'data/recovery-67b0c73c'
async def main():
    with sqlite3.connect((ROOT/'data/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        state,output=db.execute('select state,output from jobs where id=?',(JOB,)).fetchone()
    if state not in ('failed','retrying'):raise RuntimeError('Wait for the old transport attempt to stop; job was not modified')
    scenes=json.loads((Path(output)/'script.json').read_text(encoding='utf8'))['scenes']
    batch_path=ROOT/'data/flow-images/batches/23a1e17b-9933-5d8f-b158-074b98072253.json'
    manifest=json.loads(batch_path.read_text(encoding='utf8'));verified=json.loads((FOLDER/'verified-mapping.json').read_text(encoding='utf8'))['mapping'];scan=json.loads((FOLDER/'grid-scan.json').read_text(encoding='utf8'))
    if len(scan['positions'])!=204 or len(scan['fresh'])!=4:raise RuntimeError('Original exhaustive-grid evidence changed')
    bridge=ChromeChatGPTBridge();await bridge.connect();flow=bridge.flow_images;flow._media_scroll_positions=scan['positions'];target=await flow._target();session=await flow._session(target)
    try:
        for item in manifest['tasks']:
            task=item['task_id'];receipt=flow._read_receipt(task);prompt=scenes[item['ordinal']]['visual_prompt']
            if hashlib.sha256(prompt.encode()).hexdigest()!=receipt['prompt_sha256']:raise RuntimeError('Prompt changed')
            if receipt.get('stage')=='downloaded' and flow._cached_result(task,receipt):continue
            if task in verified:
                receipt.update(stage='image_ready',media_id=verified[task],download_resolution_requested='1K',download_fallback_reason='owner-authorized recovery using verified existing image')
                flow._write_receipt(task,receipt)
                receipt=await flow._download_2k(task,target,session,receipt,prompt,media_id=receipt['media_id'])
                print(json.dumps({'ordinal':item['ordinal'],'reused_existing_image':True,'stage':'downloaded'}),flush=True)
            else:
                recovery=str(uuid.uuid5(uuid.UUID(task),'exhaustive-grid-missing-recovery-1'))
                old=flow._read_receipt(recovery)
                if not old:
                    await flow.generate(recovery,JOB,prompt,submit_only=True,require_zero_credit=True)
                recovered=flow._read_receipt(recovery)
                recovered.update(download_resolution_requested='1K',download_fallback_reason='recovery uses original resolution');flow._write_receipt(recovery,recovered)
                result=await flow.generate(recovery,JOB,prompt,timeout=240,require_zero_credit=True)
                path=flow.root/(task+'.png');source=Path(result['file_path'])
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=result['sha256']:raise RuntimeError('Original output differs; refusing overwrite')
                if not path.exists():shutil.copyfile(source,path)
                receipt.update(stage='downloaded',media_id=result['media_id'],download_path=str(path.resolve()),download_sha256=result['sha256'],width=result['width'],height=result['height'],format='PNG',download_resolution_requested='1K',recovery_task_id=recovery,recovery_reason='Absent after exhaustive 204-media scan; 4 existing requested media verified by exact full prompts',updated_at=time.time())
                flow._write_receipt(task,receipt);verified[task]=result['media_id']
                print(json.dumps({'ordinal':item['ordinal'],'created_only_missing_scene':True,'stage':'downloaded'}),flush=True)
            manifest['mapping'][task]=receipt['media_id'];manifest['task_state'][task]='downloaded';flow._write_batch_manifest(manifest['batch_id'],manifest)
        manifest.update(stage='completed',completed_at=time.time(),updated_at=time.time(),prefer_original_resolution=True,recovery_note='4 existing images identified by full prompt; 6 absent scenes generated sequentially with separate auditable recovery tasks');manifest.pop('last_error',None);flow._write_batch_manifest(manifest['batch_id'],manifest)
        print(json.dumps({'group21_complete':True,'tasks':len(manifest['tasks']),'job_cancelled':False}),flush=True)
    finally:await bridge.cdp.close()
if __name__=='__main__':asyncio.run(main())

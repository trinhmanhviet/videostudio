"""Continue missing scenes in a new Flow account, preserving the original video job."""
import asyncio,hashlib,json,shutil,sqlite3,time,uuid
from pathlib import Path
from videostudio.cdp_daemon import ChromeChatGPTBridge
ROOT=Path(__file__).resolve().parents[2];JOB='67b0c73c-4008-4083-954d-5a9e9dc8d851';FOLDER=ROOT.parent/'data/archive/recovery-67b0c73c'
RUN=str(uuid.uuid5(uuid.UUID(JOB),'google-account-switch-20261030-1'))
async def main():
    with sqlite3.connect((ROOT.parent/'data/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        status,output=db.execute('select state,output from jobs where id=?',(JOB,)).fetchone()
    if status!='failed':raise RuntimeError('The original job must be idle during account migration')
    scenes=json.loads((Path(output)/'script.json').read_text(encoding='utf8'))['scenes']
    batch_path=ROOT.parent/'data/flow-images/batches/23a1e17b-9933-5d8f-b158-074b98072253.json';manifest=json.loads(batch_path.read_text(encoding='utf8'))
    bridge=ChromeChatGPTBridge();await bridge.connect();flow=bridge.flow_images
    tabs=[t for t in (await bridge.cdp.command('Target.getTargets'))['targetInfos'] if t.get('type')=='page' and t.get('url','').startswith('https://flow.google.com/')]
    if len(tabs)>1:
        visible=[]
        for tab in tabs:
            sid=await bridge.session(tab['targetId'])
            if await flow._eval(sid,"document.visibilityState==='visible'"):visible.append(tab)
        if len(visible)!=1:raise RuntimeError('Select the new-account Flow tab before recovery')
        for tab in tabs:
            if tab['targetId']==visible[0]['targetId']:continue
            if tab['url'].split('?')[0].rstrip('/')!='https://flow.google.com':raise RuntimeError('Another Flow project is open; no tab closed')
            await bridge.cdp.command('Target.closeTarget',{'targetId':tab['targetId']})
    try:
        for item in manifest['tasks']:
            original=item['task_id'];receipt=flow._read_receipt(original);prompt=scenes[item['ordinal']]['visual_prompt']
            if hashlib.sha256(prompt.encode()).hexdigest()!=receipt['prompt_sha256']:raise RuntimeError('Original scene prompt mismatch')
            cached=flow._cached_result(original,receipt)
            if not cached:
                recovery=str(uuid.uuid5(uuid.UUID(original),'new-account-missing-recovery-20261030-1'))
                saved=flow._read_receipt(recovery)
                if not saved:await flow.generate(recovery,RUN,prompt,submit_only=True,require_zero_credit=True)
                saved=flow._read_receipt(recovery);saved.update(download_resolution_requested='1K',download_fallback_reason='owner requested original resolution for account recovery');flow._write_receipt(recovery,saved)
                result=await flow.generate(recovery,RUN,prompt,timeout=240,require_zero_credit=True)
                path=flow.root/(original+'.png');source=Path(result['file_path'])
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=result['sha256']:raise RuntimeError('Refusing to overwrite a different original scene')
                if not path.exists():shutil.copyfile(source,path)
                receipt.update(stage='downloaded',project_url=result['project_url'],media_id=result['media_id'],download_path=str(path.resolve()),download_sha256=result['sha256'],width=result['width'],height=result['height'],format='PNG',download_resolution_requested='1K',recovery_task_id=recovery,recovery_run_id=RUN,recovery_reason='Owner changed Google account; original missing scene retained with separate recovery receipt',updated_at=time.time())
                flow._write_receipt(original,receipt)
                print(json.dumps({'ordinal':item['ordinal'],'new_account_image_downloaded':True}),flush=True)
            manifest['mapping'][original]=receipt['media_id'];manifest['task_state'][original]='downloaded';flow._write_batch_manifest(manifest['batch_id'],manifest)
        new_registry=flow._load_project_registry(RUN)
        if not new_registry:raise RuntimeError('No completed new-account project to activate')
        registry_path=flow.projects/(JOB+'.json');old_registry=json.loads(registry_path.read_text(encoding='utf8'));backup=FOLDER/'project-before-account-switch.json'
        if not backup.exists():backup.write_text(json.dumps(old_registry,indent=2),encoding='utf8')
        active={**old_registry,'project_url':new_registry['project_url'],'previous_projects':[old_registry['project_url']],'active_account_run':RUN,'account_switched_at':time.time()}
        part=registry_path.with_suffix('.part');part.write_text(json.dumps(active,indent=2),encoding='utf8');part.replace(registry_path)
        manifest.update(stage='completed',completed_at=time.time(),updated_at=time.time(),prefer_original_resolution=True,recovery_note='4 verified originals preserved; 6 missing images generated in owner-selected new Google account');manifest.pop('last_error',None);flow._write_batch_manifest(manifest['batch_id'],manifest)
        print(json.dumps({'group21_complete':True,'main_job_unchanged':JOB,'active_flow_project':new_registry['project_url']}),flush=True)
    finally:await bridge.cdp.close()
if __name__=='__main__':asyncio.run(main())

"""Recover exact media identities for the stalled, already-submitted batch."""
import asyncio,hashlib,json,sqlite3
from pathlib import Path
from videostudio.cdp_daemon import ChromeChatGPTBridge

ROOT=Path(__file__).resolve().parents[1]
JOB='67b0c73c-4008-4083-954d-5a9e9dc8d851'
FOLDER=ROOT/'data/recovery-67b0c73c'

async def main():
    with sqlite3.connect((ROOT/'data/jobs.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        output=Path(db.execute('select output from jobs where id=?',(JOB,)).fetchone()[0])
    scenes=json.loads((output/'script.json').read_text(encoding='utf8'))['scenes']
    manifest=json.loads((ROOT/'data/flow-images/batches/23a1e17b-9933-5d8f-b158-074b98072253.json').read_text(encoding='utf8'))
    scan=json.loads((FOLDER/'grid-scan.json').read_text(encoding='utf8'))
    bridge=ChromeChatGPTBridge();await bridge.connect();flow=bridge.flow_images
    flow._media_scroll_positions=scan['positions']
    target=await flow._target();session=await flow._session(target)
    tasks=[]
    for item in manifest['tasks']:
        receipt=flow._read_receipt(item['task_id']);(FOLDER/(item['task_id']+'.original.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf8')
        prompt=scenes[item['ordinal']]['visual_prompt']
        if hashlib.sha256(prompt.encode()).hexdigest()!=receipt['prompt_sha256']:raise RuntimeError('Saved prompt mismatch')
        tasks.append({**item,'job_id':JOB,'prompt':prompt,'character_mentions':receipt.get('character_mentions',[])})
    mapping={}
    try:
        for tile in scan['fresh']:
            detail=await flow._read_prompt_for_media(session,tile['media_id'])
            try:
                key=flow._batch_prompt_fingerprint(detail['prompt'],detail.get('mention_entity_ids',[]))
                matched=[t for t in tasks if flow._batch_prompt_fingerprint(' '.join([m['name'] for m in t['character_mentions']]+[t['prompt']]),[m['character_id'] for m in t['character_mentions']])==key]
                if len(matched)!=1:raise RuntimeError('A visible saved image does not identify exactly one requested scene')
                task=matched[0];mapping[task['task_id']]=tile['media_id']
                (FOLDER/'verified-mapping.json').write_text(json.dumps({'job_id':JOB,'project_url':manifest['project_url'],'mapping':mapping},indent=2),encoding='utf8')
                print(json.dumps({'verified_ordinal':task['ordinal'],'media_id':tile['media_id']}),flush=True)
            finally:await flow._clear_verified_reused_prompt(session,manifest['project_url'],detail['prompt'])
    finally:await bridge.cdp.close()
    print(json.dumps({'verified_existing':len(mapping),'missing_ordinals':[t['ordinal'] for t in tasks if t['task_id'] not in mapping]}),flush=True)

if __name__=='__main__':asyncio.run(main())

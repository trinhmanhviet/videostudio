"""Owner-authorized ten-image Flow pilot; replay uses identical durable task IDs."""
import hashlib,json,time,uuid,urllib.request,urllib.error,sys
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'data'/'flow-batch-pilot-2026-10-30'

def main():
    FOLDER.mkdir(parents=True,exist_ok=True)
    request_path=FOLDER/'request.json'
    if not request_path.exists():
        job=str(uuid.uuid4())
        subjects=[
            'a cobalt-blue Chinese porcelain teapot on a wooden tea table',
            'a single red silk Chinese lantern hanging under a tiled eave',
            'a green bamboo grove beside a quiet Chinese courtyard',
            'an old thread-bound Chinese book closed on a scholar desk',
            'a tall white porcelain vase with a blue dragon pattern',
            'an empty dark wooden Ming-style chair beside a window',
            'a small arched stone bridge over a Chinese village canal',
            'a brown terracotta horse figurine on a museum display plinth',
            'a woven bamboo basket filled with ripe yellow pears',
            'a black vintage bicycle leaning against a grey brick courtyard wall',
        ]
        tasks=[{'task_id':str(uuid.uuid5(uuid.UUID(job),f'pilot:{i}')),'ordinal':i,
                'prompt':f'Vertical documentary still, {subject}. Chinese setting, soft natural afternoon light, realistic physical materials, clear single subject, no people, no lettering, no watermark.',
                'character_mentions':[]} for i,subject in enumerate(subjects)]
        request_path.write_text(json.dumps({'job_id':job,'tasks':tasks,'timeout':1200,'download_results':True},ensure_ascii=False,indent=2),encoding='utf8')
    payload=json.loads(request_path.read_text(encoding='utf8'))
    verify_only='--verify-only' in sys.argv
    if verify_only:
        run=json.loads((FOLDER/'run.json').read_text());started=run['started_at']
        body=json.loads((FOLDER/'response.json').read_text())
    else:
        started=time.time();run={'job_id':payload['job_id'],'started_at':started,'task_count':len(payload['tasks'])}
        (FOLDER/'run.json').write_text(json.dumps(run,indent=2))
        print(json.dumps({'pilot_job':payload['job_id'],'task_count':len(payload['tasks']),'action':'submit ten, wait, then download same media'}),flush=True)
        request=urllib.request.Request('http://127.0.0.1:8879/api/flow/images/generate-batch',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-VS-Client':'videostudio'},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=1500) as response:body=json.load(response)
        except urllib.error.HTTPError as error:
            detail=error.read().decode();run.update(error=detail,elapsed_seconds=round(time.time()-started,2))
            (FOLDER/'run.json').write_text(json.dumps(run,indent=2))
            print(detail,flush=True);raise
        (FOLDER/'response.json').write_text(json.dumps(body,indent=2))
    results=body.get('data',[]);expected={t['task_id']:t for t in payload['tasks']}
    if len(results)!=10 or {r['task_id'] for r in results}!=set(expected):raise ValueError('Pilot must return all ten exact tasks')
    if len({r['media_id'] for r in results})!=10:raise ValueError('Pilot media IDs must be unique')
    verified=[]
    for result in results:
        task=expected[result['task_id']];path=Path(result['file_path'])
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=result['sha256']:raise ValueError('Pilot file hash mismatch')
        with Image.open(path) as im:
            im.load()
            if im.format!='PNG' or min(im.size)<512:raise ValueError('Pilot image validation failed')
            size=im.size
        receipt=json.loads((ROOT/'data'/'flow-images'/'tasks'/(result['task_id']+'.json')).read_text(encoding='utf8'))
        if receipt.get('prompt_sha256')!=hashlib.sha256(task['prompt'].encode()).hexdigest() or receipt.get('media_id')!=result['media_id']:raise ValueError('Pilot task/prompt/media mismatch')
        verified.append({'ordinal':task['ordinal'],'task_id':task['task_id'],'media_id':result['media_id'],'path':str(path),'size':size,'sha256':sha,'requested_resolution':receipt.get('download_resolution_requested')})
    run.update(passed=True,elapsed_seconds=run.get('elapsed_seconds') if verify_only else round(time.time()-started,2),completed_at=run.get('completed_at',time.time()),verified=sorted(verified,key=lambda r:r['ordinal']),last_verified_at=time.time())
    (FOLDER/'run.json').write_text(json.dumps(run,indent=2))
    (ROOT/'data'/'flow-batch-acceptance.json').write_text(json.dumps({
        'schema_version':1,'passed':True,'validated_sizes':[10],'verified_images':10,
        'pilot_job_id':payload['job_id'],'verified_at':time.time(),'evidence_run':str(FOLDER/'run.json'),
    },indent=2))
    print(json.dumps({'passed':True,'verified_images':len(verified),'elapsed_seconds':run['elapsed_seconds']}),flush=True)

if __name__=='__main__':main()

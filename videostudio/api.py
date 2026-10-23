from __future__ import annotations
import os, threading, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .core import Store, Worker, validate_request
from .voices import Voices
from .providers import Pipeline

ROOT=Path(__file__).resolve().parent.parent

def create_app(store=None,pipeline=None,worker_enabled=True):
    store=store or Store(os.getenv('VS_DATABASE',str(ROOT/'data'/'jobs.sqlite3')),os.getenv('VS_OUTPUT_DIR','E:/Videos'))
    voices=Voices(os.getenv('VS_STORYFORGE_ROOT','D:/Projects/storyforge'),os.getenv('VS_VOICES_EXPORT'))
    pipeline=pipeline or Pipeline(voices)
    worker=Worker(store,pipeline.handlers());stop=threading.Event();working=threading.Event()
    def loop():
        while not stop.is_set():
            working.set()
            try: did=worker.step()
            except Exception:did=False
            finally:working.clear()
            if not did:stop.wait(.5)
    def heartbeat():
        while not stop.wait(5):
            if working.is_set():store.lock(worker.owner)
    @asynccontextmanager
    async def lifespan(app):
        threads=[]
        if worker_enabled:
            for target in (loop,heartbeat):
                t=threading.Thread(target=target,daemon=True);t.start();threads.append(t)
        yield
        stop.set()
        # Running stage checks cancellation through store; shutdown leaves running
        # checkpoint recoverable, rather than falsely changing it to success.
        for t in threads:t.join(timeout=2)
    app=FastAPI(title='VideoStudio local',lifespan=lifespan)
    app.state.store=store;app.state.pipeline=pipeline
    @app.get('/api/health')
    def health():return {'status':'ok','service':'videostudio','durable':True,'worker_enabled':worker_enabled}
    def public_job(j):
        return {**j,'status':j['state'],'progress':round(len(j['checkpoints'])/9*100),'output_url':'/api/jobs/'+j['id']+'/files/video.mp4' if j['state']=='completed' else None}
    @app.get('/api/preflight')
    def preflight():
        result=pipeline.preflight()
        result['checks']=[{**c,'message':c.get('message',c.get('detail',''))} for c in result['checks']]
        return result
    @app.get('/api/voices')
    def catalog():
        c=voices.catalog()
        # Absolute filesystem paths are server-private, sample URLs are scoped.
        c['voices']=[{k:v for k,v in r.items() if k not in ('reference_path','sample_path','sha256')}|{'sample_url':'/api/voices/'+r['id']+'/sample' if r.get('sample_path') else None} for r in c['voices']]
        c['unmapped_sample_files']=[Path(p).name for p in c['unmapped_sample_files']]
        return {**c,'items':c['voices'],'unavailable_reasons':c['warnings']}
    @app.get('/api/voices/{voice_id:path}/sample')
    def sample(voice_id:str):
        for v in voices.catalog()['voices']:
            if v['id']==voice_id and v.get('sample_path') and Path(v['sample_path']).is_file():return FileResponse(v['sample_path'],media_type='audio/wav')
        raise HTTPException(404,'Sample unavailable; no synthesis performed')
    @app.post('/api/jobs',status_code=201)
    def submit(data:dict,request:Request,idempotency_key:str|None=Header(default=None)):
        # Loopback-only API: avoid drive-by browser mutations (no permissive CORS).
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Cross-origin writes denied')
        if not idempotency_key:
            raise HTTPException(422,'Idempotency-Key required')
        # Reject new jobs before allocation; existing idempotent receipts remain readable.
        with store.db() as connection:
            previous=connection.execute('SELECT id FROM jobs WHERE idem=?',(idempotency_key,)).fetchone()
        if previous is None:
            pf=pipeline.preflight()
            if not pf['ready']:
                raise HTTPException(503,{'message':'Production preflight blocked','checks':[c for c in pf['checks'] if not c['ok']]})
        try:
            job,created=store.create(data,idempotency_key)
            return {**public_job(job),'job':public_job(job),'created':created}
        except ValueError as e:raise HTTPException(409 if 'already used' in str(e) else 422,str(e))
    @app.get('/api/jobs')
    def jobs():
        items=[public_job(j) for j in store.list()]
        return {'items':items,'jobs':items}
    @app.get('/api/jobs/{job_id}')
    def detail(job_id:str):
        try:return public_job(store.get(job_id))
        except KeyError:raise HTTPException(404,'Job not found')
    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id:str,request:Request):
        origin=request.headers.get('origin')
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Cross-origin writes denied')
        try:return public_job(store.cancel(job_id))
        except KeyError:raise HTTPException(404,'Job not found')
    @app.get('/api/jobs/{job_id}/files/{name}')
    def file(job_id:str,name:str):
        try:j=store.get(job_id)
        except KeyError:raise HTTPException(404,'Job not found')
        # Only checkpoint-attested files may be streamed, never arbitrary paths.
        root=Path(j['output']).resolve();candidate=(root/name).resolve()
        if candidate.parent!=root:raise HTTPException(404,'File not found')
        allowed={Path(a['path']).resolve() for cp in j['checkpoints'].values() for a in cp.get('assets',[])}
        if candidate not in allowed or not candidate.is_file():raise HTTPException(404,'File not checkpointed')
        if name=='video.mp4' and j['state']!='completed':raise HTTPException(409,'Video not verified')
        return FileResponse(candidate)
    static=ROOT/'static'
    if static.is_dir():app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    return app

app=create_app(worker_enabled=os.getenv('VS_WORKER_ENABLED','1')=='1')

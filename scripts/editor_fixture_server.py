"""Local-only acceptance fixture. Never opens production DB or calls a provider."""
import argparse,json,os
from pathlib import Path
from scripts.create_editor_fixture import FIXTURE,create_fixture
os.environ['VS_DATABASE']=str(FIXTURE/'jobs.sqlite3')
os.environ['VS_OUTPUT_DIR']=str(FIXTURE/'outputs')
os.environ['VS_WORKER_ENABLED']='0'
os.environ['VS_LLM_TRANSPORT']='cdp'
os.environ['VS_STORYFORGE_ROOT']=str(FIXTURE/'unused-legacy')
from fastapi import HTTPException
from videostudio.api import create_app
from videostudio.core import Worker
from videostudio.edit_render import render_edit_plan,verify_edit_render
from videostudio.output_layout import publish_video

class FixtureVoices:
    def catalog(self):return {'voices':[{'id':'fixture','name':'Âm thanh thử tổng hợp','kind':'preset','sample_url':None}]}
class FixturePipeline:
    voices=FixtureVoices()
    def preflight(self,*args):return {'ready':True,'checks':[{'name':'synthetic_fixture','ok':True,'detail':'No external AI calls'}]}
    def handlers(self):return {'render':lambda job,check:publish_video(job,render_edit_plan(job,check)), 'verify':verify_edit_render}

def fixture_app():
    store,info=create_fixture()
    if Path(store.path).resolve()!=Path(FIXTURE/'jobs.sqlite3').resolve():raise RuntimeError('Fixture DB scope mismatch')
    pipeline=FixturePipeline();app=create_app(store,pipeline,False)
    @app.get('/fixture/info')
    def fixture_info():return info
    @app.get('/api/voices')
    def fixture_voices():
        result=FixtureVoices().catalog();return {**result,'items':result['voices'],'warnings':[],'unavailable_reasons':[],'unmapped_sample_files':[]}
    @app.post('/fixture/advance-export')
    def advance(data:dict):
        job=store.get(data.get('job_id',''))
        if not job['checkpoints'].get('images',{}).get('edit_plan_snapshot') or FIXTURE.resolve() not in Path(job['output']).resolve().parents:raise HTTPException(422,'Only a local fixture edit export may run')
        class OnlyJob:
            def __getattr__(self,key):return getattr(store,key)
            def list(self,*args,**kwargs):return [store.get(job['id'])]
        worker=Worker(OnlyJob(),pipeline.handlers())
        for _ in range(3):
            current=store.get(job['id'])
            if current['state'] in ('completed','failed'):break
            worker.step()
        result=store.get(job['id']);return {'id':result['id'],'state':result['state'],'error':result.get('error')}
    fixture_routes=[route for route in app.router.routes if getattr(route,'path','').startswith('/fixture/') or getattr(route,'name','')=='fixture_voices']
    app.router.routes[:]=fixture_routes+[route for route in app.router.routes if route not in fixture_routes]
    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8886);args=parser.parse_args()
    import uvicorn
    uvicorn.run(fixture_app(),host='127.0.0.1',port=args.port,log_level='warning')

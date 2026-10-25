from __future__ import annotations
import json, os, sqlite3, threading, time
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
    default_export=ROOT/'data'/'voices-export.json'
    voices=Voices(os.getenv('VS_STORYFORGE_ROOT','D:/Projects/storyforge'),os.getenv('VS_VOICES_EXPORT',str(default_export) if default_export.is_file() else None))
    pipeline=pipeline or Pipeline(voices)
    pipeline.store=store
    from .scene_editor import SceneEditor
    scene_editor=SceneEditor(store);pipeline.scene_editor=scene_editor
    from .scene_images import SceneImageJobs
    image_jobs=SceneImageJobs(store,scene_editor)
    from .exchanges import Exchanges
    exchanges=Exchanges(store)
    if hasattr(pipeline,'use_exchanges'):pipeline.use_exchanges(exchanges)
    worker=Worker(store,pipeline.handlers());stop=threading.Event();working=threading.Event()
    def loop():
        while not stop.is_set():
            working.set()
            try: did=image_jobs.step(worker.owner) or worker.step()
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
    app.state.store=store;app.state.pipeline=pipeline;app.state.image_jobs=image_jobs
    @app.get('/api/health')
    def health():return {'status':'ok','service':'videostudio','durable':True,'worker_enabled':worker_enabled,'chatgpt_scene_images':True}
    def diagnose_job_error(j):
        err=j.get('error')
        if not err:return None
        stage=j.get('stage')
        reason='Tác vụ dừng ở bước '+str(stage)
        suggestion='Kiểm tra chi tiết lỗi bên dưới và bấm Thử lại khi đã điều chỉnh.'
        if stage=='script' and 'Script quality' in err:
            reason='Kịch bản chưa đáp ứng tiêu chí kiểm chứng thực tế hoặc đang lệch khỏi trọng tâm ý tưởng ban đầu.'
            reviews=sorted(Path(j['output']).glob('script-attempt-*.review.json'))
            if reviews:
                try:
                    last=json.loads(reviews[-1].read_text(encoding='utf8'))
                    blockers=last.get('blocking_issues') or last.get('issues') or []
                    details=[str(x.get('reason','')) if isinstance(x,dict) else str(x) for x in blockers[:2]]
                    if details:reason=' '.join(details)[:800]
                except (OSError,ValueError,TypeError):pass
                suggestion='Tool đã tự sửa có giới hạn nhưng vẫn thiếu bằng chứng cho các dữ kiện quan trọng. Hãy xem các nguồn và vấn đề được liệt kê; không có dữ kiện nào được duyệt chỉ vì hết lượt sửa.'
            else:
                if '[' in err and ']' in err:
                    try:
                        import ast
                        issues=ast.literal_eval(err.split('Script quality/grounding retry budget exhausted: ',1)[-1])
                        if isinstance(issues,list) and issues:reason=' '.join(str(x) for x in issues[:2])[:800]
                    except (SyntaxError,ValueError):pass
                suggestion='Bản job cũ không có nhật ký sửa từng câu; hãy tạo job mới để dùng cơ chế tự sửa có kiểm chứng.'
        elif stage=='script' and 'delivery_indeterminate' in err:
            reason='Chưa xác nhận được phản hồi ChatGPT khớp request ID; receipt gửi vẫn được giữ, không gửi lại mù quáng.'
            suggestion='Tool tự đối soát trong số lượt thử giới hạn. Nếu vẫn dừng, kiểm tra phiên ChatGPT riêng; không nhấn gửi lại yêu cầu cũ.'
        elif stage=='speech' and 'Duration' in err:
            reason='Thời lượng lời đọc thực tế chênh lệch quá ngưỡng cho phép so với thời lượng video yêu cầu.'
            suggestion='Điều chỉnh độ dài ý tưởng hoặc tăng/giảm số giây đặt cho video để khớp với tốc độ đọc tự nhiên.'
        elif stage=='images' and ('10061' in err or 'refused' in err):
            reason='Không thể kết nối tới ComfyUI trên cổng 8188 trong giai đoạn tạo hình ảnh.'
            suggestion='Hãy đảm bảo ComfyUI đang hoạt động trên máy rồi bấm Thử lại bước này.'
        elif 'Chrome' in err or 'connector' in err:
            reason='Mất kết nối hoặc phiên Chrome riêng chưa sẵn sàng tương tác với ChatGPT.'
            suggestion='Bấm "Kiểm tra kết nối" hoặc "Mở Chrome riêng" để xác thực trạng thái đăng nhập.'
        return {'reason':reason,'suggestion':suggestion}
    def public_job(j):
        with store.db() as c:owner=c.execute('SELECT id FROM connector_scopes WHERE job=?',(j['id'],)).fetchone()
        diag=diagnose_job_error(j)
        events=j.get('events',[])
        latest_event=events[-1] if events else None
        return {
            **j,
            'connector_scope':owner['id'] if owner else None,
            'status':j['state'],
            'progress':round(len(j['checkpoints'])/9*100),
            'output_url':'/api/jobs/'+j['id']+'/files/video.mp4' if j['state']=='completed' else None,
            'project':j.get('request',{}).get('project','Dự án mặc định'),
            'quality_mode':scene_editor.mode(j),
            'visual_quality':j.get('checkpoints',{}).get('verify',{}).get('visual_quality',{'status':'not_checked'}),
            'diagnostics':diag,
            'latest_event':latest_event,
            'events':events[-30:]
        }
    @app.get('/api/projects')
    def get_projects():
        with store.db() as c:
            rows=c.execute('SELECT id, request, state, stage, created, output FROM jobs ORDER BY created DESC').fetchall()
            p_rows=c.execute('SELECT name, created FROM projects ORDER BY created DESC').fetchall()
        projects_dict={}
        for r in rows:
            try:req=json.loads(r['request'])
            except Exception:req={}
            pname=req.get('project') or 'Dự án mặc định'
            out_url=f"/api/jobs/{r['id']}/files/video.mp4" if r['state']=='completed' else None
            thumb=None
            if r['output']:
                img0=Path(r['output'])/'images-0000.png'
                if img0.is_file():thumb=f"/api/jobs/{r['id']}/files/images-0000.png"
            if pname not in projects_dict:
                projects_dict[pname]={
                    'name':pname,
                    'count':1,
                    'latest_id':r['id'],
                    'latest_state':r['state'],
                    'latest_stage':r['stage'],
                    'latest_created':r['created'],
                    'latest_video':out_url,
                    'thumbnail':thumb,
                    'idea':req.get('idea','')
                }
            else:
                projects_dict[pname]['count']+=1
                if not projects_dict[pname]['thumbnail'] and thumb:
                    projects_dict[pname]['thumbnail']=thumb
                if not projects_dict[pname]['latest_video'] and out_url:
                    projects_dict[pname]['latest_video']=out_url
        for pr in p_rows:
            if pr['name'] not in projects_dict:
                projects_dict[pr['name']]={'name':pr['name'],'count':0,'latest_id':None,'latest_state':None,'latest_stage':None,'latest_created':pr['created'],'latest_video':None,'thumbnail':None,'idea':''}
        if 'Dự án mặc định' not in projects_dict:
            projects_dict['Dự án mặc định']={'name':'Dự án mặc định','count':0,'latest_id':None,'latest_state':None,'latest_stage':None,'latest_created':time.time(),'latest_video':None,'thumbnail':None,'idea':''}
        items=sorted(list(projects_dict.values()),key=lambda x:x['latest_created'] or 0,reverse=True)
        return {'items':items,'projects':[x['name'] for x in items]}
    @app.post('/api/projects')
    def create_project(data:dict,request:Request):
        same_origin(request)
        pname=data.get('name','').strip()
        if not pname or len(pname)>200:raise HTTPException(422,'Tên dự án không hợp lệ')
        with store.db() as c:
            c.execute('INSERT OR IGNORE INTO projects VALUES(?,?)',(pname,time.time()))
        return {'ok':True,'name':pname}
    @app.post('/api/jobs/{job_id}/retry')
    def retry_job(job_id:str,data:dict|None=None,request:Request=None):
        if request:same_origin(request)
        try:j=store.get(job_id)
        except KeyError:raise HTTPException(404,'Job not found')
        if j['state']!='failed':raise HTTPException(400,'Chỉ có thể thử lại job ở trạng thái thất bại')
        stage=j['stage']
        new_idea=(data or {}).get('idea')
        with store.db() as c:
            if new_idea and isinstance(new_idea,str) and new_idea.strip():
                req=j['request'];req['idea']=new_idea.strip()
                c.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(req,ensure_ascii=False),job_id))
            if stage:
                c.execute('DELETE FROM attempts WHERE job=? AND stage=?',(job_id,stage))
            c.execute("UPDATE jobs SET state='queued',error=NULL,next_at=0,updated=? WHERE id=?",(time.time(),job_id))
            store.event(c,job_id,stage,'retried','Người dùng yêu cầu thử lại bước '+str(stage))
        return public_job(store.get(job_id))
    @app.post('/api/jobs/{job_id}/change-voice')
    def change_voice(job_id:str,data:dict,request:Request):
        same_origin(request)
        new_voice=data.get('voice_id','').strip()
        if not new_voice:raise HTTPException(422,'Vui lòng chọn giọng đọc mới')
        pitch_val=data.get('pitch',0)
        import math
        if isinstance(pitch_val,bool) or not isinstance(pitch_val,(int,float)) or not math.isfinite(pitch_val) or not (-12<=pitch_val<=12):
            raise HTTPException(422,'Pitch phải là số thực hữu hạn trong khoảng -12 đến 12')
        try:voices.selected(new_voice)
        except Exception as e:raise HTTPException(422,f'Giọng đọc không khả dụng: {e}')
        try:
            job=store.create_derived(job_id,new_voice,pitch=round(float(pitch_val),1))
            return public_job(job)
        except KeyError:raise HTTPException(404,'Job not found')
        except ValueError as e:raise HTTPException(400,str(e))
    @app.get('/api/system/logs')
    def system_logs():
        with store.db() as c:
            events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 50').fetchall()]
        comfy_log=''
        clog=ROOT.parent/'1_SD_and_workflow'/'ComfyUI-Easy-Install'/'ComfyUI-Easy-Install'/'ComfyUI'/'user'/'comfyui.log'
        if clog.is_file():
            try:comfy_log='\n'.join(clog.read_text(encoding='utf-8',errors='replace').splitlines()[-40:])
            except Exception:pass
        return {'events':events,'comfy_log':comfy_log}
    @app.get('/api/preflight')
    def preflight(scope:str|None=None):
        result=pipeline.preflight(scope) if isinstance(pipeline,Pipeline) else pipeline.preflight()
        result['checks']=[{**c,'message':c.get('message',c.get('detail',''))} for c in result['checks']]
        return result
    def browser_endpoint():
        from urllib.parse import urlparse
        url=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/')
        p=urlparse(url)
        if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password:
            raise HTTPException(503,'Only loopback dedicated browser daemon allowed')
        return url
    def browser_request_local(request):
        from urllib.parse import urlparse
        try:
            host=urlparse('//'+request.headers.get('host',''))
            allowed=host.hostname in ('127.0.0.1','localhost','::1') and not (host.username or host.password or host.path or host.query or host.fragment)
        except ValueError:allowed=False
        if not allowed:raise HTTPException(403,'Loopback Host required for browser control')
    @app.get('/api/browser/status')
    def browser_status(request:Request):
        import httpx
        browser_request_local(request)
        try:
            r=httpx.get(browser_endpoint()+'/api/status',timeout=2,trust_env=False)
            if r.status_code!=200:raise HTTPException(503,'Browser service unavailable')
            return r.json()
        except httpx.HTTPError:raise HTTPException(503,'Start the dedicated VideoStudio browser service first')
    def browser_control(action,request):
        import httpx
        browser_request_local(request)
        same_origin(request)
        try:
            r=httpx.post(browser_endpoint()+'/api/browser/'+action,json={},headers={'X-VS-Client':'videostudio'},timeout=40,trust_env=False)
            data=r.json()
            if r.status_code!=200:raise HTTPException(r.status_code,data.get('error','Browser check failed'))
            return data
        except httpx.HTTPError:raise HTTPException(503,'Dedicated browser service unavailable; no extension fallback')
    @app.post('/api/browser/start')
    def browser_start(request:Request):return browser_control('start',request)
    @app.post('/api/browser/probe')
    def browser_probe(request:Request):return browser_control('probe',request)
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
    @app.post('/api/voices/clone')
    async def clone_voice(data:dict,request:Request):
        same_origin(request)
        name=data.get('name','').strip()
        if not name:raise HTTPException(422,'Tên giọng đọc không được để trống')
        audio_b64=data.get('audio_base64','')
        if not audio_b64:raise HTTPException(422,'Thiếu dữ liệu âm thanh mẫu')
        duration=max(3.0,min(60.0,float(data.get('duration',15.0))))
        import base64,uuid,subprocess
        from .core import digest
        try:
            raw_bytes=base64.b64decode(audio_b64.split('base64,')[-1])
        except Exception:raise HTTPException(422,'Dữ liệu âm thanh không hợp lệ')
        if len(raw_bytes)<1000:raise HTTPException(422,'Tệp âm thanh quá ngắn hoặc rỗng')
        vdir=ROOT/'data'/'voices';vdir.mkdir(parents=True,exist_ok=True)
        vid=str(uuid.uuid4())
        tmp_in=vdir/f'tmp-in-{vid}.bin'
        ref_wav=vdir/f'ref-{vid}.wav'
        prev_wav=vdir/f'preview-{vid}.wav'
        try:
            tmp_in.write_bytes(raw_bytes)
            subprocess.run([pipeline.ffmpeg,'-y','-v','error','-i',str(tmp_in),'-t',str(duration),'-ar','16000','-ac','1',str(ref_wav)],check=True,timeout=30)
            if not ref_wav.is_file() or ref_wav.stat().st_size<1000:
                raise RuntimeError('Chuyển đổi âm thanh mẫu thất bại')
            existing_cache=pipeline.speech_cache
            args=[pipeline.speech_python,'-m','videostudio.speech_worker',json.dumps({
                'text':'Xin chào, đây là giọng đọc mẫu vừa được nhân bản trong VideoStudio.',
                'voice':{'kind':'clone','reference_path':str(ref_wav.resolve()),'sha256':digest(ref_wav)},
                'cache':existing_cache,
                'output':str(prev_wav.resolve())
            },ensure_ascii=False)]
            subprocess.run(args,check=True,timeout=60)
            export_path=ROOT/'data'/'voices-export.json'
            catalog_data={'complete':True,'source':'user_clones','voices':[]}
            if export_path.is_file():
                try:catalog_data=json.loads(export_path.read_text(encoding='utf-8'))
                except Exception:pass
            entry={
                'id':f'clone:{vid}',
                'name':name,
                'gender':'custom',
                'region':'custom',
                'style':'clone',
                'description':f'Giọng clone từ mẫu {duration:.0f}s',
                'source':'VideoStudio-Clone',
                'kind':'clone',
                'reference_path':str(ref_wav.resolve()),
                'sample_path':str(prev_wav.resolve()),
                'sha256':digest(ref_wav)
            }
            catalog_data.setdefault('voices',[]).append(entry)
            export_path.write_text(json.dumps(catalog_data,ensure_ascii=False,indent=2),encoding='utf-8')
            return {'ok':True,'voice':{'id':entry['id'],'name':entry['name'],'sample_url':f'/api/voices/{entry["id"]}/sample'}}
        finally:
            if tmp_in.is_file():tmp_in.unlink(missing_ok=True)
    def same_origin(request):
        from urllib.parse import urlparse
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Cross-origin writes denied')
    from .editor_api import register_editor_routes
    register_editor_routes(app,store,scene_editor,same_origin,public_job,image_jobs)
    @app.post('/api/connector/sessions')
    def connector_session(request:Request):
        same_origin(request)
        scope=exchanges.scope()
        return {'project_id':scope,'run_id':scope,'url':f'/story-video/projects/{scope}/production'}
    @app.post('/api/connector/status/{scope}')
    def report_connector(scope:str,data:dict,request:Request):
        same_origin(request)
        try:exchanges.pending(scope)
        except KeyError:raise HTTPException(404,'Scope not found')
        # Informational heartbeat only, never grants authorization or readiness.
        from .connector_diagnostics import sanitize_status
        allowed=sanitize_status(data)
        import json
        with store.db() as c:
            previous=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(scope,)).fetchone()
            # A second Studio tab reports other_run; it must not replace the
            # fresh owner-tab heartbeat. This remains informational, not auth.
            if previous:
                old=json.loads(previous['status'])
                if allowed.get('stage')=='other_run' and old.get('enabled') is True and old.get('build')==allowed.get('build') and time.time()-previous['updated']<30:
                    return {'recorded':False,'reason':'non_owner_tab'}
            c.execute('INSERT OR REPLACE INTO connector_status VALUES(?,?,?)',(scope,json.dumps(allowed),time.time()))
        return {'recorded':True}
    @app.post('/api/connector/smoke/{scope}')
    def smoke_connector(scope:str,request:Request):
        same_origin(request)
        try:identifier=exchanges.enqueue(scope,'Engineering connection test only. Return exactly one JSON object: {"connection_test":"videostudio","ok":true}. Do not create media or use tools.')
        except KeyError:raise HTTPException(404,'Scope not found')
        return {'exchange_id':identifier}
    @app.get('/api/connector/status')
    def connector_status():
        import json
        with store.db() as c:rows=c.execute('SELECT * FROM connector_status ORDER BY updated DESC LIMIT 10').fetchall()
        return {'items':[{'scope':r['scope'],'status':json.loads(r['status']),'updated':r['updated']} for r in rows]}
    prefix='/api/v1/projects/{project_id}/runs/{run_id}/chatgpt-exchanges'
    def checked_scope(project_id,run_id):
        if project_id!=run_id:raise HTTPException(404,'Scope not found')
        return project_id
    @app.get(prefix)
    def pending(project_id:str,run_id:str):
        try:return exchanges.pending(checked_scope(project_id,run_id))
        except KeyError:raise HTTPException(404,'Scope not found')
    @app.get(prefix+'/{exchange_id}')
    def receipt(project_id:str,run_id:str,exchange_id:str):
        try:r=exchanges.get(checked_scope(project_id,run_id),exchange_id)
        except KeyError:raise HTTPException(404,'Exchange not found')
        return {'id':r['id'],'version':r['version'],'accepted':r['response'] is not None}
    @app.post(prefix+'/{exchange_id}/response')
    def response(project_id:str,run_id:str,exchange_id:str,data:dict,request:Request):
        same_origin(request)
        try:return exchanges.receive(checked_scope(project_id,run_id),exchange_id,data.get('expected_version'),data.get('response_text'))
        except KeyError:raise HTTPException(404,'Exchange not found')
        except ValueError as e:raise HTTPException(422,str(e))
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
            pf=pipeline.preflight(request.headers.get('x-connector-scope')) if isinstance(pipeline,Pipeline) else pipeline.preflight()
            if not pf['ready']:
                raise HTTPException(503,{'message':'Production preflight blocked','checks':[c for c in pf['checks'] if not c['ok']]})
        scope=request.headers.get('x-connector-scope')
        if isinstance(pipeline,Pipeline) and os.getenv('VS_LLM_TRANSPORT','cdp')=='chrome' and not scope:
            raise HTTPException(422,'Existing Chrome connector scope required')
        if scope:
            with store.db() as c:
                bound=c.execute('SELECT job FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if bound is None:raise HTTPException(422,'Unknown connector scope')
            if bound['job'] and (previous is None or previous['id']!=bound['job']):raise HTTPException(409,'Connector scope already owns another job; open a new video session')
        try:
            job,created=store.create(data,idempotency_key,scope)
            if scope:exchanges.bind(scope,job['id'])
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
    @app.post('/api/jobs/{job_id}/resume')
    def resume(job_id:str,request:Request):
        same_origin(request)
        scope=request.headers.get('x-connector-scope')
        if not scope:raise HTTPException(422,'Connector scope required')
        import json
        with store.db() as c:status=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(scope,)).fetchone()
        if not status or json.loads(status['status']).get('build')!='0.1.25' or time.time()-status['updated']>120:
            raise HTTPException(409,'Reload connector 0.1.25 and refresh this Studio tab before continuing; no attempt budget changed')
        # The page's REAL Resume click starts the existing extension handler.
        # This API never invokes or simulates extension authorization itself.
        try:return public_job(store.resume(job_id,scope))
        except KeyError:raise HTTPException(404,'Job not found')
        except ValueError as e:raise HTTPException(409,str(e))
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
    if static.is_dir():
        @app.get('/story-video/projects/{project_id}/production')
        def production_page(project_id:str,connector_test:bool=False):
            try:exchanges.pending(project_id)
            except KeyError:raise HTTPException(404,'Unknown connector scope')
            return FileResponse(static/('connector-test.html' if connector_test else 'index.html'))
        app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    return app

app=create_app(worker_enabled=os.getenv('VS_WORKER_ENABLED','1')=='1')

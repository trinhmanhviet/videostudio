from __future__ import annotations
from .paths import DATA_ROOT, VOICE_ROOT
import json, os, sqlite3, threading, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .core import Store, Worker, PermanentError, validate_request, available_flow_batch_sizes
from .plain_text import is_user_script, strip_markdown
from .voices import Voices
from .providers import Pipeline

ROOT=Path(__file__).resolve().parent.parent

def create_app(store=None,pipeline=None,worker_enabled=True):
    from .output_settings import configured_root
    store=store or Store(os.getenv('VS_DATABASE',str(DATA_ROOT/'jobs.sqlite3')),configured_root())
    default_export=DATA_ROOT/'voices-export.json'
    voices=Voices(VOICE_ROOT,os.getenv('VS_VOICES_EXPORT',str(default_export) if default_export.is_file() else None))
    pipeline=pipeline or Pipeline(voices)
    pipeline.store=store
    from .scene_editor import SceneEditor
    scene_editor=SceneEditor(store);pipeline.scene_editor=scene_editor
    from .scene_images import SceneImageJobs
    image_jobs=SceneImageJobs(store,scene_editor);image_jobs.pipeline=pipeline
    from .flow_account import FlowAccountService
    flow_accounts=FlowAccountService(store,scene_editor)
    pipeline.flow_accounts=flow_accounts
    from .browser_manager import BrowserManager
    def browser_active_jobs():
        with store.db() as connection:
            states="('running')" if flow_accounts.blocks_workers() else "('queued','running','retrying')"
            count=connection.execute('SELECT COUNT(*) FROM jobs WHERE state IN '+states).fetchone()[0]
            count+=connection.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_studio_tasks'").fetchone():
                count+=connection.execute("SELECT COUNT(*) FROM voice_studio_tasks WHERE state IN ('queued','running')").fetchone()[0]
            if connection.execute("SELECT 1 FROM worker_lock WHERE owner LIKE 'voice-clone-%' AND expires>?",(time.time(),)).fetchone():count+=1
            if flow_accounts.blocks_browser_changes():count=max(count,1)
            return count
    browser_manager=BrowserManager(active_jobs=browser_active_jobs)
    from .exchanges import Exchanges, EXTENSION_HEARTBEAT_SECONDS
    exchanges=Exchanges(store)
    from .project_lifecycle import ProjectLifecycle, deleted_job_ids, reject_deleted_project, reject_retired_job
    project_lifecycle=ProjectLifecycle(store)
    if hasattr(pipeline,'use_exchanges'):pipeline.use_exchanges(exchanges)
    worker=Worker(store,pipeline.handlers());stop=threading.Event();working=threading.Event()
    factory=None;publisher=None;posted_cleanup=None;voice_studio=None
    def loop():
        while not stop.is_set():
            if flow_accounts.blocks_workers():stop.wait(.5);continue
            working.set()
            try:
                if factory:
                    try:factory.tick()
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception('Factory admission tick failed; existing jobs continue')
                did=image_jobs.step(worker.owner) or worker.step() or (voice_studio.step(worker.owner) if voice_studio else False)
            except Exception:did=False
            finally:working.clear()
            if not did:stop.wait(.5)
    def heartbeat():
        while not stop.wait(5):
            if working.is_set():store.lock(worker.owner)
    def publishing_loop():
        while not stop.is_set():
            try:
                if publisher:publisher.tick()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Publishing scheduler tick failed')
            stop.wait(5)
    def cleanup_loop():
        while not stop.is_set():
            try:
                if posted_cleanup:posted_cleanup.tick()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Publication cleanup will retry')
            if posted_cleanup:
                posted_cleanup.wake.wait(1)
                posted_cleanup.wake.clear()
            else:stop.wait(1)
    @asynccontextmanager
    async def lifespan(app):
        threads=[]
        if worker_enabled:
            if posted_cleanup:posted_cleanup.recover()
            flow_accounts.recover_after_restart()
            if voice_studio:voice_studio.recover()
            for target in (loop,heartbeat,publishing_loop,cleanup_loop):
                t=threading.Thread(target=target,daemon=True);t.start();threads.append(t)
        yield
        stop.set()
        # Running stage checks cancellation through store; shutdown leaves running
        # checkpoint recoverable, rather than falsely changing it to success.
        for t in threads:t.join(timeout=2)
    app=FastAPI(title='VideoStudio local',lifespan=lifespan)
    app.state.store=store;app.state.pipeline=pipeline;app.state.image_jobs=image_jobs;app.state.flow_accounts=flow_accounts
    @app.middleware('http')
    async def revalidate_pages(request,call_next):
        # Pages name their scripts with ?v=; without this a browser or phone keeps an old page
        # (and so old scripts) from heuristic caching. ETag keeps the revalidation cheap.
        response=await call_next(request)
        if response.headers.get('content-type','').startswith('text/html') and 'cache-control' not in response.headers:
            response.headers['Cache-Control']='no-cache'
        return response
    # Explicit request lab only; video jobs keep their existing Flow provider.
    from FlowAPI.server import create_router as flow_request_router
    app.include_router(flow_request_router(store.path.parent/'flow-request.sqlite3'))
    @app.get('/api/health')
    def health():return {'status':'ok','service':'videostudio','durable':True,'worker_enabled':worker_enabled,'text_transport':os.getenv('VS_LLM_TRANSPORT','cdp'),'chatgpt_scene_images':True,'comfy_scene_images':True,'flow_scene_images':True,'flow_batch_sizes':available_flow_batch_sizes()}
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
            'output_wide_url':'/api/jobs/'+j['id']+'/files/video-ngang.mp4' if j['state']=='completed' and j['checkpoints'].get('render',{}).get('video_ngang') else None,
            'output_names':{'doc':Path(j['checkpoints']['render']['video']).name,'ngang':Path(j['checkpoints']['render']['video_ngang']).name} if j['checkpoints'].get('render',{}).get('video_ngang') else None,
            'project':j.get('request',{}).get('project','Dự án mặc định'),
            'quality_mode':scene_editor.mode(j),
            'visual_quality':j.get('checkpoints',{}).get('verify',{}).get('visual_quality',{'status':'not_checked'}),
            'diagnostics':diag,
            'latest_event':latest_event,
            'events':events[-30:]
        }
    @app.get('/api/projects')
    def get_projects(archived:bool=False,q:str="",page:int=1,page_size:int|None=None):
        if page<1 or (page_size is not None and page_size not in (10,20,30)):raise HTTPException(422,"Invalid project pagination")
        with store.db() as c:
            hidden=deleted_job_ids(c)
            rows=[r for r in c.execute('SELECT id, request, state, stage, created, output FROM jobs ORDER BY created DESC').fetchall() if r['id'] not in hidden]
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
        metadata=project_lifecycle.metadata()
        search=q.strip().casefold()
        matching_names=set()
        if search:
            for r in rows:
                try:req=json.loads(r['request'])
                except (ValueError,TypeError):continue
                if search in str(req.get('idea','')).casefold():matching_names.add(req.get('project') or 'Dự án mặc định')
        items=[dict(item,archived=bool(metadata.get(item['name'],{}).get('archived',False))) for item in items
               if not metadata.get(item['name'],{}).get('deleted')
               and bool(metadata.get(item['name'],{}).get('archived',False))==archived
               and (not search or search in item['name'].casefold() or item['name'] in matching_names)]
        total=len(items);total_pages=max(1,(total+page_size-1)//page_size) if page_size else 1
        if page_size:items=items[(page-1)*page_size:page*page_size]
        return {'items':items,'projects':[x['name'] for x in items],'page':page,'page_size':page_size,'total':total,'total_pages':total_pages}
    def project_input(data):
        name=data.get('name')
        if not isinstance(name,str) or not name.strip() or len(name.strip())>200:raise HTTPException(422,'Tên dự án không hợp lệ')
        return name.strip()
    @app.post('/api/projects/archive')
    def archive_project(data:dict,request:Request):
        same_origin(request);name=project_input(data)
        if type(data.get('archived')) is not bool:raise HTTPException(422,'archived phải là boolean')
        try:return project_lifecycle.archive(name,data['archived'])
        except KeyError:raise HTTPException(404,'Project not found')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.post('/api/projects/delete')
    def delete_project(data:dict,request:Request):
        same_origin(request);name=project_input(data)
        if data.get('confirm') is not True:raise HTTPException(422,'Cần xác nhận xóa dự án')
        if type(data.get('delete_files',False)) is not bool:raise HTTPException(422,'delete_files phải là boolean')
        try:return project_lifecycle.delete(name,data.get('delete_files',False))
        except KeyError:raise HTTPException(404,'Project not found')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.post('/api/projects')
    def create_project(data:dict,request:Request):
        same_origin(request)
        pname=project_input(data)
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            try:reject_deleted_project(c,pname)
            except ValueError as error:raise HTTPException(409,str(error))
            c.execute('INSERT OR IGNORE INTO projects VALUES(?,?)',(pname,time.time()))
        return {'ok':True,'name':pname}
    @app.post('/api/jobs/{job_id}/retry')
    def retry_job(job_id:str,data:dict|None=None,request:Request=None):
        if request:same_origin(request)
        try:j=store.get(job_id)
        except KeyError:raise HTTPException(404,'Job not found')
        resume_cancelled=(data or {}).get('resume_cancelled') is True
        resumable_stages=('speech','images','subtitles','music','render','verify')
        from .meme_animation import enabled as animated_meme
        resume_script=(j['stage']=='script' and animated_meme(j) and all(s in j['checkpoints'] for s in ('plan','research')))
        if j['state']!='failed' and not (j['state']=='cancelled' and resume_cancelled and ((j['stage'] in resumable_stages and 'script' in j['checkpoints']) or resume_script)):
            raise HTTPException(400,'Chỉ thử lại job lỗi hoặc chủ động tiếp tục job đã hủy sau bước kịch bản')
        stage=j['stage']
        new_idea=(data or {}).get('idea')
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT state,cancel,stage FROM jobs WHERE id=?',(job_id,)).fetchone()
            if current['state'] not in ('failed','cancelled'):raise HTTPException(400,'Trạng thái job đã thay đổi; hãy làm mới trang')
            if current['state']=='cancelled' and (not resume_cancelled or (current['stage'] not in resumable_stages and not resume_script)):raise HTTPException(400,'Cần chủ động chọn tiếp tục job đã hủy')
            if c.execute("SELECT 1 FROM flow_account_changes WHERE job=? AND json_extract(data,'$.needs_quiescence')=1",(job_id,)).fetchone():raise HTTPException(409,'Flow chưa xác nhận dừng thao tác cũ; hãy chuẩn bị lại kết nối Flow trước')
            try:reject_retired_job(c,job_id)
            except ValueError as error:raise HTTPException(409,str(error))
            if new_idea and isinstance(new_idea,str) and new_idea.strip():
                req=j['request'];req['idea']=(strip_markdown(new_idea) if is_user_script(req) else '') or new_idea.strip()
                c.execute('UPDATE jobs SET request=? WHERE id=?',(json.dumps(req,ensure_ascii=False),job_id))
            if stage:
                c.execute('DELETE FROM attempts WHERE job=? AND stage=?',(job_id,stage))
            if current['state']=='cancelled' and resume_script:
                exchanges.restart_cancelled_script_scope(c,job_id)
            c.execute("UPDATE jobs SET state='queued',cancel=0,error=NULL,next_at=0,updated=? WHERE id=?",(time.time(),job_id))
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
    @app.post('/api/jobs/{job_id}/reset-images')
    def reset_images(job_id:str,data:dict|None=None,request:Request=None):
        if request:same_origin(request)
        data=data or {}
        provider=data.get('image_provider')
        batch_size=data.get('flow_batch_size')
        try:
            job=store.reset_stage_images(job_id,image_provider=provider,flow_batch_size=batch_size)
            return public_job(job)
        except KeyError:raise HTTPException(404,'Job not found')
        except ValueError as e:raise HTTPException(400,str(e))
    @app.get('/api/system/logs')
    def system_logs():
        with store.db() as c:
            events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 50').fetchall()]
        comfy_log=''
        clog=ROOT.parents[1]/'1_SD_and_workflow'/'ComfyUI-Easy-Install'/'ComfyUI-Easy-Install'/'ComfyUI'/'user'/'comfyui.log'
        if clog.is_file():
            try:comfy_log='\n'.join(clog.read_text(encoding='utf-8',errors='replace').splitlines()[-40:])
            except Exception:pass
        return {'events':events,'comfy_log':comfy_log}
    @app.get('/api/preflight')
    def preflight(scope:str|None=None,workflow_mode:str|None=None,meme_engine:str|None=None):
        result=pipeline.preflight(scope) if isinstance(pipeline,Pipeline) else pipeline.preflight()
        from .meme_animation import preflight_for_request
        result=preflight_for_request(result,{'workflow_mode':workflow_mode,'meme_engine':meme_engine})
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
    @app.get('/api/browser/profile')
    def browser_profile_status(request:Request):
        browser_request_local(request)
        try:return browser_manager.status()
        except RuntimeError as error:raise HTTPException(503,str(error))
    @app.post('/api/browser/profile/open')
    def browser_profile_open(data:dict,request:Request):
        browser_request_local(request);same_origin(request)
        if set(data)!={'mode'} or data.get('mode') not in ('clean','debug'):raise HTTPException(422,'Chọn Mở sạch hoặc Mở debug; profile được giữ cố định.')
        try:return browser_manager.open(data['mode'])
        except ValueError as error:raise HTTPException(409,str(error))
        except RuntimeError as error:raise HTTPException(503,str(error))
    @app.post('/api/browser/profile/stop')
    def browser_profile_stop(request:Request):
        browser_request_local(request);same_origin(request)
        try:return browser_manager.stop()
        except ValueError as error:raise HTTPException(409,str(error))
        except RuntimeError as error:raise HTTPException(503,str(error))
    def flow_account_response(job_id,request,operation):
        browser_request_local(request)
        if operation!='status':same_origin(request)
        with store.db() as connection:
            owned=connection.execute('SELECT id FROM connector_scopes WHERE job=?',(job_id,)).fetchone()
        if owned:
            bridge=request.headers.get('x-connector-scope')
            if not bridge:raise HTTPException(403,'Kết nối Studio không sở hữu video này.')
            try:exchanges.bridge_job(bridge,job_id)
            except KeyError:raise HTTPException(403,'Kết nối Studio không sở hữu video này.')
        try:return getattr(flow_accounts,operation)(job_id)
        except KeyError:raise HTTPException(404,'Không tìm thấy video.')
        except ValueError as error:raise HTTPException(409,str(error))
        except RuntimeError as error:raise HTTPException(503,str(error))
    @app.get('/api/jobs/{job_id}/flow-account')
    def flow_account_status(job_id:str,request:Request):return flow_account_response(job_id,request,'status')
    @app.post('/api/jobs/{job_id}/flow-account/prepare')
    def flow_account_prepare(job_id:str,request:Request):return flow_account_response(job_id,request,'prepare')
    @app.post('/api/jobs/{job_id}/flow-account/continue')
    def flow_account_continue(job_id:str,request:Request):return flow_account_response(job_id,request,'continue_job')
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
        from .voice_timing import reading_profiles
        profiles=reading_profiles(store,c['voices'])
        # Absolute filesystem paths are server-private, sample URLs are scoped.
        c['voices']=[{k:v for k,v in r.items() if k not in ('reference_path','sample_path','sha256')}|{'sample_url':'/api/voices/'+r['id']+'/sample' if r.get('sample_path') else None,'reading_profile':profiles[r['id']]} for r in c['voices']]
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
        vdir=DATA_ROOT/'voices';vdir.mkdir(parents=True,exist_ok=True)
        vid=str(uuid.uuid4())
        tmp_in=vdir/f'tmp-in-{vid}.bin'
        ref_wav=vdir/f'ref-{vid}.wav'
        prev_wav=vdir/f'preview-{vid}.wav'
        clone_owner='voice-clone-'+vid
        if browser_active_jobs() or not store.lock(clone_owner,ttl=120):
            raise HTTPException(409,'GPU đang được dùng hoặc có tác vụ chờ. Hãy đợi trước khi thêm giọng từ bản thu.')
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
            export_path=DATA_ROOT/'voices-export.json'
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
            store.release(clone_owner)
    def same_origin(request):
        from urllib.parse import urlparse
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'Cross-origin writes denied')
    from .voice_studio_api import register_voice_studio
    voice_studio=register_voice_studio(app,store,pipeline,voices,same_origin)
    voice_studio.stop_event=stop
    @app.get('/api/system/status')
    def system_status(request:Request):
        browser_request_local(request)
        active=browser_active_jobs()
        return {'status':'running','port':8877,'active_jobs':active,'cdp_port':8879}
    @app.post('/api/system/stop')
    def system_stop(request:Request,data:dict|None=None):
        browser_request_local(request);same_origin(request)
        data=data or {}
        force=bool(data.get('force',False))
        active=browser_active_jobs()
        if active>0 and not force:
            raise HTTPException(409,f'Có {active} tác vụ đang chạy. Hãy hủy video trước hoặc chọn Buộc tắt.')
        import subprocess
        flags=0
        if os.name=='nt':
            flags=getattr(subprocess,'DETACHED_PROCESS',0x00000008)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0x00000200)
        script=str(ROOT/'scripts'/'stop_system.ps1')
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',f"Start-Sleep -Milliseconds 600; & '{script}'"+(' -Force' if force else '')]
        subprocess.Popen(cmd,creationflags=flags,close_fds=True)
        return {'ok':True,'message':'VideoStudio đang tắt...'}
    @app.post('/api/system/restart')
    def system_restart(request:Request,data:dict|None=None):
        browser_request_local(request);same_origin(request)
        data=data or {}
        force=bool(data.get('force',False))
        active=browser_active_jobs()
        if active>0 and not force:
            raise HTTPException(409,f'Có {active} tác vụ đang chạy. Hãy hủy video trước hoặc chọn Buộc khởi động lại.')
        import subprocess
        flags=0
        if os.name=='nt':
            flags=getattr(subprocess,'DETACHED_PROCESS',0x00000008)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0x00000200)
        script=str(ROOT/'scripts'/'restart_system.ps1')
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',f"Start-Sleep -Milliseconds 600; & '{script}'"+(' -Force' if force else '')]
        subprocess.Popen(cmd,creationflags=flags,close_fds=True)
        return {'ok':True,'message':'VideoStudio đang khởi động lại...'}
    from .editor_api import register_editor_routes
    register_editor_routes(app,store,scene_editor,same_origin,public_job,image_jobs)
    from .job_details import register_job_details_routes
    register_job_details_routes(app,store,scene_editor,same_origin)
    from .workflow_api import register_workflow_routes
    register_workflow_routes(app,store,same_origin)
    from .edit_plan_api import register_edit_plan_routes
    edit_plan_service=register_edit_plan_routes(app,store,same_origin,public_job,ffmpeg=getattr(pipeline,'ffmpeg','ffmpeg'),ffprobe=getattr(pipeline,'ffprobe','ffprobe'))
    app.state.edit_plan_service=edit_plan_service
    pipeline.edit_plan_service=edit_plan_service
    @app.post('/api/connector/sessions')
    def connector_session(request:Request):
        same_origin(request)
        scope=exchanges.scope()
        return {'project_id':scope,'run_id':scope,'url':f'/story-video/projects/{scope}/production'}
    @app.post('/api/connector/status/{scope}')
    def report_connector(scope:str,data:dict,request:Request):
        # The extension service worker can keep its existing bridge heartbeat
        # alive while Studio is throttled. This exception is status-only.
        import re
        origin=request.headers.get('origin','')
        if re.fullmatch(r'chrome-extension://[a-p]{32}',origin) and request.headers.get('x-vs-client')=='videostudio-extension':
            browser_request_local(request)
        else:same_origin(request)
        try:exchanges.pending(scope)
        except KeyError:raise HTTPException(404,'Scope not found')
        # Informational heartbeat only; a correlated latest smoke is still required.
        from .connector_diagnostics import sanitize_status
        allowed=sanitize_status(data)
        import json
        with store.db() as c:
            previous=c.execute('SELECT status,updated FROM connector_status WHERE scope=?',(scope,)).fetchone()
            # A second Studio tab reports other_run; it must not replace the
            # fresh owner-tab heartbeat. This remains informational, not auth.
            if previous:
                old=json.loads(previous['status'])
                if allowed.get('stage')=='other_run' and old.get('enabled') is True and old.get('build')==allowed.get('build') and time.time()-previous['updated']<=EXTENSION_HEARTBEAT_SECONDS:
                    return {'recorded':False,'reason':'non_owner_tab'}
            c.execute('INSERT OR REPLACE INTO connector_status VALUES(?,?,?)',(scope,json.dumps(allowed),time.time()))
        return {'recorded':True}
    @app.post('/api/connector/smoke/{scope}')
    def smoke_connector(scope:str,request:Request):
        same_origin(request)
        try:identifier=exchanges.enqueue_smoke(scope)
        except KeyError:raise HTTPException(404,'Scope not found')
        except PermanentError as e:raise HTTPException(409,str(e))
        return {'exchange_id':identifier}
    @app.get('/api/connector/status')
    def connector_status():
        import json
        with store.db() as c:rows=c.execute('SELECT * FROM connector_status ORDER BY updated DESC LIMIT 10').fetchall()
        return {'items':[{'scope':r['scope'],'status':json.loads(r['status']),'updated':r['updated']} for r in rows]}
    @app.get('/api/connector/bridges/{bridge}/sessions')
    def bridge_sessions(bridge:str):
        try:return exchanges.bridge_sessions(bridge)
        except KeyError:raise HTTPException(404,'Bridge not found')
    @app.get('/api/connector/bridges/{bridge}/status')
    def bridge_status(bridge:str):
        try:
            exchanges.bridge_root(bridge)
            return exchanges.extension_status(bridge)
        except KeyError:raise HTTPException(404,'Bridge not found')
    @app.get('/api/connector/bridges/{bridge}/pending')
    def bridge_pending(bridge:str):
        try:return exchanges.bridge_pending(bridge)
        except KeyError:raise HTTPException(404,'Bridge not found')
    @app.get('/api/connector/bridges/{bridge}/jobs/{job_id}')
    def bridge_job(bridge:str,job_id:str):
        try:return exchanges.bridge_job(bridge,job_id)
        except KeyError:raise HTTPException(404,'Job not found in bridge')
    @app.post('/api/connector/bridges/{bridge}/jobs/{job_id}/dismiss')
    def dismiss_bridge_job(bridge:str,job_id:str,request:Request,data:dict|None=None):
        same_origin(request);data=data or {}
        if type(data.get('delete_files',False)) is not bool:raise HTTPException(422,'delete_files phải là boolean')
        if data.get('delete_files') is True and data.get('confirm') is not True:raise HTTPException(422,'Cần xác nhận xóa tệp')
        try:return exchanges.dismiss_job(bridge,job_id,delete_files=data.get('delete_files',False))
        except KeyError:raise HTTPException(404,'Job not found in bridge')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.post('/api/connector/bridges/{bridge}/jobs/{job_id}/cancel')
    def bridge_cancel(bridge:str,job_id:str,request:Request):
        same_origin(request)
        try:sessions=exchanges.bridge_sessions(bridge)['items']
        except KeyError:raise HTTPException(404,'Bridge not found')
        if not any(item['job_id']==job_id for item in sessions):raise HTTPException(404,'Job not found in bridge')
        store.cancel(job_id)
        return next(item for item in exchanges.bridge_sessions(bridge)['items'] if item['job_id']==job_id)
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
        # Graph compilation belongs to the new-job submission boundary, not
        # Store.validate_request: voice derivatives and editor exports retain
        # explicit scalar overrides while preserving their source graph.
        if 'workflow' in data:
            from .workflow import compile_workflow
            try:data=compile_workflow(data['workflow'],data)
            except ValueError as error:raise HTTPException(422,str(error)) from error
        # Reject new jobs before allocation; existing idempotent receipts remain readable.
        with store.db() as connection:
            previous=connection.execute('SELECT id FROM jobs WHERE idem=?',(idempotency_key,)).fetchone()
        scope=request.headers.get('x-connector-scope')
        extension=os.getenv('VS_LLM_TRANSPORT','cdp')=='extension'
        if previous is None:
            try:
                normalized=validate_request(data)
            except ValueError as error:
                raise HTTPException(422,str(error)) from error
            if os.getenv('VS_LLM_TRANSPORT','cdp') in ('extension','chrome','webauth') and normalized['text_provider']!='chatgpt':
                raise HTTPException(422,'This text transport supports ChatGPT only; select ChatGPT')
            if normalized['flow_batch_size'] not in available_flow_batch_sizes():
                raise HTTPException(422,'Flow image batch size is not validated/enabled on this installation; choose 1 image per batch')
            if extension:
                if not scope:raise HTTPException(422,'Connector bridge scope required')
                try:compatible=exchanges.bridge_supports_sessions(scope)
                except KeyError:raise HTTPException(422,'Unknown connector bridge root')
                if not compatible:raise HTTPException(409,'Reload VideoStudio extension 0.3.0, refresh this Studio tab and start the bridge before creating another video')
            pf=pipeline.preflight(request.headers.get('x-connector-scope')) if isinstance(pipeline,Pipeline) else pipeline.preflight()
            from .speech_engine import preflight_for_request as speech_preflight
            pf=speech_preflight(pf,pipeline,normalized)
            from .meme_animation import preflight_for_request
            pf=preflight_for_request(pf,normalized)
            from .story_pipeline import preflight_for_request as story_preflight
            pf=story_preflight(pf,pipeline,normalized)
            if not pf['ready']:
                raise HTTPException(503,{'message':'Production preflight blocked','checks':[c for c in pf['checks'] if not c['ok']]})
        if isinstance(pipeline,Pipeline) and os.getenv('VS_LLM_TRANSPORT','cdp') in ('chrome','extension') and not scope:
            raise HTTPException(422,'Connector scope required')
        if extension and not scope:raise HTTPException(422,'Connector bridge scope required')
        if scope and not extension:
            with store.db() as c:
                bound=c.execute('SELECT job FROM connector_scopes WHERE id=?',(scope,)).fetchone()
            if bound is None:raise HTTPException(422,'Unknown connector scope')
            if bound['job'] and (previous is None or previous['id']!=bound['job']):raise HTTPException(409,'Connector scope already owns another job; open a new video session')
        try:
            with browser_manager.lock:
                if previous is None and browser_manager.last_mode=='clean' and normalized['image_provider'] in ('flow','chatgpt','meta'):
                    raise HTTPException(409,'Chrome riêng đang mở sạch để đăng nhập. Bấm Mở debug rồi tạo video; tài khoản được giữ nguyên.')
                job,created=store.create(data,idempotency_key,connector_scope=None if extension else scope,connector_bridge=scope if extension else None)
            return {**public_job(job),'job':public_job(job),'created':created}
        except ValueError as e:raise HTTPException(409 if 'already used' in str(e) else 422,str(e))
    @app.get('/api/jobs')
    def jobs():
        with store.db() as c:hidden=deleted_job_ids(c)
        items=[public_job(j) for j in store.list() if j['id'] not in hidden]
        return {'items':items,'jobs':items}
    @app.post('/api/jobs/{job_id}/delete')
    def delete_job(job_id:str,request:Request,data:dict|None=None):
        same_origin(request);data=data or {}
        if type(data.get('delete_files',False)) is not bool:raise HTTPException(422,'delete_files phải là boolean')
        if data.get('confirm') is not True:raise HTTPException(422,'Cần xác nhận xóa video')
        try:return project_lifecycle.delete_job(job_id,data.get('delete_files',False))
        except KeyError:raise HTTPException(404,'Job not found')
        except ValueError as error:raise HTTPException(409,str(error))
    @app.get('/api/jobs/{job_id}')
    def detail(job_id:str):
        try:return public_job(store.get(job_id))
        except KeyError:raise HTTPException(404,'Job not found')
    @app.get('/api/jobs/{job_id}/social')
    def social(job_id:str):
        from . import social_copy
        try:j=store.get(job_id)
        except KeyError:raise HTTPException(404,'Job not found')
        value=social_copy.read(j) or {'state':'none'}
        if value.get('state')=='running' and job_id not in social_copy._running:
            value={**value,'state':'error','error':'Bị gián đoạn khi đang viết; bấm Viết lại.'}
        return value
    @app.post('/api/jobs/{job_id}/social')
    def write_social(job_id:str,request:Request):
        same_origin(request)
        from . import social_copy
        try:j=store.get(job_id)
        except KeyError:raise HTTPException(404,'Job not found')
        if j['state']!='completed':raise HTTPException(409,'Chỉ viết tiêu đề và caption cho video đã xong')
        def ask(prompt):
            pipeline.context.job=job_id;pipeline.context.text_provider=j['request'].get('text_provider','chatgpt')
            try:return pipeline.llm_json(prompt,lambda:None)
            finally:pipeline.context.job=None
        from .meme_editor import _LIB_LOCK
        with _LIB_LOCK:
            try:j=store.get(job_id)
            except KeyError:raise HTTPException(404,'Video đã được dọn hoặc không còn tồn tại')
            social_copy.start(ask,j)
            return social_copy.read(j)
    @app.post('/api/jobs/{job_id}/composer-diagnostics')
    def composer_diagnostics(job_id:str,data:dict,request:Request):
        same_origin(request)
        import uuid
        identifier=data.get('request_id')
        try:uuid.UUID(identifier)
        except (ValueError,TypeError,AttributeError):raise HTTPException(422,'Invalid request ID')
        bridge=request.headers.get('x-connector-scope')
        try:members=exchanges.bridge_sessions(bridge)['items']
        except KeyError:raise HTTPException(403,'Unknown connector bridge')
        if not any(item['job_id']==job_id for item in members):raise HTTPException(403,'Job does not belong to bridge')
        try:
            job=store.get(job_id);scope=exchanges.for_job(job_id)
            record=exchanges.get(scope,identifier)
        except (KeyError,TypeError):raise HTTPException(404,'Scoped request not found')
        attempt=data.get('attempt')
        if type(attempt) is not int or not 1<=attempt<=2 or type(data.get('version')) is not int or data.get('version')!=record['version']:raise HTTPException(422,'Diagnostic request correlation mismatch')
        from .composer_diagnostics import bounded_diagnostic
        try:diagnostic=bounded_diagnostic(data.get('diagnostic'))
        except ValueError as error:raise HTTPException(422,str(error))
        filename=f'composer-diagnostic-{identifier}-attempt{attempt}.json'
        target=Path(job['output'])/filename
        body={'job_id':job_id,'scope':scope,'request_id':identifier,'version':record['version'],'attempt':attempt,'diagnostic':diagnostic}
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.part.json');temporary.write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(target)
        return {'saved':True,'filename':filename}
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
        if name=='video.mp4':
            from .output_layout import final_video_path
            expected=final_video_path(j).resolve()
            recorded=j['checkpoints'].get('render',{}).get('video')
            if recorded and Path(recorded).resolve()==expected:candidate=expected
        if name=='video-ngang.mp4':
            recorded=j['checkpoints'].get('render',{}).get('video_ngang')
            if recorded:candidate=Path(recorded).resolve()
        allowed={Path(a['path']).resolve() for cp in j['checkpoints'].values() for a in cp.get('assets',[])}
        if candidate not in allowed or not candidate.is_file():raise HTTPException(404,'File not checkpointed')
        if name in ('video.mp4','video-ngang.mp4') and j['state']!='completed':raise HTTPException(409,'Video not verified')
        return FileResponse(candidate)
    @app.post('/api/jobs/{job_id}/open-folder')
    def open_video_folder(job_id:str,request:Request,data:dict|None=None):
        browser_request_local(request);same_origin(request)
        data=data or {}
        if set(data)-{'version_id'}:raise HTTPException(422,'Chỉ nhận phiên bản video, không nhận đường dẫn tùy ý')
        try:
            job=store.get(job_id)
            if data.get('version_id'):
                video=Path(factory.get_video_version(job_id,data['version_id'])['path'])
            else:
                from .output_layout import final_video_path
                video=final_video_path(job)
        except KeyError:raise HTTPException(404,'Không tìm thấy video')
        except (ValueError,TypeError):raise HTTPException(409,'Phiên bản video không còn khả dụng')
        if not video.is_file():raise HTTPException(409,'Chưa có file video để mở thư mục')
        try:os.startfile(str(video.resolve().parent))
        except (OSError,AttributeError):raise HTTPException(503,'Không mở được Windows Explorer trên máy chạy VideoStudio')
        return {'opened':True}

    meme_assets = ROOT / 'memestudio' / 'assets'
    if meme_assets.is_dir():
        app.mount('/meme-assets', StaticFiles(directory=meme_assets), name='meme_assets')

    @app.get('/characters')
    def characters_page():
        return FileResponse(ROOT / 'static' / 'characters.html')

    @app.get('/resources')
    def resources_page():
        return FileResponse(ROOT/'static'/'resources.html')

    @app.get('/api/characters')
    def get_characters():
        from .character_store import load_roster
        wardrobe_path = ROOT / 'memestudio' / 'assets' / 'rig' / 'wardrobe' / 'wardrobe.json'
        wardrobe_data = json.loads(wardrobe_path.read_text(encoding='utf-8')) if wardrobe_path.is_file() else {'items': []}
        faces_path = ROOT / 'memestudio' / 'assets' / 'rig' / 'faces' / 'faces.json'
        faces_data = json.loads(faces_path.read_text(encoding='utf-8')) if faces_path.is_file() else {}
        return {
            'characters': load_roster(),
            'catalog': {
                'costumes': [item for item in wardrobe_data.get('items', []) if item.get('kind') == 'costume'],
                'accessories': [item for item in wardrobe_data.get('items', []) if item.get('kind') != 'costume'],
                'faces': faces_data.get('faces', {}),
                'face_names': sorted(faces_data.get('faces', {}).keys()),
                'head': faces_data.get('head', {}),
                'rig': wardrobe_data.get('rig', {}),
                'voices': voices.catalog().get('voices', []) if hasattr(voices, 'catalog') else []
            }
        }

    @app.post('/api/characters')
    async def save_character(request: Request):
        import re
        from .character_store import edit_roster,validate_roster
        same_origin(request)
        try:body=await request.json()
        except ValueError as error:raise HTTPException(422,'Invalid character JSON') from error
        if not isinstance(body,dict):raise HTTPException(422,'Character must be an object')
        cid = str(body.get('id', '')).strip().lower()
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,63}',cid):
            raise HTTPException(400, 'Invalid character ID (must be lowercase alphanumeric and underscores)')
        if not isinstance(body.get('aliases',[]),list):raise HTTPException(422,'aliases must be a list')
        char_data = {
            'id': cid,
            'name': str(body.get('name', cid)).strip(),
            'aliases': [str(a).strip() for a in body.get('aliases', []) if str(a).strip()],
            'costume': str(body.get('costume', 'ao_phong_xanh')),
            'costume_offset': body.get('costume_offset', {'dx': 0, 'dy': 0, 'scale': 1.0}),
            'acc': body.get('acc', []),
            'acc_offsets': body.get('acc_offsets', {}),
            'default_face': str(body.get('default_face', 'noi')),
            'voice': str(body.get('voice', '')),
            'description': str(body.get('description', ''))
        }
        try:
            validate_roster([char_data])
            from .meme_animation_script import AnimationCatalog,validate as validate_appearance
            catalog=AnimationCatalog()
            validate_appearance({'title':['A','B'],'payoff':['A','B'],'cast':{cid:{**char_data,'face':char_data['default_face']}},
                                 'scenes':{'check':{'bg':next(iter(catalog.backgrounds)),'cast':[cid]}}},
                                catalog,{'voice_id':'validation','duration_seconds':15},metadata_only=True)
            def change(rows):
                idx=next((i for i,c in enumerate(rows) if c['id']==cid),None)
                if idx is None:rows.append(char_data)
                else:rows[idx]={**rows[idx],**char_data}
                return rows
            roster=edit_roster(change)
        except ValueError as error:raise HTTPException(422,str(error)) from error
        return {'ok': True, 'character': char_data, 'characters': roster}

    @app.delete('/api/characters/{char_id}')
    def delete_character(char_id: str,request:Request):
        from .character_store import edit_roster
        same_origin(request)
        cid = char_id.strip().lower()
        def change(rows):
            kept=[c for c in rows if c['id'].lower()!=cid]
            if len(kept)==len(rows):raise HTTPException(404,'Character not found')
            return kept
        try:new_roster=edit_roster(change)
        except ValueError as error:raise HTTPException(409,str(error)) from error
        return {'ok': True, 'characters': new_roster}

    # ---- Dynamic Meme Episode Editor & Prop Ingestion Routes ----
    prop_assets_dir = ROOT / 'assets' / 'Meme_Animation_Asset_Pack' / 'catalog' / 'library'
    if prop_assets_dir.is_dir():
        app.mount('/prop-assets', StaticFiles(directory=prop_assets_dir), name='prop_assets')

    @app.get('/meme-editor')
    def meme_editor_page():
        return FileResponse(ROOT / 'static' / 'meme-editor.html')

    @app.get('/api/meme/catalog')
    def get_meme_catalog():
        from .meme_editor import load_prop_library
        from .meme_animation_script import AnimationCatalog
        catalog = AnimationCatalog()
        props = load_prop_library()
        wardrobe_path = ROOT / 'memestudio' / 'assets' / 'rig' / 'wardrobe' / 'wardrobe.json'
        wardrobe_data = json.loads(wardrobe_path.read_text(encoding='utf-8')) if wardrobe_path.is_file() else {'items': []}
        faces_path = ROOT / 'memestudio' / 'assets' / 'rig' / 'faces' / 'faces.json'
        faces_data = json.loads(faces_path.read_text(encoding='utf-8')) if faces_path.is_file() else {}
        return {
            'props': list(props.values()),
            'backgrounds': sorted(list(catalog.backgrounds)),
            'face_names': sorted(faces_data.get('faces', {}).keys()),
            'costumes': [item for item in wardrobe_data.get('items', []) if item.get('kind') == 'costume'],
            'accessories': [item for item in wardrobe_data.get('items', []) if item.get('kind') != 'costume']
        }

    @app.get('/api/meme/jobs/{job_id}/editor')
    def get_meme_job_editor_data(job_id: str):
        from .meme_editor import detect_missing_props, load_prop_library
        try:
            j = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')
        
        ep_dir = Path(j['output']) / 'episode'
        script_file = ep_dir / 'script.json'
        if not script_file.is_file():
            script_file = Path(j['output']) / 'animation-script.json'
            if not script_file.is_file():
                raise HTTPException(404, 'Episode script not found for this job')
        
        script = json.loads(script_file.read_text(encoding='utf-8'))
        props_status = detect_missing_props(script)

        # Video URL if rendered
        from .output_layout import final_video_path
        vid_path = final_video_path(j)
        video_url = f'/api/jobs/{job_id}/files/video.mp4' if vid_path.is_file() else None

        timeline={}
        staging_file=ep_dir/'staging.json'
        if staging_file.is_file():
            try:timeline=json.loads(staging_file.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        return {
            'job_id': job_id,
            'job': public_job(j),
            'script': script,
            'props_status': props_status,
            'video_url': video_url,
            'timeline': timeline
        }

    @app.post('/api/meme/jobs/{job_id}/props/{prop_id}/upload')
    async def upload_meme_prop_asset(job_id: str, prop_id: str, request: Request, label: str | None = None):
        same_origin(request)
        from .meme_editor import _LIB_LOCK, save_prop_asset, update_job_prop_asset, detect_missing_props
        try:
            j = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')

        image_bytes = await request.body()
        if not image_bytes or len(image_bytes) < 32:
            raise HTTPException(422, 'Empty or invalid image file')
        if len(image_bytes) > 20 * 1024 * 1024:
            raise HTTPException(413, 'Image exceeds 20 MB limit')

        try:
            with _LIB_LOCK:
                saved = save_prop_asset(prop_id, image_bytes, label)
                updated_script = update_job_prop_asset(j['output'], prop_id, saved['prop_id'])
                props_status = detect_missing_props(updated_script)
            return {
                'ok': True,
                'prop_id': prop_id,
                'asset': saved['prop_id'],
                'file': saved['file'],
                'props_status': props_status
            }
        except ValueError as err:
            raise HTTPException(422, str(err))

    @app.post('/api/meme/jobs/{job_id}/props/{prop_id}/assign')
    async def assign_meme_prop_asset(job_id: str, prop_id: str, request: Request):
        same_origin(request)
        from .meme_editor import _LIB_LOCK, load_prop_library, update_job_prop_asset, detect_missing_props
        try:
            j = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')

        body = await request.json()
        asset_id = body.get('asset_id')
        if asset_id is not None and not isinstance(asset_id, str):
            raise HTTPException(422, 'asset_id must be string or null')

        with _LIB_LOCK:
            if asset_id is not None and not load_prop_library().get(asset_id, {}).get('exists'):
                raise HTTPException(404, 'Ảnh này không còn trong kho.')
            updated_script = update_job_prop_asset(j['output'], prop_id, asset_id)
            props_status = detect_missing_props(updated_script)
        return {'ok': True, 'props_status': props_status}

    @app.delete('/api/meme/jobs/{job_id}/prop-uploads/{asset_id}')
    def delete_meme_prop_upload(job_id: str, asset_id: str, request: Request):
        same_origin(request)
        from .meme_editor import remove_prop_upload, detect_missing_props
        try:
            job = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')
        if job['request'].get('workflow_mode') != 'meme':
            raise HTTPException(422, 'Chỉ dùng được trong tập hoạt hình.')
        try:
            script = remove_prop_upload(store, job, asset_id)
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(409, str(error)) from error
        return {'ok': True, 'props_status': detect_missing_props(script)}

    @app.post('/api/meme/jobs/{job_id}/update-script')
    async def update_meme_script(job_id: str, request: Request):
        same_origin(request)
        from .meme_editor import _LIB_LOCK, update_episode_script, detect_missing_props
        try:
            j = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, 'Request body must be an object')

        try:
            with _LIB_LOCK:
                updated_script = update_episode_script(j['output'], body)
                props_status = detect_missing_props(updated_script)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'ok': True, 'script': updated_script, 'props_status': props_status}

    @app.post('/api/meme/jobs/{job_id}/re-render')
    def re_render_meme_job(job_id: str, request: Request):
        same_origin(request)
        from .meme_editor import _EDITOR_RENDERS, _LIB_LOCK, re_render_job
        try:
            j = store.get(job_id)
        except KeyError:
            raise HTTPException(404, 'Job not found')

        with _LIB_LOCK:
            if job_id in _EDITOR_RENDERS:
                raise HTTPException(409, 'Tập này đang xuất video.')
            try:j=store.get(job_id)
            except KeyError:raise HTTPException(404,'Video đã được dọn hoặc không còn tồn tại')
            with store.db() as connection:
                try:reject_retired_job(connection,job_id)
                except ValueError as error:raise HTTPException(409,str(error))
            _EDITOR_RENDERS.add(job_id)
        try:
            if factory:factory.remember_verified(job_id)
            result = re_render_job(j, store=store)
            if factory:factory.remember_verified(job_id)
            return {'ok': True, 'result': result}
        except Exception as e:
            raise HTTPException(500, f'Re-rendering failed: {e}')
        finally:
            with _LIB_LOCK:
                _EDITOR_RENDERS.discard(job_id)

    @app.post('/api/meme/props/prompt')
    async def get_prop_prompt(request: Request):
        same_origin(request)
        from .meme_editor import build_prop_prompt
        body = await request.json()
        label = str(body.get('label', '')).strip()
        prop_id = str(body.get('prop_id', '')).strip()
        if not label and not prop_id:
            raise HTTPException(422, 'label or prop_id required')
        return build_prop_prompt(label, prop_id)

    @app.get('/api/resources')
    def resources():
        usage={}
        with store.db() as connection:
            rows=connection.execute('SELECT output FROM jobs').fetchall()
        for row in rows:
            source=Path(row['output'])/'episode'/'script.json'
            if not source.is_file():source=Path(row['output'])/'animation-script.json'
            try:script=json.loads(source.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            props=script.get('props',{})
            if not isinstance(props,dict):continue
            for identifier in {card.get('asset') for card in props.values() if isinstance(card,dict) and isinstance(card.get('asset'),str)}:
                usage[identifier]=usage.get(identifier,0)+1
        from .meme_editor import load_prop_library
        library=load_prop_library()
        layouts={key:card['handheld_layout'] for key,card in library.items() if card.get('handheld_layout')}
        return {'sfx':list(resource_sfx().values()),'prop_usage':usage,'prop_layouts':layouts}

    def resource_sfx():
        source=ROOT/'memestudio'/'assets'/'sfx'/'manifest.json'
        try:assets=json.loads(source.read_text(encoding='utf-8')).get('assets',[])
        except (OSError,ValueError):assets=[]
        allowed=[(DATA_ROOT/'editor-sfx').resolve(),(ROOT/'memestudio'/'assets'/'sfx').resolve()]
        result={}
        for item in assets:
            path=Path(item.get('path','')).resolve()
            if path.is_file() and any(path.is_relative_to(root) for root in allowed):
                identifier=item.get('id')
                if isinstance(identifier,str):result[identifier]={'id':identifier,'name':item.get('name',identifier),'url':'/api/resources/sfx/'+identifier,'duration':item.get('duration')}
        return result

    @app.get('/api/resources/sfx/{identifier}')
    def resource_sound(identifier:str):
        if identifier not in resource_sfx():raise HTTPException(404,'SFX not found')
        assets=json.loads((ROOT/'memestudio'/'assets'/'sfx'/'manifest.json').read_text(encoding='utf-8'))['assets']
        card=next(item for item in assets if item.get('id')==identifier)
        return FileResponse(Path(card['path']),media_type='audio/wav')

    @app.post('/api/resources/props/upload')
    async def upload_resource_prop(request:Request,label:str='',prop_id:str=''):
        same_origin(request)
        from .meme_editor import save_prop_asset
        import re,uuid
        if len(label)>300 or (prop_id and not re.fullmatch(r'[a-z0-9_]{1,64}',prop_id)):
            raise HTTPException(422,'Tên hoặc ID đạo cụ không hợp lệ')
        body=bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body)>20*1024*1024:raise HTTPException(413,'Ảnh tối đa 20 MB')
        if not body:raise HTTPException(422,'Chọn tệp ảnh')
        try:return save_prop_asset(prop_id or 'prop_'+uuid.uuid4().hex[:12],bytes(body),label or prop_id or 'Đạo cụ mới')
        except ValueError as error:raise HTTPException(422,str(error))

    from .content_factory_api import register_content_factory_routes
    def factory_request(scope):
        headers=[(b'host',b'127.0.0.1:8877')]
        if scope:headers.append((b'x-connector-scope',scope.encode('ascii')))
        return Request({'type':'http','method':'POST','path':'/api/jobs','headers':headers})
    def validate_factory_request(data):
        if os.getenv('VS_LLM_TRANSPORT','cdp')=='chrome':
            raise ValueError('Hàng đợi tự động cần extension bridge hoặc CDP; chế độ chrome thử nghiệm cũ chỉ chạy từng phiên có giám sát')
        normalized=validate_request(data)
        selected_voice=voices.selected(normalized['voice_id'])
        if normalized.get('speech_engine')=='khanhtts':
            from .speech_engine import engine_status
            readiness=engine_status(pipeline,selected_voice,normalized)
            if not readiness['ready']:
                if not readiness.get('reference_ready',True):
                    raise ValueError('Giọng clone này chưa có lời của bản thu mẫu. Mở Cài đặt riêng → Nâng cao để nhập lời chính xác, hoặc tạo mẫu tham chiếu trước trong Phòng thử giọng.')
                raise ValueError('KhanhTTS chưa sẵn sàng. Kiểm tra bộ đọc trong Kho tài nguyên → Giọng đọc trước khi xếp video vào hàng đợi.')
        return normalized
    factory=register_content_factory_routes(app,store,same_origin,public_job,
        lambda data,key,scope:submit(data,factory_request(scope),idempotency_key=key),
        validate_submission=validate_factory_request,
        retry_job=lambda job_id,scope,resume_cancelled=False:retry_job(job_id,{'resume_cancelled':resume_cancelled},factory_request(scope)))
    def name_video(content,request):
        from . import social_copy
        pipeline.context.job='name-'+uuid.uuid4().hex;pipeline.context.text_provider=request.get('text_provider','chatgpt')
        try:return social_copy.ask_name(lambda prompt:pipeline.llm_json(prompt,lambda:None),content)
        finally:pipeline.context.job=None
    factory.name_video=name_video
    from .publishing_api import register_publishing_routes
    publisher=register_publishing_routes(app,store,factory,same_origin,browser_request_local)
    factory.channel_states=publisher.channel_states
    from .posted_cleanup_api import register_posted_cleanup_routes
    posted_cleanup=register_posted_cleanup_routes(app,store,same_origin,browser_request_local)
    @app.get('/api/settings/output-root')
    def output_root():
        from .output_settings import describe
        return describe(store)
    @app.put('/api/settings/output-root')
    def set_output_root(data:dict,request:Request):
        same_origin(request)
        from .output_settings import save
        try:return save(store,data.get('path'))
        except ValueError as error:raise HTTPException(422,str(error))
    from .drive_api import register_drive_routes
    drive_storage=register_drive_routes(app,store,factory,same_origin,stop,background=worker_enabled)
    from .story_api import register_story_routes
    register_story_routes(app,store,factory,pipeline,voices,same_origin,resume_editing=worker_enabled)

    static=ROOT/'static'
    if static.is_dir():
        @app.get('/story-video/projects/{project_id}/production')
        def production_page(project_id:str,connector_test:bool=False,workspace:str|None=None):
            try:exchanges.pending(project_id)
            except KeyError:raise HTTPException(404,'Unknown connector scope')
            return FileResponse(static/('connector-test.html' if connector_test else 'editor.html' if workspace=='editor' else 'index.html'))
        app.mount('/',StaticFiles(directory=static,html=True),name='frontend')
    app.state.browser_manager=browser_manager
    return app

app=create_app(worker_enabled=os.getenv('VS_WORKER_ENABLED','1')=='1')

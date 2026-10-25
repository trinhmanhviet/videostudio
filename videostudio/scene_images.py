"""Persistent, single-flight scene-image candidates; applying is a separate user action."""
import json,os,time,uuid,shutil
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from .core import digest
from .scene_editor import SceneEditor
from .visual_quality import fingerprint
ROOT=Path(__file__).resolve().parents[1]

class ImageTaskIssue(RuntimeError):
    def __init__(self,message,code='uncertain'):super().__init__(message);self.code=code

class SceneImageJobs:
    def __init__(self,store,editor=None):
        self.store=store;self.editor=editor or SceneEditor(store);self.download_root=ROOT/'data'/'chatgpt-images';self.candidate_root=store.path.parent/'scene-image-candidates';self.pipeline=None;self.runner=self._run_provider
        with store.db() as c:c.executescript('''CREATE TABLE IF NOT EXISTS scene_image_tasks(
          id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,job TEXT NOT NULL,scene TEXT NOT NULL,prompt TEXT NOT NULL,provider TEXT NOT NULL,
          editor_version INTEGER NOT NULL,timeline_sha256 TEXT NOT NULL,source_image_sha256 TEXT NOT NULL,state TEXT NOT NULL,
          error TEXT,result TEXT,applied_edit_id TEXT,created REAL NOT NULL,updated REAL NOT NULL);''')
    def get(self,identifier):
        with self.store.db() as c:r=c.execute('SELECT * FROM scene_image_tasks WHERE id=?',(identifier,)).fetchone()
        if not r:raise KeyError(identifier)
        d=dict(r);d['result']=json.loads(d['result']) if d['result'] else None;return d
    def scoped(self,jid,sid,identifier):
        d=self.get(identifier)
        if d['job']!=jid or d['scene']!=sid:raise ValueError('Image task belongs to another scene/job')
        return d
    def list(self,jid,sid):
        self.editor._scene(self.editor.view(jid),sid)
        with self.store.db() as c:ids=[r[0] for r in c.execute('SELECT id FROM scene_image_tasks WHERE job=? AND scene=? ORDER BY created DESC LIMIT 6',(jid,sid))]
        return [self.get(i) for i in ids]
    def start(self,jid,sid,prompt,provider,key,version):
        if provider not in ('chatgpt','comfy','flow'):raise ValueError('Unknown scene image provider')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000 or '[VideoStudio image request ' in prompt:raise ValueError('Image prompt must be 1..12000 characters, without tracking markers')
        if not isinstance(key,str) or not 1<=len(key)<=150:raise ValueError('Idempotency-Key required (max 150)')
        prompt=prompt.strip();v=self.editor.view(jid);row=self.editor._scene(v,sid)
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM scene_image_tasks WHERE idem=?',(key,)).fetchone()
            if old:
                if (old['job'],old['scene'],old['prompt'],old['provider'],old['editor_version'])!=(jid,sid,prompt,provider,version):raise ValueError('Idempotency key already used for another image request')
                identifier=old['id']
            else:
                self.editor._mutable(c,jid,version)
                if c.execute("SELECT 1 FROM scene_image_tasks WHERE job=? AND scene=? AND state IN ('queued','running','uncertain','needs_auth','needs_comfy_idle','needs_zero_credit','needs_flow_check')",(jid,sid)).fetchone():raise ValueError('This scene already has a pending image request; resume or stop waiting first')
                if c.execute("SELECT COUNT(*) FROM scene_image_tasks WHERE state IN ('queued','running')").fetchone()[0]>=10:raise ValueError('Image queue is full; wait before adding more scenes')
                identifier=str(uuid.uuid4());now=time.time()
                c.execute('INSERT INTO scene_image_tasks VALUES(?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)',(identifier,key,jid,sid,prompt,provider,version,v['timeline_sha256'],row['image_sha256'],'queued',now,now))
                self.store.event(c,jid,'images','image_generation_queued',sid+' via '+provider)
        return self.get(identifier)
    def _run_provider(self,task):
        if task.get('provider')=='chatgpt':return self._run_chatgpt(task)
        if task.get('provider')=='comfy':return self._run_comfy(task)
        if task.get('provider')=='flow':return self._run_flow(task)
        raise ImageTaskIssue('Unsupported scene image provider','failed')
    def _run_comfy(self,task):
        if self.pipeline is None:raise ImageTaskIssue('Comfy runner is not configured','failed')
        from .providers import image_graph
        task_dir=self.download_root/'comfy-tasks'/task['id'];task_dir.mkdir(parents=True,exist_ok=True)
        output=self.download_root/(task['id']+'.png')
        task_identity={'id':task['id'],'output':str(task_dir.resolve())}
        seed=uuid.UUID(task['id']).int%(2**32)
        prefix='videostudio/scene-candidates/'+task['id']
        graph=image_graph(task['prompt'],seed,prefix)
        def check():
            self.store.active(task['job'])
            current=self.get(task['id'])
            if current['state']=='cancelled':raise ImageTaskIssue('Đã dừng chờ trong VideoStudio; không gửi lệnh interrupt tới ComfyUI.','cancelled')
            if current['state']!='running':raise ImageTaskIssue('Trạng thái task đã đổi; giữ receipt Comfy và dừng polling an toàn.','cancelled')
        try:
            result=self.pipeline.comfy_asset(task_identity,'images-scene-'+task['id'],graph,output,check,strict_resume=True,skip_vram_check=True)
        except Exception as e:
            text=str(e)
            if 'busy with other work' in text or 'Insufficient free VRAM' in text:
                raise ImageTaskIssue('ComfyUI đang bận hoặc thiếu VRAM; queue không bị thay đổi. Khi Comfy rảnh, chọn thử lại cùng yêu cầu.','needs_comfy_idle') from e
            if 'receipt is absent from history and queue' in text or 'submitting' in text.casefold():
                raise ImageTaskIssue('Comfy đã nhận hoặc có thể đã nhận yêu cầu nhưng chưa có receipt kết quả rõ ràng. Không tự gửi lại để tránh tạo trùng.','uncertain') from e
            if isinstance(e,httpx.HTTPError) or isinstance(e,TimeoutError):
                raise ImageTaskIssue('Trạng thái yêu cầu Comfy chưa rõ; giữ nguyên receipt và không gửi lại mù quáng.','uncertain') from e
            raise
        with Image.open(output) as im:im.load();width,height=im.size
        return {'task_id':task['id'],'file_path':str(output.resolve()),'sha256':digest(output),'width':width,'height':height,'request_id':result['prompt_id'],'source':'comfy_qwen_image_2_1'}
    def recover_existing_comfy_result(self,jid,sid,identifier):
        """Fetch an already-finished Comfy history result after metadata canonicalization fixes; never POST a prompt."""
        task=self.scoped(jid,sid,identifier)
        if task['provider']!='comfy' or task['state']!='failed' or task['error']!='Unsafe Comfy output':
            raise ValueError('Only the specifically rejected Comfy output-format task is recoverable')
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("UPDATE scene_image_tasks SET state='running',updated=? WHERE id=? AND state='failed' AND error='Unsafe Comfy output'",(time.time(),identifier)).rowcount!=1:
                raise ValueError('Comfy recovery task changed; not resumed')
        current=self.get(identifier)
        try:
            result=self._run_comfy(current) # strict receipt path: no new /prompt
            validated=self._validate(current,result)
            with self.store.db() as c:
                c.execute("UPDATE scene_image_tasks SET state='completed',result=?,error=NULL,updated=? WHERE id=? AND state='running'",(json.dumps(validated),time.time(),identifier))
                self.store.event(c,jid,'images','comfy_existing_history_recovered',sid)
        except Exception as error:
            with self.store.db() as c:c.execute("UPDATE scene_image_tasks SET state='failed',error=?,updated=? WHERE id=? AND state='running'",(str(error)[:1200],time.time(),identifier))
            raise
        return self.get(identifier)
    def _run_flow(self,task):
        url=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/');p=urlparse(url)
        if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password:raise ImageTaskIssue('Only loopback dedicated browser daemon allowed','failed')
        try:r=httpx.post(url+'/api/flow/images/generate',json={'task_id':task['id'],'job_id':task['job'],'prompt':task['prompt']},headers={'X-VS-Client':'videostudio'},timeout=1200,trust_env=False)
        except httpx.HTTPError as e:raise ImageTaskIssue('Flow browser result is unclear; reconcile the same request, never submit a replacement','uncertain') from e
        try:body=r.json()
        except ValueError as e:raise ImageTaskIssue('Flow browser response malformed; request state uncertain','uncertain') from e
        if r.status_code!=200:
            code=body.get('code');state=code if code in ('needs_auth','needs_zero_credit','needs_flow_check','uncertain') else 'uncertain'
            raise ImageTaskIssue(body.get('error','Google Flow generation unavailable'),state)
        value=body.get('data')
        if not isinstance(value,dict) or value.get('task_id')!=task['id'] or not isinstance(value.get('request_id'),str):raise ImageTaskIssue('Flow result receipt does not match the scene task','uncertain')
        source=(ROOT/'data'/'flow-images'/(task['id']+'.png')).resolve();received=Path(value.get('file_path','')).resolve()
        if received!=source or not source.is_file() or digest(source)!=value.get('sha256'):raise ImageTaskIssue('Flow download path/hash is invalid','failed')
        output=(self.download_root/(task['id']+'.png')).resolve();self.download_root.mkdir(parents=True,exist_ok=True);part=output.with_suffix('.part');shutil.copyfile(source,part);part.replace(output)
        return {**value,'file_path':str(output),'sha256':digest(output),'source':'google_flow_nano_banana_2_1'}
    def _run_chatgpt(self,task):
        url=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/');p=urlparse(url)
        if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password:raise ImageTaskIssue('Only loopback dedicated browser daemon allowed','failed')
        try:r=httpx.post(url+'/api/images/generate',json={'task_id':task['id'],'prompt':task['prompt']},headers={'X-VS-Client':'videostudio'},timeout=600,trust_env=False)
        except httpx.HTTPError as e:raise ImageTaskIssue('Browser connection uncertain; same request can be reconciled, not resent') from e
        try:body=r.json()
        except ValueError as e:raise ImageTaskIssue('Browser response malformed; generation state uncertain') from e
        if r.status_code!=200:
            code=body.get('code');state='needs_auth' if code=='authentication_required' else ('failed' if code=='image_rejected' else 'uncertain')
            raise ImageTaskIssue(body.get('error','Browser image generation unavailable'),state)
        return body.get('data')
    def _validate(self,task,result):
        if not isinstance(result,dict) or result.get('task_id')!=task['id'] or not isinstance(result.get('request_id'),str) or not result['request_id']:raise ValueError('Image result receipt does not match task')
        expected=(self.download_root/(task['id']+'.png')).resolve();received=Path(result.get('file_path','')).resolve()
        if received!=expected or not received.is_file() or not 0<received.stat().st_size<=20*1024*1024 or digest(received)!=result.get('sha256'):raise ValueError('Image download path/hash/size invalid')
        with Image.open(received) as im:
            if im.format not in ('PNG','JPEG','WEBP') or min(im.size)<512 or max(im.size)>8192 or im.width*im.height>20_000_000:raise ValueError('Generated image invalid dimensions or format')
            im.load()
            if (result.get('width'),result.get('height'))!=im.size:raise ValueError('Generated image metadata does not match file')
        self.candidate_root.mkdir(parents=True,exist_ok=True);out=self.candidate_root/(task['id']+'.png');part=out.with_suffix('.part');shutil.copyfile(received,part);part.replace(out)
        return {**result,'candidate_path':str(out.resolve()),'candidate_sha256':digest(out)}
    def step(self,owner):
        if not self.store.lock(owner):return False
        try:
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT id FROM scene_image_tasks WHERE state IN ('queued','running') ORDER BY created LIMIT 1").fetchone()
                if not r:return False
                identifier=r['id'];c.execute("UPDATE scene_image_tasks SET state='running',error=NULL,updated=? WHERE id=?",(time.time(),identifier))
            task=self.get(identifier)
            try:
                result=self._validate(task,self.runner(task))
                with self.store.db() as c:c.execute("UPDATE scene_image_tasks SET state='completed',result=?,error=NULL,updated=? WHERE id=? AND state='running'",(json.dumps(result),time.time(),identifier))
            except Exception as e:
                state=e.code if isinstance(e,ImageTaskIssue) else ('uncertain' if isinstance(e,(TimeoutError,ConnectionError)) else 'failed')
                with self.store.db() as c:c.execute('UPDATE scene_image_tasks SET state=?,error=?,updated=? WHERE id=? AND state=\'running\'',(state,str(e)[:1200],time.time(),identifier))
            return True
        finally:self.store.release(owner)
    def resume(self,jid,sid,identifier):
        self.scoped(jid,sid,identifier)
        with self.store.db() as c:
            if c.execute("UPDATE scene_image_tasks SET state='queued',error=NULL,updated=? WHERE id=? AND state IN ('uncertain','needs_auth','needs_comfy_idle','needs_zero_credit','needs_flow_check')",(time.time(),identifier)).rowcount!=1:raise ValueError('Only uncertain/auth/comfy-idle requests can resume; no new task is created')
        return self.get(identifier)
    def cancel(self,jid,sid,identifier):
        self.scoped(jid,sid,identifier)
        with self.store.db() as c:c.execute("UPDATE scene_image_tasks SET state='cancelled',updated=? WHERE id=? AND state IN ('queued','running','uncertain','needs_auth','needs_zero_credit','needs_flow_check','needs_comfy_idle')",(time.time(),identifier))
        return self.get(identifier)
    def candidate(self,jid,sid,identifier):
        t=self.scoped(jid,sid,identifier);r=t.get('result')
        if t['state'] not in ('completed','applied') or not r:raise ValueError('Image candidate is not ready')
        p=Path(r['candidate_path'])
        if p.resolve()!=(self.candidate_root/(identifier+'.png')).resolve() or not p.is_file() or digest(p)!=r['candidate_sha256']:raise ValueError('Image candidate changed/missing')
        return p
    def apply(self,jid,sid,identifier,version,fit):
        t=self.scoped(jid,sid,identifier)
        if t['state']=='applied':return self.editor.view(jid) # retry ack, never apply twice
        if t['state']!='completed':raise ValueError('Image candidate is not completed')
        v=self.editor.view(jid)
        if v['timeline_sha256']!=t['timeline_sha256']:raise ValueError('Scene narration/timeline changed since generation; cannot apply stale candidate')
        p=self.candidate(jid,sid,identifier)
        return self.editor.replace(jid,sid,p.read_bytes(),fit,version,generated_task=identifier)
    def public(self,t):
        r=t.get('result') or {};return {'id':t['id'],'scene_id':t['scene'],'provider':t['provider'],'prompt':t['prompt'],'state':t['state'],'error':t['error'],'created':t['created'],'width':r.get('width'),'height':r.get('height'),'request_id':r.get('request_id'),'image_url':f'/api/jobs/{t["job"]}/scene-editor/scenes/{t["scene"]}/generations/{t["id"]}/image' if t['state'] in ('completed','applied') else None}

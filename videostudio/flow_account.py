"""Durable, cooperative Flow account handoff for the original video job.

Preparation only salvages existing assets. It never submits a generation request,
changes Chrome accounts, or rewrites an original Flow task/project receipt.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .core import digest
from .project_lifecycle import has_table, reject_retired_job

class FlowAccountTransportUncertain(RuntimeError):
    flow_busy_uncertain=True


class FlowAccountService:
    def __init__(self, store, scene_editor=None, *, flow_root=None, browser_check=None,
                 reconciler=None, pause_timeout=300, reconcile_timeout=600):
        self.store = store
        self.scene_editor = scene_editor
        self.flow_root = Path(flow_root or Path(__file__).resolve().parents[1]/'data'/'flow-images')
        self.browser_check = browser_check or self._debug_available
        self._production_browser_check = browser_check is None
        self.reconciler = reconciler or self._reconcile_browser
        self.pause_timeout = pause_timeout
        self.reconcile_timeout = reconcile_timeout
        self._threads = {}
        self._lock = threading.RLock()
        with store.db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS flow_account_changes(
                job TEXT PRIMARY KEY,phase TEXT NOT NULL,data TEXT NOT NULL DEFAULT '{}',updated REAL NOT NULL)""")

    @staticmethod
    def _debug_available():
        from .chrome_browser import DedicatedChrome
        return bool(DedicatedChrome().discover())

    def _read(self, c, job_id):
        row = c.execute('SELECT phase,data FROM flow_account_changes WHERE job=?',(job_id,)).fetchone()
        return (row['phase'],json.loads(row['data'])) if row else ('idle',{})

    def _write(self, c, job_id, phase, data):
        c.execute('INSERT OR REPLACE INTO flow_account_changes VALUES(?,?,?,?)',
                  (job_id,phase,json.dumps(data,ensure_ascii=False),time.time()))

    def _require(self, c, job_id):
        row = c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row:raise KeyError(job_id)
        reject_retired_job(c,job_id)
        if row['cancel'] or row['state'] in ('cancelled','completed'):
            raise ValueError('Chỉ đổi tài khoản Flow cho video chưa hoàn tất và chưa bị hủy')
        if json.loads(row['request']).get('image_provider','comfy') != 'flow' or row['stage'] != 'images':
            raise ValueError('Chỉ đổi tài khoản khi video đang ở bước tạo ảnh bằng Flow')
        return row

    def _idle_browser(self, c, job_id):
        if c.execute("SELECT 1 FROM jobs WHERE id<>? AND state='running' LIMIT 1",(job_id,)).fetchone():
            raise ValueError('Chờ video khác đang chạy hoàn tất trước khi đổi tài khoản Flow')
        if has_table(c,'scene_image_tasks') and c.execute("SELECT 1 FROM scene_image_tasks WHERE state IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('Chờ tác vụ ảnh cảnh đang chạy hoặc đang chờ hoàn tất trước khi đổi tài khoản Flow')

    def status(self, job_id):
        job = self.store.get(job_id)
        with self.store.db() as c:
            phase,data = self._read(c,job_id)
            try:self._require(c,job_id);eligible=True
            except ValueError:eligible=False
        total = data.get('total',len(job.get('checkpoints',{}).get('speech',{}).get('utterances',[])))
        cached = data.get('cached_count',0)
        return {'job_id':job_id,'phase':phase,'message':data.get('message','Chuẩn bị video này trước khi đổi tài khoản Flow.'),
                'cached_count':cached,'total':total,'missing_count':max(0,total-cached),
                'can_prepare':eligible and phase in ('idle','error','running'),
                'can_continue':eligible and phase=='ready'}

    def pause_requested(self, job_id):
        with self.store.db() as c:return self._read(c,job_id)[0]=='pausing'

    def active_run(self, job_id):
        with self.store.db() as c:return self._read(c,job_id)[1].get('active_run')

    def _blocked(self, phases):
        with self.store.db() as c:
            placeholders=','.join('?' for _ in phases)
            return bool(c.execute(f"SELECT 1 FROM flow_account_changes f JOIN jobs j ON j.id=f.job WHERE (f.phase IN ({placeholders}) OR (f.phase='error' AND json_extract(f.data,'$.needs_quiescence')=1)) AND j.cancel=0 AND j.state NOT IN ('cancelled','completed') LIMIT 1",phases).fetchone())

    def blocks_workers(self):return self._blocked(('pausing','reconciling','ready'))

    def blocks_browser_changes(self):return self._blocked(('pausing','reconciling'))

    def prepare(self, job_id):
        with self._lock:
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                row=self._require(c,job_id)
                phase,data=self._read(c,job_id)
                if phase in ('pausing','reconciling','ready'):return self.status(job_id)
                self._idle_browser(c,job_id)
                other=c.execute("SELECT f.job FROM flow_account_changes f JOIN jobs j ON j.id=f.job WHERE f.job<>? AND f.phase IN ('pausing','reconciling','ready') AND j.cancel=0 AND j.state NOT IN ('cancelled','completed') LIMIT 1",(job_id,)).fetchone()
                if other:raise ValueError('Hoàn tất đổi tài khoản Flow đang chờ trước khi chuẩn bị video khác')
                if row['state'] not in ('running','queued','retrying','failed','awaiting_flow_account'):
                    raise ValueError('Video phải đang chạy hoặc đang chờ ở bước tạo ảnh')
                data.update(message='Đang chờ yêu cầu Flow hiện tại dừng tại điểm an toàn.',prepare_id=str(uuid.uuid4()))
                self._write(c,job_id,'pausing',data)
                if row['state']!='running':
                    c.execute("UPDATE jobs SET state='awaiting_flow_account',next_at=0,updated=? WHERE id=?",(time.time(),job_id))
                self.store.event(c,job_id,'images','flow_account_prepare')
            thread=threading.Thread(target=self._prepare_background,args=(job_id,data['prepare_id']),daemon=True,name='flow-account-'+job_id[:8])
            self._threads[job_id]=thread
            thread.start()
        return self.status(job_id)

    def _update(self, job_id, prepare_id, phase, **updates):
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            self._require(c,job_id)
            _,data=self._read(c,job_id)
            if data.get('prepare_id')!=prepare_id:raise ValueError('Yêu cầu chuẩn bị này đã được thay thế')
            data.update(updates);self._write(c,job_id,phase,data)

    def _prepare_background(self, job_id, prepare_id):
        try:
            deadline=time.monotonic()+self.pause_timeout
            while True:
                with self.store.db() as c:
                    row=self._require(c,job_id)
                if row['state'] in ('awaiting_flow_account','failed'):break
                if time.monotonic()>=deadline:raise TimeoutError('Flow chưa dừng an toàn. Giữ Chrome mở và thử chuẩn bị lại sau khi yêu cầu hiện tại kết thúc.')
                time.sleep(.1)
            self._update(job_id,prepare_id,'reconciling',message='Đang giữ lại ảnh đã tải và kiểm tra dự án Flow của tài khoản cũ.')
            with self.store.db() as c:_,data=self._read(c,job_id)
            if data.pop('needs_quiescence',False):
                self._quiesce_daemon(job_id)
                self._update(job_id,prepare_id,'reconciling',needs_quiescence=False,message='Flow đã xác nhận lượt quét trước kết thúc. Đang đối chiếu lại ảnh đã lưu.')
            job=self.store.get(job_id)
            tasks=self._scene_tasks(job)
            cached=self._preserve_local(job,tasks)
            self._update(job_id,prepare_id,'reconciling',total=len(tasks),cached_count=cached)
            missing=[task for task in tasks if not task['cached']]
            warning=''
            if missing:
                try:warning=self.reconciler(job,missing) or ''
                except (ConnectionError,TimeoutError) as error:
                    warning=f'Chưa kiểm tra được dự án Flow cũ: {error}. Ảnh đã tải được giữ lại. Bấm Tiếp tục để tạo các cảnh còn thiếu bằng tài khoản đã chọn.'
                cached=self._preserve_local(job,tasks)
            self._update(job_id,prepare_id,'ready',total=len(tasks),cached_count=cached,
                         missing_indices=[t['index'] for t in tasks if not t['cached']],
                         message=f'Đã giữ {cached}/{len(tasks)} ảnh cảnh. Có thể đổi tài khoản, mở Chrome debug rồi bấm Tiếp tục. '+warning)
        except Exception as error:
            # Cancellation/deletion must stop the operation without resurrecting the job.
            with self.store.db() as c:
                phase,data=self._read(c,job_id)
                if data.get('prepare_id')==prepare_id and phase in ('pausing','reconciling'):
                    if getattr(error,'flow_busy_uncertain',False):data['needs_quiescence']=True
                    data['message']='Không chuẩn bị được đổi tài khoản Flow: '+str(error)[:1600];self._write(c,job_id,'error',data)

    def continue_job(self, job_id):
        with self._lock:
            with self.store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                row=self._require(c,job_id)
                phase,data=self._read(c,job_id)
                if phase=='running':return self.status(job_id)
                if phase!='ready':raise ValueError('Chuẩn bị video và chờ trạng thái đổi tài khoản Flow sẵn sàng')
                if row['state'] not in ('awaiting_flow_account','failed'):
                    raise ValueError('Video phải dừng an toàn trước khi tiếp tục')
                self._idle_browser(c,job_id)
                if not self.browser_check():raise ValueError('Đăng nhập tài khoản Flow mong muốn rồi mở Chrome riêng ở chế độ debug')
                if self._production_browser_check:self._continue_preflight()
                previous=data.get('active_run')
                if previous:data.setdefault('previous_runs',[]).append(previous)
                data.update(active_run=str(uuid.uuid4()),message='Đang tiếp tục video hiện tại bằng tài khoản Flow đã chọn; các ảnh đã giữ sẽ được dùng lại.')
                self._write(c,job_id,'running',data)
                c.execute("UPDATE jobs SET state='queued',cancel=0,error=NULL,next_at=0,updated=? WHERE id=?",(time.time(),job_id))
                count=c.execute("SELECT count FROM attempts WHERE job=? AND stage='images'",(job_id,)).fetchone()
                # Explicit continuation grants one further images attempt while retaining history.
                if count:
                    existing=c.execute("SELECT attempt_limit FROM recovery_grants WHERE job=? AND stage='images'",(job_id,)).fetchone()
                    limit=max(3,count[0]+1,existing[0] if existing else 0)
                    c.execute('INSERT OR REPLACE INTO recovery_grants VALUES(?,?,?,?,?)',(job_id,'images',limit,'explicit Flow account continuation; prior attempts preserved',time.time()))
                self.store.event(c,job_id,'images','flow_account_continue',data['active_run'])
        return self.status(job_id)

    def recover_after_restart(self):
        """Call once from the worker-owning lifespan, never from import-time setup."""
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            for row in list(c.execute("SELECT * FROM flow_account_changes WHERE phase IN ('pausing','reconciling')")):
                if row['job'] in self._threads and self._threads[row['job']].is_alive():continue
                data=json.loads(row['data']);data['message']='Chuẩn bị bị gián đoạn khi máy chủ khởi động lại. Giữ tài khoản Flow cũ mở rồi chuẩn bị lại; ảnh đã tải được giữ nguyên.'
                self._write(c,row['job'],'error',data)
                c.execute("UPDATE jobs SET state='awaiting_flow_account',updated=? WHERE id=? AND cancel=0 AND state IN ('queued','running','retrying','failed')",(time.time(),row['job']))

    @staticmethod
    def _json(path):
        return json.loads(path.read_text(encoding='utf8')) if path.is_file() else None

    def _scene_tasks(self, job):
        from .cdp_flow import FlowImages
        utterances=job.get('checkpoints',{}).get('speech',{}).get('utterances',[])
        if not utterances:raise ValueError('Thiếu checkpoint lời đọc chứa prompt chính xác của các cảnh')
        references=self._json(Path(job['output'])/'flow-character-references.json') or {}
        refs={item['character_manifest_id']:item for item in references.get('characters',[])}
        with self.store.db() as c:_,data=self._read(c,job['id'])
        runs=list(dict.fromkeys([job['id'],*data.get('previous_runs',[]),*([data['active_run']] if data.get('active_run') else [])]))
        tasks=[]
        for index,utterance in enumerate(utterances):
            mentions=[{k:refs[cid][k] for k in ('character_id','name','project_url')} for cid in utterance.get('character_ids',[]) if cid in refs]
            mentions=FlowImages._validate_character_mentions(job['id'],mentions)
            task={'index':index,'prompt':utterance['visual_prompt'],'mentions':mentions,'receipts':[],'cached':False}
            for run in runs:
                tid=str(uuid.uuid5(uuid.UUID(run),f'bulk-scene-image:{index}'))
                receipt=self._json(self.flow_root/'tasks'/(tid+'.json'))
                if not receipt:continue
                if receipt.get('task_id')!=tid or receipt.get('job_id')!=run:
                    raise ValueError('Biên nhận Flow không khớp cảnh/video; các tệp đã lưu được giữ nguyên')
                if receipt.get('prompt_sha256')!=hashlib.sha256(task['prompt'].encode('utf8')).hexdigest():
                    raise ValueError('Prompt của biên nhận Flow đã thay đổi; các tệp đã lưu được giữ nguyên')
                saved_mentions=FlowImages._validate_character_mentions(run,receipt.get('character_mentions',[]))
                if receipt.get('reference_media_ids') or receipt.get('reference_identity'):
                    raise ValueError('Biên nhận Flow dùng ảnh tham chiếu cũ chưa thể đối chiếu an toàn')
                if receipt.get('conditioning_sha256'):
                    mentions_sha=hashlib.sha256(json.dumps(saved_mentions,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
                    conditioning=hashlib.sha256(json.dumps({'prompt_sha256':receipt['prompt_sha256'],'character_mentions_sha256':mentions_sha},sort_keys=True).encode('utf8')).hexdigest()
                    if conditioning!=receipt['conditioning_sha256']:
                        raise ValueError('Mã hash điều kiện tạo ảnh của biên nhận Flow không khớp')
                if saved_mentions and receipt.get('stage') in ('submitting','waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                    if receipt.get('submitted_character_ids')!=[m['character_id'] for m in saved_mentions]:
                        raise ValueError('Danh tính Character đã gửi trong biên nhận Flow không khớp')
                # Migrated runs may deliberately use fixed-text conditioning.
                if run==job['id'] and saved_mentions!=mentions:
                    raise ValueError('Character của biên nhận Flow khác với bản mô tả cảnh đã lưu')
                task['receipts'].append(receipt)
            tasks.append(task)
        return tasks

    @staticmethod
    def _validate_image(path, sha):
        from PIL import Image
        if not path.is_file() or not sha or digest(path)!=sha or path.stat().st_size>25*1024*1024:
            raise ValueError('Ảnh cảnh đã lưu không đạt kiểm tra hash/kích thước; tệp được giữ nguyên')
        with Image.open(path) as image:
            if image.format!='PNG' or min(image.size)<512 or max(image.size)>8192 or image.width*image.height>20_000_000:
                raise ValueError('Kích thước hoặc định dạng ảnh cảnh đã lưu không hợp lệ')
            image.load();return image.size

    def _preserve_local(self, job, tasks):
        for task in tasks:
            self._ensure_paused(job['id'])
            output=Path(job['output'])/f"images-{task['index']:04}.png"
            cp_path=output.with_suffix('.checkpoint.json');cp=self._json(cp_path)
            if output.is_file() and cp:
                if cp.get('provider')!='flow' or cp.get('prompt')!=task['prompt'] or cp.get('reference_media_ids') or cp.get('reference_identity'):
                    raise ValueError('Checkpoint ảnh hiện có khác prompt/nguồn/điều kiện tạo ảnh; tệp được giữ nguyên')
                if cp.get('character_mentions',[])!=task['mentions']:
                    correlated=any(r['task_id']==cp.get('task_id') and r.get('character_mentions',[])==cp.get('character_mentions',[]) for r in task['receipts'])
                    if not correlated:raise ValueError('Ảnh cảnh hiện có dùng Character Flow khác')
                self._validate_image(output,cp.get('sha256'));task['cached']=True;continue
            found=None
            for receipt in reversed(task['receipts']):
                source=self.flow_root/(receipt['task_id']+'.png')
                if not source.is_file():continue
                width,height=self._validate_image(source,receipt.get('download_sha256'))
                if not receipt.get('media_id') or not receipt.get('project_url'):
                    raise ValueError('Ảnh Flow đã lưu thiếu danh tính ảnh/dự án đã xác thực')
                found=(source,receipt,width,height);break
            if not found:
                if output.exists():raise ValueError('Ảnh cảnh hiện có thiếu checkpoint hoặc biên nhận Flow khớp; tệp được giữ nguyên')
                task['cached']=False;continue
            source,receipt,width,height=found
            if output.exists() and digest(output)!=digest(source):raise ValueError('Ảnh cảnh hiện có khác ảnh Flow đã xác thực; tệp được giữ nguyên')
            self._ensure_paused(job['id'])
            if not output.exists():
                part=output.with_suffix('.handoff.part');shutil.copyfile(source,part);part.replace(output)
            cp={'sha256':digest(output),'prompt':task['prompt'],'submitted_prompt':task['prompt'],'provider':'flow',
                'task_id':receipt['task_id'],'request_id':'flow-'+receipt['task_id'],'width':width,'height':height,
                'character_mentions':receipt.get('character_mentions',[]),'media_id':receipt['media_id'],'project_url':receipt['project_url']}
            part=cp_path.with_suffix('.handoff.part');part.write_text(json.dumps(cp,ensure_ascii=False),encoding='utf8');part.replace(cp_path)
            task['cached']=True
        return sum(task['cached'] for task in tasks)

    def _ensure_paused(self, job_id):
        with self.store.db() as c:
            row=self._require(c,job_id)
            if row['state'] not in ('awaiting_flow_account','failed'):raise ValueError('Video không còn ở trạng thái dừng an toàn')

    def _reconcile_browser(self, job, tasks):
        if not self.browser_check():
            raise ConnectionError('Mở tài khoản cũ bằng Chrome riêng ở chế độ debug để lấy các ảnh còn lại')
        import httpx
        url=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/')+'/api/flow/account/reconcile'
        try:
            response=httpx.post(url,json={'job_id':job['id'],'quiesce_only':False},headers={'X-VS-Client':'videostudio'},timeout=self.reconcile_timeout+45,trust_env=False)
        except httpx.HTTPError as error:
            raise FlowAccountTransportUncertain('Mất xác nhận từ dịch vụ Flow. Giữ Chrome ở debug; bấm Chuẩn bị lại sau khi dịch vụ phản hồi.') from error
        if response.status_code!=200:
            try:detail=response.json().get('error') or 'Không xác nhận được trạng thái quét Flow.'
            except ValueError:detail='Không xác nhận được trạng thái quét Flow.'
            if response.status_code>=500:
                raise FlowAccountTransportUncertain(str(detail))
            raise ConnectionError(str(detail))
        body=response.json()
        if not isinstance(body,dict) or body.get('ok') is not True or not isinstance(body.get('data'),dict):
            raise FlowAccountTransportUncertain('Flow chưa xác nhận kết thúc lượt đối chiếu.')
        return body['data'].get('message','')

    def _quiesce_daemon(self,job_id):
        import httpx
        url=os.getenv('VS_CDP_DAEMON_URL','http://127.0.0.1:8879').rstrip('/')+'/api/flow/account/reconcile'
        try:response=httpx.post(url,json={'job_id':job_id,'quiesce_only':True},headers={'X-VS-Client':'videostudio'},timeout=60,trust_env=False)
        except httpx.HTTPError as error:raise FlowAccountTransportUncertain('Flow chưa xác nhận kết thúc thao tác cũ. Giữ Chrome debug, chuẩn bị lại sau.') from error
        if response.status_code!=200 or response.json().get('data',{}).get('quiesced') is not True:raise FlowAccountTransportUncertain('Flow chưa xác nhận kết thúc thao tác cũ. Giữ Chrome debug, chuẩn bị lại sau.')

    @staticmethod
    def _select_continue_tab(pages):
        tabs=[p for p in pages if p.get('type')=='page' and urlparse(p.get('url','')).hostname=='flow.google.com']
        if not tabs:raise ValueError('Mở Flow trong Chrome riêng bằng tài khoản đã chọn trước khi tiếp tục')
        if len(tabs)!=1:raise ValueError('Chỉ để một tab Flow mở trước khi tiếp tục; tự đóng các tab Flow khác')
        return tabs[0]

    def _continue_preflight(self):
        async def inspect():
            from .cdp_daemon import ChromeChatGPTBridge
            from .chrome_browser import DedicatedChrome
            launcher=DedicatedChrome();endpoint=launcher.discover()
            if not endpoint:raise ValueError('Mở Chrome riêng ở chế độ debug trước khi tiếp tục')
            bridge=ChromeChatGPTBridge(launcher=launcher,journal=object())
            try:
                await bridge.cdp.connect(endpoint)
                command=await bridge.cdp.command('Browser.getBrowserCommandLine')
                if '--user-data-dir='+str(launcher.config.profile.resolve()) not in command.get('arguments',[]):
                    raise ValueError('Kết nối Chrome không xác nhận đúng hồ sơ riêng của Studio')
                tab=self._select_continue_tab((await bridge.cdp.command('Target.getTargets')).get('targetInfos',[]))
                session=await bridge.session(tab['targetId'])
                if urlparse(tab['url']).path.rstrip('/') not in ('','/home'):
                    state=await bridge.flow_images._snapshot(session,'')
                    if not state.get('composerAvailable'):raise ValueError('Đăng nhập Flow và mở dự án có ô nhập prompt trước khi tiếp tục')
                    if not state.get('draftEmpty'):raise ValueError('Xóa bản nháp Flow đang mở trước khi tiếp tục; video vẫn được giữ ở trạng thái chờ')
            finally:await bridge.cdp.close()
        async def bounded():return await asyncio.wait_for(inspect(),timeout=20)
        try:asyncio.run(bounded())
        except ValueError:raise
        except Exception as error:raise ValueError('Chưa kiểm tra được tab Flow. Giữ Chrome debug mở rồi thử tiếp tục lại. '+str(error)[:250]) from error

    @staticmethod
    def _unambiguous_matches(tasks, identities):
        from .cdp_flow import FlowImages
        expected={}
        for task in tasks:
            mentions=task['character_mentions']
            key=FlowImages._batch_prompt_fingerprint(' '.join([m['name'] for m in mentions]+[task['prompt']]),[m['character_id'] for m in mentions])
            expected.setdefault(key,[]).append(task)
        return [(matching[0],identities[key][0]) for key,matching in expected.items()
                if len(matching)==1 and len(identities.get(key,[]))==1]

    @staticmethod
    async def _media_identity(flow, session, media_id, project, *, native=False):
        from .cdp_flow import FlowTaskError
        if not native:
            try:return await flow._read_detail_prompt_for_media(session,media_id,project)
            except FlowTaskError as error:
                if str(error)!='Flow visible info panel did not expose one full prompt':raise
        # Native Reuse exposes both the full text and entity IDs; clear only the
        # exact draft inserted by that read, even when the tile is unrelated.
        detail=await flow._read_prompt_for_media(session,media_id)
        try:return detail
        finally:await flow._clear_verified_reused_prompt(session,project,detail['prompt'])

    def _reconciliation_projects(self, job, tasks):
        run=self.active_run(job['id']) or job['id']
        registry=self._json(self.flow_root/'projects'/(run+'.json')) or {}
        if registry.get('project_url'):return {registry['project_url'].split('?')[0].rstrip('/')}
        # A migrated run must never silently inspect the original account's tab.
        return {r['project_url'].split('?')[0].rstrip('/') for t in tasks for r in t['receipts']
                if r.get('job_id')==run and r.get('project_url')}

    async def _reconcile_browser_async(self, job, tasks, *, bridge=None):
        from .cdp_daemon import ChromeChatGPTBridge
        from .cdp_flow import FlowImages
        from .chrome_browser import DedicatedChrome
        launcher=DedicatedChrome();endpoint=launcher.discover()
        if not endpoint:raise ConnectionError('Không kết nối được Chrome riêng ở chế độ debug')
        # No journal or Chrome startup: this connection is exclusively read/recover.
        owns_bridge=bridge is None
        if owns_bridge:
            bridge=ChromeChatGPTBridge(launcher=launcher,journal=object())
            flow=FlowImages(bridge,self.flow_root);bridge.flow_images=flow
        else:flow=bridge.flow_images
        try:
            await bridge.cdp.connect(endpoint)
            command=await bridge.cdp.command('Browser.getBrowserCommandLine')
            if '--user-data-dir='+str(launcher.config.profile.resolve()) not in command.get('arguments',[]):
                raise ValueError('Kết nối Chrome không xác nhận đúng hồ sơ riêng của Studio')
            pages=(await bridge.cdp.command('Target.getTargets')).get('targetInfos',[])
            projects=self._reconciliation_projects(job,tasks)
            if not projects:raise ConnectionError('Không có dự án Flow cũ đã lưu; ảnh đã tải vẫn được giữ nguyên')
            available=[p for p in pages if p.get('type')=='page' and p.get('url','').split('?')[0].rstrip('/') in projects]
            if len(available)!=1:raise ConnectionError('Mở đúng một tab dự án Flow cũ đã lưu trước khi chuẩn bị')
            tab=available[0];project=tab['url'].split('?')[0].rstrip('/');target=tab['targetId'];session=await bridge.session(target)
            state=await flow._snapshot(session,'')
            if not state.get('composerAvailable'):raise ConnectionError('Dự án Flow cũ không truy cập được hoặc cần đăng nhập')
            if not state.get('draftEmpty'):raise ValueError('Xóa bản nháp Flow hiện có trước khi chuẩn bị đổi tài khoản')
            candidates=[]
            for task in tasks:
                receipts=[r for r in task['receipts'] if r.get('project_url','').split('?')[0].rstrip('/')==project]
                if receipts:
                    receipt=receipts[-1];mentions=receipt.get('character_mentions',[])
                    candidates.append({**task,'receipt':receipt,'character_mentions':mentions,'job_id':receipt['job_id'],'task_id':receipt['task_id']})
                else:
                    # A requested scene without a receipt can still have an existing
                    # asset if the browser returned after image acceptance but before
                    # the page persisted the tile ID. Claim it only by exact visible
                    # full prompt (plus native entity IDs); never regenerate here.
                    run=self.active_run(job['id']) or job['id']
                    mentions=task['character_mentions'] if run==job['id'] else []
                    from .cdp_flow import FlowImages
                    candidates.append({**task,'character_mentions':mentions,'job_id':run,
                        'task_id':str(uuid.uuid5(uuid.UUID(run),f'bulk-scene-image:{task["index"]}')),
                        'receipt':{'task_id':None,'job_id':run,'stage':'project_ready',
                            'prompt_sha256':hashlib.sha256(task['prompt'].encode('utf8')).hexdigest(),
                            'character_mentions':mentions,'project_url':project}})
            # Full grid scan exactly once; positions serve navigation only.
            tiles=await flow._scan_grid_tiles(session,project)
            identities={}
            for tile in tiles:
                self._ensure_paused(job['id'])
                detail=await self._media_identity(flow,session,tile['media_id'],project,native=any(t['character_mentions'] for t in candidates))
                key=flow._batch_prompt_fingerprint(detail.get('prompt',''),detail.get('mention_entity_ids',[]))
                identities.setdefault(key,[]).append(tile['media_id'])
            recovered=0
            for task,media_id in self._unambiguous_matches(candidates,identities):
                self._ensure_paused(job['id'])
                # A separate salvage receipt leaves historical task evidence unchanged.
                recovery_id=str(uuid.uuid5(uuid.UUID(task['task_id']),'account-handoff-existing:'+media_id))
                receipt={**task['receipt'],'task_id':recovery_id,'stage':'image_ready','media_id':media_id,
                         'recovered_from_task':task['task_id'],'prompt_identity_verified':True,
                         'download_resolution_requested':'1K','download_fallback_reason':'account handoff preserves existing original image'}
                mentions=task['character_mentions'];composed=' '.join([m['name'] for m in mentions]+[task['prompt']]).strip()
                flow._write_receipt(recovery_id,receipt)
                receipt=await flow._download_2k(recovery_id,target,session,receipt,composed,media_id=media_id)
                next(t for t in tasks if t['index']==task['index'])['receipts'].append(receipt)
                self._preserve_local(job,[next(t for t in tasks if t['index']==task['index'])]);recovered+=1
            return f'Đã lấy thêm {recovered} ảnh hiện có từ dự án Flow cũ.'
        finally:
            if owns_bridge:await bridge.cdp.close()

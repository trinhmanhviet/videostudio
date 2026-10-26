"""Google Flow image adapter using the existing dedicated Chrome tab only.

This intentionally uses visible Flow UI controls. It never calls Flow-private APIs,
never opens a second Flow tab, and submits only when the UI explicitly says 0 credits.
"""
import asyncio
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from .core import digest

FLOW_HOME = 'https://flow.google.com/'
MAX_FLOW_DOWNLOAD = 25 * 1024 * 1024


class FlowTaskError(RuntimeError):
    def __init__(self, message, code='needs_flow_check'):
        super().__init__(message)
        self.code = code


class FlowImages:
    def __init__(self, bridge, root):
        self.bridge = bridge
        self.root = Path(root)
        self.tasks = self.root / 'tasks'
        self.projects = self.root / 'projects'
        self.events = []
        self.active_frame = None
        self.download_guid = None
        self.download_complete = False
        self.download_error = None
        self.download_changed = asyncio.Event()

    def on_event(self, event):
        if not self.active_frame:
            return
        method = event.get('method')
        p = event.get('params', {})
        if method == 'Browser.downloadWillBegin':
            if p.get('frameId') != self.active_frame:
                return
            guid = p.get('guid')
            try:
                uuid.UUID(guid)
            except (ValueError, TypeError, AttributeError):
                return
            if self.download_guid and self.download_guid != guid:
                self.download_error = 'More than one Flow download started; refusing to choose a file'
            else:
                self.download_guid = guid
            self.events.append({'method': method, 'frameId': p.get('frameId'), 'guid': guid, 'suggestedFilename': p.get('suggestedFilename')})
            self.download_changed.set()
        elif method == 'Browser.downloadProgress' and p.get('guid') == self.download_guid:
            self.events.append({'method': method, 'guid': p.get('guid'), 'state': p.get('state'), 'receivedBytes': p.get('receivedBytes'), 'totalBytes': p.get('totalBytes')})
            if p.get('state') == 'completed':
                self.download_complete = True
            elif p.get('state') == 'canceled':
                self.download_error = 'Flow download was canceled'
            self.download_changed.set()

    def _receipt_path(self, task_id):
        return self.tasks / (task_id + '.json')

    def _write_receipt(self, task_id, value):
        self.tasks.mkdir(parents=True, exist_ok=True)
        path = self._receipt_path(task_id)
        part = path.with_suffix('.json.part')
        part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
        part.replace(path)

    def _read_receipt(self, task_id):
        path = self._receipt_path(task_id)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding='utf8'))
        if value.get('task_id') != task_id:
            raise FlowTaskError('Flow receipt does not match this scene request', 'uncertain')
        return value

    @staticmethod
    def _valid_project_url(job_id, url):
        try:uuid.UUID(job_id)
        except (ValueError,TypeError,AttributeError):return False
        parsed=urlparse(url or '')
        return parsed.scheme=='https' and parsed.hostname=='flow.google.com' and bool(re.fullmatch(r'/project/[A-Za-z0-9-]+/?',parsed.path))

    def _project_registry_path(self,job_id):
        try:uuid.UUID(job_id)
        except (ValueError,TypeError,AttributeError) as error:raise FlowTaskError('Flow project mapping requires a UUID job id','uncertain') from error
        return self.projects/(job_id+'.json')

    def _save_project_registry(self,job_id,project_url):
        if not self._valid_project_url(job_id,project_url):raise FlowTaskError('Refusing to store an invalid Flow project URL','uncertain')
        self.projects.mkdir(parents=True,exist_ok=True);path=self._project_registry_path(job_id);part=path.with_suffix('.json.part')
        part.write_text(json.dumps({'job_id':job_id,'project_url':project_url.split('?')[0],'created_at':time.time()},ensure_ascii=False,indent=2),encoding='utf8');part.replace(path)

    def _load_project_registry(self,job_id):
        path=self._project_registry_path(job_id)
        if path.is_file():
            value=json.loads(path.read_text(encoding='utf8'))
            if value.get('job_id')!=job_id or not self._valid_project_url(job_id,value.get('project_url')):raise FlowTaskError('Flow project registry is invalid; refusing a new project','uncertain')
            return value
        # Migrate earlier per-task receipts when they all point at one project for this job.
        projects=set()
        if self.tasks.is_dir():
            for receipt_path in self.tasks.glob('*.json'):
                try:value=json.loads(receipt_path.read_text(encoding='utf8'))
                except (OSError,ValueError):continue
                if value.get('job_id')==job_id and value.get('project_url'):
                    if not self._valid_project_url(job_id,value['project_url']):raise FlowTaskError('Legacy Flow receipt contains an invalid project URL','uncertain')
                    projects.add(value['project_url'].split('?')[0])
        if len(projects)>1:raise FlowTaskError('Existing Flow receipts for this video point at multiple projects; refusing to mix assets','uncertain')
        if projects:
            url=projects.pop();self._save_project_registry(job_id,url)
            return {'job_id':job_id,'project_url':url}
        return None

    @staticmethod
    def _new_media(baseline,images):
        before=set(baseline or []);new=[image for image in images if image.get('media_id') and image['media_id'] not in before]
        if len(new)>1:raise FlowTaskError('More than one new Flow media item appeared; refusing ambiguous scene match','uncertain')
        return new[0] if new else None

    async def _eval(self, session, expression, timeout=8):
        result = await self.bridge.cdp.command(
            'Runtime.evaluate', {'expression': expression, 'returnByValue': True}, session=session, timeout=timeout)
        if result.get('exceptionDetails'):
            raise FlowTaskError('Google Flow page inspection failed')
        return result.get('result', {}).get('value')

    async def _click_point(self, session, point):
        if not point or not isinstance(point.get('x'), (int, float)) or not isinstance(point.get('y'), (int, float)):
            raise FlowTaskError('Required Google Flow control was not found')
        for kind in ('mousePressed', 'mouseReleased'):
            await self.bridge.cdp.command('Input.dispatchMouseEvent', {
                'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1
            }, session=session)

    async def _click_expr(self, session, expression, label):
        point = await self._eval(session, expression)
        if not point:
            raise FlowTaskError('Google Flow control unavailable: ' + label)
        await self._click_point(session, point)
        await asyncio.sleep(.18)

    async def _click_named(self, session, name, *, exact=False, selector='button,[role=button]', timeout=5):
        # Text/aria lookup only locates a visible control; the actual action is a CDP mouse press.
        expression = r'''(()=>{const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLocaleLowerCase();const wanted=norm(LABEL);const all=[...document.querySelectorAll(SELECTOR)].filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'});const matches=all.filter(e=>{const text=norm(e.innerText),aria=norm(e.getAttribute('aria-label'));return EXACT?(text===wanted||aria===wanted):(text.includes(wanted)||aria.includes(wanted))});if(matches.length!==1)return null;const r=matches[0].getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()'''
        expression = expression.replace('LABEL', json.dumps(name, ensure_ascii=False)).replace('SELECTOR', json.dumps(selector)).replace('EXACT', 'true' if exact else 'false')
        point = await self._eval(session, expression, timeout=timeout)
        if not point:
            raise FlowTaskError('Google Flow needs exactly one visible control named ' + name)
        await self._click_point(session, point)
        await asyncio.sleep(.2)

    async def _snapshot(self, session, prompt=''):
        prompt_js = json.dumps(prompt, ensure_ascii=False)
        expression = r'''(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const norm=s=>(s||'').replace(/\s+/g,' ').trim();const body=document.body.innerText||'';const lines=body.split('\n').map(x=>x.trim()).filter(Boolean);const box=document.querySelector('[role="textbox"][aria-label="Bạn muốn tạo những gì?"],.ProseMirror[contenteditable="true"]');const draft=box?norm(box.innerText||box.textContent):'';const attachedMediaIds=box?[...new Set([...box.querySelectorAll('[data-media-id]')].map(e=>e.getAttribute('data-media-id')).filter(Boolean))]:[];const agent=document.querySelector('button.agent-mode-chip');let agentOn=null;if(agent){const p=agent.getAttribute('aria-pressed');if(p==='true')agentOn=true;else if(p==='false')agentOn=false;else{const m=getComputedStyle(agent).backgroundColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);if(m){const y=(.2126*+m[1]+.7152*+m[2]+.0722*+m[3])/255;if(y>.78)agentOn=true;else if(y<.28)agentOn=false;}}}const imgs=[...document.querySelectorAll('img[data-media-id]')].filter(i=>visible(i)&&i.complete&&i.naturalWidth>=512&&i.naturalHeight>=512).map(i=>{let r=i.getBoundingClientRect(),card=i.closest('flow-grid-tile-container');return{media_id:i.getAttribute('data-media-id'),title:card?.getAttribute('aria-label')||'',width:i.naturalWidth,height:i.naturalHeight,alt:i.alt||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}});const genButton=document.querySelector('button[aria-label="Bắt đầu tạo"]');const genDisabled=!genButton||genButton.disabled;const credit=lines.filter(x=>/tín dụng|credit/i.test(x));const exact=norm(draft)===norm(PROMPT);const settingsOpen=document.querySelectorAll('button.mat-button-toggle-button').length>=8;return{url:location.href,title:document.title,login:/accounts\.google\.com/i.test(location.href)||/đăng nhập vào google|sign in to google/i.test(body.slice(0,900)),challenge:/captcha|verify you are human|xác minh bạn là người/i.test(body.slice(0,1200)),draftLength:draft.length,draftEmpty:!draft&&attachedMediaIds.length===0,composerAvailable:!!box,draftMatches:exact,attachedMediaIds,agentOn,creditLines:credit,settingsOpen,settingsText:(document.querySelector('button.settings-trigger-button')?.innerText||''),generateDisabled:genDisabled,largeImages:imgs};})()'''
        return await self._eval(session, expression.replace('PROMPT', prompt_js))

    async def _target(self):
        targets = (await self.bridge.cdp.command('Target.getTargets')).get('targetInfos', [])
        flows = [t for t in targets if t.get('type') == 'page' and urlparse(t.get('url', '')).hostname == 'flow.google.com']
        if len(flows) > 1:
            raise FlowTaskError('More than one Flow tab is open. Nothing was closed or submitted.')
        if flows:
            return flows[0]['targetId']
        created = await self.bridge.cdp.command('Target.createTarget', {'url': FLOW_HOME})
        target = created.get('targetId')
        if not target:
            raise FlowTaskError('Could not open the single dedicated Flow tab')
        self.bridge.journal.own_target(target, 'flow')
        return target

    async def _session(self, target):
        if target not in self.bridge.sessions:
            result = await self.bridge.cdp.command('Target.attachToTarget', {'targetId': target, 'flatten': True})
            self.bridge.sessions[target] = result['sessionId']
        return self.bridge.sessions[target]

    async def _wait_page(self, session, predicate, timeout=40, prompt=''):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = await self._snapshot(session, prompt)
            if last.get('login') or last.get('challenge'):
                raise FlowTaskError('Google Flow requires sign-in or verification in the dedicated Chrome window', 'needs_auth')
            if predicate(last):
                return last
            await asyncio.sleep(.35)
        raise FlowTaskError('Google Flow page did not reach the expected state; no prompt was submitted')

    async def _ensure_project(self, task_id, job_id, prompt, target, session, receipt):
        state = await self._snapshot(session, prompt)
        if state.get('login') or state.get('challenge'):
            raise FlowTaskError('Google Flow requires sign-in or verification in the dedicated Chrome window', 'needs_auth')
        registry=self._load_project_registry(job_id)
        if receipt:
            project_url=receipt.get('project_url')
            if not project_url:
                raise FlowTaskError('Project creation outcome is unclear; refusing to create another project','uncertain')
            if not self._valid_project_url(job_id,project_url):
                raise FlowTaskError('Saved Flow project URL is invalid','uncertain')
            if registry and registry.get('project_url')!=project_url.split('?')[0]:
                raise FlowTaskError('Task receipt conflicts with this video’s Flow project registry','uncertain')
            if not registry:self._save_project_registry(job_id,project_url)
            project_path=project_url.split('?')[0].rstrip('/')
            if state['url'].split('?')[0].rstrip('/')!=project_path:
                if receipt.get('stage') in ('references_attaching','references_attached','prompt_ready','submitting','waiting_result','image_ready','download_menu_open','downloading'):
                    raise FlowTaskError('Submitted Flow request is open in another project; refusing to navigate or resubmit','uncertain')
                if not state.get('draftEmpty') or not state.get('generateDisabled'):
                    raise FlowTaskError('Flow tab has a draft or generation in progress; refusing to change project')
                await self.bridge.cdp.command('Page.navigate',{'url':project_url},session=session)
                state=await self._wait_page(session,lambda s:s['url'].split('?')[0].rstrip('/')==project_path and s.get('composerAvailable'),prompt=prompt)
            elif not state.get('composerAvailable'):
                state=await self._wait_page(session,lambda s:s['url'].split('?')[0].rstrip('/')==project_path and s.get('composerAvailable'),prompt=prompt)
            if 'baseline_media_ids' not in receipt and receipt.get('stage')=='project_ready':
                receipt['baseline_media_ids']=[x['media_id'] for x in state.get('largeImages',[]) if x.get('media_id')]
                self._write_receipt(task_id,receipt)
            return receipt,state
        if registry:
            project_url=registry['project_url'];project_path=project_url.rstrip('/')
            if state['url'].split('?')[0].rstrip('/')!=project_path:
                if not state.get('draftEmpty') or not state.get('generateDisabled'):
                    raise FlowTaskError('Flow tab has a draft or generation in progress; refusing to switch to the video project')
                await self.bridge.cdp.command('Page.navigate',{'url':project_url},session=session)
                state=await self._wait_page(session,lambda s:s['url'].split('?')[0].rstrip('/')==project_path and s.get('composerAvailable'),prompt=prompt)
            elif not state.get('composerAvailable'):
                state=await self._wait_page(session,lambda s:s['url'].split('?')[0].rstrip('/')==project_path and s.get('composerAvailable'),prompt=prompt)
            receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),'project_url':project_url,'target_id':target,'stage':'project_ready','baseline_media_ids':[x['media_id'] for x in state.get('largeImages',[]) if x.get('media_id')],'created_at':time.time()}
            self._write_receipt(task_id,receipt)
            return receipt,state
        if state.get('draftLength') or not state.get('generateDisabled'):
            raise FlowTaskError('Flow demo project has a draft or active request; refusing to replace it')
        self._write_receipt(task_id,{'task_id':task_id,'job_id':job_id,'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),'stage':'creating_project','created_at':time.time()})
        if not re.fullmatch(r'/+',urlparse(state['url']).path or '/'):
            await self._click_named(session,'Trang chủ',exact=True)
            state=await self._wait_page(session,lambda s:bool(re.fullmatch(r'/+',urlparse(s['url']).path or '/')),timeout=25,prompt=prompt)
        await self._click_named(session,'Dự án mới',selector='button,[role=button],a')
        state=await self._wait_page(session,lambda s:bool(re.fullmatch(r'/project/[A-Za-z0-9-]+/?',urlparse(s['url']).path)) and s.get('composerAvailable'),timeout=35,prompt=prompt)
        project_url=state['url'].split('?')[0]
        self._save_project_registry(job_id,project_url)
        receipt={'task_id':task_id,'job_id':job_id,'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),'project_url':project_url,'target_id':target,'stage':'project_ready','baseline_media_ids':[x['media_id'] for x in state.get('largeImages',[]) if x.get('media_id')],'created_at':time.time()}
        self._write_receipt(task_id,receipt)
        return receipt,state

    async def _ensure_agent_and_settings(self, session, prompt):
        state = await self._snapshot(session, prompt)
        if state.get('agentOn') is None:
            raise FlowTaskError('Cannot verify whether Tác nhân is off; no image request submitted')
        if state['agentOn']:
            await self._click_expr(session, '(()=>{const e=document.querySelector("button.agent-mode-chip");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()', 'Tác nhân')
            state = await self._wait_page(session, lambda s: s.get('agentOn') is False, timeout=5, prompt=prompt)
        # Open the documented model/settings panel on the existing Flow page.
        if not state.get('settingsOpen'):
            await self._click_expr(session, '(()=>{const e=document.querySelector("button.settings-trigger-button");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()', 'Cài đặt hình ảnh')
            state = await self._wait_page(session, lambda s: s.get('settingsOpen'), timeout=5, prompt=prompt)
        # Desired controls use the visible UI. Re-clicking a single-choice option is idempotent.
        await self._click_named(session, 'Hình ảnh', selector='button.mat-button-toggle-button')
        await self._click_named(session, '9:16', selector='button.mat-button-toggle-button')
        await self._click_named(session, 'x1', exact=True, selector='button.mat-button-toggle-button')
        state = await self._snapshot(session, prompt)
        if 'Nano Banana 2.1' not in (state.get('settingsText') or ''):
            await self._click_expr(session, '(()=>{const e=document.querySelector("button[aria-label=\"Chọn nhóm mô hình\"]");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()', 'chọn model')
            await self._click_named(session, 'Nano Banana 2.1')
        state = await self._snapshot(session, prompt)
        settings = state.get('settingsText') or ''
        if not all(v in settings for v in ('Nano Banana 2.1', 'crop_9_16', 'x1')):
            raise FlowTaskError('Model/aspect/count selection could not be verified; no image submitted')
        if state.get('agentOn') is not False:
            raise FlowTaskError('Tác nhân is not confirmed off; no image submitted')
        if not any(re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits', x, re.I) for x in state.get('creditLines', [])):
            raise FlowTaskError('Flow does not explicitly confirm generation costs 0 credits; request was not submitted', 'needs_zero_credit')
        return state

    async def _prompt_box(self, session):
        return await self._eval(session, r'''(()=>{const e=document.querySelector('[role="textbox"][aria-label="Bạn muốn tạo những gì?"],.ProseMirror[contenteditable="true"]');if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,text:(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim()}})()''')

    async def _image(self, session):
        return await self._eval(session, r'''(()=>{const a=[...document.querySelectorAll('img[data-media-id]')].filter(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);return r.width>40&&r.height>40&&s.display!=='none'&&i.complete&&i.naturalWidth>=512&&i.naturalHeight>=512});return a.map(i=>{const r=i.getBoundingClientRect(),card=i.closest('flow-grid-tile-container');return{media_id:i.getAttribute('data-media-id'),title:card?.getAttribute('aria-label')||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),width:i.naturalWidth,height:i.naturalHeight,alt:i.alt||''}})})()''')

    async def _click_media_control(self,session,media_id,name):
        expression=r'''(()=>{const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLocaleLowerCase(),wanted=norm(NAME);const img=document.querySelector('img[data-media-id="'+MEDIA+'"]'),card=img?.closest('flow-grid-tile-container');if(!card)return null;const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const matches=[...card.querySelectorAll('button,[role=button]')].filter(visible).filter(e=>norm(e.innerText)===wanted||norm(e.getAttribute('aria-label'))===wanted);if(matches.length!==1)return null;const r=matches[0].getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()'''.replace('NAME',json.dumps(name,ensure_ascii=False)).replace('MEDIA',json.dumps(media_id))
        point=await self._eval(session,expression)
        if not point:raise FlowTaskError('Could not find exactly one '+name+' control on the matched Flow media card','uncertain')
        await self._click_point(session,point);await asyncio.sleep(.2)

    async def _attach_reference(self, session, media_id, prompt):
        images=await self._image(session);matches=[image for image in images if image.get('media_id')==media_id]
        if len(matches)!=1:raise FlowTaskError('Exact Flow reference media card is missing or ambiguous; no prompt submitted','needs_flow_check')
        point=matches[0]
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':point['x'],'y':point['y'],'button':'none'},session=session)
        await asyncio.sleep(.15)
        await self._click_media_control(session,media_id,'Tuỳ chọn khác')
        labels=('Thêm vào câu lệnh','Thêm vào lời nhắc','Thêm vào prompt','Thêm vào ô nhập câu lệnh','Add to Prompt','Add to prompt')
        clicked=False
        for label in labels:
            try:
                await self._click_named(session,label,exact=True)
                clicked=True
                break
            except FlowTaskError:
                continue
        if not clicked:raise FlowTaskError('Flow reference menu has no uniquely identified Add to Prompt action; no image submitted','needs_flow_check')
        state=await self._wait_page(session,lambda value:media_id in value.get('attachedMediaIds',[]),timeout=6,prompt=prompt)
        if state.get('attachedMediaIds',[]).count(media_id)!=1:
            raise FlowTaskError('Flow did not expose exactly one attached reference media ID; no image submitted','needs_flow_check')
        return state

    async def _download_2k(self, task_id, target, session, receipt, prompt, media_id=None, timeout=75):
        folder = self.root / 'downloads' / task_id
        folder.mkdir(parents=True, exist_ok=True)
        if receipt.get('stage') == 'downloaded':
            path = Path(receipt.get('download_path', ''))
            if path.is_file() and digest(path) == receipt.get('download_sha256'):
                return receipt
        await self.bridge.cdp.command('Target.activateTarget', {'targetId': target})
        frame = (await self.bridge.cdp.command('Page.getFrameTree', session=session))['frameTree']['frame']['id']
        self.active_frame = frame; self.download_guid = None; self.download_complete = False; self.download_error = None; self.events = []; self.download_changed.clear()
        try:
            if getattr(self.bridge.images, 'download_behavior_uncertain', False):
                await self.bridge.cdp.command('Browser.setDownloadBehavior', {'behavior': 'default', 'eventsEnabled': False})
                self.bridge.images.download_behavior_uncertain = False
            await self.bridge.cdp.command('Browser.setDownloadBehavior', {'behavior':'allowAndName','downloadPath':str(folder.resolve()),'eventsEnabled':True})
            images = await self._image(session)
            if media_id:
                matches=[image for image in images if image.get('media_id')==media_id]
                if len(matches)!=1:raise FlowTaskError('The task-specific Flow media card is missing or ambiguous; refusing to download another scene','uncertain')
                img=matches[0]
            elif len(images)==1:
                img=images[0]
            else:
                raise FlowTaskError('Flow media ID is required when a project contains multiple images','uncertain')
            await self.bridge.cdp.command('Input.dispatchMouseEvent', {'type':'mouseMoved','x':img['x'],'y':img['y']}, session=session)
            await asyncio.sleep(.35)
            await self._click_media_control(session,img['media_id'],'Tuỳ chọn khác')
            await self._click_named(session, 'Tải xuống')
            receipt.update({'stage':'download_menu_open','updated_at':time.time()}); self._write_receipt(task_id, receipt)
            await self._click_named(session, '2K')
            receipt.update({'stage':'downloading','updated_at':time.time()}); self._write_receipt(task_id, receipt)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not self.download_complete:
                if self.download_error:
                    raise FlowTaskError(self.download_error, 'uncertain')
                self.download_changed.clear()
                try: await asyncio.wait_for(self.download_changed.wait(), min(2, max(.1, deadline-time.monotonic())))
                except asyncio.TimeoutError: pass
            if not self.download_guid or not self.download_complete:
                raise FlowTaskError('Flow 2K download was not confirmed; do not create a second image', 'uncertain')
            downloaded = folder / self.download_guid
            if not downloaded.is_file() or not 1000 < downloaded.stat().st_size <= MAX_FLOW_DOWNLOAD:
                raise FlowTaskError('Flow download is missing or has invalid size', 'uncertain')
            with Image.open(downloaded) as im:
                if im.format not in ('PNG','JPEG','WEBP') or min(im.size) < 512 or max(im.size) > 8192 or im.width*im.height > 20_000_000:
                    raise FlowTaskError('Flow 2K image format/dimensions failed validation')
                im.load(); width,height=im.size; fmt=im.format
                destination=(self.root/(task_id+'.png')).resolve();part=destination.with_suffix('.part')
                im.convert('RGB').save(part,format='PNG',optimize=True)
            part.replace(destination)
            receipt.update({'stage':'downloaded','download_path':str(destination),'download_sha256':digest(destination),'width':width,'height':height,'format':fmt,'download_guid':self.download_guid,'media_id':media_id,'updated_at':time.time()});self._write_receipt(task_id,receipt)
            return receipt
        finally:
            self.active_frame = None
            try: await self.bridge.cdp.command('Browser.setDownloadBehavior', {'behavior':'default','eventsEnabled':False})
            except Exception: self.bridge.images.download_behavior_uncertain = True

    def _cached_result(self, task_id, receipt):
        if not receipt:
            return None
        output=(self.root/(task_id+'.png')).resolve()
        if receipt.get('stage') not in ('downloaded','download_menu_open','downloading','image_ready'):
            return None
        if not output.is_file():
            if receipt.get('stage')=='downloaded':
                raise FlowTaskError('Flow says the image was downloaded but the candidate file is missing; refusing regeneration','uncertain')
            return None
        if output.stat().st_size>MAX_FLOW_DOWNLOAD or (receipt.get('stage')=='downloaded' and digest(output)!=receipt.get('download_sha256')):
            raise FlowTaskError('Saved Flow candidate failed receipt validation; refusing regeneration','uncertain')
        try:
            with Image.open(output) as im:
                if im.format!='PNG' or min(im.size)<512 or max(im.size)>8192 or im.width*im.height>20_000_000:
                    raise ValueError('invalid image')
                im.load();width,height=im.size
        except Exception as error:
            raise FlowTaskError('Saved Flow candidate is invalid; refusing regeneration','uncertain') from error
        receipt.update({'stage':'downloaded','download_path':str(output),'download_sha256':digest(output),'width':width,'height':height,'updated_at':time.time()})
        self._write_receipt(task_id,receipt)
        return {'task_id':task_id,'file_path':str(output),'sha256':digest(output),'width':width,'height':height,'request_id':'flow-'+task_id,'source':'google_flow_nano_banana_2_1','format':'PNG','project_url':receipt.get('project_url'),'download_guid':receipt.get('download_guid'),'media_id':receipt.get('media_id')}

    async def generate(self, task_id, job_id, prompt, timeout=900, reference_media_ids=None, reference_identity=None):
        try: uuid.UUID(task_id); uuid.UUID(job_id)
        except (ValueError, TypeError, AttributeError) as e: raise ValueError('Flow requires UUID task and job IDs') from e
        if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= 12000: raise ValueError('Invalid Flow scene prompt')
        refs=[] if reference_media_ids is None else reference_media_ids
        if not isinstance(refs,list) or any(not isinstance(media_id,str) for media_id in refs) or len(refs)>16 or len(refs)!=len(set(refs)):
            raise ValueError('reference_media_ids must be a unique list of at most 16 Flow media UUIDs')
        for media_id in refs:
            try:uuid.UUID(media_id)
            except (ValueError,TypeError,AttributeError) as e:raise ValueError('Invalid Flow reference media ID') from e
        identity=[] if reference_identity is None else reference_identity
        if not isinstance(identity,list) or len(identity)!=len(refs):raise ValueError('reference_identity must match reference_media_ids exactly')
        for media_id,item in zip(refs,identity):
            if not isinstance(item,dict) or item.get('media_id')!=media_id or not isinstance(item.get('character_id'),str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',item['character_id']):
                raise ValueError('Invalid Flow reference identity mapping')
            if not isinstance(item.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',item['sha256']):raise ValueError('Flow reference identity requires a SHA-256 content hash')
            if not isinstance(item.get('project_url'),str) or not self._valid_project_url(job_id,item['project_url']):raise ValueError('Flow reference identity requires a valid same-job project URL')
        identity_hash=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
        prompt=prompt.strip();prompt_sha=hashlib.sha256(prompt.encode('utf8')).hexdigest()
        receipt=self._read_receipt(task_id)
        if receipt and receipt.get('job_id')!=job_id:raise FlowTaskError('Flow task receipt belongs to a different job; refusing cached result or regeneration','uncertain')
        if receipt and receipt.get('prompt_sha256')!=prompt_sha: raise FlowTaskError('Flow receipt prompt differs; refusing a second generation','uncertain')
        if receipt and receipt.get('reference_media_ids',[])!=refs:raise FlowTaskError('Flow receipt reference media set differs; refusing a second generation','uncertain')
        if receipt and receipt.get('reference_identity',[])!=identity:raise FlowTaskError('Flow receipt reference content/character identity differs; refusing a second generation','uncertain')
        cached=self._cached_result(task_id,receipt)
        if cached:return cached
        async with self.bridge.job_lock:
            await self.bridge.connect()
            target=await self._target();session=await self._session(target)
            await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
            receipt=self._read_receipt(task_id)
            if receipt and receipt.get('job_id')!=job_id:raise FlowTaskError('Flow task receipt belongs to a different job; refusing cached result or regeneration','uncertain')
            if receipt and receipt.get('prompt_sha256')!=prompt_sha: raise FlowTaskError('Flow receipt prompt differs; refusing a second generation','uncertain')
            if receipt and receipt.get('reference_media_ids',[])!=refs:raise FlowTaskError('Flow receipt reference media set differs; refusing a second generation','uncertain')
            if receipt and receipt.get('reference_identity',[])!=identity:raise FlowTaskError('Flow receipt reference content/character identity differs; refusing a second generation','uncertain')
            cached=self._cached_result(task_id,receipt)
            if cached:return cached
            receipt,state=await self._ensure_project(task_id,job_id,prompt,target,session,receipt)
            saved_refs=receipt.get('reference_media_ids')
            if saved_refs is None:
                if receipt.get('stage')!='project_ready':raise FlowTaskError('Flow receipt lacks reference identity after a non-empty stage; refusing ambiguous recovery','uncertain')
                receipt['reference_media_ids']=refs;receipt['reference_identity']=identity
                receipt['conditioning_sha256']=hashlib.sha256(json.dumps({'prompt_sha256':prompt_sha,'reference_identity_sha256':identity_hash},sort_keys=True).encode('utf8')).hexdigest()
                receipt['attached_reference_media_ids']=[];self._write_receipt(task_id,receipt)
            elif saved_refs!=refs:
                raise FlowTaskError('Flow receipt reference media set differs; refusing a second generation','uncertain')
            if receipt.get('reference_identity',[])!=identity:raise FlowTaskError('Flow receipt reference content/character identity differs; refusing a second generation','uncertain')
            project_path=receipt.get('project_url','').split('?')[0].rstrip('/')
            if any(item['project_url'].split('?')[0].rstrip('/')!=project_path for item in identity):raise FlowTaskError('Flow reference assets do not belong to the task’s exact project','needs_flow_check')
            available={image.get('media_id') for image in state.get('largeImages',[]) if image.get('media_id')}
            if not set(refs)<=available:raise FlowTaskError('One or more reference media IDs are not in this job’s Flow project','needs_flow_check')
            if receipt.get('stage') in ('submitting','waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                if receipt.get('attached_reference_media_ids',[])!=refs:raise FlowTaskError('Submitted Flow receipt lacks the exact attached reference set','uncertain')
            else:
                attached=list(state.get('attachedMediaIds',[]))
                if len(attached)!=len(set(attached)) or attached!=refs[:len(attached)]:
                    raise FlowTaskError('Flow composer contains unexpected or reordered media attachments; no image submitted','needs_flow_check')
                receipt.update({'stage':'references_attaching','attached_reference_media_ids':attached,'updated_at':time.time()});self._write_receipt(task_id,receipt)
                for media_id in refs[len(attached):]:
                    state=await self._attach_reference(session,media_id,prompt)
                    attached=list(state.get('attachedMediaIds',[]))
                    if attached!=refs[:len(attached)]:raise FlowTaskError('Flow attachment order/identity could not be verified; no image submitted','needs_flow_check')
                    receipt.update({'stage':'references_attaching','attached_reference_media_ids':attached,'updated_at':time.time()});self._write_receipt(task_id,receipt)
                if attached!=refs:raise FlowTaskError('Flow attachment set does not exactly match the requested references; no image submitted','needs_flow_check')
                receipt.update({'stage':'references_attached','attached_reference_media_ids':refs,'updated_at':time.time()});self._write_receipt(task_id,receipt)
            if receipt.get('stage') in ('submitting','waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                if state['url'].split('?')[0].rstrip('/')!=receipt.get('project_url','').split('?')[0].rstrip('/'):
                    raise FlowTaskError('Flow project changed during recovery; no new request sent','uncertain')
                baseline=receipt.get('baseline_media_ids')
                if baseline is None:raise FlowTaskError('Flow receipt lacks its baseline media IDs; refusing to guess a result','uncertain')
                if receipt.get('stage') in ('submitting','waiting_result'):
                    state=await self._wait_page(session,lambda s:self._new_media(baseline,s.get('largeImages',[])) is not None,timeout=timeout,prompt=prompt)
                    media=self._new_media(baseline,state.get('largeImages',[]))
                    receipt.update({'stage':'image_ready','media_id':media['media_id'],'result_dimensions':media,'updated_at':time.time()});self._write_receipt(task_id,receipt)
                else:
                    media_id=receipt.get('media_id')
                    if not media_id:raise FlowTaskError('Flow receipt lacks media ID; refusing to download another scene','uncertain')
                    images=await self._image(session)
                    if len([x for x in images if x.get('media_id')==media_id])!=1:
                        raise FlowTaskError('The task-specific Flow media card is missing; no new image will be submitted','uncertain')
            else:
                # Refuse to overwrite any human draft; only an empty or exact matching draft is safe.
                box=await self._prompt_box(session)
                if not box: raise FlowTaskError('Flow prompt box unavailable; nothing submitted')
                if box['text'] and box['text']!=' '.join(prompt.split()): raise FlowTaskError('A different Flow draft exists; refusing to overwrite it')
                if not box['text']:
                    await self._click_point(session,box)
                    await self.bridge.cdp.command('Input.insertText',{'text':prompt},session=session)
                    state=await self._wait_page(session,lambda s:s.get('draftMatches'),timeout=6,prompt=prompt)
                configured=await self._ensure_agent_and_settings(session,prompt)
                if configured.get('draftMatches') is not True or configured.get('attachedMediaIds',[])!=refs:
                    raise FlowTaskError('Flow prompt/reference attachment changed before Submit; no image request sent','needs_flow_check')
                cost_line=next((x for x in configured.get('creditLines',[]) if re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',x,re.I)),None)
                if not cost_line or configured.get('agentOn') is not False:
                    raise FlowTaskError('Zero-credit/Agent-off confirmation changed before Submit; no image request sent','needs_zero_credit')
                receipt.update({'stage':'submitting','agent_off':True,'settings_text':configured.get('settingsText'),'credit_confirmation':cost_line,'attached_reference_media_ids':refs,'submitted_prompt_sha256':prompt_sha,'submitted_at':time.time(),'updated_at':time.time()});self._write_receipt(task_id,receipt)
                await self._click_named(session,'Bắt đầu tạo',exact=True)
                receipt.update({'stage':'waiting_result','updated_at':time.time()});self._write_receipt(task_id,receipt)
            if receipt.get('stage') not in ('image_ready','download_menu_open','downloading'):
                baseline=receipt.get('baseline_media_ids')
                if baseline is None:raise FlowTaskError('Flow receipt lacks its baseline media IDs; refusing to guess a result','uncertain')
                state=await self._wait_page(session,lambda s:self._new_media(baseline,s.get('largeImages',[])) is not None,timeout=timeout,prompt=prompt)
                media=self._new_media(baseline,state.get('largeImages',[]))
                receipt.update({'stage':'image_ready','media_id':media['media_id'],'updated_at':time.time(),'result_dimensions':media});self._write_receipt(task_id,receipt)
            if not receipt.get('media_id'):raise FlowTaskError('Flow receipt lacks the completed media ID; refusing ambiguous download','uncertain')
            receipt=await self._download_2k(task_id,target,session,receipt,prompt,media_id=receipt['media_id'])
            output=Path(receipt['download_path'])
            return {'task_id':task_id,'file_path':str(output),'sha256':digest(output),'width':receipt['width'],'height':receipt['height'],'request_id':'flow-'+task_id,'source':'google_flow_nano_banana_2_1','format':'PNG','flow_download_format':receipt.get('format'),'project_url':receipt.get('project_url'),'download_guid':receipt.get('download_guid'),'media_id':receipt.get('media_id')}

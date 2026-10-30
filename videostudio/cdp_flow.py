"""Google Flow image adapter using the existing dedicated Chrome tab only.

This intentionally uses visible Flow UI controls. It never calls Flow-private APIs,
never opens a second Flow tab, and submits only when the UI explicitly says 0 credits.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import re
import time
import unicodedata
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
        self.batches = self.root / 'batches'
        self._flow_batch_lock=asyncio.Lock()
        self.events = []
        self.active_frame = None
        self.download_guid = None
        self.downloads = {}
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
            self.downloads.setdefault(guid,{'state':'inProgress'})
            if not self.download_guid:
                self.download_guid = guid
            self.download_complete = False
            self.events.append({'method': method, 'frameId': p.get('frameId'), 'guid': guid, 'suggestedFilename': p.get('suggestedFilename')})
            self.download_changed.set()
        elif method == 'Browser.downloadProgress' and p.get('guid') in self.downloads:
            self.downloads[p['guid']]['state']=p.get('state')
            self.events.append({'method': method, 'guid': p.get('guid'), 'state': p.get('state'), 'receivedBytes': p.get('receivedBytes'), 'totalBytes': p.get('totalBytes')})
            if p.get('state') == 'completed':
                self.download_complete = all(item['state']=='completed' for item in self.downloads.values())
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

    def _batch_path(self,batch_id):
        try:uuid.UUID(batch_id)
        except (ValueError,TypeError,AttributeError) as error:raise FlowTaskError('Flow batch ID must be a UUID','uncertain') from error
        return self.batches/(batch_id+'.json')

    def _read_batch_manifest(self,batch_id):
        path=self._batch_path(batch_id)
        if not path.is_file():return None
        value=json.loads(path.read_text(encoding='utf8'))
        if value.get('batch_id')!=batch_id:raise FlowTaskError('Flow batch manifest identity mismatch','uncertain')
        return value

    def _write_batch_manifest(self,batch_id,value):
        self.batches.mkdir(parents=True,exist_ok=True);path=self._batch_path(batch_id);part=path.with_suffix('.json.part')
        part.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');part.replace(path)

    @staticmethod
    def _prompt_text(value):
        return re.sub(r'\\s+',' ',unicodedata.normalize('NFC',str(value or ''))).strip()

    @classmethod
    def _batch_prompt_fingerprint(cls,text,mention_ids):
        payload={'prompt':cls._prompt_text(text),'mention_entity_ids':list(mention_ids or [])}
        return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()

    @classmethod
    def _batch_prompt_mapping(cls,tasks,media_prompts):
        """Match media to manifest only by exact full prompt text plus native entity IDs."""
        groups={}
        for task in tasks:
            mentions=cls._validate_character_mentions(task['job_id'],task.get('character_mentions',[]))
            expected=' '.join([x['name'] for x in mentions]+[task['prompt']]).strip()
            key=cls._batch_prompt_fingerprint(expected,[x['character_id'] for x in mentions])
            if key in groups:raise FlowTaskError('Duplicate prompt/entity fingerprints require sequential generation, not arbitrary batch ownership','uncertain')
            groups[key]=[task]
        assets={};seen_media=set()
        for media in media_prompts:
            media_id=media.get('media_id')
            if not media_id or media_id in seen_media:raise FlowTaskError('Flow batch media IDs are missing or duplicated','uncertain')
            seen_media.add(media_id)
            key=cls._batch_prompt_fingerprint(media.get('prompt',''),media.get('mention_entity_ids',[]))
            if key not in groups:raise FlowTaskError('Full prompt read from a Flow card does not match any submitted task','uncertain')
            assets.setdefault(key,[]).append(media_id)
        mapping={}
        for key,group in groups.items():
            media_ids=sorted(assets.get(key,[]))
            ordered=sorted(group,key=lambda x:(int(x.get('ordinal',0)),x['task_id']))
            if len(media_ids)!=len(ordered):raise FlowTaskError('Flow full-prompt identity count does not match the batch manifest','uncertain')
            for task,media_id in zip(ordered,media_ids):mapping[task['task_id']]=media_id
        if len(mapping)!=len(tasks) or len(set(mapping.values()))!=len(tasks):raise FlowTaskError('Flow batch mapping is not one-to-one','uncertain')
        return mapping

    @classmethod
    def _batch_row_mapping(cls,tasks,tiles,baseline,media_prompts=None):
        """Freeze UI media IDs before download; require row geometry AND full detail-panel prompt identity."""
        baseline=set(baseline or []);fresh=[];seen=set()
        for tile in tiles:
            media_id=tile.get('media_id')
            if not media_id or media_id in baseline:continue
            if media_id in seen or not tile.get('complete'):
                raise FlowTaskError('Flow cohort media IDs are duplicated or incomplete','uncertain')
            seen.add(media_id)
            if not all(isinstance(tile.get(key),(int,float)) for key in ('x','y','tile_height')):
                raise FlowTaskError('Flow cohort tile coordinates are unavailable','uncertain')
            fresh.append(tile)
        if len(fresh)!=len(tasks):
            raise FlowTaskError('Flow cohort has a different number of new tiles than prompts','uncertain')
        height=min(tile['tile_height'] for tile in fresh)
        if height<=0:raise FlowTaskError('Flow cohort tile height is invalid','uncertain')
        tolerance=max(8,height*.1);rows=[]
        for tile in sorted(fresh,key=lambda value:(value['y'],value['x'])):
            if not rows or abs(tile['y']-rows[-1][0]['y'])>tolerance:rows.append([tile])
            else:rows[-1].append(tile)
        if not rows:raise FlowTaskError('Flow cohort has no visible rows','uncertain')
        visual=[tile for row in rows for tile in sorted(row,key=lambda value:value['x'])]
        if len({tile['x'] for row in rows for tile in row})<2 and len(fresh)>1:
            raise FlowTaskError('Flow cohort tile positions overlap','uncertain')
        mapping={}
        if media_prompts is not None:
            full_by_id={value['media_id']:cls._prompt_text(value['prompt']) for value in media_prompts}
            if set(full_by_id)!={tile['media_id'] for tile in visual}:
                raise FlowTaskError('Flow detail prompts do not cover every cohort media ID','uncertain')
            used_media=set()
            for task in sorted(tasks,key=lambda value:value['ordinal']):
                expected=' '.join([mention['name'] for mention in task.get('character_mentions',[])]+[task['prompt']]).strip()
                expected_norm=cls._prompt_text(expected)
                matched=[mid for mid,prompt_text in full_by_id.items() if prompt_text==expected_norm and mid not in used_media]
                if len(matched)!=1:
                    raise FlowTaskError('Flow detail prompt did not match exactly one cohort task','uncertain')
                chosen=matched[0];used_media.add(chosen)
                mapping[task['task_id']]=chosen
        else:
            for task,tile in zip(sorted(tasks,key=lambda value:value['ordinal']),reversed(visual)):
                expected=' '.join([mention['name'] for mention in task.get('character_mentions',[])]+[task['prompt']]).strip()
                text=cls._prompt_text(tile.get('text',''))
                if cls._prompt_text(expected)!=text:
                    raise FlowTaskError('Flow detail prompt conflicts with the visual row order; refusing positional ownership','uncertain')
                mapping[task['task_id']]=tile['media_id']
        return mapping

    @staticmethod
    def _flow_asset_rows(tiles):
        if not tiles:return []
        tolerance=max(8,min(tile.get('tile_height',0) for tile in tiles)*.1)
        rows=[]
        for tile in sorted(tiles,key=lambda value:(value['y'],value['x'])):
            if not rows or abs(tile['y']-rows[-1][0]['y'])>tolerance:rows.append([tile])
            else:rows[-1].append(tile)
        return rows

    async def _ensure_batch_row_layout(self,session,project_url,tasks,baseline,tiles):
        def expected_rows(rows):
            count=len(tasks);expected=(count+9)//10;last=count%10 or 10
            return len(rows)==expected and all(len(row)==10 for row in rows[:-1]) and len(rows[-1])==last
        rows=self._flow_asset_rows(tiles)
        if expected_rows(rows):return tiles
        state=await self._snapshot(session,'')
        if (state.get('url','').split('?')[0].rstrip('/')!=project_url.split('?')[0].rstrip('/') or
                not state.get('draftEmpty') or not state.get('generateDisabled')):
            raise FlowTaskError('Flow project/draft changed before row layout check','uncertain')
        toggle=await self._eval(session,r'''(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};return[...document.querySelectorAll('button,[role=button]')].filter(visible).filter(e=>/thu gọn/i.test(e.innerText||'')).length})()''')
        if toggle!=1:
            raise FlowTaskError('Flow grid does not fit ten tiles per row and the sidebar-collapse control is not unique','uncertain')
        await self._click_named(session,'Thu gọn',selector='button,[role=button]')
        state=await self._wait_page(session,lambda s:s.get('url','').split('?')[0].rstrip('/')==project_url.split('?')[0].rstrip('/'),timeout=5,prompt='')
        tiles=[tile for tile in state.get('assetTiles',[]) if tile.get('media_id') and tile['media_id'] not in set(baseline or []) and tile.get('complete')]
        if not expected_rows(self._flow_asset_rows(tiles)):
            raise FlowTaskError('Flow grid still wraps away from the expected ten-image rows after collapsing the sidebar','uncertain')
        return tiles

    @classmethod
    def _batch_download_order(cls,tasks,tiles,mapping):
        task_ids={task['task_id'] for task in tasks}
        if set(mapping)!=task_ids or len(set(mapping.values()))!=len(tasks):
            raise FlowTaskError('Flow mapping is not one-to-one before download ordering','uncertain')
        reverse={media_id:task_id for task_id,media_id in mapping.items()}
        fresh=[tile for tile in tiles if tile.get('media_id') in reverse and tile.get('complete')]
        if len(fresh)!=len(tasks):
            raise FlowTaskError('Mapped Flow media tiles are not all visible/complete for download ordering','uncertain')
        rows=cls._flow_asset_rows(fresh)
        # Window width/sidebar/zoom can wrap a cohort into any number of rows.
        # Full prompt/media IDs establish identity; geometry only orders clicks.
        # Flow displays newest on the left; traversing older/bottom rows first and
        # each row right-to-left follows the user's download direction.
        ordered_tiles=[tile for row in reversed(rows) for tile in sorted(row,key=lambda item:item['x'],reverse=True)]
        order=[reverse[tile['media_id']] for tile in ordered_tiles]
        positions={tile['media_id']:{'x':tile['x'],'y':tile['y'],'row':row_index} for row_index,row in enumerate(rows) for tile in row}
        return order,positions

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

    @classmethod
    def _validate_character_mentions(cls,job_id,mentions):
        try:uuid.UUID(job_id)
        except (ValueError,TypeError,AttributeError) as error:raise FlowTaskError('Native Character mentions require a UUID job ID','uncertain') from error
        if not isinstance(mentions,list) or len(mentions)>8:raise FlowTaskError('Native Character mentions must be a list of at most eight entities')
        normalized=[];ids=set();names=set();project=None
        for item in mentions:
            if not isinstance(item,dict):raise FlowTaskError('Invalid native Character mention')
            entity_id=item.get('character_id');name=item.get('name');project_url=item.get('project_url')
            try:uuid.UUID(entity_id)
            except (ValueError,TypeError,AttributeError) as error:raise FlowTaskError('Invalid native Flow Character entity ID') from error
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name):raise FlowTaskError('Invalid registered Flow Character name')
            if not isinstance(project_url,str) or not cls._valid_project_url(job_id,project_url):raise FlowTaskError('Invalid native Flow Character project URL')
            project_path=project_url.split('?')[0].rstrip('/')
            if project is not None and project_path!=project:raise FlowTaskError('Native Characters must belong to the same Flow project')
            project=project_path
            if entity_id in ids or name.casefold() in names:raise FlowTaskError('Duplicate native Character ID or registered name')
            ids.add(entity_id);names.add(name.casefold());normalized.append({'character_id':entity_id,'name':name,'project_url':project_path})
        return normalized

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

    async def _click_named(self, session, name, *, exact=False, selector='button,[role=button],[role=menuitem]', timeout=5, native_only=False, download_frame=None):
        # Text/aria lookup only locates a visible, unobscured control; the action remains a trusted CDP mouse press.
        expression = r'''(()=>{const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLocaleLowerCase();const wanted=norm(LABEL);const all=[...document.querySelectorAll(SELECTOR)].filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'});const matches=all.filter(e=>{const text=norm(e.innerText),aria=norm(e.getAttribute('aria-label'));return EXACT?(text===wanted||aria===wanted):(text.includes(wanted)||aria.includes(wanted))});if(matches.length!==1)return null;const b=matches[0],r=b.getBoundingClientRect(),x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2),hit=document.elementFromPoint(x,y);return{x,y,hitIsControl:hit===b||b.contains(hit)}})()'''
        expression = expression.replace('LABEL', json.dumps(name, ensure_ascii=False)).replace('SELECTOR', json.dumps(selector)).replace('EXACT', 'true' if exact else 'false')
        deadline=time.monotonic()+timeout;point=None
        while time.monotonic()<deadline:
            point=await self._eval(session,expression,timeout=1)
            if point and point.get('hitIsControl'):break
            await asyncio.sleep(.12)
        if not point or not point.get('hitIsControl'):
            raise FlowTaskError('Google Flow needs exactly one stable visible control named ' + name)
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':point['x'],'y':point['y']},session=session)
        landed=await self._eval(session,expression,timeout=2)
        if not landed or not landed.get('hitIsControl'):raise FlowTaskError('Google Flow '+name+' control moved or was obscured before click','uncertain')
        if download_frame is not None:
            self.download_guid=None;self.downloads={};self.download_complete=False;self.download_error=None;self.events=[];self.download_changed.clear()
            self.active_frame=download_frame
        await self._click_point(session,landed)
        if not native_only:
            await self._eval(session,r'''(()=>{const hit=document.elementFromPoint(%d,%d);const b=hit?.closest('button,[role=button],[role=menuitem]');b?.click()})()'''%(landed['x'],landed['y']))
        await asyncio.sleep(.2)

    async def _snapshot(self, session, prompt=''):
        prompt_js = json.dumps(prompt, ensure_ascii=False)
        expression = r'''(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const norm=s=>(s||'').replace(/\s+/g,' ').trim();const body=document.body?.innerText||'';const lines=body.split('\n').map(x=>x.trim()).filter(Boolean);const box=document.querySelector('[role="textbox"][aria-label="Bạn muốn tạo những gì?"],.ProseMirror[contenteditable="true"]');const draft=box?norm(box.innerText||box.textContent):'';const attachedMediaIds=box?[...new Set([...box.querySelectorAll('[data-media-id]')].map(e=>e.getAttribute('data-media-id')).filter(Boolean))]:[];const mentionEntityIds=box?[...new Set([...box.querySelectorAll('[data-entity-id]')].map(e=>e.getAttribute('data-entity-id')).filter(Boolean))]:[];const agent=document.querySelector('button.agent-mode-chip');let agentOn=null;if(agent){const p=agent.getAttribute('aria-pressed');if(p==='true')agentOn=true;else if(p==='false')agentOn=false;else{const m=getComputedStyle(agent).backgroundColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);if(m){const y=(.2126*+m[1]+.7152*+m[2]+.0722*+m[3])/255;if(y>.78)agentOn=true;else if(y<.28)agentOn=false;}}}const tiles=[...document.querySelectorAll('flow-grid-tile-container')].filter(visible).map(t=>{const i=t.querySelector('img[data-media-id]'),r=t.getBoundingClientRect();return{tile_id:t.id||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),tile_width:r.width,tile_height:r.height,aria_label:t.getAttribute('aria-label')||'',text:norm(t.innerText||'').slice(0,14000),media_id:i?.getAttribute('data-media-id')||null,complete:!!i&&i.complete&&i.naturalWidth>0&&i.naturalHeight>0,data_asset_id:t.getAttribute('data-asset-id')||'',data_request_id:t.getAttribute('data-request-id')||'',data_task_id:t.getAttribute('data-task-id')||''}});const imgs=[...document.querySelectorAll('img[data-media-id]')].filter(i=>visible(i)&&i.complete&&i.naturalWidth>=256&&i.naturalHeight>=256).map(i=>{let r=i.getBoundingClientRect(),card=i.closest('flow-grid-tile-container');return{media_id:i.getAttribute('data-media-id'),title:card?.getAttribute('aria-label')||'',width:i.naturalWidth,height:i.naturalHeight,alt:i.alt||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}});const genButton=document.querySelector('button[aria-label="Bắt đầu tạo"]');const genDisabled=!genButton||genButton.disabled;const credit=lines.filter(x=>/tín dụng|credit/i.test(x));const exact=norm(draft)===norm(PROMPT);const settingsOpen=document.querySelectorAll('button.mat-button-toggle-button').length>=8;return{url:location.href,title:document.title,login:/accounts\.google\.com/i.test(location.href)||/đăng nhập vào google|sign in to google/i.test(body.slice(0,900)),challenge:/captcha|verify you are human|xác minh bạn là người/i.test(body.slice(0,1200)),draftLength:draft.length,draftEmpty:!draft&&attachedMediaIds.length===0,composerAvailable:!!box,draftMatches:exact,attachedMediaIds,mentionEntityIds,agentOn,creditLines:credit,settingsOpen,settingsText:(document.querySelector('button.settings-trigger-button')?.innerText||''),generateDisabled:genDisabled,largeImages:imgs,assetTiles:tiles};})()'''
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
                if receipt.get('stage') in ('references_attaching','references_attached','characters_attached','prompt_ready','submitting','waiting_result','image_ready','download_menu_open','downloading'):
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

    async def _ensure_agent_and_settings(self, session, prompt, *, require_zero_credit=False):
        state = await self._snapshot(session, prompt)
        if state.get('agentOn') is None:
            raise FlowTaskError('Cannot verify whether Tác nhân is off; no image request submitted')
        if state['agentOn']:
            await self._click_expr(session, '(()=>{const e=document.querySelector("button.agent-mode-chip");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()', 'Tác nhân')
            state = await self._wait_page(session, lambda s: s.get('agentOn') is False, timeout=5, prompt=prompt)
        matches=lambda value: value.get('agentOn') is False and all(v in (value.get('settingsText') or '') for v in ('Nano Banana 2.1','crop_9_16','x1'))
        # Flow retains these choices per project. Read the current trigger text
        # instead of re-selecting image mode/aspect/count for every scene.
        # Credit-restricted calls may still need the panel to expose the estimate.
        if matches(state) and (not require_zero_credit or state.get('creditLines')):
            return state
        # Open the documented model/settings panel on the existing Flow page.
        if not state.get('settingsOpen'):
            await self._click_expr(session, '(()=>{const e=document.querySelector("button.settings-trigger-button");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()', 'Cài đặt hình ảnh')
            state = await self._wait_page(session, lambda s: s.get('settingsOpen'), timeout=5, prompt=prompt)
        if matches(state):return state
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
        return state

    async def _prompt_box(self, session):
        return await self._eval(session, r'''(()=>{const e=document.querySelector('[role="textbox"][aria-label="Bạn muốn tạo những gì?"],.ProseMirror[contenteditable="true"]');if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,text:(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim()}})()''')

    async def _image(self, session):
        return await self._eval(session, r'''(()=>{const a=[...document.querySelectorAll('img[data-media-id]')].filter(i=>{const r=i.getBoundingClientRect(),s=getComputedStyle(i);return r.width>40&&r.height>40&&s.display!=='none'&&i.complete&&i.naturalWidth>=256&&i.naturalHeight>=256});return a.map(i=>{const r=i.getBoundingClientRect(),card=i.closest('flow-grid-tile-container');return{media_id:i.getAttribute('data-media-id'),title:card?.getAttribute('aria-label')||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),width:i.naturalWidth,height:i.naturalHeight,alt:i.alt||''}})})()''')

    async def _dismiss_flow_popups(self,session,attempts=3):
        """Close layered Flow info/menu popups before interacting with another tile."""
        check="(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'};return[...document.querySelectorAll('flow-info-panel,.mat-mdc-menu-panel,[id^=\\\"mat-menu-panel-\\\"]')].filter(visible).length})()"
        for _ in range(attempts):
            count=await self._eval(session,check)
            if not count:return
            point=await self._eval(session,"(()=>({x:Math.max(8,innerWidth-12),y:Math.max(8,innerHeight-12)}))()")
            if not point:raise FlowTaskError('Could not find a safe blank viewport point to dismiss Flow popups','uncertain')
            x,y=point['x'],point['y']
            await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':x,'y':y},session=session)
            await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mousePressed','x':x,'y':y,'button':'left','clickCount':1},session=session)
            await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseReleased','x':x,'y':y,'button':'left','clickCount':1},session=session)
            for event in ('keyDown','keyUp'):
                await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':event,'key':'Escape','code':'Escape'},session=session)
            await asyncio.sleep(.15)
        if await self._eval(session,check):raise FlowTaskError('Flow popup did not close; refusing to click an obscured control','uncertain')

    async def _grid_view(self,session,top=None):
        return await self._eval(session,r'''(()=>{const e=[...document.querySelectorAll('.cdk-virtual-scrollable.page-container')].find(e=>e.clientHeight>100);if(!e)return null;const top=TOP;if(top!==null)e.scrollTop=top;return{top:e.scrollTop,height:e.clientHeight,total:e.scrollHeight}})()'''.replace('TOP',json.dumps(top)))

    def _known_job_media(self,job_id,excluded):
        known=set()
        for path in self.tasks.glob('*.json'):
            old=json.loads(path.read_text(encoding='utf8'))
            if old.get('job_id')==job_id and old.get('task_id') not in excluded and old.get('media_id'):known.add(old['media_id'])
        return known

    async def _wait_batch_slot(self,session,manifest,normalized,timeout):
        submitted=sum(value in ('waiting_result','image_ready','download_menu_open','downloading','downloaded') for value in manifest['task_state'].values())
        if submitted<3:return
        baseline=set(manifest.get('baseline_media_ids') or [])|self._known_job_media(manifest['job_id'],{item['task_id'] for item in normalized})
        await self._grid_view(session,0)
        deadline=time.monotonic()+min(timeout,180)
        while time.monotonic()<deadline:
            state=await self._snapshot(session,'')
            complete={tile['media_id'] for tile in state.get('assetTiles',[]) if tile.get('media_id') and tile['media_id'] not in baseline and tile.get('complete')}
            if submitted-len(complete)<3:return
            await asyncio.sleep(1)
        raise FlowTaskError('Flow generation slots did not clear; saved requests kept, no extra prompt sent','needs_flow_check')

    async def _scan_grid_tiles(self,session,project_url,*,wanted=None,baseline=None,expected=None):
        """Read the top of Flow once: successful new images appear newest-left."""
        await self._grid_view(session,0)
        await asyncio.sleep(.18)
        state=await self._snapshot(session,'')
        if state.get('url','').split('?')[0].rstrip('/')!=project_url.split('?')[0].rstrip('/'):
            raise FlowTaskError('Flow project changed while reading recent images','uncertain')
        baseline=set(baseline or [])
        return [tile for tile in state.get('assetTiles',[]) if tile.get('media_id') and tile.get('complete')
                and ((wanted is not None and tile['media_id'] in wanted) or (wanted is None and tile['media_id'] not in baseline))]

    async def _ensure_media_mounted(self,session,media_id):
        selector=json.dumps('img[data-media-id="'+media_id+'"]')
        if await self._eval(session,'Boolean(document.querySelector('+selector+'))'):return
        state=await self._snapshot(session,'')
        await self._scan_grid_tiles(session,state['url'],wanted={media_id})
        if not await self._eval(session,'Boolean(document.querySelector('+selector+'))'):
            raise FlowTaskError('Saved Flow media is not among the recent images at the top; no downward search performed','uncertain')

    async def _click_media_control(self,session,media_id,name):
        await self._dismiss_flow_popups(session)
        await self._ensure_media_mounted(session,media_id)
        media_js=json.dumps(media_id);name_js=json.dumps(name,ensure_ascii=False)
        hover_expr="(()=>{const i=document.querySelector("+json.dumps('img[data-media-id="'+media_id+'"]')+");if(!i)return null;i.scrollIntoView({block:'center'});const r=i.getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()"
        hover_point=await self._eval(session,hover_expr)
        if not hover_point:raise FlowTaskError('Flow tile could not be scrolled into view before hover','uncertain')
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':hover_point['x'],'y':hover_point['y']},session=session)
        expression=r'''(()=>{const norm=s=>(s||'').replace(/\s+/g,' ').trim().toLocaleLowerCase(),wanted=norm(NAME);const img=document.querySelector('img[data-media-id="'+MEDIA+'"]');if(!img)return null;const card=img.closest('flow-grid-tile-container');if(!card)return null;const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const matches=[...card.querySelectorAll('button,[role=button],[role=menuitem]')].filter(visible).filter(e=>norm(e.innerText)===wanted||norm(e.getAttribute('aria-label'))===wanted);if(matches.length!==1)return null;const b=matches[0],r=b.getBoundingClientRect(),x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2),hit=document.elementFromPoint(x,y);return{x,y,hitIsControl:hit===b||b.contains(hit)}})()'''.replace('NAME',name_js).replace('MEDIA',media_js)
        deadline=time.monotonic()+5;point=None
        while time.monotonic()<deadline:
            point=await self._eval(session,expression,timeout=1)
            if point and point.get('hitIsControl'):break
            await asyncio.sleep(.12)
        if not point or not point.get('hitIsControl'):raise FlowTaskError('Could not stably hit exactly one '+name+' control on the matched Flow media card','uncertain')
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':point['x'],'y':point['y']},session=session)
        landed=await self._eval(session,expression,timeout=2)
        if not landed or not landed.get('hitIsControl'):raise FlowTaskError('Flow '+name+' control moved or was obscured before click','uncertain')
        # One trusted CDP press/release is sufficient; avoid a second synthetic click that toggles menus closed.
        await self._click_point(session,landed)
        await asyncio.sleep(.25)

    async def _read_detail_prompt_for_media(self,session,media_id,project_url,timeout=8):
        """Read full prompt from the visible asset info panel, never from a clipped tile title."""
        await self._ensure_media_mounted(session,media_id)
        state=await self._snapshot(session,'')
        if (state.get('url','').split('?')[0].rstrip('/')!=project_url.rstrip('/') or
                not state.get('draftEmpty')):
            raise FlowTaskError('Flow project/draft changed before visible prompt inspection','uncertain')
        tiles=[x for x in state.get('assetTiles',[]) if x.get('media_id')==media_id]
        if len(tiles)!=1 or not tiles[0].get('aria_label'):
            raise FlowTaskError('Flow detail tile is missing or ambiguous','uncertain')
        existing=await self._eval(session,"(()=>[...document.querySelectorAll('flow-info-panel')].some(e=>e.getBoundingClientRect().width>0))()")
        if existing:
            for kind in ('mouseMoved','mousePressed','mouseReleased'):
                params={'type':kind,'x':50,'y':50}
                if 'mouse' in kind and kind!='mouseMoved':params.update(button='left',clickCount=1)
                try:await self.bridge.cdp.command('Input.dispatchMouseEvent',params,session=session)
                except Exception:pass
            await asyncio.sleep(.2)
        await self._click_media_control(session,media_id,tiles[0]['aria_label'])
        prompt=None
        try:
            expression=r'''(()=>{const panels=[...document.querySelectorAll('flow-info-panel')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0});if(panels.length!==1)return null;const prompts=[...panels[0].querySelectorAll('.prompt-text')].map(e=>(e.innerText||'').trim()).filter(Boolean);return prompts.length===1?prompts[0]:null})()'''
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                prompt=await self._eval(session,expression)
                if prompt:break
                await asyncio.sleep(.15)
            if not prompt:raise FlowTaskError('Flow visible info panel did not expose one full prompt','uncertain')
            return {'media_id':media_id,'prompt':prompt,'mention_entity_ids':[]}
        finally:
            await self._dismiss_flow_popups(session)
            visible=await self._eval(session,"(()=>[...document.querySelectorAll('flow-info-panel')].some(e=>e.getBoundingClientRect().width>0))()")
            if visible:raise FlowTaskError('Flow info panel did not close after reading prompt','uncertain')

    async def _read_prompt_for_media(self,session,media_id,timeout=12):
        await self._ensure_media_mounted(session,media_id)
        state=await self._snapshot(session,'')
        if not state or not state.get('composerAvailable') or not state.get('draftEmpty'):
            raise FlowTaskError('Flow composer is not empty before prompt-identity read; refusing to overwrite a draft','uncertain')
        selector=json.dumps('img[data-media-id="'+media_id+'"]')
        point=await self._eval(session,"(()=>{const i=document.querySelector("+selector+");if(!i)return null;const c=i.closest('flow-grid-tile-container');c?.scrollIntoView({block:'center'});const r=i.getBoundingClientRect();return{x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()")
        if not point:raise FlowTaskError('Flow media tile is not mounted for full-prompt identity read','uncertain')
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':point['x'],'y':point['y']},session=session)
        expression=r'''(()=>{const i=document.querySelector(SELECTOR),c=i?.closest('flow-grid-tile-container');if(!c)return null;const b=[...c.querySelectorAll('button[aria-label="Sử dụng lại câu lệnh"],button[aria-label="Reuse prompt"]')].find(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'});if(!b)return null;const r=b.getBoundingClientRect(),x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2),h=document.elementFromPoint(x,y);return{x,y,hitIsButton:h===b||b.contains(h)}})()'''.replace('SELECTOR',selector)
        deadline=time.monotonic()+timeout;button=None
        while time.monotonic()<deadline:
            button=await self._eval(session,expression)
            if button and button.get('hitIsButton'):break
            await asyncio.sleep(.2)
        if not button or not button.get('hitIsButton'):
            raise FlowTaskError('Flow Reuse prompt button is not stably hittable; refusing title-prefix fallback','uncertain')
        await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':button['x'],'y':button['y']},session=session)
        landed=await self._eval(session,expression)
        if not landed or not landed.get('hitIsButton'):
            raise FlowTaskError('Flow Reuse prompt control moved before click; refusing ambiguous identity','uncertain')
        await self._click_point(session,landed)
        state=await self._wait_page(session,lambda value:value.get('composerAvailable') and value.get('draftLength',0)>0,timeout=timeout,prompt='')
        draft=(await self._prompt_box(session) or {}).get('text','')
        if not state or not draft:
            raise FlowTaskError('Flow Reuse prompt did not expose full prompt text in the composer','uncertain')
        return {'media_id':media_id,'prompt':draft,'mention_entity_ids':state.get('mentionEntityIds',[]),'title':next((x.get('title') for x in state.get('largeImages',[]) if x.get('media_id')==media_id),None)}

    async def _clear_verified_reused_prompt(self,session,project_url,expected):
        """Clear only the exact Flow prompt this tool inserted from a saved tile."""
        box=await self._prompt_box(session)
        if not box or self._prompt_text(box.get('text',''))!=self._prompt_text(expected):
            raise FlowTaskError('Flow reuse-prompt draft changed; leaving it untouched for recovery','uncertain')
        await self._click_point(session,box)
        commands=[
            ('keyDown','Control',0,17),('keyDown','a',2,65),('keyUp','a',2,65),
            ('keyUp','Control',0,17),('keyDown','Backspace',0,8),('keyUp','Backspace',0,8),
        ]
        for kind,key,modifiers,keycode in commands:
            await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':kind,'key':key,'code':key if key=='Control' else ('KeyA' if key=='a' else key),'modifiers':modifiers,'windowsVirtualKeyCode':keycode,'nativeVirtualKeyCode':keycode},session=session)
        await self._wait_page(session,lambda state:state.get('draftEmpty') and state.get('url','').split('?')[0].rstrip('/')==project_url.split('?')[0].rstrip('/'),timeout=8,prompt='')

    async def _read_batch_media_prompt(self,session,media_id,project_url,tasks):
        try:return await self._read_detail_prompt_for_media(session,media_id,project_url)
        except FlowTaskError as error:
            if str(error)!='Flow visible info panel did not expose one full prompt':raise
        # Some Flow builds render the info panel without its old .prompt-text node.
        # The card's native Reuse control exposes the saved full prompt instead.
        detail=await self._read_prompt_for_media(session,media_id)
        fingerprint=self._batch_prompt_fingerprint(detail['prompt'],detail.get('mention_entity_ids',[]))
        matches=[]
        for task in tasks:
            expected=' '.join([m['name'] for m in task.get('character_mentions',[])]+[task['prompt']]).strip()
            if self._batch_prompt_fingerprint(expected,[m['character_id'] for m in task.get('character_mentions',[])])==fingerprint:matches.append(task)
        try:
            if len(matches)!=1:raise FlowTaskError('Flow saved prompt does not identify exactly one batch scene','uncertain')
        finally:
            # The tool verified this card before inserting its saved prompt and
            # the composer was blank. Restore that original blank state by name.
            await self._clear_verified_reused_prompt(session,project_url,detail['prompt'])
        return detail

    async def _attach_character_mentions(self,session,prompt,mentions,timeout=12):
        expected_ids=[item['character_id'] for item in mentions]
        expected_text=' '.join([item['name'] for item in mentions]+([prompt] if prompt else [])).strip()
        state=await self._snapshot(session,expected_text)
        if state.get('draftMatches') and state.get('mentionEntityIds',[])==expected_ids and not state.get('attachedMediaIds'):
            return state
        box=await self._prompt_box(session)
        if not box:raise FlowTaskError('Flow prompt box unavailable; no scene submitted')
        if box.get('text'):raise FlowTaskError('A different Flow draft exists; refusing to overwrite it')
        await self._click_point(session,box)
        for index,item in enumerate(mentions):
            await self.bridge.cdp.command('Input.insertText',{'text':'@'},session=session)
            deadline=time.monotonic()+timeout;options=[]
            while time.monotonic()<deadline:
                options=await self._eval(session,r'''(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};return[...document.querySelectorAll('[role="listbox"] [role="option"]')].filter(visible).map(e=>({name:(e.innerText||'').split(String.fromCharCode(10))[0].trim(),active:e.classList.contains('asset-item-active'),selected:e.getAttribute('aria-selected')==='true'}))})()''')
                if any(option.get('name')==item['name'] for option in options):break
                await asyncio.sleep(.12)
            matches=[i for i,option in enumerate(options) if option.get('name')==item['name']]
            if len(matches)!=1:raise FlowTaskError('Flow @name lookup did not produce one exact native Character; no scene submitted','needs_flow_check')
            selected=next((i for i,option in enumerate(options) if option.get('active') or option.get('selected')),0);delta=matches[0]-selected
            key='ArrowDown' if delta>0 else 'ArrowUp'
            for _ in range(abs(delta)):
                await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':'keyDown','key':key,'code':key},session=session)
                await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':'keyUp','key':key,'code':key},session=session)
            await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':'keyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13},session=session)
            await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13},session=session)
            state=await self._wait_page(session,lambda value:value.get('mentionEntityIds',[])==expected_ids[:index+1],timeout=timeout,prompt='')
            if state.get('attachedMediaIds'):raise FlowTaskError('Unexpected media attachment appeared while resolving @name; no scene submitted','needs_flow_check')
            if index+1<len(mentions) or prompt:await self.bridge.cdp.command('Input.insertText',{'text':' '},session=session)
        if prompt:await self.bridge.cdp.command('Input.insertText',{'text':prompt},session=session)
        state=await self._wait_page(session,lambda value:value.get('draftMatches') and value.get('mentionEntityIds',[])==expected_ids,timeout=timeout,prompt=expected_text)
        if state.get('attachedMediaIds'):raise FlowTaskError('Unexpected media attachment appeared in Flow prompt; no scene submitted','needs_flow_check')
        return state

    async def _close_upscale_failure(self,session):
        # Scope Close to the ancestor of this specific failure notification.
        # Never press an unrelated modal/page Close button.
        notice=await self._eval(session,r'''(()=>{const norm=s=>(s||'').normalize('NFC').replace(/\s+/g,' ').trim();const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const texts=[...document.querySelectorAll('*')].filter(e=>!e.children.length&&visible(e)&&/không tăng được độ phân giải|unable to upscale|couldn.t upscale/i.test(norm(e.textContent)));for(const text of texts){let box=text;for(let i=0;box&&i<7;i++,box=box.parentElement){const r=box.getBoundingClientRect();if(r.width>850||r.height>400)break;const buttons=[...box.querySelectorAll('button,[role="button"],a')].filter(e=>visible(e)&&/^(đóng|close)$/i.test(norm(e.innerText)||norm(e.getAttribute('aria-label'))));if(buttons.length===1){const b=buttons[0],p=b.getBoundingClientRect(),x=p.x+p.width/2,y=p.y+p.height/2,hit=document.elementFromPoint(x,y);if(hit===b||b.contains(hit))return{found:true,point:{x,y}};}}}return{found:texts.length>0,point:null}})()''')
        if not notice or not notice.get('found'):return False
        if not notice.get('point'):raise FlowTaskError('Không tăng được độ phân giải; cần bấm Đóng trên thông báo Flow','uncertain')
        await self._click_point(session,notice['point'])
        await asyncio.sleep(.15)
        return True

    async def _download_2k(self, task_id, target, session, receipt, prompt, media_id=None, timeout=30):
        folder = self.root / 'downloads' / task_id
        folder.mkdir(parents=True, exist_ok=True)
        if receipt.get('stage') == 'downloaded':
            path = Path(receipt.get('download_path', ''))
            if path.is_file() and digest(path) == receipt.get('download_sha256'):
                return receipt
        await self.bridge.cdp.command('Target.activateTarget', {'targetId': target})
        frame = (await self.bridge.cdp.command('Page.getFrameTree', session=session))['frameTree']['frame']['id']
        self.active_frame = None; self.download_guid = None; self.downloads={};self.download_complete = False; self.download_error = None; self.events = []; self.download_changed.clear()
        try:
            if getattr(self.bridge.images, 'download_behavior_uncertain', False):
                await self.bridge.cdp.command('Browser.setDownloadBehavior', {'behavior': 'default', 'eventsEnabled': False})
                self.bridge.images.download_behavior_uncertain = False
            await self.bridge.cdp.command('Browser.setDownloadBehavior', {'behavior':'allowAndName','downloadPath':str(folder.resolve()),'eventsEnabled':True})
            if media_id:await self._ensure_media_mounted(session,media_id)
            images = await self._image(session)
            if media_id:
                matches=[image for image in images if image.get('media_id')==media_id]
                if len(matches)!=1:raise FlowTaskError('The task-specific Flow media card is missing or ambiguous; refusing to download another scene','uncertain')
                img=matches[0]
            elif len(images)==1:
                img=images[0]
            else:
                raise FlowTaskError('Flow media ID is required when a project contains multiple images','uncertain')
            fallback=receipt.get('download_resolution_requested')=='1K'
            failure=None
            if await self._close_upscale_failure(session):
                fallback=True;failure='Flow báo Không tăng được độ phân giải; đã bấm Đóng'
            if not fallback:
                await self.bridge.cdp.command('Input.dispatchMouseEvent', {'type':'mouseMoved','x':img['x'],'y':img['y']}, session=session)
                await asyncio.sleep(.35)
                await self._click_media_control(session,img['media_id'],'Tuỳ chọn khác')
                await self._click_named(session, 'Tải xuống')
                receipt.update({'stage':'download_menu_open','updated_at':time.time()}); self._write_receipt(task_id, receipt)
                try:
                    await self._click_named(session, '2K', exact=False, native_only=True, download_frame=frame)
                    receipt.update({'stage':'downloading','download_resolution_requested':'2K','updated_at':time.time()});self._write_receipt(task_id,receipt)
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline and not self.download_complete and not self.download_error:
                        if await self._close_upscale_failure(session):
                            failure='Flow báo Không tăng được độ phân giải; đã bấm Đóng';break
                        self.download_changed.clear()
                        try:await asyncio.wait_for(self.download_changed.wait(),min(2,max(.1,deadline-time.monotonic())))
                        except asyncio.TimeoutError:pass
                    if not self.download_guid or not self.download_complete:
                        failure=failure or self.download_error or '2K download not confirmed within budget'
                except FlowTaskError as error:
                    failure=str(error)
                fallback=failure is not None
            if fallback:
                receipt.update({'stage':'download_menu_open','download_resolution_requested':'1K','download_fallback_reason':failure or receipt.get('download_fallback_reason','resume original-resolution download'),'updated_at':time.time()});self._write_receipt(task_id,receipt)
                await self._dismiss_flow_popups(session)
                # Re-locate the immutable media ID. Never choose the newest tile,
                # regenerate a scene, or download a different card as a fallback.
                matches=[image for image in await self._image(session) if image.get('media_id')==img['media_id']]
                if len(matches)!=1:raise FlowTaskError('The task-specific Flow media card is missing or ambiguous; refusing 1K fallback','uncertain')
                img=matches[0]
                await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':'mouseMoved','x':img['x'],'y':img['y']},session=session)
                await self._click_media_control(session,img['media_id'],'Tuỳ chọn khác')
                await self._click_named(session,'Tải xuống')
                # Preserve late 2K events: both downloads address this same card.
                self.active_frame=frame;self.download_error=None
                await self._click_named(session,'1K',exact=False,native_only=True)
                receipt.update({'stage':'downloading','updated_at':time.time()});self._write_receipt(task_id,receipt)
                deadline=time.monotonic()+timeout
                while time.monotonic()<deadline and not any(item['state']=='completed' for item in self.downloads.values()):
                    self.download_changed.clear()
                    try:await asyncio.wait_for(self.download_changed.wait(),min(2,max(.1,deadline-time.monotonic())))
                    except asyncio.TimeoutError:pass
                completed=[guid for guid,item in self.downloads.items() if item['state']=='completed']
                if not completed:raise FlowTaskError('Flow 1K download was not confirmed; keep the same image for download recovery, do not regenerate','uncertain')
                self.download_guid=completed[-1]
            else:
                completed=list(self.downloads)
            # Normally only identical duplicates are interchangeable. During
            # fallback, 2K and 1K variants of this re-verified card may differ.
            hashes=set()
            for guid in completed:
                candidate=folder/guid
                if not candidate.is_file() or not 1000<candidate.stat().st_size<=MAX_FLOW_DOWNLOAD:
                    raise FlowTaskError('Flow download is missing or has invalid size','uncertain')
                hashes.add(digest(candidate))
            if not fallback and len(hashes)!=1:
                raise FlowTaskError('Different Flow files downloaded for one scene; inspect the saved download receipts','uncertain')
            downloaded = folder / self.download_guid
            if not downloaded.is_file() or not 1000 < downloaded.stat().st_size <= MAX_FLOW_DOWNLOAD:
                raise FlowTaskError('Flow download is missing or has invalid size', 'uncertain')
            with Image.open(downloaded) as im:
                if im.format not in ('PNG','JPEG','WEBP') or min(im.size) < 512 or max(im.size) > 8192 or im.width*im.height > 20_000_000:
                    raise FlowTaskError('Flow image format/dimensions failed validation')
                im.load(); width,height=im.size; fmt=im.format
                destination=(self.root/(task_id+'.png')).resolve();part=destination.with_suffix('.part')
                im.convert('RGB').save(part,format='PNG',optimize=True)
            part.replace(destination)
            receipt.update({'stage':'downloaded','download_path':str(destination),'download_sha256':digest(destination),'width':width,'height':height,'format':fmt,'download_guid':self.download_guid,'duplicate_download_guids':[guid for guid in completed if guid!=self.download_guid and digest(folder/guid)==digest(downloaded)],'alternate_resolution_download_guids':[guid for guid in completed if guid!=self.download_guid and digest(folder/guid)!=digest(downloaded)],'media_id':img['media_id'],'updated_at':time.time()});self._write_receipt(task_id,receipt)
            return receipt
        finally:
            self.active_frame = None
            try:await self._dismiss_flow_popups(session)
            except Exception:pass
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

    async def _return_to_project_root(self,session,project_url,prompt=''):
        project_url=project_url.split('?')[0].rstrip('/');project_path=urlparse(project_url).path
        state=await self._snapshot(session,prompt)
        if urlparse(state.get('url','')).path.rstrip('/')==project_path and state.get('composerAvailable'):return state
        await self.bridge.cdp.command('Page.navigate',{'url':project_url},session=session)
        state=await self._wait_page(session,lambda value:urlparse(value.get('url','')).path.rstrip('/')==project_path and value.get('composerAvailable'),timeout=30,prompt=prompt)
        return state

    async def create_character(self,task_id,job_id,character_id,name,prompt,timeout=900):
        async with self._flow_batch_lock:
            return await self._create_character_unreserved(task_id,job_id,character_id,name,prompt,timeout)

    async def _create_character_unreserved(self, task_id, job_id, character_id, name, prompt, timeout=900):
        """Create and name one reusable Character through Flow's visible UI only."""
        for value,label in ((task_id,'task_id'),(job_id,'job_id')):
            try:uuid.UUID(value)
            except (ValueError,TypeError,AttributeError) as error:raise ValueError('Flow Character requires a UUID '+label) from error
        if not isinstance(character_id,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',character_id):raise ValueError('Invalid Flow character manifest ID')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}',name):raise ValueError('Flow registered Character name must be a stable ASCII identifier')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000:raise ValueError('Invalid Flow Character appearance prompt')
        prompt=prompt.strip();prompt_sha=hashlib.sha256(prompt.encode('utf8')).hexdigest();receipt=self._read_receipt(task_id)
        if receipt and (receipt.get('job_id')!=job_id or receipt.get('kind')!='native_character' or receipt.get('character_manifest_id')!=character_id or receipt.get('name')!=name or receipt.get('prompt_sha256')!=prompt_sha):
            raise FlowTaskError('Flow Character task receipt identity differs; refusing a second creation','uncertain')
        if receipt and receipt.get('stage')=='character_saved':
            async with self.bridge.job_lock:
                await self.bridge.connect();target=await self._target();session=await self._session(target)
                await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
                await self._return_to_project_root(session,receipt['project_url'],prompt)
            return {'task_id':task_id,'character_id':receipt['character_id'],'name':name,'project_url':receipt['project_url']}
        if receipt and receipt.get('character_create_stage') in ('submitting','saving'):
            raise FlowTaskError('Flow Character creation may already have been submitted; manual reconciliation required, no duplicate generated','uncertain')
        async with self.bridge.job_lock:
            await self.bridge.connect();target=await self._target();session=await self._session(target)
            await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
            receipt=self._read_receipt(task_id)
            if receipt and receipt.get('stage')=='character_saved':
                await self._return_to_project_root(session,receipt['project_url'],prompt)
                return {'task_id':task_id,'character_id':receipt['character_id'],'name':name,'project_url':receipt['project_url']}
            if receipt and receipt.get('character_create_stage') in ('submitting','saving'):
                raise FlowTaskError('Flow Character creation may already have been submitted; manual reconciliation required, no duplicate generated','uncertain')
            receipt,state=await self._ensure_project(task_id,job_id,prompt,target,session,receipt)
            project_url=receipt.get('project_url','').split('?')[0].rstrip('/');project_path=urlparse(project_url).path
            if state.get('url','').split('?')[0].rstrip('/')!=project_url:
                if not state.get('draftEmpty') or not state.get('generateDisabled'):raise FlowTaskError('Flow tab has a draft or active request; refusing to switch to the Character project')
                await self.bridge.cdp.command('Page.navigate',{'url':project_url},session=session)
                state=await self._wait_page(session,lambda value:value.get('url','').split('?')[0].rstrip('/')==project_url and value.get('composerAvailable'),prompt=prompt)
            if urlparse(state.get('url','')).path.rstrip('/')==project_path:
                await self._click_named(session,'Nhân vật',selector='button,[role=button]')
                state=await self._wait_page(session,lambda value:urlparse(value.get('url','')).path.startswith(project_path+'/character'),timeout=20,prompt=prompt)
            char_path=urlparse(state.get('url','')).path
            if not re.fullmatch(re.escape(project_path)+r'/character(?:/[0-9a-fA-F-]{36})?',char_path):raise FlowTaskError('Flow did not open the native Character workflow in the registered project','needs_flow_check')
            if char_path==project_path+'/character':
                box=await self._eval(session,r'''(()=>{const boxes=[...document.querySelectorAll('[role="textbox"][contenteditable="true"]')].filter(e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'});if(boxes.length!==1)return null;const r=boxes[0].getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2,text:(boxes[0].innerText||'').trim()}})()''')
                if not box or box.get('text') not in ('',prompt):raise FlowTaskError('Native Flow Character prompt is absent or contains a different draft')
                if not box.get('text'):
                    await self._click_point(session,box);await self.bridge.cdp.command('Input.insertText',{'text':prompt},session=session)
                state_data=await self._eval(session,r'''(()=>{const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};const buttons=[...document.querySelectorAll('button')].filter(visible);const models=buttons.filter(b=>(b.innerText||'').includes('Nano Banana 2.1'));const generate=buttons.filter(b=>(b.innerText||'').trim()==='arrow_forward');const body=document.body.innerText||'';return{prompt:(document.querySelector('[role="textbox"][contenteditable="true"]')?.innerText||'').trim(),models:models.length,generate:generate.map(b=>({disabled:b.disabled,rect:(()=>{const r=b.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()})),credits:body.split(String.fromCharCode(10)).map(x=>x.trim()).filter(x=>/tín dụng|credits?/i.test(x))}})()''')
                if state_data.get('prompt')!=prompt or state_data.get('models')!=1 or len(state_data.get('generate',[]))!=1 or state_data['generate'][0]['disabled']:
                    raise FlowTaskError('Native Character model/prompt/Generate control could not be verified; no request sent','needs_flow_check')
                credit_lines=state_data.get('credits',[]);credit_estimate=credit_lines[0] if credit_lines else None
                receipt.update({'kind':'native_character','character_manifest_id':character_id,'name':name,'prompt_sha256':prompt_sha,'project_url':project_url,'target_id':target,'stage':'project_ready','character_create_stage':'submitting','submitted_at':time.time(),'credit_estimate':credit_estimate,'updated_at':time.time()});self._write_receipt(task_id,receipt)
                await self._click_point(session,state_data['generate'][0]['rect'])
                state=await self._wait_page(session,lambda value:re.fullmatch(re.escape(project_path)+r'/character/[0-9a-fA-F-]{36}',urlparse(value.get('url','')).path) is not None,timeout=timeout,prompt=prompt)
                char_path=urlparse(state['url']).path
            entity_id=char_path.rsplit('/',1)[-1]
            try:uuid.UUID(entity_id)
            except (ValueError,TypeError,AttributeError) as error:raise FlowTaskError('Flow Character route lacks a UUID entity ID; manual reconciliation required','uncertain') from error
            receipt.update({'kind':'native_character','character_manifest_id':character_id,'name':name,'prompt_sha256':prompt_sha,'project_url':project_url,'character_id':entity_id,'target_id':target,'character_create_stage':'saving','updated_at':time.time()});self._write_receipt(task_id,receipt)
            fields=await self._eval(session,r'''(()=>[...document.querySelectorAll('input')].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0}).map(x=>({value:x.value,rect:(()=>{const r=x.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()})))()''')
            if not isinstance(fields,list) or len(fields)<2:raise FlowTaskError('Flow Character name field is not visible; manual reconciliation required','uncertain')
            if fields[1].get('value')!=name:
                point=fields[1].get('rect')
                await self._click_point(session,point)
                for event in ({'type':'keyDown','key':'a','code':'KeyA','windowsVirtualKeyCode':65,'nativeVirtualKeyCode':65,'modifiers':2},{'type':'keyUp','key':'a','code':'KeyA','windowsVirtualKeyCode':65,'nativeVirtualKeyCode':65,'modifiers':2}):await self.bridge.cdp.command('Input.dispatchKeyEvent',event,session=session)
                await self.bridge.cdp.command('Input.insertText',{'text':name},session=session)
            named=await self._eval(session,r'''(()=>{const f=[...document.querySelectorAll('input')].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0});const done=[...document.querySelectorAll('button')].filter(b=>(b.innerText||'').trim().normalize('NFC')==='Xong'.normalize('NFC')&&(()=>{const r=b.getBoundingClientRect();return r.width>0&&r.height>0})());return{values:f.map(x=>x.value),done:done.length,disabled:done.map(b=>b.disabled),point:done.length===1?(()=>{const r=done[0].getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})():null}})()''')
            if not isinstance(named,dict) or len(named.get('values',[]))<2 or named['values'][1]!=name or named.get('done')!=1 or named.get('disabled')!=[False]:raise FlowTaskError('Flow Character name/save control could not be verified; manual reconciliation required','uncertain')
            await self._click_point(session,named['point'])
            verified=await self._eval(session,r'''(()=>{const f=[...document.querySelectorAll('input')].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.height>0});return f.length>=2&&f[1].value===NAME})()'''.replace('NAME',json.dumps(name)))
            if verified is not True:raise FlowTaskError('Flow did not retain the registered Character name; manual reconciliation required','uncertain')
            receipt.update({'character_create_stage':'saved','stage':'character_saved','saved_at':time.time(),'updated_at':time.time()});self._write_receipt(task_id,receipt)
            await self._return_to_project_root(session,project_url,prompt)
            return {'task_id':task_id,'character_id':entity_id,'name':name,'project_url':project_url}

    @asynccontextmanager
    async def _maybe_job_lock(self,held=False):
        if held:yield
        else:
            async with self.bridge.job_lock:yield

    async def generate(self,task_id,job_id,prompt,timeout=900,character_mentions=None,*,submit_only=False,require_zero_credit=False):
        async with self._flow_batch_lock:
            return await self._generate_unreserved(task_id,job_id,prompt,timeout=timeout,character_mentions=character_mentions,submit_only=submit_only,require_zero_credit=require_zero_credit)

    async def _generate_unreserved(self, task_id, job_id, prompt, timeout=900, character_mentions=None, *, submit_only=False, require_zero_credit=False, batch_settings_verified=False, batch_credit_estimate=None, batch_credit_verified_at=None, batch_credit_source_task_id=None, submit_with_enter=False, bridge_lock_held=False):
        try: uuid.UUID(task_id); uuid.UUID(job_id)
        except (ValueError, TypeError, AttributeError) as e: raise ValueError('Flow requires UUID task and job IDs') from e
        if not isinstance(prompt,str) or not 1 <= len(prompt.strip()) <= 12000: raise ValueError('Invalid Flow scene prompt')
        mentions=self._validate_character_mentions(job_id,character_mentions or [])
        prompt=prompt.strip();prompt_sha=hashlib.sha256(prompt.encode('utf8')).hexdigest()
        mentions_sha=hashlib.sha256(json.dumps(mentions,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
        composed_prompt=' '.join([item['name'] for item in mentions]+[prompt]).strip()
        receipt=self._read_receipt(task_id)
        if receipt and (receipt.get('reference_media_ids') or receipt.get('reference_identity')):
            raise FlowTaskError('Legacy Flow media-ID reference receipt is not supported; native @Character conditioning required','uncertain')
        if receipt and receipt.get('job_id')!=job_id:raise FlowTaskError('Flow task receipt belongs to a different job; refusing cached result or regeneration','uncertain')
        if receipt and receipt.get('prompt_sha256')!=prompt_sha: raise FlowTaskError('Flow receipt prompt differs; refusing a second generation','uncertain')
        if receipt and receipt.get('character_mentions',[])!=mentions:raise FlowTaskError('Flow receipt native Character mention set differs; refusing a second generation','uncertain')
        cached=self._cached_result(task_id,receipt)
        if cached:return cached
        async with self._maybe_job_lock(bridge_lock_held):
            await self.bridge.connect()
            target=await self._target();session=await self._session(target)
            await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
            receipt=self._read_receipt(task_id)
            if receipt and receipt.get('job_id')!=job_id:raise FlowTaskError('Flow task receipt belongs to a different job; refusing cached result or regeneration','uncertain')
            if receipt and receipt.get('prompt_sha256')!=prompt_sha: raise FlowTaskError('Flow receipt prompt differs; refusing a second generation','uncertain')
            if receipt and receipt.get('character_mentions',[])!=mentions:raise FlowTaskError('Flow receipt native Character mention set differs; refusing a second generation','uncertain')
            cached=self._cached_result(task_id,receipt)
            if cached:return cached
            receipt,state=await self._ensure_project(task_id,job_id,prompt,target,session,receipt)
            saved_mentions=receipt.get('character_mentions')
            if saved_mentions is None:
                if receipt.get('stage')!='project_ready':raise FlowTaskError('Flow receipt lacks native Character identity after a non-empty stage; refusing ambiguous recovery','uncertain')
                receipt['character_mentions']=mentions
                receipt['conditioning_sha256']=hashlib.sha256(json.dumps({'prompt_sha256':prompt_sha,'character_mentions_sha256':mentions_sha},sort_keys=True).encode('utf8')).hexdigest()
                receipt['attached_character_ids']=[];self._write_receipt(task_id,receipt)
            elif saved_mentions!=mentions:
                raise FlowTaskError('Flow receipt native Character mention set differs; refusing a second generation','uncertain')
            project_path=receipt.get('project_url','').split('?')[0].rstrip('/')
            if any(item['project_url'].split('?')[0].rstrip('/')!=project_path for item in mentions):raise FlowTaskError('Native Flow Characters do not belong to this exact job project','needs_flow_check')
            entity_ids=[item['character_id'] for item in mentions]
            if receipt.get('stage') in ('submitting','waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                if receipt.get('submitted_character_ids',[])!=entity_ids:raise FlowTaskError('Submitted Flow receipt lacks the exact native Character entity IDs','uncertain')
            else:
                state=await self._attach_character_mentions(session,prompt,mentions)
                if state.get('mentionEntityIds',[])!=entity_ids:raise FlowTaskError('Flow prompt does not contain the exact native Character entity mentions; no image submitted','needs_flow_check')
                receipt.update({'stage':'characters_attached','attached_character_ids':entity_ids,'updated_at':time.time()});self._write_receipt(task_id,receipt)
            if receipt.get('stage') in ('submitting','waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                if state['url'].split('?')[0].rstrip('/')!=receipt.get('project_url','').split('?')[0].rstrip('/'):
                    raise FlowTaskError('Flow project changed during recovery; no new request sent','uncertain')
                baseline=receipt.get('baseline_media_ids')
                if baseline is None:raise FlowTaskError('Flow receipt lacks its baseline media IDs; refusing to guess a result','uncertain')
                if receipt.get('stage') in ('submitting','waiting_result'):
                    if submit_only:
                        return {'task_id':task_id,'stage':receipt.get('stage'),'project_url':receipt.get('project_url'),'media_id':receipt.get('media_id'),'credit_estimate':receipt.get('credit_estimate'),'credit_verified_at':receipt.get('credit_verified_at'),'submitted_at':receipt.get('submitted_at')}
                    state=await self._wait_page(session,lambda s:self._new_media(baseline,s.get('largeImages',[])) is not None,timeout=timeout,prompt=composed_prompt)
                    media=self._new_media(baseline,state.get('largeImages',[]))
                    receipt.update({'stage':'image_ready','media_id':media['media_id'],'result_dimensions':media,'updated_at':time.time()});self._write_receipt(task_id,receipt)
                else:
                    media_id=receipt.get('media_id')
                    if not media_id:raise FlowTaskError('Flow receipt lacks media ID; refusing to download another scene','uncertain')
                    images=await self._image(session)
                    if len([x for x in images if x.get('media_id')==media_id])!=1:
                        raise FlowTaskError('The task-specific Flow media card is missing; no new image will be submitted','uncertain')
            else:
                if batch_settings_verified:
                    configured=await self._snapshot(session,composed_prompt)
                    if not all(value in (configured.get('settingsText') or '') for value in ('Nano Banana 2.1','crop_9_16','x1')):
                        raise FlowTaskError('Flow batch settings changed after first prompt; no new image submitted','needs_flow_check')
                    if require_zero_credit and (not batch_credit_estimate or not re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',batch_credit_estimate,re.I)):
                        raise FlowTaskError('Flow batch has no persisted explicit zero-credit evidence; no image submitted','needs_flow_check')
                else:configured=await self._ensure_agent_and_settings(session,composed_prompt,require_zero_credit=require_zero_credit)
                if configured.get('draftMatches') is not True or configured.get('mentionEntityIds',[])!=entity_ids or configured.get('attachedMediaIds',[]):
                    raise FlowTaskError('Flow prompt/@Character entity set changed before Submit; no image request sent','needs_flow_check')
                visible_cost=next((x for x in configured.get('creditLines',[]) if re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',x,re.I)),None)
                cost_line=visible_cost or (batch_credit_estimate if batch_settings_verified else None)
                contradictory_cost=False
                if require_zero_credit:
                    contradictory_cost=any(re.search(r'quá trình tạo sẽ tốn|generation will cost',x,re.I) and not re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',x,re.I) for x in configured.get('creditLines',[]))
                    if contradictory_cost:raise FlowTaskError('Visible Flow estimate is not explicitly 0; no image submitted','needs_flow_check')
                if configured.get('agentOn') is not False:
                    raise FlowTaskError('Tác nhân is not confirmed off; no image request sent','needs_flow_check')
                if require_zero_credit and not cost_line:
                    raise FlowTaskError('Visible Flow estimate is not explicitly 0; no image request sent','needs_flow_check')
                if submit_with_enter:
                    if configured.get('settingsOpen'):
                        await self._click_expr(session,'(()=>{const e=document.querySelector("button.settings-trigger-button");if(!e)return null;const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()','đóng cài đặt trước khi Enter')
                        closed=await self._wait_page(session,lambda value:not value.get('settingsOpen'),timeout=5,prompt=composed_prompt)
                        if closed.get('url','').split('?')[0].rstrip('/')!=project_path:
                            raise FlowTaskError('Flow project changed after zero-credit check; no image submitted','needs_flow_check')
                    box=await self._prompt_box(session)
                    if not box:raise FlowTaskError('Flow prompt editor unavailable before Enter; no image submitted','needs_flow_check')
                    await self._click_point(session,box)
                    focus=await self._eval(session,r'''(()=>{const box=document.querySelector('[role="textbox"][aria-label="Bạn muốn tạo những gì?"],.ProseMirror[contenteditable="true"]');return !!box&&(box===document.activeElement||box.contains(document.activeElement))})()''')
                    if not focus:raise FlowTaskError('Flow prompt editor did not receive focus; no Enter sent','needs_flow_check')
                    focused=await self._snapshot(session,composed_prompt)
                    visible_cost=focused.get('creditLines',[])
                    conflicting_cost=False
                    if require_zero_credit:
                        conflicting_cost=any(re.search(r'quá trình tạo sẽ tốn|generation will cost',line,re.I) and not re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',line,re.I) for line in visible_cost)
                    if (focused.get('url','').split('?')[0].rstrip('/')!=project_path or not focused.get('draftMatches') or focused.get('mentionEntityIds',[])!=entity_ids or focused.get('attachedMediaIds',[]) or focused.get('agentOn') is not False or not all(value in (focused.get('settingsText') or '') for value in ('Nano Banana 2.1','crop_9_16','x1')) or conflicting_cost):
                        raise FlowTaskError('Flow prompt/settings changed at Enter boundary; no image submitted','needs_flow_check')
                credit_verified_at=(batch_credit_verified_at if batch_settings_verified else time.time())
                receipt['baseline_media_ids']=list(set(receipt.get('baseline_media_ids',[]))|self._known_job_media(job_id,{task_id}))
                receipt.update({'stage':'submitting','agent_off':True,'settings_text':configured.get('settingsText'),'credit_estimate':cost_line,'credit_verified_at':credit_verified_at,'credit_batch_source_task_id':batch_credit_source_task_id if batch_settings_verified else task_id,'submitted_character_ids':entity_ids,'submitted_prompt_sha256':prompt_sha,'submitted_at':time.time(),'updated_at':time.time()});self._write_receipt(task_id,receipt)
                if submit_with_enter:
                    for event in ('keyDown','keyUp'):
                        await self.bridge.cdp.command('Input.dispatchKeyEvent',{'type':event,'key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13},session=session)
                    await self._wait_page(session,lambda value:value.get('draftEmpty') and value.get('generateDisabled'),timeout=6,prompt='')
                else:
                    await self._click_named(session,'Bắt đầu tạo',exact=True,native_only=True)
                    await self._wait_page(session,lambda value:value.get('draftEmpty'),timeout=10,prompt='')
                receipt.update({'stage':'waiting_result','updated_at':time.time()});self._write_receipt(task_id,receipt)
                if submit_only:
                    return {'task_id':task_id,'stage':receipt.get('stage'),'project_url':receipt.get('project_url'),'media_id':receipt.get('media_id'),'credit_estimate':receipt.get('credit_estimate'),'credit_verified_at':receipt.get('credit_verified_at'),'submitted_at':receipt.get('submitted_at')}
            if receipt.get('stage') not in ('image_ready','download_menu_open','downloading'):
                baseline=receipt.get('baseline_media_ids')
                if baseline is None:raise FlowTaskError('Flow receipt lacks its baseline media IDs; refusing to guess a result','uncertain')
                state=await self._wait_page(session,lambda s:self._new_media(baseline,s.get('largeImages',[])) is not None,timeout=timeout,prompt=composed_prompt)
                media=self._new_media(baseline,state.get('largeImages',[]))
                receipt.update({'stage':'image_ready','media_id':media['media_id'],'updated_at':time.time(),'result_dimensions':media});self._write_receipt(task_id,receipt)
            if submit_only:
                return {'task_id':task_id,'stage':receipt.get('stage'),'project_url':receipt.get('project_url'),'media_id':receipt.get('media_id'),'credit_estimate':receipt.get('credit_estimate'),'submitted_at':receipt.get('submitted_at')}
            if not receipt.get('media_id'):raise FlowTaskError('Flow receipt lacks the completed media ID; refusing ambiguous download','uncertain')
            receipt=await self._download_2k(task_id,target,session,receipt,composed_prompt,media_id=receipt['media_id'])
            output=Path(receipt['download_path'])
            return {'task_id':task_id,'file_path':str(output),'sha256':digest(output),'width':receipt['width'],'height':receipt['height'],'request_id':'flow-'+task_id,'source':'google_flow_nano_banana_2_1','format':'PNG','flow_download_format':receipt.get('format'),'project_url':receipt.get('project_url'),'download_guid':receipt.get('download_guid'),'media_id':receipt.get('media_id')}

    async def generate_batch(self,job_id,tasks,timeout=1200,download_results=True,require_zero_credit=True):
        async with self._flow_batch_lock:
            async with self.bridge.job_lock:
                return await self._generate_batch_unreserved(job_id,tasks,timeout=timeout,bridge_lock_held=True,download_results=download_results,require_zero_credit=require_zero_credit)

    async def _generate_batch_unreserved(self,job_id,tasks,timeout=1200,bridge_lock_held=False,download_results=True,require_zero_credit=True):
        """Submit up to 30 independent Flow prompts before mapping and serial download."""
        try:job_uuid=uuid.UUID(job_id)
        except (ValueError,TypeError,AttributeError) as error:raise ValueError('Flow batch requires a UUID job ID') from error
        if not isinstance(tasks,list) or not 1<=len(tasks)<=30:raise ValueError('Flow batch accepts 1..30 scene tasks')
        normalized=[];task_ids=set();ordinals=set()
        for index,item in enumerate(tasks):
            if not isinstance(item,dict):raise ValueError('Invalid Flow batch task')
            task_id=item.get('task_id')
            try:uuid.UUID(task_id)
            except (ValueError,TypeError,AttributeError) as error:raise ValueError('Flow batch task ID must be a UUID') from error
            prompt=item.get('prompt')
            if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000:raise ValueError('Invalid Flow batch prompt')
            prompt=prompt.strip();mentions=self._validate_character_mentions(job_id,item.get('character_mentions') or [])
            ordinal=item.get('ordinal',index)
            if not isinstance(ordinal,int) or ordinal<0 or ordinal in ordinals:raise ValueError('Flow batch ordinals must be unique non-negative integers')
            if task_id in task_ids:raise ValueError('Duplicate Flow batch task ID')
            task_ids.add(task_id);ordinals.add(ordinal)
            composed=' '.join([x['name'] for x in mentions]+[prompt]).strip()
            normalized.append({'task_id':task_id,'job_id':job_id,'prompt':prompt,'character_mentions':mentions,'ordinal':ordinal,
                               'prompt_sha256':hashlib.sha256(prompt.encode('utf8')).hexdigest(),
                               'conditioning_sha256':hashlib.sha256(json.dumps({'prompt':self._prompt_text(composed),'mention_entity_ids':[x['character_id'] for x in mentions]},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest(),
                               'prompt_fingerprint':self._batch_prompt_fingerprint(composed,[x['character_id'] for x in mentions])})
        if len({x['prompt_fingerprint'] for x in normalized})!=len(normalized):
            raise FlowTaskError('Duplicate prompt/entity fingerprints cannot be safely associated in a concurrent batch; run duplicates sequentially','needs_flow_check')
        normalized.sort(key=lambda x:(x['ordinal'],x['task_id']))
        manifest_items=[{k:x[k] for k in ('task_id','ordinal','prompt_sha256','conditioning_sha256')} for x in normalized]
        signature=hashlib.sha256(json.dumps(manifest_items,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
        batch_id=str(uuid.uuid5(job_uuid,'flow-image-batch:'+signature))
        manifest=self._read_batch_manifest(batch_id);resumed=manifest is not None
        if manifest and (manifest.get('job_id')!=job_id or manifest.get('tasks')!=manifest_items):
            raise FlowTaskError('Flow batch manifest differs from this request; refusing new submissions','uncertain')
        if not manifest:
            manifest={'schema_version':1,'batch_id':batch_id,'job_id':job_id,'tasks':manifest_items,'baseline_media_ids':None,'project_url':None,
                      'task_state':{},'mapping':{},'stage':'prepared','created_at':time.time(),'submission_started_at':time.time(),'updated_at':time.time()}
            self._write_batch_manifest(batch_id,manifest)
        results={};settings_verified=False;batch_credit_estimate=None;batch_credit_verified_at=None;batch_credit_source_task_id=None
        if resumed:
            for candidate in normalized:
                old=self._read_receipt(candidate['task_id'])
                if old and old.get('stage') in ('waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                    evidence=old.get('credit_estimate') or ''
                    if re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',evidence,re.I):
                        settings_verified=True;batch_credit_estimate=evidence;batch_credit_verified_at=old.get('credit_verified_at');batch_credit_source_task_id=old.get('credit_batch_source_task_id') or old.get('task_id');break
        try:
            for item in normalized:
                task_id=item['task_id'];receipt=self._read_receipt(task_id)
                if receipt and (receipt.get('job_id')!=job_id or receipt.get('prompt_sha256')!=item['prompt_sha256'] or receipt.get('character_mentions',[])!=item['character_mentions']):
                    raise FlowTaskError('Flow batch task identity differs from its durable receipt','uncertain')
                cached=self._cached_result(task_id,receipt)
                if cached:
                    results[task_id]=cached
                    if receipt.get('stage')=='downloaded':
                        receipt.update({'batch_id':batch_id,'batch_ordinal':item['ordinal'],'batch_prompt_fingerprint':item['prompt_fingerprint']});self._write_receipt(task_id,receipt)
                        manifest['task_state'][task_id]='downloaded';manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
                        continue
                if receipt and receipt.get('stage')=='submitting':
                    raise FlowTaskError('Flow batch has an indeterminate submitting receipt; reconcile it before submitting another task','uncertain')
                if receipt and receipt.get('stage') in ('waiting_result','image_ready','download_menu_open','downloading'):
                    safe_resume=resumed and manifest.get('task_state',{}).get(task_id) in ('submit_started','waiting_result','image_ready','download_menu_open','downloading')
                    if receipt.get('batch_id')!=batch_id and not safe_resume:
                        raise FlowTaskError('A pending single-task receipt cannot be folded into a new batch','uncertain')
                else:
                    manifest['task_state'][task_id]='submit_started';manifest['stage']='submitting';manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
                    if manifest.get('project_url'):
                        await self.bridge.connect();slot_target=await self._target();slot_session=await self._session(slot_target)
                        await self._wait_batch_slot(slot_session,manifest,normalized,timeout)
                    submission=await self._generate_unreserved(task_id,job_id,item['prompt'],timeout=1,character_mentions=item['character_mentions'],submit_only=True,require_zero_credit=require_zero_credit,batch_settings_verified=settings_verified,batch_credit_estimate=batch_credit_estimate,batch_credit_verified_at=batch_credit_verified_at,batch_credit_source_task_id=batch_credit_source_task_id,submit_with_enter=False,bridge_lock_held=bridge_lock_held)
                    if not settings_verified:
                        estimate=submission.get('credit_estimate')
                        if require_zero_credit and (not estimate or not re.search(r'quá trình tạo sẽ tốn\s*0\s*tín dụng|generation will cost\s*0\s*credits',estimate,re.I)):
                            raise FlowTaskError('First batch prompt lacks explicit zero-credit estimate; no subsequent prompt will be sent','needs_flow_check')
                        batch_credit_estimate=estimate;batch_credit_verified_at=submission.get('credit_verified_at');batch_credit_source_task_id=task_id;settings_verified=True
                receipt=self._read_receipt(task_id) or {}
                if receipt.get('stage')=='submitting':raise FlowTaskError('Flow batch submission is indeterminate; no further task submitted','uncertain')
                if receipt.get('stage') not in ('waiting_result','image_ready','download_menu_open','downloading','downloaded'):
                    raise FlowTaskError('Flow batch task did not reach a durable submitted/result stage','uncertain')
                receipt.update({'batch_id':batch_id,'batch_ordinal':item['ordinal'],'batch_prompt_fingerprint':item['prompt_fingerprint']});self._write_receipt(task_id,receipt)
                if manifest.get('baseline_media_ids') is None and receipt.get('baseline_media_ids') is not None:
                    manifest['baseline_media_ids']=list(receipt.get('baseline_media_ids') or [])
                project_url=receipt.get('project_url')
                if project_url:
                    if manifest.get('project_url') and manifest['project_url'].split('?')[0].rstrip('/')!=project_url.split('?')[0].rstrip('/'):
                        raise FlowTaskError('Flow batch receipts point at multiple projects','uncertain')
                    manifest['project_url']=project_url.split('?')[0]
                manifest['task_state'][task_id]=receipt.get('stage');manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
            if not manifest.get('submission_completed_at'):
                manifest['submission_completed_at']=time.time();manifest['submit_elapsed_seconds']=round(manifest['submission_completed_at']-manifest.get('submission_started_at',manifest['created_at']),2)
                self._write_batch_manifest(batch_id,manifest)
            if len(results)==len(normalized):
                manifest.pop('last_error',None)
                manifest['stage']='completed';manifest['completed_at']=time.time();manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
                return [results[x['task_id']] for x in normalized]
            if not manifest.get('project_url') or manifest.get('baseline_media_ids') is None:
                raise FlowTaskError('Flow batch lacks a durable project URL or baseline; refusing ownership guesses','uncertain')
            await self.bridge.connect();target=await self._target();session=await self._session(target)
            await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
            project_path=urlparse(manifest['project_url']).path.rstrip('/');baseline=set(manifest['baseline_media_ids'] or [])
            current_task_ids={item['task_id'] for item in normalized}
            # The initial UI baseline contains only mounted tiles. Previously
            # accepted media from this job also belong to the baseline offscreen.
            for path in self.tasks.glob('*.json'):
                old=json.loads(path.read_text(encoding='utf8'))
                if old.get('job_id')==job_id and old.get('task_id') not in current_task_ids and old.get('media_id') and old.get('project_url','').split('?')[0].rstrip('/')==manifest['project_url'].rstrip('/'):
                    baseline.add(old['media_id'])
            current_state=await self._snapshot(session,'')
            if urlparse(current_state.get('url','')).path.rstrip('/')!=project_path:
                if not current_state.get('draftEmpty') or not current_state.get('generateDisabled'):
                    raise FlowTaskError('Flow tab has an active draft or request; refusing to switch to the batch project','uncertain')
                await self.bridge.cdp.command('Page.navigate',{'url':manifest['project_url']},session=session)
                await self._wait_page(session,lambda s:urlparse(s.get('url','')).path.rstrip('/')==project_path and s.get('composerAvailable'),timeout=25,prompt='')
            mapped=dict(manifest.get('mapping') or {})
            for item in normalized:
                if item['task_id'] in results:continue
                receipt=self._read_receipt(item['task_id']) or {}
                if receipt.get('media_id') and receipt.get('batch_prompt_fingerprint')==item['prompt_fingerprint']:
                    mapped[item['task_id']]=receipt['media_id']
            if mapped and (len(set(mapped.values()))!=len(mapped) or any(task_id not in {x['task_id'] for x in normalized} for task_id in mapped)):
                raise FlowTaskError('Saved Flow cohort mapping is duplicated or foreign','uncertain')
            state=None;new_tiles=[];deadline=time.monotonic()+min(timeout,180)
            if len(mapped)<len(normalized):
                await self._grid_view(session,0)
                while time.monotonic()<deadline:
                    async with self._maybe_job_lock(bridge_lock_held):state=await self._snapshot(session,'')
                    if not state or urlparse(state.get('url','')).path.rstrip('/')!=project_path:
                        raise FlowTaskError('Flow navigated away from the batch project; refusing asset association','uncertain')
                    new_tiles=[tile for tile in state.get('assetTiles',[]) if tile.get('media_id') and tile['media_id'] not in baseline and tile.get('complete')]
                    if len(new_tiles)>len(normalized):
                        raise FlowTaskError('Flow project contains extra new assets; refusing cohort assignment','uncertain')
                    if len(new_tiles)==len(normalized):break
                    await asyncio.sleep(.4)
                if len(new_tiles)!=len(normalized):
                    manifest['stage']='waiting_result';manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
                    raise FlowTaskError('Flow cohort results are incomplete; no task will be resubmitted','uncertain')
                media_prompts=[]
                for tile in new_tiles:
                    async with self._maybe_job_lock(bridge_lock_held):
                        detail=await self._read_batch_media_prompt(session,tile['media_id'],manifest['project_url'],normalized)
                    media_prompts.append(detail)
                frozen=(self._batch_row_mapping(normalized,new_tiles,baseline,media_prompts=media_prompts) if download_results else self._batch_prompt_mapping(normalized,media_prompts))
                if any(frozen.get(task_id)!=media_id for task_id,media_id in mapped.items()):
                    raise FlowTaskError('Flow row mapping conflicts with saved receipts','uncertain')
                mapped=frozen
                manifest['mapping']=dict(mapped);manifest['stage']='mapped';manifest['results_ready_at']=time.time();manifest['wait_elapsed_seconds']=round(manifest['results_ready_at']-manifest['submission_completed_at'],2);manifest['mapped_at']=time.time();manifest['updated_at']=time.time()
                self._write_batch_manifest(batch_id,manifest)
            if len(mapped)!=len(normalized):raise FlowTaskError('Flow cohort did not map every task','uncertain')
            if not new_tiles:
                state=await self._snapshot(session,'')
                if not state or urlparse(state.get('url','')).path.rstrip('/')!=project_path:
                    raise FlowTaskError('Flow project changed before resuming saved download order','uncertain')
                new_tiles=await self._scan_grid_tiles(session,manifest['project_url'],wanted=set(mapped.values()))
            order,positions=self._batch_download_order(normalized,new_tiles,mapped)
            # A resumed batch may have scrolled/reflowed. Preserve the frozen ID
            # order, then locate each card afresh; never infer ownership by position.
            if not manifest.get('download_order'):manifest['download_order']=order
            manifest['tile_positions']=positions
            tile_by_id={x.get('media_id'):x for x in new_tiles}
            for item in normalized:
                task_id=item['task_id']
                if task_id in results:continue
                receipt=self._read_receipt(task_id) or {};media_id=mapped.get(task_id)
                if not media_id:raise FlowTaskError('Flow batch mapping omitted a task','uncertain')
                if receipt.get('media_id') and receipt.get('media_id')!=media_id:raise FlowTaskError('Flow batch mapping conflicts with a saved media receipt','uncertain')
                receipt.update({'stage':'image_ready','media_id':media_id,'batch_id':batch_id,'batch_ordinal':item['ordinal'],'batch_prompt_fingerprint':item['prompt_fingerprint'],'prompt_identity_verified':True,'prompt_identity_method':'frozen_row_order_and_full_tile_prompt','result_dimensions':{'media_id':media_id,'title':tile_by_id.get(media_id,{}).get('aria_label','')},'updated_at':time.time()})
                self._write_receipt(task_id,receipt);manifest['task_state'][task_id]='image_ready';manifest['mapping'][task_id]=media_id
            if not download_results:
                manifest.update({'stage':'images_ready','images_ready_at':time.time(),'download_results':False,'updated_at':time.time()})
                self._write_batch_manifest(batch_id,manifest)
                return [{'task_id':item['task_id'],'media_id':mapped[item['task_id']],'project_url':manifest['project_url'],'ordinal':item['ordinal'],'stage':'image_ready'} for item in normalized]
            if len(manifest['download_order'])!=len(normalized) or set(manifest['download_order'])!={x['task_id'] for x in normalized}:
                raise FlowTaskError('Frozen Flow download order is invalid','uncertain')
            if not download_results:
                manifest.update({'stage':'images_ready','images_ready_at':time.time(),'download_results':False,'updated_at':time.time()})
                self._write_batch_manifest(batch_id,manifest)
                return [{'task_id':item['task_id'],'media_id':mapped[item['task_id']],'project_url':manifest['project_url'],'ordinal':item['ordinal'],'stage':'image_ready'} for item in normalized]
            manifest['download_results']=True;manifest['stage']='downloading';manifest.setdefault('downloads_started_at',time.time());manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
            items_by_id={item['task_id']:item for item in normalized}
            for task_id in manifest['download_order']:
                item=items_by_id[task_id]
                if task_id in results:continue
                receipt=self._read_receipt(task_id) or {};cached=self._cached_result(task_id,receipt)
                if cached:results[task_id]=cached;continue
                if receipt.get('stage') not in ('image_ready','download_menu_open','downloading') or not receipt.get('media_id'):
                    raise FlowTaskError('Flow batch task is not durably mapped before download','uncertain')
                composed=' '.join([m['name'] for m in item['character_mentions']]+[item['prompt']]).strip()
                async with self._maybe_job_lock(bridge_lock_held):
                    current=await self._snapshot(session,'')
                    if not current or urlparse(current.get('url','')).path.rstrip('/')!=project_path:
                        raise FlowTaskError('Flow left the mapped batch project; refusing download','uncertain')
                    await self.bridge.cdp.command('Target.activateTarget',{'targetId':target})
                    if manifest.get('prefer_original_resolution'):
                        receipt.update(download_resolution_requested='1K',download_fallback_reason='2K unavailable earlier in this cohort; use original resolution')
                        self._write_receipt(task_id,receipt)
                    receipt=await self._download_2k(task_id,target,session,receipt,composed,media_id=receipt['media_id'])
                    if receipt.get('download_resolution_requested')=='1K' and receipt.get('download_fallback_reason'):
                        manifest['prefer_original_resolution']=True
                results[task_id]={'task_id':task_id,'file_path':receipt['download_path'],'sha256':receipt['download_sha256'],'width':receipt['width'],'height':receipt['height'],'request_id':'flow-'+task_id,'source':'google_flow_nano_banana_2_1','format':'PNG','flow_download_format':receipt.get('format'),'project_url':receipt.get('project_url'),'download_guid':receipt.get('download_guid'),'media_id':receipt.get('media_id')}
                manifest['task_state'][task_id]='downloaded';manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
            manifest.pop('last_error',None)
            manifest['stage']='completed';manifest['completed_at']=time.time();manifest['download_elapsed_seconds']=round(manifest['completed_at']-manifest['downloads_started_at'],2);manifest['total_elapsed_seconds']=round(manifest['completed_at']-manifest['created_at'],2);manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
            return [results[x['task_id']] for x in normalized]
        except FlowTaskError as error:
            manifest['last_error']={'code':error.code,'message':str(error),'updated_at':time.time()};manifest['stage']='needs_reconciliation';manifest['updated_at']=time.time();self._write_batch_manifest(batch_id,manifest)
            raise

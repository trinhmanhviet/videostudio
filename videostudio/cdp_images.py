"""ChatGPT image UI adapter for the dedicated browser, never a private API client."""
import asyncio,json,re,sys,time,uuid,shutil
from pathlib import Path
from urllib.parse import urlparse
from PIL import Image
from .core import digest
from .cdp_requests import IndeterminateRequest,valid_chat_url
from .cdp_page import snapshot_expression,composer_expression,send_button_expression,chat_mode_button_expression

class ImageAuthentication(RuntimeError):pass
class ImageRejected(ValueError):pass
MAX_IMAGE=20*1024*1024

def image_prompt(prompt,identifier):
    return ('Create exactly ONE portrait 9:16 image for a video scene. Return the generated image, not a written description or JSON. Do not draw tracking markers, labels or watermarks. Follow this scene description:\n'+prompt+'\nTracking marker (never draw it): [VideoStudio image request '+identifier+']')

def image_snapshot(marker):
    return r'''(()=>{const base=BASE;const turns=[...document.querySelectorAll('[data-talvt-turn-state]')].map(t=>{
      const h=[...t.querySelectorAll('h4')].find(h=>/^(You said:|Bạn đã nói:|Bạn nói:)$/i.test(h.textContent.trim()));
      const user=h?.parentElement?.textContent||'';
      const generated=[...t.querySelectorAll('button[data-testid="generated-image-preview"] img')];
      return {user,state:t.getAttribute('data-talvt-turn-state'),text:t.innerText.slice(-2500),images:generated.map(i=>({src:i.currentSrc,width:i.naturalWidth,height:i.naturalHeight,loaded:i.complete}))};
    });return {...base,image_turns:turns};})()'''.replace('BASE',snapshot_expression(marker))

def match_image(state,marker):
    if not state or state.get('login') or state.get('challenge') or state.get('mode') not in ('chat','unknown'):return None
    turns=[t for t in state.get('image_turns',[]) if marker in t.get('user','')]
    if len(turns)>1:raise ValueError('Duplicate request marker; refusing to choose an image')
    if not turns or turns[0].get('state')!='complete':return None
    images=turns[0].get('images',[])
    if len(images)>1:raise ValueError('Multiple generated images; explicit review required')
    if not images:return None
    image=images[0];src=image.get('src','')
    if not image.get('loaded') or min(image.get('width',0),image.get('height',0))<512:return None
    if not (src.startswith('blob:https://chatgpt.com/') or urlparse(src).scheme=='https'):raise ValueError('Invalid generated image source')
    return image

def correlated_download(events,frame):
    starts=[e['params'] for e in events if e.get('method')=='Browser.downloadWillBegin' and e.get('params',{}).get('frameId')==frame]
    guids=list(dict.fromkeys(s.get('guid','') for s in starts if s.get('guid')))
    if len(guids)!=1:return None
    guid=guids[0]
    try:uuid.UUID(guid)
    except (ValueError,TypeError,AttributeError):return None
    return guid if any(e.get('method')=='Browser.downloadProgress' and e.get('params',{}).get('guid')==guid and e['params'].get('state')=='completed' for e in events) else None

def stable_control_point(previous,current):
    keys=('control','x','y','width','height')
    return bool(previous and current and all(previous.get(k)==current.get(k) for k in keys))

class ChatGPTImages:
    def __init__(self,bridge,root):
        self.bridge=bridge;self.root=Path(root);self.events=[];self.changed=asyncio.Event();self.active_frame=None;self.download_guid=None;self.too_large=False;self.attempt=None;self.attempt_started=None;self.download_behavior_uncertain=False
    def _record(self,phase,**data):
        if self.attempt is None:return
        self.attempt['steps'].append({'at':time.time(),'elapsed_ms':round((time.monotonic()-self.attempt_started)*1000),'phase':phase,**data})
    def _record_event(self,event,accepted):
        p=event.get('params',{})
        item={'at':time.time(),'method':event.get('method'),'accepted':accepted}
        for key in ('frameId','guid','state','receivedBytes','totalBytes'):
            if key in p:item[key]=p[key]
        if self.attempt is not None:self.attempt['events'].append(item)
    def _save_attempt(self,folder):
        if self.attempt is None:return
        try:(folder/('download-attempt-'+self.attempt['attempt_id']+'.json')).write_text(json.dumps(self.attempt,indent=2),encoding='utf8')
        except Exception:pass
        self.attempt=None;self.attempt_started=None
    async def _finish_download_attempt(self,folder,primary_error=None):
        try:
            await self.bridge.cdp.command('Browser.setDownloadBehavior',{'behavior':'default','eventsEnabled':False})
            self.download_behavior_uncertain=False;self._record('download_behavior_restored',acknowledged=True)
        except Exception as error:
            self.download_behavior_uncertain=True
            self._record('download_behavior_restore_failed',error_type=type(error).__name__)
        finally:
            self.active_frame=None;self._save_attempt(folder)
    def on_event(self,event):
        if not self.active_frame:return
        method=event.get('method');p=event.get('params',{})
        if method=='Browser.downloadWillBegin':
            accepted=p.get('frameId')==self.active_frame;self._record_event(event,accepted)
            if not accepted:return
            self.download_guid=p.get('guid');self.events.append(event);self.changed.set()
        elif method=='Browser.downloadProgress':
            accepted=p.get('guid')==self.download_guid;self._record_event(event,accepted)
            if not accepted:return
            self.events.append(event)
            if max(p.get('receivedBytes',0),p.get('totalBytes',0))>MAX_IMAGE:self.too_large=True
            self.changed.set()
    async def _click(self,session,p):
        if not p:raise RuntimeError('Required image UI control not available')
        for k in ('mousePressed','mouseReleased'):
            await self.bridge.cdp.command('Input.dispatchMouseEvent',{'type':k,'x':p['x'],'y':p['y'],'button':'left','clickCount':1},session=session)
    async def _target(self,job,recover):
        b=self.bridge;saved=b.journal.conversation(job);targets=(await b.cdp.command('Target.getTargets'))['targetInfos']
        if saved:
            for t in targets:
                if t['targetId']==saved['target'] and t['type']=='page' and valid_chat_url(t.get('url','')) and t['url'].split('?')[0].rstrip('/')==saved['url'].split('?')[0].rstrip('/'):
                    return saved['target']
            if recover and '/c/' not in saved['url']:raise IndeterminateRequest('Image conversation URL unknown; inspect dedicated Chrome, never resend')
        # Never borrow/reuse another open conversation; only this image job owns this target.
        target=(await b.cdp.command('Target.createTarget',{'url':saved['url'] if saved else 'https://chatgpt.com/'}))['targetId']
        b.journal.own_target(target,'image')
        b.journal.set_conversation(job,saved['url'] if saved else 'https://chatgpt.com/',target)
        return target
    async def _ready(self,session,marker):
        b=self.bridge;deadline=time.monotonic()+35;switched=False
        while time.monotonic()<deadline:
            state=await b.evaluate(session,image_snapshot(marker))
            if state.get('login') or state.get('challenge'):raise ImageAuthentication('Sign in or finish verification in dedicated Chrome; no credentials automated')
            if state.get('mode')=='work':
                if state.get('draft','').strip() or switched:raise RuntimeError('Work draft or uncertain mode; no image prompt sent')
                await self._click(session,await b.evaluate(session,chat_mode_button_expression()));switched=True
            elif state.get('mode')=='chat' and state.get('composer'):return state
            await asyncio.sleep(.3)
        raise TimeoutError('Image composer not ready; no send attempted')
    async def generate(self,task_id,prompt,timeout=480):
        uuid.UUID(task_id)
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=12000 or '[VideoStudio image request ' in prompt:raise ValueError('Invalid scene image prompt')
        b=self.bridge;job='__image__'+task_id;record=b.journal.prepare(job,prompt);identifier=record['id'];marker='[VideoStudio image request '+identifier+']';self.root.mkdir(parents=True,exist_ok=True)
        if record['state']=='completed':
            value=record['response'];p=self.root/(task_id+'.png')
            if value.get('task_id')!=task_id or not p.is_file() or digest(p)!=value.get('sha256'):raise ImageRejected('Completed image artifact changed/missing; no automatic regeneration')
            return value
        async with b.job_lock:
            # Another request may have completed while this waiter queued on the shared browser lock.
            record=b.journal.get(identifier)
            if record['state']=='completed':
                value=record['response'];p=self.root/(task_id+'.png')
                if not p.is_file() or digest(p)!=value.get('sha256'):raise ImageRejected('Image artifact missing')
                return value
            await b.connect();target=await self._target(job,record['state']!='prepared');session=await b.session(target);await b.cdp.command('Target.activateTarget',{'targetId':target})
            if record['state']=='prepared':
                state=await self._ready(session,marker);wrapped=image_prompt(prompt,identifier);draft=state.get('draft','').strip()
                if state.get('generating'):raise RuntimeError('Image tab already generating; no overwrite')
                if draft and ' '.join(draft.split())!=' '.join(wrapped.split()):raise RuntimeError('Different draft exists; no overwrite')
                if not draft:
                    await self._click(session,await b.evaluate(session,composer_expression()));await b.cdp.command('Input.insertText',{'text':wrapped},session=session)
                button=None;deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    button=await b.evaluate(session,send_button_expression())
                    if button:break
                    await asyncio.sleep(.2)
                if not button:raise RuntimeError('Image Send button unavailable; draft preserved')
                b.journal.claim_send(identifier) # must be durable BEFORE input
                final=await b.evaluate(session,image_snapshot(marker))
                if final.get('login') or final.get('challenge'):raise ImageAuthentication('Authentication changed before Send; receipt retained')
                if final.get('mode')!='chat' or final.get('generating') or ' '.join(final.get('draft','').split())!=' '.join(wrapped.split()):raise IndeterminateRequest('Draft/mode changed at image send boundary; no resend')
                await self._click(session,button) # exactly one submit, no fallback click
            deadline=time.monotonic()+timeout;found=None
            while time.monotonic()<deadline:
                state=await b.evaluate(session,image_snapshot(marker))
                if state.get('login') or state.get('challenge'):raise ImageAuthentication('Image request pending; authentication required, not resent')
                if not valid_chat_url(state.get('url','')):raise IndeterminateRequest('Image tab navigated away; not resent')
                turns=[t for t in state.get('image_turns',[]) if marker in t.get('user','')]
                if turns:b.journal.set_conversation(job,state['url'],target)
                found=match_image(state,marker)
                if found:break
                if len(turns)==1 and turns[0].get('state')=='complete' and not turns[0].get('images') and re.search(r"cannot generate|can't create|unable to generate|you.ve (?:hit|reached)|rate limit|try again later|image limit",turns[0].get('text',''),re.I):raise ImageRejected('ChatGPT declined or image limit reached; inspect this conversation')
                await asyncio.sleep(1)
            if not found:raise IndeterminateRequest('Matching image not completed within deadline; recover this request, never auto resend')
            value=await self._download(task_id,target,session,marker,found,state['url']);value['request_id']=identifier;b.journal.complete(identifier,value)
            # Only close this explicitly created image target, only if it still contains our marker.
            try:
                current=await b.evaluate(session,image_snapshot(marker))
                if any(marker in t.get('user','') for t in current.get('image_turns',[])) and current.get('url')==state['url']:
                    await b.cdp.command('Target.closeTarget',{'targetId':target});b.sessions.pop(target,None)
            except Exception:pass
            return value
    async def _stable_control_point(self,session,expression,timeout,control):
        deadline=time.monotonic()+timeout;previous=None
        while time.monotonic()<deadline:
            point=await self.bridge.evaluate(session,expression)
            if point:
                point['control']=control
                self._record('control_observed',control=control,bounds={k:point.get(k) for k in ('x','y','width','height')})
                if stable_control_point(previous,point):
                    self._record('control_stable',control=control,bounds={k:point.get(k) for k in ('x','y','width','height')})
                    return point
            previous=point
            await asyncio.sleep(.2)
        return None
    async def _download(self,task_id,target,session,marker,found,url):
        b=self.bridge;folder=self.root/'downloads'/task_id;folder.mkdir(parents=True,exist_ok=True)
        await b.cdp.command('Target.activateTarget',{'targetId':target})
        current=await b.evaluate(session,image_snapshot(marker))
        if current.get('login') or current.get('challenge'):raise ImageAuthentication('Authentication required before image download')
        if current.get('url')!=url or match_image(current,marker)!=found:raise IndeterminateRequest('Image/conversation changed before download; generation not resent')
        self.events=[];self.download_guid=None;self.too_large=False;self.changed.clear();self.attempt_started=time.monotonic();self.active_frame=None
        self.attempt={'attempt_id':uuid.uuid4().hex,'task_id':task_id,'target_id':target,'session_id':session,'started_at':time.time(),'frame_id':None,'steps':[],'events':[]}
        try:
            self.active_frame=(await b.cdp.command('Page.getFrameTree',session=session))['frameTree']['frame']['id'];self.attempt['frame_id']=self.active_frame
            self._record('capture_armed',frame_id=self.active_frame)
        except Exception as e:
            self._record('failure',error_type=type(e).__name__,error=str(e)[:400]);self._save_attempt(folder);raise
        # Arm browser-level capture before opening the image viewer or measuring controls.
        download_expr=r'''(()=>{const dialogs=[...document.querySelectorAll('[role=dialog]')].filter(d=>[...d.querySelectorAll('img')].some(i=>i.currentSrc===SOURCE));const bs=[...new Set(dialogs.flatMap(d=>[...d.querySelectorAll('button[aria-label="Download"],button[aria-label="Save"]')]))].filter(e=>e.getBoundingClientRect().width);if(bs.length!==1)return null;const r=bs[0].getBoundingClientRect();const x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2),hit=document.elementFromPoint(x,y);if(bs[0].disabled||!hit||!(hit===bs[0]||bs[0].contains(hit)))return null;return {x,y,width:Math.round(r.width),height:Math.round(r.height)}})()'''.replace('SOURCE',json.dumps(found['src']))
        preview_expr=r'''(()=>{const turns=[...document.querySelectorAll('[data-talvt-turn-state]')].filter(t=>{const h=[...t.querySelectorAll('h4')].find(h=>/^(You said:|Bạn đã nói:|Bạn nói:)$/i.test(h.textContent.trim()));return h?.parentElement?.textContent.includes(MARKER)});if(turns.length!==1)return null;const bs=[...turns[0].querySelectorAll('button[data-testid="generated-image-preview"]')].filter(e=>e.querySelector('img')?.currentSrc===SOURCE);if(bs.length!==1)return null;bs[0].scrollIntoView({block:'center'});const r=bs[0].getBoundingClientRect();const x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2),hit=document.elementFromPoint(x,y);if(bs[0].disabled||!hit||!(hit===bs[0]||bs[0].contains(hit)))return null;return {x,y,width:Math.round(r.width),height:Math.round(r.height)}})()'''.replace('MARKER',json.dumps(marker)).replace('SOURCE',json.dumps(found['src']))
        try:
            if self.download_behavior_uncertain:
                await b.cdp.command('Browser.setDownloadBehavior',{'behavior':'default','eventsEnabled':False})
                self.download_behavior_uncertain=False
                self._record('previous_download_behavior_reset',acknowledged=True)
            self._record('download_behavior_enable_begin')
            await b.cdp.command('Browser.setDownloadBehavior',{'behavior':'allowAndName','downloadPath':str(folder.resolve()),'eventsEnabled':True})
            self._record('download_behavior_enabled',acknowledged=True)
            point=await self._stable_control_point(session,download_expr,2,'viewer-download')
            if not point:
                preview=await self._stable_control_point(session,preview_expr,5,'matching-image-preview')
                if not preview:raise IndeterminateRequest('Matching image preview control unavailable; generation not resent')
                self._record('preview_click_begin',bounds={k:preview.get(k) for k in ('x','y','width','height')})
                await self._click(session,preview)
                self._record('preview_click_acknowledged')
                point=await self._stable_control_point(session,download_expr,8,'viewer-download')
            if not point:raise IndeterminateRequest('Generated image exists but no stable matching Download control; generation not resent')
            self._record('viewer_ready',control=point['control'],bounds={k:point.get(k) for k in ('x','y','width','height')})
            # Re-query immediately before the click; if the viewer reflowed, stabilize the new bounds first.
            fresh=await b.evaluate(session,download_expr)
            if not fresh:
                self._record('control_missing_before_click')
                point=await self._stable_control_point(session,download_expr,3,'viewer-download')
                if not point:raise IndeterminateRequest('Matching Download control disappeared; generation not resent')
            else:
                fresh['control']='viewer-download'
                if not stable_control_point(point,fresh):
                    self._record('control_reflowed_before_click',previous={k:point.get(k) for k in ('x','y','width','height')},current={k:fresh.get(k) for k in ('x','y','width','height')})
                    point=await self._stable_control_point(session,download_expr,3,'viewer-download')
                    if not point:raise IndeterminateRequest('Download control kept moving; generation not resent')
                else:point=fresh
            self._record('download_click_begin',bounds={k:point.get(k) for k in ('x','y','width','height')})
            await self._click(session,point)
            self._record('download_click_acknowledged')
            deadline=time.monotonic()+45;guid=None
            while time.monotonic()<deadline:
                if self.too_large:
                    if self.download_guid:await b.cdp.command('Browser.cancelDownload',{'guid':self.download_guid})
                    raise ImageRejected('Generated image exceeds 20 MB')
                guid=correlated_download(self.events,self.active_frame)
                if guid:break
                if any(e.get('params',{}).get('state')=='canceled' for e in self.events):raise IndeterminateRequest('Image download canceled; generation not resent')
                self.changed.clear()
                try:await asyncio.wait_for(self.changed.wait(),min(2,max(.1,deadline-time.monotonic())))
                except asyncio.TimeoutError:pass
            if not guid:raise IndeterminateRequest('Owned image download not confirmed; generation not resent')
            self._record('download_correlated',guid=guid)
            p=folder/guid
            if not p.is_file() or not 1000<p.stat().st_size<=MAX_IMAGE:raise ImageRejected('Downloaded image file missing or invalid size')
            with Image.open(p) as im:
                if im.format not in ('PNG','JPEG','WEBP') or min(im.size)<512 or max(im.size)>8192 or im.width*im.height>20_000_000:raise ImageRejected('Downloaded image invalid format/dimensions')
                im.load();width,height=im.size;fmt=im.format
            destination=self.root/(task_id+'.png');part=destination.with_suffix('.part');shutil.copyfile(p,part);part.replace(destination)
            self._record('image_validated',bytes=destination.stat().st_size,width=width,height=height,format=fmt,sha256=digest(destination))
            return {'task_id':task_id,'file_path':str(destination.resolve()),'sha256':digest(destination),'width':width,'height':height,'format':fmt,'conversation_url':url,'download_guid':guid,'download_frame':self.active_frame,'source':'chatgpt_visible_download'}
        except Exception as e:
            self._record('failure',error_type=type(e).__name__,error=str(e)[:400])
            raise
        finally:
            await self._finish_download_attempt(folder,sys.exc_info()[1])

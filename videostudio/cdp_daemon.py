"""Loopback-only browser owner. Start with python -m videostudio.cdp_daemon.
GET status is passive. Only explicit browser/start or a scoped job may connect.
"""
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from aiohttp import web
from .chrome_browser import DedicatedChrome, ROOT
from .cdp_protocol import CDPConnection, CDPError
from .cdp_requests import RequestJournal, IndeterminateRequest, valid_chat_url
from .cdp_page import snapshot_expression, composer_expression, send_button_expression, chat_mode_button_expression, correlate_turns
from .exchanges import parse_reply
from .cdp_images import ChatGPTImages, ImageAuthentication, ImageRejected
from .cdp_flow import FlowImages, FlowTaskError


class NeedsAuthentication(RuntimeError):
    pass


class ChromeChatGPTBridge:
    def __init__(self, launcher=None, journal=None):
        self.launcher = launcher or DedicatedChrome()
        self.journal = journal or RequestJournal(ROOT/'data'/'cdp-requests.sqlite3')
        self.sessions = {}
        self.cdp = CDPConnection(on_event=self.on_event)
        self.connect_lock = asyncio.Lock()
        self.job_lock = asyncio.Lock()
        self.authenticated = False
        self.last_error = None
        self.images = ChatGPTImages(self, ROOT/'data'/'chatgpt-images')
        self.flow_images = FlowImages(self, ROOT/'data'/'flow-images')

    def on_event(self, event):
        if getattr(self,'images',None):self.images.on_event(event)
        if getattr(self,'flow_images',None):self.flow_images.on_event(event)
        if event.get('method') in ('Target.targetDestroyed', 'Target.targetCrashed'):
            self.sessions.pop(event.get('params', {}).get('targetId'), None)

    def status(self):
        connected = self.cdp.connected
        return {'ok':True, 'service':'videostudio-dedicated-cdp', 'connected':connected,
                'ready':connected and self.authenticated, 'mode':'headed', 'readiness_scope':'connector_only', 'production_ready':False,
                'authentication':'verified' if connected and self.authenticated else 'unverified',
                'last_error':self.last_error}

    async def connect(self):
        async with self.connect_lock:
            if self.cdp.connected:
                return
            self.authenticated = False
            endpoint = await asyncio.to_thread(self.launcher.ensure_started)
            await self.cdp.connect(endpoint)
            try:
                command = await self.cdp.command('Browser.getBrowserCommandLine')
                expected = '--user-data-dir='+str(self.launcher.config.profile.resolve())
                if expected not in command.get('arguments', []):
                    raise RuntimeError('CDP endpoint does not attest the dedicated profile')
                await self.cdp.command('Target.setDiscoverTargets', {'discover':True})
            except BaseException:
                await self.cdp.close()
                raise

    async def ensure_tab(self, job):
        saved = self.journal.conversation(job)
        result = await self.cdp.command('Target.getTargets')
        targets = result.get('targetInfos', [])
        target = None
        if saved:
            for t in targets:
                if t.get('targetId') == saved['target'] and t.get('type') == 'page' and valid_chat_url(t.get('url','')):
                    # Never commandeer a different conversation the user navigated to.
                    if t['url'].split('?')[0].rstrip('/') == saved['url'].split('?')[0].rstrip('/'):
                        target = t['targetId']
                        break
        else:
            # Reuse active ChatGPT tab if one already exists
            for t in targets:
                if t.get('type') == 'page' and valid_chat_url(t.get('url','')) and self.journal.reusable_text_target(t.get('targetId'),t.get('url','')):
                    target = t['targetId']
                    self.journal.set_conversation(job, t.get('url', 'https://chatgpt.com/'), target)
                    break
        if not target:
            url = saved['url'] if saved else 'https://chatgpt.com/'
            created = await self.cdp.command('Target.createTarget', {'url':url})
            target = created['targetId']
            self.journal.own_target(target,'text')
            self.journal.set_conversation(job, url, target)

        # Never close tabs merely because they are present. Uncertain image requests
        # and owner-opened conversations remain untouched; reuse only attested text tabs.
        return target

    async def session(self, target):
        if target not in self.sessions:
            result = await self.cdp.command('Target.attachToTarget', {'targetId':target, 'flatten':True})
            self.sessions[target] = result['sessionId']
        return self.sessions[target]

    async def evaluate(self, session, expression):
        result = await self.cdp.command('Runtime.evaluate', {'expression':expression, 'returnByValue':True}, session=session)
        if result.get('exceptionDetails'):
            raise RuntimeError('ChatGPT DOM evaluation failed')
        return result.get('result', {}).get('value')

    async def page_ready(self, job, marker='', timeout=30):
        target = await self.ensure_tab(job)
        session = await self.session(target)
        # Only activate the tool-owned tab; no global freeze/Memory Saver changes.
        await self.cdp.command('Target.activateTarget', {'targetId':target})
        deadline = time.monotonic()+timeout
        switched = False
        reattachments = 0
        while time.monotonic() < deadline:
            try:
                state = await self.evaluate(session, snapshot_expression(marker))
            except TimeoutError:
                # A newly recreated target may still be hydrating. Retry reads only;
                # no navigation, typing or submission is performed here.
                await asyncio.sleep(.2)
                continue
            except CDPError as error:
                transient = ('session with given id not found','no session with given id','execution context was destroyed','cannot find context')
                if reattachments >= 2 or not any(t in str(error).lower() for t in transient):
                    raise
                self.sessions.pop(target, None)
                target = await self.ensure_tab(job)
                session = await self.session(target)
                await self.cdp.command('Target.activateTarget', {'targetId':target})
                reattachments += 1
                await asyncio.sleep(.2)
                continue
            if state and (state.get('login') or state.get('challenge')):
                self.authenticated = False
                raise NeedsAuthentication('Use the dedicated Chrome window to sign in or finish verification')
            if state and state.get('mode') == 'work':
                self.authenticated = False
                if state.get('draft','').strip():
                    raise RuntimeError('Work draft exists; refusing to discard it by changing modes')
                if switched:
                    raise RuntimeError('Chat mode switch did not take effect; no prompt sent')
                button = await self.evaluate(session, chat_mode_button_expression())
                if not button:
                    raise RuntimeError('Chat mode control unavailable; no prompt sent')
                for kind in ('mousePressed','mouseReleased'):
                    await self.cdp.command('Input.dispatchMouseEvent', {'type':kind, 'x':button['x'], 'y':button['y'], 'button':'left', 'clickCount':1}, session=session)
                switched = True
                await asyncio.sleep(.5)
                continue
            if state and state.get('composer') and state.get('mode') != 'chat':
                self.authenticated = False
                raise RuntimeError('Chat mode not verified; refusing to type or send')
            if state and valid_chat_url(state.get('url','')) and state.get('composer') and state.get('mode') == 'chat':
                self.authenticated = True
                self.journal.set_conversation(job, state['url'], target)
                return target, session, state
            await asyncio.sleep(.5)
        raise TimeoutError('ChatGPT composer not ready; no prompt sent')

    async def open_login(self):
        async with self.job_lock:
            await self.connect()
            target = await self.ensure_tab('__login__')
            await self.cdp.command('Target.activateTarget', {'targetId':target})
            return {**self.status(), 'target_id':target, 'message':'Sign in in the dedicated Chrome window; no credentials are copied.'}

    async def probe_login(self):
        async with self.job_lock:
            await self.connect()
            await self.page_ready('__login__')
            return self.status()

    async def ensure_high_effort(self, session):
        expression=r'''(() => {
          const visible=e=>{const r=e?.getBoundingClientRect();return !!r&&r.width>0&&r.height>0};
          const button=[...document.querySelectorAll('button')].find(e=>visible(e)&&e.getAttribute('aria-label')==='Select ChatGPT model');
          const label=button?.innerText||'';
          const thumb=[...document.querySelectorAll('[role="slider"][aria-valuemax]')].find(visible);
          const track=thumb?.parentElement;
          const tr=visible(track)?track.getBoundingClientRect():null;
          const b=button?.getBoundingClientRect();
          const value=thumb?Number(thumb.getAttribute('aria-valuenow')):null;
          const max=thumb?Number(thumb.getAttribute('aria-valuemax')):null;
          return JSON.stringify({high:/\bHigh\b/i.test(label)||(value!==null&&max!==null&&value>=max),
            button:b?{x:b.x+b.width/2,y:b.y+b.height/2}:null,
            slider:tr?{track:{x:tr.x,y:tr.y+tr.height/2,width:tr.width},value,max}:null});
        })()'''
        async def state():
            raw=await self.evaluate(session,expression)
            if isinstance(raw,str):
                try:return json.loads(raw)
                except ValueError:pass
            return raw if isinstance(raw,dict) else {}
        current=await state()
        if current.get('high'):return
        button=current.get('button')
        if not isinstance(button,dict):raise RuntimeError('ChatGPT High reasoning control unavailable; no request sent')
        for kind in ('mousePressed','mouseReleased'):
            await self.cdp.command('Input.dispatchMouseEvent',{'type':kind,'x':button['x'],'y':button['y'],'button':'left','clickCount':1},session=session)
        slider=None
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            current=await state();slider=current.get('slider')
            if isinstance(slider,dict) and isinstance(slider.get('track'),dict) and slider.get('max',0)>0:break
            await asyncio.sleep(.1)
        if not isinstance(slider,dict):raise RuntimeError('ChatGPT reasoning slider unavailable; no request sent')
        track=slider['track']
        for kind in ('mousePressed','mouseReleased'):
            await self.cdp.command('Input.dispatchMouseEvent',{'type':kind,'x':track['x']+track['width']-2,'y':track['y'],'button':'left','clickCount':1},session=session)
        verified=await state()
        if not verified.get('high'):
            raise RuntimeError('ChatGPT High reasoning effort could not be verified; no request sent')

    async def ask_chatgpt(self, job, prompt_text, timeout_seconds=300):
        async with self.job_lock:
            record = self.journal.prepare(job, prompt_text)
            if record['state'] == 'completed':
                return record['response']
            identifier = record['id']
            marker = '[VideoStudio request '+identifier+']'
            await self.connect()
            if record['state'] == 'prepared':
                target, session, state = await self.page_ready(job, marker)
                wrapped = (marker+'\n'+prompt_text+'\nReturn exactly one JSON object with this envelope: '
                           +json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
                draft = state.get('draft','').strip()
                if state.get('generating'):
                    raise RuntimeError('Owned tab has active generation; no overwrite or send')
                if draft and ' '.join(draft.split()) != ' '.join(wrapped.split()):
                    raise RuntimeError('Owned tab has a different draft; no overwrite or send')
                await self.ensure_high_effort(session)
                if not draft:
                    focused = await self.evaluate(session, composer_expression())
                    if not focused:
                        raise RuntimeError('Composer unavailable; no prompt sent')
                    if isinstance(focused, dict) and 'x' in focused and 'y' in focused:
                        for kind in ('mousePressed', 'mouseReleased'):
                            await self.cdp.command('Input.dispatchMouseEvent', {'type':kind, 'x':focused['x'], 'y':focused['y'], 'button':'left', 'clickCount':1}, session=session)
                        await asyncio.sleep(0.1)
                    await self.cdp.command('Input.insertText', {'text':wrapped}, session=session)
                button = None
                send_deadline = time.monotonic()+5
                while time.monotonic() < send_deadline:
                    button = await self.evaluate(session, send_button_expression())
                    if button:
                        break
                    await asyncio.sleep(.2)
                if not button:
                    raise RuntimeError('Send button unavailable; draft preserved, no request sent')
                # Durable write BEFORE mouse input. Any crash from here is recovery-only.
                self.journal.claim_send(identifier)
                final = await self.evaluate(session, snapshot_expression(marker))
                draft_clean = ' '.join(final.get('draft','').replace('\u00a0',' ').split()) if final else ''
                wrapped_clean = ' '.join(wrapped.replace('\u00a0',' ').split())
                if not final or final.get('mode')!='chat' or final.get('login') or final.get('challenge') or final.get('generating') or not draft_clean or (draft_clean != wrapped_clean and marker not in draft_clean):
                    raise IndeterminateRequest('Chat mode or draft changed at send boundary; no mouse dispatch, receipt retained')
                for kind in ('mousePressed', 'mouseReleased'):
                    await self.cdp.command('Input.dispatchMouseEvent', {'type':kind, 'x':button['x'], 'y':button['y'], 'button':'left', 'clickCount':1}, session=session)
                await self.evaluate(session, "(() => { const b = document.querySelector('button[aria-label=\"Send\"],button[data-testid=\"send-button\"],button[aria-label=\"Send prompt\"],button[aria-label=\"Send message\"]'); if(b && !b.disabled) b.click(); })()")
            else:
                target = await self.ensure_tab(job)
                session = await self.session(target)
                await self.cdp.command('Target.activateTarget', {'targetId':target})
            # Previously attempted request: only read its conversation, never send again.
            deadline = time.monotonic()+timeout_seconds
            previous = None
            while time.monotonic() < deadline:
                state = correlate_turns(await self.evaluate(session, snapshot_expression(marker)), marker)
                if state and (state.get('login') or state.get('challenge')):
                    self.authenticated = False
                    raise NeedsAuthentication('Authentication required; pending request retained, not resent')
                if state and valid_chat_url(state.get('url','')):
                    self.journal.set_conversation(job, state['url'], target)
                text = (state or {}).get('text','')
                if state and state.get('matched') and not state.get('generating') and text and text == previous:
                    try:
                        value = parse_reply(text)
                        self.journal.accept(identifier, value)
                        return value['result']
                    except (ValueError, json.JSONDecodeError):
                        pass
                if text != previous or (state and state.get('generating')):
                    deadline = max(deadline, time.monotonic() + 90)
                previous = text
                await asyncio.sleep(1)
            raise IndeterminateRequest('Matching completed response unavailable; receipt retained, no automatic resubmission')

    async def close(self):
        await self.cdp.close()  # leave owned Chrome open; never close personal Chrome

    # ---------- Gemini text transport (isolated from ChatGPT/Flow) ----------

    async def ensure_gemini_tab(self, job):
        """Own a dedicated Gemini tab; never adopt a tab the owner already had."""
        from .cdp_gemini import GEMINI_HOME, valid_gemini_url
        saved = self.journal.conversation(job, provider='gemini')
        targets = (await self.cdp.command('Target.getTargets')).get('targetInfos', [])
        target = None
        if saved:
            for t in targets:
                if t.get('targetId') == saved['target'] and t.get('type') == 'page' and valid_gemini_url(t.get('url', '')):
                    if t['url'].split('?')[0].rstrip('/') == saved['url'].split('?')[0].rstrip('/'):
                        target = t['targetId']
                        break
        else:
            for t in targets:
                if t.get('type') == 'page' and valid_gemini_url(t.get('url', '')) and self.journal.reusable_text_target(t.get('targetId'), t.get('url', ''), provider='gemini'):
                    target = t['targetId']
                    self.journal.set_conversation(job, t.get('url', GEMINI_HOME), target, provider='gemini')
                    break
        if not target:
            # One dedicated Gemini tab for the whole installation: reuse any owned
            # Gemini page even after Gemini navigated it to a new conversation URL.
            owned = set(self.journal.owned_targets('gemini'))
            for t in targets:
                if t.get('type') == 'page' and t.get('targetId') in owned and valid_gemini_url(t.get('url', '')):
                    target = t['targetId']
                    self.journal.set_conversation(job, t.get('url', GEMINI_HOME), target, provider='gemini')
                    break
        if not target:
            url = saved['url'] if saved else GEMINI_HOME
            created = await self.cdp.command('Target.createTarget', {'url': url})
            target = created['targetId']
            self.journal.own_target(target, 'gemini')
            self.journal.set_conversation(job, url, target, provider='gemini')
        return target

    async def gemini_page_ready(self, job, timeout=35):
        from .cdp_gemini import gemini_snapshot_expression, parse_snapshot
        target = await self.ensure_gemini_tab(job)
        session = await self.session(target)
        await self.cdp.command('Target.activateTarget', {'targetId': target})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression()))
            except (TimeoutError, CDPError):
                await asyncio.sleep(.4)
                continue
            if state.get('login') or state.get('challenge'):
                self.authenticated = False
                raise NeedsAuthentication('Sign in or finish verification in the dedicated Chrome Gemini tab')
            if state.get('composer'):
                return target, session, state
            await asyncio.sleep(.5)
        raise TimeoutError('Gemini composer not ready; no prompt sent')

    async def ask_gemini(self, job, prompt_text, timeout_seconds=300):
        """Visible-UI Gemini request: one send at most, receipt before input."""
        from .cdp_gemini import (gemini_snapshot_expression, gemini_composer_expression,
                                 gemini_send_button_expression, correlate_gemini, parse_snapshot,
                                 gemini_chat_count_expression, gemini_new_chat_expression,
                                 gemini_click_send_expression)
        async with self.job_lock:
            record = self.journal.prepare(job, prompt_text, provider='gemini')
            if record['state'] == 'completed':
                return record['response']
            identifier = record['id']
            marker = '[VideoStudio request ' + identifier + ']'
            await self.connect()
            if record['state'] == 'prepared':
                target, session, state = await self.gemini_page_ready(job)
                # A restored conversation must never receive our prompt: always open a new chat.
                fresh = await self.evaluate(session, gemini_new_chat_expression())
                if fresh:
                    for kind in ('mousePressed', 'mouseReleased'):
                        await self.cdp.command('Input.dispatchMouseEvent', {'type': kind, 'x': fresh['x'], 'y': fresh['y'], 'button': 'left', 'clickCount': 1}, session=session)
                    await asyncio.sleep(.8)
                    state = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression()))
                    if not state.get('composer'):
                        raise RuntimeError('Gemini composer unavailable after New chat; no prompt sent')
                wrapped = (marker + '\n' + prompt_text + '\nReturn exactly one JSON object with this envelope: '
                           + json.dumps({'request_id': identifier, 'result': {'your_response': 'replace with the requested JSON object'}}, ensure_ascii=False))
                if state.get('generating'):
                    raise RuntimeError('Gemini tab has an active response; no overwrite or send')
                draft = ' '.join((state.get('draft') or '').split())
                if draft and draft != ' '.join(wrapped.split()):
                    raise RuntimeError('Gemini tab has a different draft; no overwrite or send')
                if not draft:
                    point = await self.evaluate(session, gemini_composer_expression())
                    if not point:
                        raise RuntimeError('Gemini composer unavailable; no prompt sent')
                    for kind in ('mousePressed', 'mouseReleased'):
                        await self.cdp.command('Input.dispatchMouseEvent', {'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1}, session=session)
                    await asyncio.sleep(0.1)
                    await self.cdp.command('Input.insertText', {'text': wrapped}, session=session)
                button = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    button = await self.evaluate(session, gemini_send_button_expression())
                    if button:
                        break
                    await asyncio.sleep(.2)
                if not button:
                    raise RuntimeError('Gemini send control unavailable; draft preserved, no request sent')
                # Durable write BEFORE mouse input: any crash from here is recovery-only.
                self.journal.claim_send(identifier)
                final = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression(identifier)))
                final_draft = ' '.join((final.get('draft') or '').replace('\u00a0', ' ').split())
                if (not final or not final.get('composer') or final.get('login') or final.get('challenge')
                        or final.get('generating') or not final_draft
                        or (final_draft != ' '.join(wrapped.split()) and marker not in final_draft)):
                    raise IndeterminateRequest('Gemini composer/draft changed at send boundary; no dispatch, receipt retained')
                for kind in ('mousePressed', 'mouseReleased'):
                    await self.cdp.command('Input.dispatchMouseEvent', {'type': kind, 'x': button['x'], 'y': button['y'], 'button': 'left', 'clickCount': 1}, session=session)
                # Angular Material ignores a synthetic pointer in some builds; the element
                # click is required, and the composer clearing is the only proof of dispatch.
                await self.evaluate(session, gemini_click_send_expression())
                cleared = False
                verify_deadline = time.monotonic() + 6
                while time.monotonic() < verify_deadline:
                    check = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression()))
                    if check.get('composer') and not (check.get('draft') or '').strip():
                        cleared = True
                        break
                    await asyncio.sleep(.3)
                if not cleared:
                    raise IndeterminateRequest('Gemini composer did not clear after send; receipt retained, not resent')
            else:
                target = await self.ensure_gemini_tab(job)
                session = await self.session(target)
                await self.cdp.command('Target.activateTarget', {'targetId': target})
            # Already-attempted request: read only, never submit again.
            deadline = time.monotonic() + timeout_seconds
            previous = None
            while time.monotonic() < deadline:
                raw = await self.evaluate(session, gemini_snapshot_expression(identifier))
                state = parse_snapshot(raw)
                if state.get('login') or state.get('challenge'):
                    self.authenticated = False
                    raise NeedsAuthentication('Authentication required; pending Gemini request retained, not resent')
                try:
                    out = correlate_gemini(state, marker, identifier)
                except ValueError:
                    raise IndeterminateRequest('Ambiguous Gemini transcript for this request; not resent')
                if out:
                    text = out['text']
                    if text == previous:
                        try:
                            value = parse_reply(text)
                            self.journal.accept(identifier, value)
                            return value['result']
                        except (ValueError, json.JSONDecodeError):
                            pass
                    previous = text
                if state.get('generating'):
                    deadline = max(deadline, time.monotonic() + 90)
                await asyncio.sleep(1)
            raise IndeterminateRequest('Matching completed Gemini response unavailable; receipt retained, no automatic resubmission')



async def create_app(bridge=None):
    bridge = bridge or ChromeChatGPTBridge()

    @web.middleware
    async def local_only(request, handler):
        host = urlparse('//'+request.host).hostname
        if host not in ('127.0.0.1', 'localhost', '::1'):
            raise web.HTTPForbidden(text='Loopback Host required')
        if request.method != 'GET':
            origin = request.headers.get('Origin')
            if request.headers.get('X-VS-Client') != 'videostudio':
                raise web.HTTPForbidden(text='VideoStudio client header required')
            if origin and origin not in ('http://127.0.0.1:8877','http://localhost:8877','http://127.0.0.1:8879','http://localhost:8879'):
                raise web.HTTPForbidden(text='Cross-origin browser control denied')
            if request.content_type != 'application/json':
                raise web.HTTPUnsupportedMediaType()
        return await handler(request)

    async def status(request):
        return web.json_response(bridge.status())  # no network, startup or reconnect

    async def mutate(request):
        try:
            body = await request.json()
            if request.path.endswith('/start'):
                value = await bridge.open_login()
            elif request.path.endswith('/probe'):
                value = await bridge.probe_login()
            elif request.path == '/api/images/generate':
                value = {'ok':True, 'data':await bridge.images.generate(body.get('task_id'),body.get('prompt'))}
            elif request.path == '/api/flow/characters/create':
                value = {'ok':True, 'data':await bridge.flow_images.create_character(body.get('task_id'),body.get('job_id'),body.get('character_id'),body.get('name'),body.get('prompt'))}
            elif request.path == '/api/flow/images/generate':
                value = {'ok':True, 'data':await bridge.flow_images.generate(body.get('task_id'),body.get('job_id'),body.get('prompt'),character_mentions=body.get('character_mentions'))}
            elif request.path == '/api/flow/images/generate-batch':
                job_id,tasks=body.get('job_id'),body.get('tasks')
                timeout=body.get('timeout',1200);download_results=body.get('download_results',True)
                if not isinstance(job_id,str) or not isinstance(tasks,list) or not 1<=len(tasks)<=30:
                    raise web.HTTPBadRequest(text='Flow batch requires a job_id and 1..30 tasks')
                if not isinstance(timeout,(int,float)) or not 1<=timeout<=3600:
                    raise web.HTTPBadRequest(text='Flow batch timeout must be 1..3600 seconds')
                if type(download_results) is not bool:
                    raise web.HTTPBadRequest(text='download_results must be boolean')
                value={'ok':True,'data':await bridge.flow_images.generate_batch(job_id,tasks,timeout=float(timeout),download_results=download_results)}
            elif request.path == '/api/gemini':
                prompt, job = body.get('prompt'), body.get('job_id')
                if not isinstance(prompt, str) or not 1 <= len(prompt) <= 500000 or not isinstance(job, str) or not 1 <= len(job) <= 200:
                    raise web.HTTPBadRequest(text='Scoped job_id and prompt required')
                timeout = body.get('timeout_seconds', 300)
                if not isinstance(timeout, (int, float)) or not 30 <= timeout <= 1800:
                    raise web.HTTPBadRequest(text='timeout_seconds must be 30..1800')
                value = {'ok': True, 'data': await bridge.ask_gemini(job, prompt, timeout_seconds=float(timeout))}
                from .gemini_smoke import normalize as _normalize_gemini
                smoke = _normalize_gemini(value['data'])
                if job == '__acceptance__' and smoke == {'connection_test': 'videostudio', 'ok': True}:
                    from .gemini_smoke import record_gemini_smoke
                    record_gemini_smoke(smoke)
            else:
                prompt, job = body.get('prompt'), body.get('job_id')
                if not isinstance(prompt,str) or not 1 <= len(prompt) <= 500000 or not isinstance(job,str) or not 1 <= len(job) <= 200:
                    raise web.HTTPBadRequest(text='Scoped job_id and prompt required')
                value = {'ok':True, 'data':await bridge.ask_chatgpt(job, prompt)}
            bridge.last_error = None
            return web.json_response(value)
        except ImageRejected as e:
            bridge.last_error = 'image_rejected'
            return web.json_response({'ok':False,'code':'image_rejected','error':str(e)},status=422)
        except (NeedsAuthentication,ImageAuthentication) as e:
            bridge.last_error = 'authentication_required'
            return web.json_response({'ok':False,'code':'authentication_required','error':str(e)}, status=409)
        except IndeterminateRequest as e:
            bridge.last_error = 'delivery_indeterminate'
            return web.json_response({'ok':False,'code':'delivery_indeterminate','error':str(e)}, status=409)
        except FlowTaskError as e:
            bridge.last_error = e.code
            return web.json_response({'ok':False,'code':e.code,'error':str(e)}, status=409)
        except web.HTTPException:
            raise
        except Exception as e:
            bridge.last_error = type(e).__name__
            return web.json_response({'ok':False,'code':'browser_unavailable','error':str(e)}, status=503)

    async def cleanup(app):
        await bridge.close()

    app = web.Application(middlewares=[local_only], client_max_size=512*1024)
    app.router.add_get('/api/status',status)
    for route in ('/api/browser/start','/api/browser/probe','/api/chat','/api/gemini','/api/images/generate','/api/flow/characters/create','/api/flow/images/generate','/api/flow/images/generate-batch'):
        app.router.add_post(route,mutate)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='127.0.0.1', port=int(os.getenv('VS_CDP_PORT','8879')))

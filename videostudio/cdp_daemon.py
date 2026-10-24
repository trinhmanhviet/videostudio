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

    def on_event(self, event):
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
                if t.get('type') == 'page' and valid_chat_url(t.get('url','')):
                    target = t['targetId']
                    self.journal.set_conversation(job, t.get('url', 'https://chatgpt.com/'), target)
                    break
        if not target:
            url = saved['url'] if saved else 'https://chatgpt.com/'
            created = await self.cdp.command('Target.createTarget', {'url':url})
            target = created['targetId']
            self.journal.set_conversation(job, url, target)

        # Close all other page tabs to keep only one active tab and save RAM
        for t in targets:
            tid = t.get('targetId')
            if t.get('type') == 'page' and tid != target:
                try:
                    await self.cdp.command('Target.closeTarget', {'targetId': tid})
                    self.sessions.pop(tid, None)
                except BaseException:
                    pass

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

    async def ask_chatgpt(self, job, prompt_text, timeout_seconds=180):
        async with self.job_lock:
            record = self.journal.prepare(job, prompt_text)
            if record['state'] == 'completed':
                return record['response']
            identifier = record['id']
            marker = '[VideoStudio request '+identifier+']'
            await self.connect()
            target, session, state = await self.page_ready(job, marker)
            if record['state'] == 'prepared':
                wrapped = (marker+'\n'+prompt_text+'\nReturn exactly one JSON object with this envelope: '
                           +json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
                draft = state.get('draft','').strip()
                if state.get('generating'):
                    raise RuntimeError('Owned tab has active generation; no overwrite or send')
                if draft:
                    # Rich-text composers may render newline paragraphs as blank lines.
                    # Resume only our exact text/marker modulo whitespace, never another draft.
                    if ' '.join(draft.split()) != ' '.join(wrapped.split()):
                        raise RuntimeError('Owned tab has a different draft; no overwrite or send')
                else:
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
                previous = text
                await asyncio.sleep(1)
            raise IndeterminateRequest('Matching completed response unavailable; receipt retained, no automatic resubmission')

    async def close(self):
        await self.cdp.close()  # leave owned Chrome open; never close personal Chrome


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
            else:
                prompt, job = body.get('prompt'), body.get('job_id')
                if not isinstance(prompt,str) or not 1 <= len(prompt) <= 100000 or not isinstance(job,str) or not 1 <= len(job) <= 200:
                    raise web.HTTPBadRequest(text='Scoped job_id and prompt required')
                value = {'ok':True, 'data':await bridge.ask_chatgpt(job, prompt)}
            bridge.last_error = None
            return web.json_response(value)
        except NeedsAuthentication as e:
            bridge.last_error = 'authentication_required'
            return web.json_response({'ok':False,'code':'authentication_required','error':str(e)}, status=409)
        except IndeterminateRequest as e:
            bridge.last_error = 'delivery_indeterminate'
            return web.json_response({'ok':False,'code':'delivery_indeterminate','error':str(e)}, status=409)
        except web.HTTPException:
            raise
        except Exception as e:
            bridge.last_error = type(e).__name__
            return web.json_response({'ok':False,'code':'browser_unavailable','error':str(e)}, status=503)

    async def cleanup(app):
        await bridge.close()

    app = web.Application(middlewares=[local_only], client_max_size=512*1024)
    app.router.add_get('/api/status',status)
    for route in ('/api/browser/start','/api/browser/probe','/api/chat'):
        app.router.add_post(route,mutate)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='127.0.0.1', port=int(os.getenv('VS_CDP_PORT','8879')))

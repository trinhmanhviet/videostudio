"""Loopback-only browser owner. Start with python -m videostudio.cdp_daemon.
GET status is passive. Only explicit browser/start or a scoped job may connect.
"""
from .paths import DATA_ROOT
import asyncio
import contextlib
import re
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
from .cdp_images import ChatGPTImages, ImageAuthentication, ImageRejected, valid_attachments, SOCIAL_ROOT
from .cdp_social import PostReader
from .cdp_flow import FlowImages, FlowTaskError
from .cdp_meta import MetaImages, MetaQuotaExhausted


class NeedsAuthentication(RuntimeError):
    pass


# ChatGPT work runs in lanes, each with its own tab, so a story edit or a Facebook analysis never waits for a video.
# 'video' (the one video job at a time, plus its image/Flow/Gemini work) keeps the original job_lock; every story
# being edited is its own lane ('story-<source>'), Facebook analyses share 'social'. At most SIDE_LANES side lanes
# talk to ChatGPT at once. A lane's tab stays open while it is busy or was used in the last LANE_IDLE seconds.
SIDE_LANES = 3
LANE_IDLE = 20 * 60
FRESH_CHAT = 'https://chatgpt.com/'
COMPOSE_WAIT = 180
EMPTY_WAIT = 30          # a finished turn empty this long is reloaded once, then treated as an empty answer
EMPTY_RELOAD_PAUSE = 5   # longest wait for another tab to finish typing; then nothing is sent and the caller retries


def lane_log(message):
    """One line in data/logs/cdp.out.log (the daemon's stdout), so a slow lane shows where it waited."""
    print(time.strftime('%Y-%m-%d %H:%M:%S'), message, flush=True)


def lane_of(job):
    job = str(job or '')
    story = re.match(r'(story-[0-9a-f]+)-', job)
    if story:
        return story.group(1)
    if job.startswith('social-'):
        return 'social'
    return 'video'


class ChromeChatGPTBridge:
    def __init__(self, launcher=None, journal=None):
        self.launcher = launcher or DedicatedChrome()
        self.journal = journal or RequestJournal(DATA_ROOT/'cdp-requests.sqlite3')
        self.sessions = {}
        self.cdp = CDPConnection(on_event=self.on_event)
        self.connect_lock = asyncio.Lock()
        self.job_lock = asyncio.Lock()          # the 'video' lane (and the image/Flow/Meta/Gemini work it owns)
        self.lane_locks = {}                    # other lanes: one request at a time per lane
        self.side_lanes = asyncio.Semaphore(SIDE_LANES)
        # Typing a prompt and pressing Send happen in one tab at a time (a few seconds each): ChatGPT copies an
        # unsent draft into a chat opened meanwhile in another tab, which would mix two prompts.
        self.compose_lock = asyncio.Lock()
        self.lane_targets = {}                  # lane -> its ChatGPT tab
        self.lane_used = {}                     # lane -> last time it used its tab
        self.authenticated = False
        self.last_error = None
        self.reasoning_effort = None  # 'high' once High reasoning was verified
        self.images = ChatGPTImages(self, DATA_ROOT/'chatgpt-images')
        self.flow_images = FlowImages(self, DATA_ROOT/'flow-images')
        self.meta_images = MetaImages(self, DATA_ROOT/'meta-images')
        self.social = PostReader(self, SOCIAL_ROOT)

    def on_event(self, event):
        if getattr(self,'images',None):self.images.on_event(event)
        if getattr(self,'flow_images',None):self.flow_images.on_event(event)
        if event.get('method') in ('Target.targetDestroyed', 'Target.targetCrashed'):
            gone = event.get('params', {}).get('targetId')
            self.sessions.pop(gone, None)
            for lane, target in list(getattr(self, 'lane_targets', {}).items()):
                if target == gone:
                    self.lane_targets.pop(lane, None)

    def lock_for(self, lane):
        return self.job_lock if lane == 'video' else self.lane_locks.setdefault(lane, asyncio.Lock())

    def busy_targets(self):
        """Tabs another lane may still need: its lane is working now or used it recently."""
        now = time.time()
        return {target for lane, target in self.lane_targets.items()
                if self.lock_for(lane).locked() or now - self.lane_used.get(lane, 0) < LANE_IDLE}

    def status(self):
        connected = self.cdp.connected
        return {'ok':True, 'service':'videostudio-dedicated-cdp', 'connected':connected,
                'ready':connected and self.authenticated, 'mode':'headed', 'readiness_scope':'connector_only', 'production_ready':False,
                'authentication':'verified' if connected and self.authenticated else 'unverified',
                'last_error':self.last_error,'reasoning_effort':self.reasoning_effort}

    async def connect(self):
        async with self.connect_lock:
            if self.cdp.connected:
                return
            self.authenticated = False
            endpoint = await asyncio.to_thread(self.launcher.ensure_started)
            await self.cdp.connect(endpoint)
            try:
                await asyncio.to_thread(self.launcher.attest_endpoint,endpoint)
                await self.cdp.command('Target.setDiscoverTargets', {'discover':True})
            except BaseException:
                await self.cdp.close()
                raise

    async def ensure_tab(self, job):
        lane = lane_of(job)
        saved = self.journal.conversation(job)
        if saved and lane != 'video' and not self.journal.ever_sent(job):
            saved = None  # only the composer's page was noted; nothing to read back there, so a new chat is fine
        result = await self.cdp.command('Target.getTargets')
        targets = result.get('targetInfos', [])
        alive = {t.get('targetId') for t in targets if t.get('type') == 'page'}
        others = {t for l, t in self.lane_targets.items() if l != lane}
        target = None
        if saved:
            for t in targets:
                if t.get('targetId') == saved['target'] and t.get('type') == 'page' and valid_chat_url(t.get('url','')):
                    # Never commandeer a different conversation the user navigated to.
                    if t['url'].split('?')[0].rstrip('/') == saved['url'].split('?')[0].rstrip('/'):
                        target = t['targetId']
                        break
        elif lane != 'video':
            # A story chapter or a Facebook analysis is a self-contained prompt: it starts a NEW chat in its lane's tab,
            # so one long conversation never slows ChatGPT down or lets earlier chapters colour the next one.
            # A tab still holding a sent request with no known conversation stays put (its reply is only there):
            # the lane then gets a new tab instead.
            mine = self.lane_targets.get(lane)
            urls = {t.get('targetId'): t.get('url', '') for t in targets}
            if mine in alive and mine not in self.journal.pinned_targets() and valid_chat_url(urls.get(mine, '')):
                session = await self.session(mine)
                if urls[mine].split('?')[0].rstrip('/') != FRESH_CHAT.rstrip('/'):
                    await self.cdp.command('Page.navigate', {'url': FRESH_CHAT}, session=session)
                    await self.settle_new_chat(session)
                target = mine
                self.journal.set_conversation(job, FRESH_CHAT, target)
        else:
            # Reuse this lane's ChatGPT tab (or, for the video lane, any reusable one no other lane holds).
            mine = self.lane_targets.get(lane)
            for t in targets:
                ident = t.get('targetId')
                if ident in others or (mine and ident != mine) or ident not in alive:
                    continue
                if valid_chat_url(t.get('url','')) and self.journal.reusable_text_target(ident, t.get('url','')):
                    target = ident
                    self.journal.set_conversation(job, t.get('url', 'https://chatgpt.com/'), target)
                    break
        if not target:
            url = saved['url'] if saved else FRESH_CHAT
            # Side lanes open in the background: they never take the window from the video lane or the user.
            created = await self.cdp.command('Target.createTarget', {'url':url, 'background': lane != 'video'})
            target = created['targetId']
            self.journal.own_target(target,'text')
            self.journal.set_conversation(job, url, target)
        self.lane_targets[lane] = target
        self.lane_used[lane] = time.time()
        await self.close_other_chat_tabs(targets, {target} | self.busy_targets())
        return target

    async def settle_new_chat(self, session, timeout=20):
        """After Page.navigate: wait until the NEW page is there (root address, loaded, empty composer), so the
        previous conversation's page is never read or typed into while it is being replaced."""
        deadline = time.monotonic() + timeout
        probe = r'''(()=>{const c=document.querySelector('#prompt-textarea,[contenteditable="true"][role="textbox"]');
          return {path:location.pathname,ready:document.readyState,composer:!!c,draft:c?(c.innerText||'').trim().length:-1}})()'''
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            try:
                state = await self.evaluate(session, probe)
            except (RuntimeError, TimeoutError, CDPError):
                continue
            if isinstance(state, dict) and state.get('path') == '/' and state.get('ready') == 'complete' and state.get('composer'):
                await asyncio.sleep(0.8)  # the composer's controls (model menu) hydrate just after it appears
                return True
        return False

    async def close_other_chat_tabs(self, targets, keep):
        """Close ChatGPT tabs nobody needs (owner request 2026-11-08: extra tabs cost RAM). keep: the tabs of lanes
        that are working or were used recently (each lane has one). Every conversation URL is journaled, so a closed
        conversation reopens from its URL when needed. Tabs holding a sent request whose URL is still unknown stay."""
        keep = {keep} if isinstance(keep, str) else set(keep)
        pinned = self.journal.pinned_targets()
        for t in targets:
            ident = t.get('targetId')
            if t.get('type') != 'page' or ident in keep or ident in pinned or not valid_chat_url(t.get('url', '')):
                continue
            try:
                await self.cdp.command('Target.closeTarget', {'targetId': ident})
            except CDPError:
                pass
            self.sessions.pop(ident, None)

    def stale_own_draft(self, draft):
        """ChatGPT restores an unsent composer draft into new chats. A draft that is one of our own
        prompts which already has its answer is a stale copy and may be cleared; anything else stays."""
        match = re.match(r'\[VideoStudio (?:image )?request ([0-9a-f]{16,128})\]', (draft or '').strip())
        if not match:
            return False
        try:
            record = self.journal.get(match.group(1))
        except KeyError:
            return False
        return record['state'] == 'completed'

    async def clear_composer(self, session):
        focused = await self.evaluate(session, "(()=>{const e=[...document.querySelectorAll('#prompt-textarea,[contenteditable=\"true\"][role=\"textbox\"]')].find(n=>n.getBoundingClientRect().width>0);if(!e)return false;e.focus();return true})()")
        if not focused:
            raise RuntimeError('Composer unavailable; stale draft not cleared')
        for kind in ('keyDown', 'keyUp'):
            await self.cdp.command('Input.dispatchKeyEvent', {'type': kind, 'key': 'a', 'code': 'KeyA', 'modifiers': 2, 'windowsVirtualKeyCode': 65}, session=session)
        for kind in ('keyDown', 'keyUp'):
            await self.cdp.command('Input.dispatchKeyEvent', {'type': kind, 'key': 'Backspace', 'code': 'Backspace', 'windowsVirtualKeyCode': 8}, session=session)
        await asyncio.sleep(.3)

    async def session(self, target):
        if target not in self.sessions:
            result = await self.cdp.command('Target.attachToTarget', {'targetId':target, 'flatten':True})
            self.sessions[target] = result['sessionId']
            # A tab behind another tab must keep rendering ChatGPT's answer: the page is told it has focus and is
            # active (not frozen). Best effort; older Chrome builds may not know one of these commands.
            for method, params in (('Emulation.setFocusEmulationEnabled', {'enabled': True}), ('Page.setWebLifecycleState', {'state': 'active'})):
                try:
                    await self.cdp.command(method, params, session=result['sessionId'])
                except Exception:
                    pass
        return self.sessions[target]

    async def evaluate(self, session, expression):
        result = await self.cdp.command('Runtime.evaluate', {'expression':expression, 'returnByValue':True}, session=session)
        if result.get('exceptionDetails'):
            raise RuntimeError('ChatGPT DOM evaluation failed')
        return result.get('result', {}).get('value')

    async def page_ready(self, job, marker='', timeout=60):
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
                    if self.stale_own_draft(state['draft']):
                        await self.clear_composer(session)
                        continue
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
        # The composer appears before its model control does (fresh or just reloaded tab): wait for the control.
        appear=time.monotonic()+10
        while not current.get('high') and not isinstance(current.get('button'),dict) and time.monotonic()<appear:
            await asyncio.sleep(.5)
            current=await state()
        if current.get('high'):
            self.reasoning_effort='high';return True
        slider=None
        # A tab that was opened behind another one may not draw the model menu at the first click: close the menu,
        # bring the tab forward and click once more (still inside the compose turn, so no other tab is typing).
        for attempt in range(2):
            button=current.get('button')
            if not isinstance(button,dict):
                await self._close_menu(session)
                raise RuntimeError('ChatGPT High reasoning control unavailable; no request sent')
            for kind in ('mousePressed','mouseReleased'):
                await self.cdp.command('Input.dispatchMouseEvent',{'type':kind,'x':button['x'],'y':button['y'],'button':'left','clickCount':1},session=session)
            deadline=time.monotonic()+(3 if attempt==0 else 6)
            while time.monotonic()<deadline:
                current=await state();slider=current.get('slider')
                if isinstance(slider,dict) and isinstance(slider.get('track'),dict) and slider.get('max',0)>0:break
                slider=None
                await asyncio.sleep(.1)
            if slider or attempt:break
            await self._close_menu(session)
            try:await self.cdp.command('Page.bringToFront',{},session=session)
            except Exception:pass
            await asyncio.sleep(1)
            current=await state()
            if current.get('high'):
                self.reasoning_effort='high';return True
        if not isinstance(slider,dict):
            await self._close_menu(session)
            raise RuntimeError('ChatGPT reasoning slider unavailable; no request sent')
        # The slider ignores a click on its track (2026-11); step it with the arrow keys it announces.
        await self.evaluate(session,"document.querySelector('[role=\"slider\"][aria-valuemax]')?.focus()")
        steps=max(1,int(slider.get('max') or 0)-int(slider.get('value') or 0))
        for _ in range(steps):
            for kind in ('keyDown','keyUp'):
                await self.cdp.command('Input.dispatchKeyEvent',{'type':kind,'key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39},session=session)
            await asyncio.sleep(.15)
        verified=await state()
        if not verified.get('high'):
            raise RuntimeError('ChatGPT High reasoning effort could not be verified; no request sent')
        await self._close_menu(session)
        self.reasoning_effort='high';return True

    async def _close_menu(self, session):
        for kind in ('keyDown','keyUp'):
            await self.cdp.command('Input.dispatchKeyEvent',{'type':kind,'key':'Escape','code':'Escape','windowsVirtualKeyCode':27},session=session)
        await asyncio.sleep(.2)

    async def ask_chatgpt(self, job, prompt_text, timeout_seconds=300, attachments=None):
        # attachments: 1-4 pictures from the tool's own folders, put into the composer before the prompt is typed
        files = valid_attachments(attachments)
        lane = lane_of(job)
        side = contextlib.nullcontext() if lane == 'video' else self.side_lanes
        asked = time.monotonic()
        if self.lock_for(lane).locked():
            lane_log(f'[{lane}] {job}: waiting for the previous request of this lane')
        async with self.lock_for(lane), side:
            self.lane_used[lane] = time.time()
            waited = time.monotonic() - asked
            lane_log(f'[{lane}] {job}: started' + (f' after waiting {waited:.0f}s' if waited >= 1 else ''))
            try:
                answer = await self._ask_in_lane(job, prompt_text, timeout_seconds, files)
                lane_log(f'[{lane}] {job}: answered in {time.monotonic() - asked:.0f}s')
                return answer
            except BaseException as error:
                lane_log(f'[{lane}] {job}: {type(error).__name__}: {str(error)[:200]}')
                raise
            finally:
                self.lane_used[lane] = time.time()

    async def _send_prompt(self, job, identifier, marker, prompt_text, files):
        """Type the prompt into this job's tab and press Send (under compose_lock: one tab at a time)."""
        target, session, state = await self.page_ready(job, marker)
        wrapped = (marker+'\n'+prompt_text+'\nReturn exactly one JSON object with this envelope: '
                   +json.dumps({'request_id':identifier,'result':{'your_response':'replace with the requested JSON object'}},ensure_ascii=False))
        draft = state.get('draft','').strip()
        if state.get('generating'):
            raise RuntimeError('Owned tab has active generation; no overwrite or send')
        if draft and ' '.join(draft.split()) != ' '.join(wrapped.split()) and self.stale_own_draft(draft):
            await self.clear_composer(session)
            draft = (await self.evaluate(session, snapshot_expression(marker)) or {}).get('draft','').strip()
        if draft and ' '.join(draft.split()) != ' '.join(wrapped.split()):
            raise RuntimeError('Owned tab has a different draft; no overwrite or send')
        await self.ensure_high_effort(session)
        if files and not draft:
            await self.images._attach(session, files)
        if not draft:
            focused = await self.evaluate(session, composer_expression())
            if not focused:
                raise RuntimeError('Composer unavailable; no prompt sent')
            if isinstance(focused, dict) and 'x' in focused and 'y' in focused:
                for kind in ('mousePressed', 'mouseReleased'):
                    await self.cdp.command('Input.dispatchMouseEvent', {'type':kind, 'x':focused['x'], 'y':focused['y'], 'button':'left', 'clickCount':1}, session=session)
                await asyncio.sleep(0.1)
            # A whole chapter (~9,000 characters) can take longer than the usual 10 s on a busy page.
            await self.cdp.command('Input.insertText', {'text':wrapped}, session=session, timeout=60)
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
        return target, session

    async def _ask_in_lane(self, job, prompt_text, timeout_seconds, files):
        record = self.journal.prepare(job, prompt_text)
        if record['state'] == 'completed':
            return record['response']
        identifier = record['id']
        marker = '[VideoStudio request '+identifier+']'
        await self.connect()
        if record['state'] == 'prepared':
            waiting = time.monotonic()
            try:
                await asyncio.wait_for(self.compose_lock.acquire(), COMPOSE_WAIT)
            except asyncio.TimeoutError:
                raise RuntimeError(f'Another ChatGPT tab kept the composer turn over {COMPOSE_WAIT}s; nothing sent, ask again') from None
            try:
                if time.monotonic() - waiting >= 1:
                    lane_log(f'[{lane_of(job)}] {job}: typing turn after {time.monotonic() - waiting:.0f}s')
                target, session = await self._send_prompt(job, identifier, marker, prompt_text, files)
                lane_log(f'[{lane_of(job)}] {job}: sent')
            finally:
                self.compose_lock.release()
        else:
            target = await self.ensure_tab(job)
            session = await self.session(target)
            await self.cdp.command('Target.activateTarget', {'targetId':target})
        # Previously attempted request: only read its conversation, never send again.
        deadline = time.monotonic()+timeout_seconds
        previous = None
        empty_since, reloaded = None, False
        while time.monotonic() < deadline:
            state = correlate_turns(await self.evaluate(session, snapshot_expression(marker)), marker)
            # ChatGPT sometimes finishes a turn with NO answer at all. After 30 s of a finished, empty turn the page is
            # reloaded once (the answer may just not have been drawn); still empty, a story chapter or a Facebook
            # analysis is asked again in a new chat (harmless), while a video request is never resent automatically.
            if state and state.get('matched') and not state.get('generating') and not (state.get('text') or '').strip():
                empty_since = empty_since or time.monotonic()
                if time.monotonic() - empty_since > EMPTY_WAIT:
                    if not reloaded:
                        lane_log(f'[{lane_of(job)}] {job}: the finished answer is empty; reloading the page once')
                        await self.cdp.command('Page.reload', {}, session=session)
                        reloaded, empty_since = True, None
                        await asyncio.sleep(EMPTY_RELOAD_PAUSE)
                        continue
                    if lane_of(job) == 'video':
                        raise IndeterminateRequest('ChatGPT finished with an empty answer; video requests are never resent automatically')
                    self.journal.forget_empty(identifier, job)
                    raise RuntimeError('ChatGPT finished with an empty answer; nothing to read, it will be asked again in a new chat')
            else:
                empty_since = None
            if state and (state.get('login') or state.get('challenge')):
                self.authenticated = False
                raise NeedsAuthentication('Authentication required; pending request retained, not resent')
            if state and valid_chat_url(state.get('url','')):
                self.journal.set_conversation(job, state['url'], target)
            text = (state or {}).get('text','')
            if state and state.get('matched') and not state.get('generating') and text and text == previous:
                try:
                    value = None
                    try:
                        value = parse_reply(text)
                    except Exception:
                        cleaned = text.strip()
                        if cleaned.startswith('`json\n') and cleaned.endswith('\n`'): cleaned = cleaned[8:-4].strip()
                        elif cleaned.startswith('`\n') and cleaned.endswith('\n`'): cleaned = cleaned[4:-4].strip()
                        dec = json.JSONDecoder()
                        raw_obj, _ = dec.raw_decode(cleaned)
                        if isinstance(raw_obj, dict):
                            value = raw_obj
                    if value:
                        self.journal.accept(identifier, value)
                        return self.journal.get(identifier)['response']
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
                                 gemini_click_send_expression, gemini_click_new_chat_expression,
                                 new_chat_ready, canonical_gemini_text)
        async with self.job_lock:
            record = self.journal.prepare(job, prompt_text, provider='gemini')
            if record['state'] == 'completed':
                return record['response']
            identifier = record['id']
            marker = '[VideoStudio request ' + identifier + ']'
            await self.connect()
            if record['state'] == 'prepared':
                target, session, state = await self.gemini_page_ready(job)
                # Each request uses a fresh Gemini conversation in the same owned tab.
                clicked = await self.evaluate(session, gemini_click_new_chat_expression())
                if clicked:
                    stable = 0
                    for _ in range(160):
                        await asyncio.sleep(.25)
                        try:
                            state = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression()))
                        except (TimeoutError, CDPError):
                            stable = 0
                            continue
                        if new_chat_ready(state):
                            stable += 1
                            if stable >= 3:
                                break
                        else:
                            stable = 0
                    if stable < 3:
                        raise RuntimeError('Gemini New chat did not reach a stable blank composer; no prompt sent')
                elif not new_chat_ready(state):
                    raise RuntimeError('Exact Gemini New chat control unavailable; refusing to append to an old conversation')
                wrapped = (marker + '\n' + prompt_text + '\nReturn exactly one JSON object with this envelope: '
                           + json.dumps({'request_id': identifier, 'result': {'your_response': 'replace with the requested JSON object'}}, ensure_ascii=False))
                if state.get('generating'):
                    raise RuntimeError('Gemini tab has an active response; no overwrite or send')
                draft = canonical_gemini_text(state.get('draft') or '')
                if draft and draft != wrapped:
                    raise RuntimeError('Gemini tab has a different draft; no overwrite or send')
                if not draft:
                    await self.cdp.command('Target.activateTarget', {'targetId': target})
                    point = await self.evaluate(session, gemini_composer_expression())
                    if not point:
                        raise RuntimeError('Gemini composer unavailable; no prompt sent')
                    for kind in ('mousePressed', 'mouseReleased'):
                        await self.cdp.command('Input.dispatchMouseEvent', {'type': kind, 'x': point['x'], 'y': point['y'], 'button': 'left', 'clickCount': 1}, session=session)
                    await asyncio.sleep(0.15)
                    # execCommand goes through the editor's own input pipeline, so
                    # Angular enables its Send control; Input.insertText often leaves
                    # the model stale (text visible, no send arrow).
                    inserted = await self.evaluate(session, "(()=>{const b=document.querySelector('rich-textarea [contenteditable=\"true\"],div[contenteditable=\"true\"][role=\"textbox\"]');if(!b)return 'NO_COMPOSER';b.focus();return document.execCommand('insertText',false,%s)?'INSERTED':'REFUSED'})()" % json.dumps(wrapped))
                    typed = False
                    for _ in range(20):
                        await asyncio.sleep(.2)
                        try:
                            probe = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression()))
                        except (TimeoutError, CDPError):
                            continue
                        if canonical_gemini_text(probe.get('draft') or '') == wrapped:
                            typed = True
                            break
                    if inserted != 'INSERTED' or not typed:
                        # Never append a second full prompt after partial insertion.
                        # The existing draft remains visible for inspection/recovery.
                        raise RuntimeError('Gemini composer did not accept the exact prompt; nothing sent')
                button = None
                deadline = time.monotonic() + 8
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
                final_draft = canonical_gemini_text(final.get('draft') or '') if final else ''
                if (not final or not final.get('composer') or final.get('login') or final.get('challenge')
                        or final.get('generating') or final_draft != wrapped):
                    raise IndeterminateRequest('Gemini composer/draft changed at send boundary; no dispatch, receipt retained')
                # Dispatch exactly one Send action. The visible user-turn marker, not
                # composer clearing, is the delivery receipt: Gemini may leave a
                # trailing newline in the editor even after accepting the message.
                await self.evaluate(session, gemini_click_send_expression())
                sent = False
                verify_deadline = time.monotonic() + 12
                while time.monotonic() < verify_deadline:
                    check = parse_snapshot(await self.evaluate(session, gemini_snapshot_expression(identifier)))
                    if any(t.get('role') == 'user' and marker in (t.get('text') or '') for t in check.get('turns', [])):
                        sent = True
                        break
                    await asyncio.sleep(.3)
                if not sent:
                    raise IndeterminateRequest('Gemini exact user-turn receipt unavailable after single Send action; request retained, not resent')
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
            if request.path=='/api/flow/account/reconcile':
                job_id=body.get('job_id')
                try:uuid.UUID(job_id)
                except (ValueError,TypeError,AttributeError):raise web.HTTPBadRequest(text='Valid job_id required')
                from .core import Store
                from .flow_account import FlowAccountService
                db=Path(os.getenv('VS_DATABASE',str(DATA_ROOT/'jobs.sqlite3')))
                from .output_settings import configured_root
                store=Store(db,configured_root());service=FlowAccountService(store,flow_root=bridge.flow_images.root)
                job=store.get(job_id)
                with store.db() as c:
                    phase=service._read(c,job_id)[0]
                    if c.execute('select cancel from jobs where id=?',(job_id,)).fetchone()['cancel'] or job['state']!='awaiting_flow_account' or phase!='reconciling':
                        raise web.HTTPConflict(text='Video is no longer safely paused for Flow recovery')
                async with bridge.flow_images._flow_batch_lock:
                    async with bridge.job_lock:
                        job=store.get(job_id)
                        with store.db() as c:
                            if c.execute('select cancel from jobs where id=?',(job_id,)).fetchone()['cancel'] or service._read(c,job_id)[0]!='reconciling':
                                raise web.HTTPConflict(text='Flow recovery state changed before the browser lock was acquired')
                        if body.get('quiesce_only') is True:return web.json_response({'ok':True,'data':{'quiesced':True}})
                        tasks=service._scene_tasks(job);service._preserve_local(job,tasks)
                        missing=[task for task in tasks if not task['cached']]
                        if missing:
                            await asyncio.wait_for(service._reconcile_browser_async(job,missing,bridge=bridge),timeout=540)
                        return web.json_response({'ok':True,'data':{'quiesced':True,'preserved':sum(task['cached'] for task in tasks)}})
            if request.path.endswith('/start'):
                value = await bridge.open_login()
            elif request.path.endswith('/probe'):
                value = await bridge.probe_login()
            elif request.path == '/api/images/generate':
                options = {}
                if body.get('attachments') is not None:options['attachments'] = body.get('attachments')
                if body.get('layout') is not None:options['layout'] = body.get('layout')
                if body.get('timeout') is not None:
                    if not isinstance(body['timeout'], (int, float)) or not 60 <= body['timeout'] <= 900:raise web.HTTPBadRequest(text='timeout must be 60..900 seconds')
                    options['timeout'] = float(body['timeout'])
                value = {'ok':True, 'data':await bridge.images.generate(body.get('task_id'),body.get('prompt'),**options)}
            elif request.path == '/api/social/fetch-images':
                value = {'ok':True, 'data':await bridge.social.fetch_images(body.get('task_id'), body.get('urls') or [])}
            elif request.path == '/api/social/read':
                value = {'ok':True, 'data':await bridge.social.read(body.get('task_id'), body.get('url'))}
            elif request.path == '/api/meta/images/generate':
                value = {'ok':True, 'data':await bridge.meta_images.generate(body.get('task_id'),body.get('prompt'))}
            elif request.path == '/api/meta/images/batch':
                value = {'ok':True, 'data':await bridge.meta_images.generate_batch(body.get('batch_id'),body.get('prompt'),body.get('count'),body.get('references') or [])}
            elif request.path == '/api/flow/characters/create':
                resume=body.get('resume_only',False)
                if type(resume) is not bool:raise web.HTTPBadRequest(text='resume_only must be boolean')
                options={'resume_only':True} if resume else {}
                value = {'ok':True, 'data':await bridge.flow_images.create_character(body.get('task_id'),body.get('job_id'),body.get('character_id'),body.get('name'),body.get('prompt'),**options)}
            elif request.path == '/api/flow/characters/reference':
                value={'ok':True,'data':await bridge.flow_images.download_character_reference(body.get('task_id'),body.get('job_id'),body.get('character_id'))}
            elif request.path == '/api/flow/images/generate':
                options = {}
                if body.get('timeout') is not None:
                    if not isinstance(body['timeout'], (int, float)) or isinstance(body['timeout'], bool) or not 30 <= body['timeout'] <= 900:raise web.HTTPBadRequest(text='timeout must be 30..900 seconds')
                    options['timeout'] = float(body['timeout'])
                value = {'ok':True, 'data':await bridge.flow_images.generate(body.get('task_id'),body.get('job_id'),body.get('prompt'),character_mentions=body.get('character_mentions'),**options)}
            elif request.path == '/api/flow/images/generate-batch':
                job_id,tasks=body.get('job_id'),body.get('tasks')
                timeout=body.get('timeout',1200);download_results=body.get('download_results',True)
                reopen_project=body.get('reopen_project',False)
                if not isinstance(job_id,str) or not isinstance(tasks,list) or not 1<=len(tasks)<=30:
                    raise web.HTTPBadRequest(text='Flow batch requires a job_id and 1..30 tasks')
                if not isinstance(timeout,(int,float)) or not 1<=timeout<=3600:
                    raise web.HTTPBadRequest(text='Flow batch timeout must be 1..3600 seconds')
                if type(download_results) is not bool:
                    raise web.HTTPBadRequest(text='download_results must be boolean')
                if type(reopen_project) is not bool:raise web.HTTPBadRequest(text='reopen_project must be boolean')
                value={'ok':True,'data':await bridge.flow_images.generate_batch(job_id,tasks,timeout=float(timeout),download_results=download_results,reopen_project=reopen_project)}
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
                # Long answers (a whole edited novel chapter) may need more than the default five minutes.
                timeout = body.get('timeout_seconds', 300)
                if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 30 <= timeout <= 1800:
                    raise web.HTTPBadRequest(text='timeout_seconds must be 30..1800')
                options = {'attachments': body['attachments']} if body.get('attachments') is not None else {}
                value = {'ok':True, 'data':await bridge.ask_chatgpt(job, prompt, timeout_seconds=float(timeout), **options)}
            bridge.last_error = None
            return web.json_response(value)
        except MetaQuotaExhausted as e:
            bridge.last_error = 'quota_exhausted'
            return web.json_response({'ok':False,'code':'quota_exhausted','error':str(e)},status=429)
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
    for route in ('/api/browser/start','/api/browser/probe','/api/chat','/api/social/read','/api/social/fetch-images','/api/gemini','/api/images/generate','/api/meta/images/generate','/api/meta/images/batch','/api/flow/characters/create','/api/flow/characters/reference','/api/flow/images/generate','/api/flow/images/generate-batch','/api/flow/account/reconcile'):
        app.router.add_post(route,mutate)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    web.run_app(create_app(), host='127.0.0.1', port=int(os.getenv('VS_CDP_PORT','8879')))

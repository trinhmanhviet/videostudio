"""Meta AI (meta.ai) scene images in the dedicated Chrome over CDP.

Same steps as github.com/mir-ashiq/metaai-api (BrowserBackend.send_message): Instant mode, type the
prompt into the composer, press Enter, wait for fbcdn image URLs, download them. It runs on the
already signed-in meta.ai tab of our dedicated Chrome, so no second browser and no copied cookies.
Owner rule (2026-11-08): at most one prompt sent every 20 seconds.
"""
import asyncio, json, time, uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from .core import digest
from .cdp_requests import IndeterminateRequest
from .cdp_images import ImageAuthentication, ImageRejected


class MetaQuotaExhausted(RuntimeError):
    """The account is out of Meta image credits for now (seen: "You reached your limit ... wait until 11:50 PM")."""

META_HOME = 'https://meta.ai/'
SEND_INTERVAL = 20.0
# Pictures arrive in 20-50 s; nothing after this long means Meta answered in words (declined).
NO_PICTURE_AFTER = 150
# Meta writes this instead of a picture when the account's image credits run out.
QUOTA_JS = ("(()=>{const t=(document.querySelector('main')||document.body).innerText.slice(-3000);"
            r"const m=t.match(/You reached your limit[^\n]*|image generation quota is exhausted[^\n]*|Upgrade to create more images/i);"
            "return m?m[0].slice(0,200):''})()")
COMPOSER = '[data-testid="composer-input"][contenteditable="true"]'
# Generated images carry alt "gallery/image_<date>.webp"; a covered window may not finish loading them,
# so take the URL (repo: is_media_url) instead of waiting for the picture to paint.
IMAGES_JS = ("JSON.stringify([...document.querySelectorAll('img')].filter(i=>(i.alt||'').startsWith('gallery/')||i.naturalWidth>=900)"
             ".map(i=>[i.currentSrc||i.getAttribute('src')||'',i.naturalWidth,i.naturalHeight]))")
BROKEN_JS = "[...document.querySelectorAll('img')].some(i=>(i.alt||'').startsWith('gallery/')&&!i.getAttribute('src'))"
MEDIA_DOMAINS = ('scontent', 'metaaiusercontent')
STATIC_PATTERNS = ('rsrc.php', 'static.xx.fbcdn', '/rsrc/', '/y_/')
STATE_JS = ("JSON.stringify({composer:!!document.querySelector('%s'),url:location.href,"
            "login:[...document.querySelectorAll('a,button')].some(b=>/^(log in|sign in|đăng nhập)$/i.test((b.innerText||'').trim())),"
            "mode:([...document.querySelectorAll('button')].find(b=>['Instant','Thinking'].includes((b.innerText||'').trim()))||{}).innerText||'',"
            "reply:(()=>{const m=document.querySelectorAll('[class*=\"assistant-message\"]');return m.length?(m[m.length-1].innerText||'').trim().slice(0,600):''})()})"
            % COMPOSER)


def valid_meta_url(url):
    host = urlparse(url or '').hostname or ''
    return host in ('meta.ai', 'www.meta.ai')


def valid_image_url(url):
    p = urlparse(url or '')
    if p.scheme != 'https' or not (p.hostname or '').endswith('.fbcdn.net'):
        return False
    return not any(s in url for s in STATIC_PATTERNS) and any(d in url for d in MEDIA_DOMAINS)


def digest_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def conversation_id(url):
    path = urlparse(url or '').path
    return path.split('/prompt/', 1)[1].strip('/') if '/prompt/' in path else ''


class MetaImages:
    def __init__(self, bridge, root, interval=SEND_INTERVAL):
        self.bridge = bridge
        self.root = Path(root)
        self.interval = interval
        self.lock = asyncio.Lock()
        self.stamp = self.root / 'last-send.txt'

    def _paths(self, task_id):
        return self.root / (task_id + '.png'), self.root / (task_id + '.json'), self.root / (task_id + '.sent.json')

    def _done(self, task_id):
        out, receipt, _ = self._paths(task_id)
        if out.is_file() and receipt.is_file():
            data = json.loads(receipt.read_text(encoding='utf8'))
            if data.get('sha256') == digest(out):
                return data
        return None

    async def _wait_turn(self):
        """Keep at least `interval` seconds between two sent prompts, across daemon restarts."""
        try:
            last = float(self.stamp.read_text().strip())
        except (OSError, ValueError):
            last = 0.0
        delay = self.interval - (time.time() - last)
        if delay > 0:
            await asyncio.sleep(min(delay, self.interval))

    async def _tab(self):
        targets = (await self.bridge.cdp.command('Target.getTargets')).get('targetInfos', [])
        for t in targets:
            if t.get('type') == 'page' and valid_meta_url(t.get('url', '')):
                return t['targetId']
        return (await self.bridge.cdp.command('Target.createTarget', {'url': META_HOME}))['targetId']

    async def _tick(self, session):
        """Windows marks a covered Chrome window hidden and meta.ai then stops rendering (no composer,
        no image). A tiny screenshot forces one frame, so every poll renders the page."""
        await self.bridge.cdp.command('Page.captureScreenshot', {'format': 'jpeg', 'quality': 5,
                                      'clip': {'x': 0, 'y': 0, 'width': 8, 'height': 8, 'scale': 1}}, session=session, timeout=20)

    async def _state(self, session):
        await self._tick(session)
        return json.loads(await self.bridge.evaluate(session, STATE_JS) or '{}')

    async def _images(self, session):
        await self._tick(session)
        return [x for x in json.loads(await self.bridge.evaluate(session, IMAGES_JS) or '[]') if valid_image_url(x[0])]

    async def _open(self, session, url, timeout=40):
        await self.bridge.cdp.command('Page.navigate', {'url': url}, session=session)
        end = time.time() + timeout
        while time.time() < end:
            await asyncio.sleep(1)
            state = await self._state(session)
            if state.get('composer'):
                return state
            if state.get('login'):
                raise ImageAuthentication('Meta AI chưa đăng nhập trong Chrome riêng')
        raise RuntimeError('Meta AI page did not become ready')

    async def _instant(self, session):
        """repo: _switch_mode('Instant') — open the mode menu and pick Instant."""
        await self.bridge.evaluate(session, "[...document.querySelectorAll('button')].find(b=>['Instant','Thinking'].includes((b.innerText||'').trim()))?.click()")
        await asyncio.sleep(1)
        await self.bridge.evaluate(session, "[...document.querySelectorAll('[role=menuitemcheckbox],[role=menuitemradio],[role=menuitem]')].find(e=>(e.textContent||'').includes('Instant'))?.click()")
        await asyncio.sleep(1)
        await self.bridge.cdp.command('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27}, session=session)
        await self.bridge.cdp.command('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27}, session=session)

    async def _wait_image(self, session, before, timeout):
        """repo: _wait_for_response — first fbcdn image wins; a stable text-only reply means refused."""
        start = time.time()
        end = start + timeout
        last, stable, reloaded = '', 0, False
        while time.time() < end:
            await asyncio.sleep(2)
            fresh = [x for x in await self._images(session) if x[0] not in before]
            if not fresh and time.time() - start > 8:
                await self._raise_if_quota(session)
            if not fresh and time.time() - start > NO_PICTURE_AFTER:
                raise ImageRejected('Meta AI không trả ảnh cho prompt này')
            if fresh:
                await asyncio.sleep(3)
                fresh = [x for x in await self._images(session) if x[0] not in before] or fresh
                return fresh, await self._state(session)
            state = await self._state(session)
            if not reloaded and conversation_id(state.get('url', '')) and await self.bridge.evaluate(session, BROKEN_JS):
                reloaded = True  # image element failed while the window was covered: reload the conversation once
                await self._open(session, state['url'])
                continue
            reply = state.get('reply', '')
            if reply and reply == last:
                stable += 1
                if stable >= 5:
                    raise ImageRejected('Meta AI trả lời chữ, không tạo ảnh: ' + reply[:300])
            else:
                last, stable = reply, 0
        return [], await self._state(session)

    async def _save(self, task_id, image_url, request_id):
        out, receipt, sent = self._paths(task_id)
        r = await asyncio.to_thread(httpx.get, image_url, timeout=60, follow_redirects=True)
        r.raise_for_status()
        if not 1000 < len(r.content) <= 20 * 1024 * 1024:
            raise ImageRejected('Meta AI image size invalid')
        with Image.open(BytesIO(r.content)) as picture:
            picture.load()
            width, height = picture.size
            if min(picture.size) < 512 or max(picture.size) > 8192:
                raise ImageRejected('Meta AI image dimensions invalid')
            part = out.with_suffix('.part')
            picture.convert('RGB').save(part, format='PNG', optimize=True)
        part.replace(out)
        data = {'task_id': task_id, 'request_id': request_id or task_id, 'file_path': str(out.resolve()), 'sha256': digest(out),
                'width': width, 'height': height, 'source': 'meta_ai', 'image_url': image_url}
        tmp = receipt.with_suffix('.part')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        tmp.replace(receipt)
        sent.unlink(missing_ok=True)
        return data

    # ---- batches: one prompt, several pictures, optional reference images ----

    def _batch_dir(self, batch_id):
        return self.root / 'batches' / batch_id

    def _batch_done(self, batch_id):
        receipt = self._batch_dir(batch_id) / 'receipt.json'
        if not receipt.is_file():
            return None
        data = json.loads(receipt.read_text(encoding='utf8'))
        for image in data.get('images', []):
            path = Path(image['file_path'])
            if not path.is_file() or digest(path) != image['sha256']:
                return None
        return data

    async def _raise_if_quota(self, session):
        message = await self.bridge.evaluate(session, QUOTA_JS)
        if message:
            raise MetaQuotaExhausted('Meta AI hết lượt tạo ảnh: ' + message)

    async def _attach(self, session, files):
        """Put reference images in the composer through its file input (same as picking them by hand)."""
        doc = await self.bridge.cdp.command('DOM.getDocument', {'depth': -1, 'pierce': True}, session=session)
        node = await self.bridge.cdp.command('DOM.querySelector', {'nodeId': doc['root']['nodeId'], 'selector': 'input[type=file]'}, session=session)
        if not node.get('nodeId'):
            raise RuntimeError('Meta AI file input not found; nothing sent')
        await self.bridge.cdp.command('DOM.setFileInputFiles', {'files': files, 'nodeId': node['nodeId']}, session=session)
        count_js = "[...document.querySelectorAll('img')].filter(i=>(i.currentSrc||i.src||'').startsWith('blob:')).length"
        for _ in range(40):
            await asyncio.sleep(1)
            await self._tick(session)
            if (await self.bridge.evaluate(session, count_js) or 0) >= len(files):
                break
        else:
            raise RuntimeError('Meta AI did not accept the reference images; nothing sent')
        await asyncio.sleep(8)  # previews appear before the upload finishes; sending early drops the text

    async def _collect(self, session, before, count, timeout):
        """Pictures in page order (= prompt order). Page order is kept across polls because finished
        pictures arrive in any order and the page may unload the ones scrolled away."""
        order, start, last_change = [], time.time(), time.time()
        end = start + timeout
        last, stable = '', 0
        while time.time() < end:
            await asyncio.sleep(2)
            snapshot = [x[0] for x in await self._images(session) if x[0] not in before]
            for k, url in enumerate(snapshot):
                if url in order:
                    continue
                previous = next((snapshot[j] for j in range(k - 1, -1, -1) if snapshot[j] in order), None)
                order.insert(order.index(previous) + 1 if previous else 0, url)
                last_change = time.time()
            if len(order) >= count and time.time() - last_change > 8:
                break
            if order and time.time() - last_change > 60:
                break  # fewer pictures than asked; the caller fills the gaps
            if not order and time.time() - start > 8:
                await self._raise_if_quota(session)
            if not order and time.time() - start > NO_PICTURE_AFTER:
                break  # Meta answered without a picture (a refusal reads as text we cannot always find)
            if not order:
                reply = (await self._state(session)).get('reply', '')
                if reply and reply == last:
                    stable += 1
                    if stable >= 8:
                        raise ImageRejected('Meta AI trả lời chữ, không tạo ảnh: ' + reply[:300])
                else:
                    last, stable = reply, 0
        return order

    async def _save_batch(self, batch_id, urls, url, count):
        folder = self._batch_dir(batch_id)
        images, seen = [], set()
        for image_url in urls:
            r = await asyncio.to_thread(httpx.get, image_url, timeout=60, follow_redirects=True)
            r.raise_for_status()
            h = digest_bytes(r.content)
            if h in seen:
                continue  # the same picture is often shown twice (preview and full size)
            seen.add(h)
            with Image.open(BytesIO(r.content)) as picture:
                picture.load()
                if min(picture.size) < 512:
                    continue
                out = folder / f'img-{len(images) + 1:02}.png'
                part = out.with_suffix('.part')
                picture.convert('RGB').save(part, format='PNG', optimize=True)
                part.replace(out)
                images.append({'index': len(images), 'file_path': str(out.resolve()), 'sha256': digest(out),
                               'width': picture.width, 'height': picture.height, 'image_url': image_url})
            if len(images) >= count:
                break
        data = {'batch_id': batch_id, 'url': url, 'count': count, 'images': images, 'complete': len(images) >= count}
        tmp = folder / 'receipt.part'
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf8')
        tmp.replace(folder / 'receipt.json')
        (folder / 'sent.json').unlink(missing_ok=True)
        return data

    async def generate_batch(self, batch_id, prompt, count, references=(), timeout=420):
        """Send one prompt asking for `count` pictures (with up to 10 reference images); never resend."""
        try:
            batch_id = str(uuid.UUID(batch_id))
        except (ValueError, TypeError, AttributeError) as e:
            raise ValueError('batch_id must be a UUID') from e
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8000:
            raise ValueError('prompt must be 1..8000 characters')
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError('count must be 1..10')
        refs = [str(Path(p).resolve()) for p in (references or [])]
        if len(refs) > 10 or not all(Path(p).is_file() and Path(p).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') for p in refs):
            raise ValueError('references must be at most 10 existing image files')
        # A line break in the composer sends the message; the prompt must be one line.
        prompt = ' '.join(prompt.split())
        folder = self._batch_dir(batch_id)
        folder.mkdir(parents=True, exist_ok=True)
        sent = folder / 'sent.json'
        async with self.lock:
            done = self._batch_done(batch_id)
            if done:
                return done
            await self.bridge.connect()
            target = await self._tab()
            session = await self.bridge.session(target)
            await self.bridge.cdp.command('Target.activateTarget', {'targetId': target})
            if sent.is_file():
                saved = json.loads(sent.read_text(encoding='utf8'))
                if not conversation_id(saved.get('url', '')):
                    raise IndeterminateRequest('Meta AI batch was sent but its conversation is unknown; not resending')
                await self._open(session, saved['url'])
                try:
                    found = await self._collect(session, set(), count, 90)
                except MetaQuotaExhausted:
                    sent.unlink(missing_ok=True)  # declined for credits, not for content: may be sent again later
                    raise
                # Sent long ago and still no picture in its conversation: Meta declined it. Record that
                # (an empty receipt) so the caller moves on instead of asking about it forever.
                return await self._save_batch(batch_id, found, saved['url'], count)
            await self._wait_turn()
            state = await self._open(session, META_HOME)
            if state.get('mode') != 'Instant':
                await self._instant(session)
            if refs:
                await self._attach(session, refs)
            before = {x[0] for x in await self._images(session)}
            await self.bridge.evaluate(session, "document.querySelector('%s')?.focus()" % COMPOSER)
            await self.bridge.cdp.command('Input.insertText', {'text': prompt}, session=session)
            await asyncio.sleep(.5)
            typed = await self.bridge.evaluate(session, "(document.querySelector('%s')?.innerText||'').trim().length" % COMPOSER)
            if not typed or typed < len(prompt) * .9:
                raise RuntimeError('Meta AI composer did not accept the whole prompt; nothing sent')
            self.stamp.write_text(str(time.time()))
            sent.write_text(json.dumps({'batch_id': batch_id, 'sent_at': time.time(), 'url': ''}), encoding='utf8')
            for kind in ('keyDown', 'keyUp'):
                await self.bridge.cdp.command('Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, **({'text': '\r'} if kind == 'keyDown' else {})}, session=session)
            url = ''
            for _ in range(20):
                await asyncio.sleep(.5)
                url = (await self._state(session)).get('url', '')
                if conversation_id(url):
                    sent.write_text(json.dumps({'batch_id': batch_id, 'sent_at': time.time(), 'url': url}), encoding='utf8')
                    break
            try:
                found = await self._collect(session, before, count, timeout)
            except MetaQuotaExhausted:
                sent.unlink(missing_ok=True)
                raise
            url = (await self._state(session)).get('url', '') or url
            if not found and not conversation_id(url):
                raise IndeterminateRequest('Meta AI did not return images in time; the same batch will look in its conversation')
            return await self._save_batch(batch_id, found, url, count)  # empty when Meta declined

    async def generate(self, task_id, prompt, timeout=240):
        try:
            task_id = str(uuid.UUID(task_id))
        except (ValueError, TypeError, AttributeError) as e:
            raise ValueError('task_id must be a UUID') from e
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 8000:
            raise ValueError('prompt must be 1..8000 characters')
        prompt = prompt.strip()
        self.root.mkdir(parents=True, exist_ok=True)
        async with self.lock:
            done = self._done(task_id)
            if done:
                return done
            await self.bridge.connect()
            target = await self._tab()
            session = await self.bridge.session(target)
            await self.bridge.cdp.command('Target.activateTarget', {'targetId': target})  # hidden tabs never render the composer
            _, _, sent = self._paths(task_id)
            if sent.is_file():
                # Sent before but no saved result: look in that conversation, never send twice.
                saved = json.loads(sent.read_text(encoding='utf8'))
                if not conversation_id(saved.get('url', '')):
                    raise IndeterminateRequest('Meta AI prompt was sent but its conversation is unknown; not resending')
                await self._open(session, saved['url'])
                try:
                    found, state = await self._wait_image(session, set(), 60)
                except MetaQuotaExhausted:
                    sent.unlink(missing_ok=True)
                    raise
                if not found:
                    raise ImageRejected('Meta AI đã nhận prompt nhưng không trả ảnh nào')
                return await self._save(task_id, found[0][0], conversation_id(saved['url']))
            await self._wait_turn()
            state = await self._open(session, META_HOME)
            if state.get('mode') != 'Instant':
                await self._instant(session)
            before = {x[0] for x in await self._images(session)}
            await self.bridge.evaluate(session, "document.querySelector('%s')?.focus()" % COMPOSER)
            await self.bridge.cdp.command('Input.insertText', {'text': prompt}, session=session)
            await asyncio.sleep(.5)
            typed = await self.bridge.evaluate(session, "(document.querySelector('%s')?.innerText||'').trim().length" % COMPOSER)
            if not typed:
                raise RuntimeError('Meta AI composer did not accept the prompt; nothing sent')
            self.stamp.write_text(str(time.time()))
            sent.write_text(json.dumps({'task_id': task_id, 'sent_at': time.time(), 'url': ''}), encoding='utf8')
            for kind in ('keyDown', 'keyUp'):  # repo: press Enter
                await self.bridge.cdp.command('Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13, **({'text': '\r'} if kind == 'keyDown' else {})}, session=session)
            url = ''
            for _ in range(20):  # remember the new conversation so a crash never leads to a second send
                await asyncio.sleep(.5)
                url = (await self._state(session)).get('url', '')
                if conversation_id(url):
                    sent.write_text(json.dumps({'task_id': task_id, 'sent_at': time.time(), 'url': url}), encoding='utf8')
                    break
            try:
                found, state = await self._wait_image(session, before, timeout)
            except MetaQuotaExhausted:
                sent.unlink(missing_ok=True)
                raise
            url = state.get('url', '') or url
            if not found:
                raise IndeterminateRequest('Meta AI did not return an image in time; the same task will look in its conversation')
            return await self._save(task_id, found[0][0], conversation_id(url))

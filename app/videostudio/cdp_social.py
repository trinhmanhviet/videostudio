"""Read one Facebook post in the dedicated Chrome, the way the user would open it: the post's text, its pictures and
a few frames of its video (for ChatGPT to look at; the video itself is never downloaded or reused).

The post opens in its own background tab, which is closed afterwards. It works without a Facebook login for public
posts; a login in the dedicated Chrome lets it read posts that need one. Nothing is clicked except the post's own
"Xem thêm / See more" link, and login pop-ups are left alone (the text is in the page behind them).
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

FACEBOOK_HOSTS = {'facebook.com', 'www.facebook.com', 'm.facebook.com', 'web.facebook.com', 'mbasic.facebook.com',
                  'fb.watch', 'www.fb.watch', 'fb.com', 'www.fb.com'}
MAX_IMAGES = 10
FRAME_POINTS = (0.15, 0.4, 0.65, 0.9)


def valid_post_url(url):
    if not isinstance(url, str) or len(url) > 2000:
        raise ValueError('Link không hợp lệ')
    parsed = urlparse(url.strip())
    if parsed.scheme != 'https' or (parsed.hostname or '').lower() not in FACEBOOK_HOSTS:
        raise ValueError('Dán link bài viết Facebook (https://www.facebook.com/…)')
    return url.strip()


# The post: its message block, the article around it (comments are nested articles and stay out), its big pictures
# and its videos. Falls back to the page's own summary (og:) when the message block is not found.
EXTRACT = r'''(()=>{
  const meta=k=>document.querySelector(`meta[property="${k}"],meta[name="${k}"]`)?.content||'';
  const message=document.querySelector('[data-ad-preview="message"],[data-ad-comet-preview="message"]');
  let root=message?.closest('[role="article"]')||null;
  const scope=root||document.querySelector('[role="main"]')||document.body;
  const inPost=n=>!root||n.closest('[role="article"]')===root;
  const more=message?[...message.querySelectorAll('[role="button"]')].some(b=>/^(Xem thêm|See more)$/i.test(b.textContent.trim())):false;
  const images=[...new Set([...scope.querySelectorAll('img')].filter(i=>inPost(i)&&/fbcdn\.net|fbsbx\.com/.test(i.src)&&i.naturalWidth>=300&&i.naturalHeight>=200).map(i=>i.src))];
  const videos=[...scope.querySelectorAll('video')].filter(inPost).map((v,i)=>{v.dataset.vsIndex=String(i);return {index:i,duration:Number.isFinite(v.duration)?v.duration:0,poster:v.poster||''};});
  const login=!!document.querySelector('form[action*="login"],#login_form,input[name="pass"]');
  const author=(root?.querySelector('h2,h3,strong a,[data-ad-rendering-role="profile_name"]')?.textContent||meta('og:title')||'').trim();
  return {ready:!!message||!!meta('og:description')||document.readyState==='complete', found:!!message,
    text:(message?.innerText||'').trim(), summary:meta('og:description'), og_image:meta('og:image'),
    title:document.title, author, url:location.href, more, images, videos, login};
})()'''

# The picture of an image document (null while loading, 'no' when the address is not a picture).
PICTURE = r'''(()=>{if(!/^image\//.test(document.contentType||''))return document.readyState==='complete'?'no':null;
  const i=document.images[0];if(!i||!i.complete||!i.naturalWidth)return null;
  const c=document.createElement('canvas');c.width=i.naturalWidth;c.height=i.naturalHeight;c.getContext('2d').drawImage(i,0,0);
  return c.toDataURL('image/jpeg',0.92)})()'''

EXPAND = r'''(()=>{const m=document.querySelector('[data-ad-preview="message"],[data-ad-comet-preview="message"]');
  const b=m&&[...m.querySelectorAll('[role="button"]')].find(b=>/^(Xem thêm|See more)$/i.test(b.textContent.trim()));if(b){b.click();return true}return false})()'''


def seek_expression(index, fraction):
    return (r'''(async()=>{const v=document.querySelector('video[data-vs-index="INDEX"]');if(!v)return null;
      v.muted=true;v.scrollIntoView({block:'center'});
      if(!(v.duration>0)){await new Promise(r=>{v.addEventListener('loadedmetadata',r,{once:true});v.load?.();setTimeout(r,4000)})}
      if(!(v.duration>0))return null;
      await new Promise(r=>{v.addEventListener('seeked',r,{once:true});v.currentTime=v.duration*FRACTION;setTimeout(r,5000)});
      await new Promise(r=>setTimeout(r,400));
      const b=v.getBoundingClientRect();return {x:b.left,y:b.top,width:b.width,height:b.height,scale:devicePixelRatio||1}})()'''
            .replace('INDEX', str(int(index))).replace('FRACTION', repr(float(fraction))))


def clean_author(name):
    """The page name without the badge text Facebook puts after it ("Verified account", "Tài khoản đã xác minh")."""
    first = str(name or '').replace('\u00a0', ' ').splitlines()[0] if name else ''
    return re.sub(r'\s*(Verified account|Tài khoản đã xác minh|Đã xác minh)\s*$', '', first, flags=re.I).strip()[:120]


class PostReader:
    def __init__(self, bridge, root):
        self.bridge, self.root = bridge, Path(root)
        self.lock = asyncio.Lock()

    async def _value(self, session, expression, awaited=False):
        result = await self.bridge.cdp.command('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': awaited},
                                               session=session)
        if result.get('exceptionDetails'):
            return None
        return result.get('result', {}).get('value')

    async def read(self, task_id, url, timeout=45):
        uuid.UUID(str(task_id))
        url = valid_post_url(url)
        folder = self.root / str(task_id)
        folder.mkdir(parents=True, exist_ok=True)
        async with self.lock:
            b = self.bridge
            await b.connect()
            target = (await b.cdp.command('Target.createTarget', {'url': url, 'background': True}))['targetId']
            try:
                session = await b.session(target)
                deadline, data = time.monotonic() + timeout, None
                while time.monotonic() < deadline:
                    await asyncio.sleep(1.5)
                    data = await self._value(session, EXTRACT)
                    if data and data.get('found') and data.get('text'):
                        break
                if not data:
                    raise RuntimeError('Không mở được trang Facebook này')
                if data.get('more') and await self._value(session, EXPAND):
                    await asyncio.sleep(1.5)
                    data = await self._value(session, EXTRACT) or data
                frames = await self._frames(session, data.get('videos') or [], folder)
                data['author'] = clean_author(data.get('author'))
                data['images'] = (data.get('images') or [])[:MAX_IMAGES]
                data['frames'] = frames
                return data
            finally:
                b.sessions.pop(target, None)
                try:
                    await b.cdp.command('Target.closeTarget', {'targetId': target})
                except Exception:
                    pass

    async def fetch_images(self, task_id, urls, timeout=25):
        """Pictures a site refuses to the tool's plain download: ONE background tab opens each picture in turn (the next
        address replaces the previous one in the same tab) and the tab is closed when all are done. The picture is
        read back from the page itself (an image document is same-origin with its picture). Returns [{url, path}]."""
        uuid.UUID(str(task_id))
        urls = [u for u in urls if isinstance(u, str) and u.startswith(('https://', 'http://'))][:20]
        folder = self.root / str(task_id) / 'fetched'
        folder.mkdir(parents=True, exist_ok=True)
        saved = []
        if not urls:
            return saved
        async with self.lock:
            b = self.bridge
            await b.connect()
            target = (await b.cdp.command('Target.createTarget', {'url': 'about:blank', 'background': True}))['targetId']
            try:
                session = await b.session(target)
                for number, url in enumerate(urls, 1):
                    try:
                        await b.cdp.command('Page.navigate', {'url': url}, session=session)
                        data = None
                        deadline = time.monotonic() + timeout
                        while time.monotonic() < deadline and data is None:
                            await asyncio.sleep(0.7)
                            data = await self._value(session, PICTURE)
                        if isinstance(data, str) and data.startswith('data:image/jpeg;base64,'):
                            path = folder / f'{number:02d}.jpg'
                            path.write_bytes(base64.b64decode(data.split(',', 1)[1]))
                            saved.append({'url': url, 'path': str(path)})
                    except Exception:
                        continue
            finally:
                b.sessions.pop(target, None)
                try:
                    await b.cdp.command('Target.closeTarget', {'targetId': target})
                except Exception:
                    pass
        return saved

    async def _frames(self, session, videos, folder):
        """A few still frames of the post's first video, captured from the page (the video file is never fetched)."""
        if not videos:
            return []
        try:
            await self.bridge.cdp.command('Page.bringToFront', {}, session=session)  # a background tab may not paint
        except Exception:
            pass
        saved = []
        for number, fraction in enumerate(FRAME_POINTS, 1):
            try:
                box = await asyncio.wait_for(self._value(session, seek_expression(videos[0]['index'], fraction), awaited=True), 12)
                if not box or box['width'] < 80 or box['height'] < 80:
                    continue
                shot = await asyncio.wait_for(self.bridge.cdp.command('Page.captureScreenshot', {
                    'format': 'jpeg', 'quality': 85,
                    'clip': {'x': box['x'], 'y': box['y'], 'width': box['width'], 'height': box['height'], 'scale': 1}}, session=session), 15)
                path = folder / f'frame-{number}.jpg'
                path.write_bytes(base64.b64decode(shot['data']))
                saved.append(str(path))
            except (asyncio.TimeoutError, KeyError, ValueError):
                continue
            except Exception:
                break
        return saved

"""Visible-UI Gemini text adapter primitives.

Safety rules encoded here (deliberate):
  * the request id travels inside the prompt, so a reply is tied to one submission;
  * a reply counts only when a structured turn (or, on builds without turn
    elements, the ordered chat text) contains a JSON object whose request_id is
    exactly this request after the marker, is not the envelope placeholder, and
    the page is not still generating;
  * a marker seen twice, only in the composer, or a reply that appears before the
    marker is ambiguous and never accepted.
"""
import json
from urllib.parse import urlparse

GEMINI_HOME = 'https://gemini.google.com/app'
GEMINI_HOST = 'gemini.google.com'
PLACEHOLDER = 'replace with the requested JSON object'


def valid_gemini_url(url):
    """Exact-host HTTPS check; no credentials, no lookalike hosts."""
    try:
        p = urlparse(url or '')
    except (TypeError, ValueError):
        return False
    return p.scheme == 'https' and p.hostname == GEMINI_HOST and not p.username and not p.password


def gemini_snapshot_expression(marker=''):
    """Read-only DOM snapshot: composer, streaming state, turns and ordered chat text."""
    return r"""(()=>{
      const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
      const composer=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
      const nodes=[...document.querySelectorAll('user-query, model-response')];
      const turns=nodes.map(n=>{
        const isUser=n.tagName.toLowerCase()==='user-query';
        const body=isUser?(n.querySelector('.query-text, .query-content, [class*=query-text]')||n):n;
        return {role:isUser?'user':'assistant',text:(body.innerText||'').trim()};
      });
      const area=document.querySelector('input-area-v2');
      const stop=!!(area&&[...area.querySelectorAll('button')].some(b=>{
        const l=(b.getAttribute('aria-label')||'');
        return /stop response|stop generating|dừng phản hồi|dừng tạo/i.test(l);
      }));
      const busy=[...document.querySelectorAll('[aria-busy="true"]')].filter(vis).length>0;
      const chat=document.querySelector('chat-window')||document.body;
      const lastAssistant=[...turns].reverse().find(t=>t.role==='assistant');
      return JSON.stringify({
        url:location.href,
        title:document.title,
        login:/sign in to gemini|đăng nhập vào gemini/i.test(document.body.innerText.slice(0,600))&&!composer,
        challenge:[...document.querySelectorAll('iframe')].some(f=>/recaptcha|challenges\.cloudflare\.com/.test(f.src||'')),
        composer:!!composer,
        draft:composer?(composer.innerText||composer.value||'').trim():'',
        generating:stop||busy,
        turns,
        lastAssistantLength:lastAssistant?lastAssistant.text.length:0,
        chatText:(chat.innerText||'').slice(-20000)
      });
    })()"""


def gemini_composer_expression():
    """Centre point of the visible Gemini prompt box, or null."""
    return r"""(()=>{
      const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
      const box=[...document.querySelectorAll('rich-textarea [contenteditable="true"],div[contenteditable="true"][role="textbox"],textarea')].filter(vis)[0];
      if(!box)return null;
      const r=box.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+Math.min(r.height/2,20)};
    })()"""


def gemini_send_button_expression():
    """The real send control: inside input-area-v2, labelled 'Gửi tin nhắn'/'Send message'.

    Scoped on purpose: a bare /gửi/ match also hits feedback and other chat
    buttons, which silently swallows the request (observed on 2026-10-28).
    """
    return r"""(()=>{
      const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
      const area=document.querySelector('input-area-v2');
      if(!area)return null;
      const hit=[...area.querySelectorAll('button')].filter(vis).find(b=>{
        if(b.disabled)return false;
        const l=(b.getAttribute('aria-label')||'').trim();
        return /^(send message|send prompt|gửi tin nhắn|gửi câu lệnh)$/i.test(l);
      });
      if(!hit)return null;
      const r=hit.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+r.height/2,label:hit.getAttribute('aria-label')};
    })()"""


def gemini_chat_count_expression():
    """Number of rendered conversation turns in the visible chat window."""
    return r"""(()=>document.querySelectorAll('conversation-container, .conversation-container').length)()"""


def gemini_new_chat_expression():
    """Centre point of the 'New chat' control, or null.

    Required before typing: a freshly opened Gemini tab restores the last
    conversation, and appending to that would pollute the owner's own chat.
    """
    return r"""(()=>{
      const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
      const hit=[...document.querySelectorAll('button,a')].filter(vis).find(e=>{
        const l=(e.getAttribute('aria-label')||'')+' '+(e.innerText||'');
        return /new chat|cuộc trò chuyện mới|tạo cuộc trò chuyện mới/i.test(l);
      });
      if(!hit)return null;
      const r=hit.getBoundingClientRect();
      return {x:r.x+r.width/2,y:r.y+r.height/2};
    })()"""


def gemini_click_send_expression():
    """Element click on the exact send control (Angular Material needs the element click too)."""
    return r"""(()=>{
      const vis=e=>{const r=e&&e.getBoundingClientRect();return !!r&&r.width>1&&r.height>1};
      const area=document.querySelector('input-area-v2');
      if(!area)return false;
      const hit=[...area.querySelectorAll('button')].filter(vis).find(b=>{
        if(b.disabled)return false;
        return /^(send message|send prompt|gửi tin nhắn|gửi câu lệnh)$/i.test((b.getAttribute('aria-label')||'').trim());
      });
      if(!hit)return false;
      hit.click();
      return true;
    })()"""


def parse_snapshot(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _json_objects_after(text, start, identifier):
    """Parseable JSON objects after `start` that carry this request id and a real result."""
    decoder = json.JSONDecoder()
    found = []
    index = text.find('{', start)
    while index != -1:
        try:
            value, end = decoder.raw_decode(text[index:])
        except ValueError:
            index = text.find('{', index + 1)
            continue
        if isinstance(value, dict) and value.get('request_id') == identifier and isinstance(value.get('result'), dict):
            if PLACEHOLDER not in json.dumps(value):
                found.append((index, text[index:index + end]))
        index = text.find('{', max(end, index + 1))
    return found


def correlate_gemini(raw_state, marker, identifier=None):
    """Return {'matched':True,'text':...} only for a NEW completed reply to `marker`.

    Returns None while the reply is missing/streaming; raises ValueError when the
    transcript is ambiguous (marker repeated).
    """
    state = parse_snapshot(raw_state)
    if not state or not marker:
        return None
    if state.get('login') or state.get('challenge'):
        return None
    expected = identifier or marker.strip().strip('[]').replace('VideoStudio request ', '').strip()

    turns = [t for t in state.get('turns', []) if isinstance(t, dict)]
    if turns:
        positions = [i for i, t in enumerate(turns) if t.get('role') == 'user' and marker in (t.get('text') or '')]
        if len(positions) > 1:
            raise ValueError('Duplicate Gemini request marker; refusing to choose a reply')
        if positions:
            reply = next((t for t in turns[positions[0] + 1:] if t.get('role') == 'assistant'), None)
            if reply is None:
                return None
            text = (reply.get('text') or '').strip()
            if not text or state.get('generating'):
                return None
            # The rendered reply carries chrome around the JSON (a "JSON" chip, fences,
            # copy labels). Only the embedded object with this exact request id counts.
            candidates = _json_objects_after(text, 0, expected)
            if candidates:
                return {'matched': True, 'text': candidates[-1][1]}
            return None
        return None

    chat = state.get('chatText') or ''
    occurrences = chat.count(marker)
    if occurrences > 1:
        raise ValueError('Duplicate Gemini request marker; refusing to choose a reply')
    if occurrences == 0:
        return None
    if state.get('generating'):
        return None
    index = chat.rfind(marker)
    candidates = _json_objects_after(chat, index + len(marker), expected)
    if not candidates:
        return None
    return {'matched': True, 'text': candidates[-1][1]}

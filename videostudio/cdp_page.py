"""DOM adapter for owned ChatGPT tabs. No private API calls or login automation."""
import json

MODE_EXPRESSION = r'''(() => {
  const visible=e=>e&&e.getBoundingClientRect().width>0;
  const buttons=[...document.querySelectorAll('button,[role="tab"]')].filter(visible);
  const chat=buttons.find(e=>e.textContent.trim()==='Chat');
  const work=buttons.find(e=>e.textContent.trim()==='Work');
  const active=e=>e&&(e.getAttribute('aria-pressed')==='true'||e.getAttribute('aria-selected')==='true');
  const composer=document.querySelector('#prompt-textarea,textarea[placeholder],[contenteditable="true"][role="textbox"]');
  const label=composer?.getAttribute('aria-label')||'';
  let mode='unknown';
  if(active(work)&&!active(chat)) mode='work';
  else if(active(chat)&&!active(work)) mode='chat';
  else if(!chat&&!work&&/^(Ask ChatGPT|Message ChatGPT)$/i.test(label)) mode='chat';
  else if(/Work with ChatGPT/i.test(label)) mode='work';
  const r=chat?.getBoundingClientRect();
  return {mode,chatButton:r?{x:r.x+r.width/2,y:r.y+r.height/2}:null};
})()'''


def chat_mode_button_expression():
    return "("+MODE_EXPRESSION+").chatButton"

# Correlate only an assistant following the exact request marker, never the last
# arbitrary code block on a page. Missing selectors are errors, not success.
def snapshot_expression(marker=''):
    return r'''(() => {
      const marker = MARKER;
      const modeInfo = MODE_INFO;
      const body = document.body?.innerText || '';
      const login = !!document.querySelector('input[type="password"],input[autocomplete="one-time-code"]') ||
        [...document.querySelectorAll('button,a')].some(e => /^(log in|sign in|đăng nhập)$/i.test(e.textContent.trim()));
      const challenge = /verify you are human|checking your browser|confirm you are human|captcha/i.test(document.title + '\n' + body.slice(0,1200));
      const composer = document.querySelector('#prompt-textarea,textarea[placeholder], [contenteditable="true"][role="textbox"]');
      const messages = [...document.querySelectorAll('[data-message-author-role]')];
      let matched = false, text = '', messageId = '';
      for (const el of messages) {
        const role=el.getAttribute('data-message-author-role');
        if (role === 'user') { if ((el.innerText||'').includes(marker) && marker) { matched=true; text=''; } else if(matched) break; }
        else if (matched && role === 'assistant') {
          text = el.innerText || ''; messageId=el.getAttribute('data-message-id') || '';
          const code=el.querySelector('code'); if(code) text=code.innerText;
        }
      }
      const turns = [...document.querySelectorAll('[data-talvt-turn-state]')].map(turn => {
        const userHeading=[...turn.querySelectorAll('h4')].find(h=>/^(You said:|B?n ?? n?i:|B?n n?i:)$/i.test(h.textContent.trim()));
        const user=userHeading?.parentElement?.textContent || '';
        const assistant=turn.querySelector('[data-chatgpt-search-unit-key$=":assistant"]');
        let assistantText='';
        if(assistant) {
          const code=assistant.querySelector('code');
          if(code) assistantText=code.textContent;
          else {
            assistantText=assistant.textContent.trimStart();
            const heading=assistant.querySelector('h4')?.textContent || '';
            if(heading && assistantText.startsWith(heading)) assistantText=assistantText.slice(heading.length);
          }
        }
        return {user,assistant:assistantText.trim(),state:turn.getAttribute('data-talvt-turn-state'),id:assistant?.getAttribute('data-chatgpt-search-message-ids')||''};
      });
      const generating=!!document.querySelector('[data-testid="stop-button"],button[aria-label="Stop generating"]');
      return {turns,mode:modeInfo.mode,url:location.href, login, challenge, composer:!!composer, draft:composer?(composer.innerText||composer.value||''):'', matched, text, messageId, generating};
    })()'''.replace('MARKER',json.dumps(marker)).replace('MODE_INFO',MODE_EXPRESSION)


def composer_expression():
    return r'''(() => {
      if (MODE_INFO.mode !== 'chat') return null;
      const e=document.querySelector('#prompt-textarea,textarea[placeholder], [contenteditable="true"][role="textbox"]');
      if(!e || (e.innerText||e.value||'').trim()) return null;
      e.focus(); return {focused:document.activeElement===e};
    })()'''.replace('MODE_INFO',MODE_EXPRESSION)


def send_button_expression():
    return r'''(() => {
      if (MODE_INFO.mode !== 'chat') return null;
      const e=document.querySelector('button[data-testid="send-button"],button[aria-label="Send prompt"],button[aria-label="Gửi prompt"],button[aria-label="Send message"],button[aria-label="Send"]');
      if(!e || e.disabled) return null;
      const r=e.getBoundingClientRect();
      if(r.width<=0 || r.height<=0) return null;
      return {x:r.x+r.width/2,y:r.y+r.height/2};
    })()'''.replace('MODE_INFO',MODE_EXPRESSION)


def correlate_turns(state, marker):
    """Modern UI keeps completed turns separate from an old streaming placeholder."""
    if not state or state.get('matched') or not marker:
        return state
    matches=[t for t in state.get('turns',[]) if marker in t.get('user','')]
    if len(matches)!=1:
        return state
    turn=matches[0]
    complete=turn.get('state')=='complete'
    return {**state,'matched':True,'text':turn.get('assistant','') if complete else '',
            'messageId':turn.get('id',''),'generating':not complete}

"""DOM adapter for owned ChatGPT tabs. No private API calls or login automation."""
import json

# Correlate only an assistant following the exact request marker, never the last
# arbitrary code block on a page. Missing selectors are errors, not success.
def snapshot_expression(marker=''):
    return r'''(() => {
      const marker = MARKER;
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
      const generating=!!document.querySelector('[data-testid="stop-button"],button[aria-label="Stop generating"]');
      return {url:location.href, login, challenge, composer:!!composer, draft:composer?(composer.innerText||composer.value||''):'', matched, text, messageId, generating};
    })()'''.replace('MARKER',json.dumps(marker))


def composer_expression():
    return r'''(() => {
      const e=document.querySelector('#prompt-textarea,textarea[placeholder], [contenteditable="true"][role="textbox"]');
      if(!e || (e.innerText||e.value||'').trim()) return null;
      e.focus(); return {focused:document.activeElement===e};
    })()'''


def send_button_expression():
    return r'''(() => {
      const e=document.querySelector('button[data-testid="send-button"],button[aria-label="Send prompt"],button[aria-label="Gửi prompt"],button[aria-label="Send message"]');
      if(!e || e.disabled) return null;
      const r=e.getBoundingClientRect();
      if(r.width<=0 || r.height<=0) return null;
      return {x:r.x+r.width/2,y:r.y+r.height/2};
    })()'''

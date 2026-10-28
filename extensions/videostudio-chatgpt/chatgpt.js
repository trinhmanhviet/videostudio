(()=>{
  if(location.origin!=='https://chatgpt.com'||window.top!==window)return;
  const visible=n=>!!n?.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
  const editor=()=>[...document.querySelectorAll('#prompt-textarea,[contenteditable="true"][role="textbox"],textarea')].find(visible);
  const user=()=>[...document.querySelectorAll('[data-message-author-role="user"],[data-content-search-unit-key$=":user"]')].filter(visible).at(-1);
  const assistants=()=>[...document.querySelectorAll('[data-message-author-role="assistant"],[data-content-search-unit-key$=":assistant"]')].filter(visible);
  const text=n=>n?.innerText?.trim()??n?.textContent?.trim()??'';
  const userText=n=>text(n?.querySelector('[data-user-message-bubble] .whitespace-pre-wrap,.whitespace-pre-wrap')||n).replace(/^You said:\s*/u,'').trim();
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  let retired=false,occupied=false;
  const runtime=async message=>{if(retired)return null;try{return await chrome.runtime.sendMessage(message);}catch(e){if(/Extension context invalidated|Receiving end does not exist/i.test(String(e?.message??e)))retired=true;return null;}};
  const error=async (id,attempt,reason)=>{await runtime({kind:'uncertain',id,attempt,reason});};
  const inspect=(id,prompt)=>{const turn=user(),node=assistants().at(-1);const complete=node&&[...node.closest('[data-testid^="conversation-turn-"],[data-content-search-unit-key]')?.querySelectorAll('button')??[]].some(n=>/good-response|bad-response|rate response/i.test(`${n.getAttribute('data-testid')} ${n.getAttribute('aria-label')}`));return {visibleUser:turn?userText(turn):null,visibleReply:turn&&userText(turn)===prompt&&complete?text(node)||null:null};};
  chrome.runtime.onMessage.addListener((message,_sender,reply)=>{
    if(retired)return;
    if(message?.kind==='inspect'){reply(inspect(message.id,message.prompt));return;}
    if(message?.kind!=='deliver')return;
    if(occupied){reply({ok:false});return;}
    occupied=true;reply({ok:true});
    (async()=>{
      const {id,prompt,attempt}=message;
      if(typeof id!=='string'||!prompt.startsWith(`YÊU CẦU STUDIO ${id}\n`))throw Error('Immutable request marker missing');
      if(/login|auth|challenge|verify/i.test(location.pathname))throw Error('Login or verification required');
      if(user()||assistants().length)throw Error('Dedicated tab is not an empty conversation');
      const input=editor();if(!input||text(input))throw Error('Composer unavailable or occupied');
      // Do not change ChatGPT mode. If mode cannot be proved Chat, stop.
      const group=document.querySelector('[role="group"][aria-label="Composer mode"]');
      if(group){const chat=[...group.querySelectorAll('button')].find(n=>text(n)==='Chat');if(chat?.getAttribute('aria-pressed')!=='true')throw Error('Chat mode not confirmed');}
      else if(!/^(ask chatgpt|message chatgpt|hỏi chatgpt|nhắn tin cho chatgpt)$/i.test((input.getAttribute('aria-label')||input.getAttribute('placeholder')||input.querySelector('[data-placeholder]')?.getAttribute('data-placeholder')||'').trim()))throw Error('Chat mode unknown');
      input.focus();
      if(input.tagName==='TEXTAREA'){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,prompt);input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:prompt}));}
      else {const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);if(!document.execCommand('insertText',false,prompt))throw Error('Composer insertion failed');}
      await wait(200);
      const actual=input.tagName==='TEXTAREA'?input.value:text(input);
      if(actual.trim()!==prompt.trim())throw Error('Composer does not match immutable prompt');
      const form=input.closest('form');const button=[...(form||document).querySelectorAll('button')].find(n=>visible(n)&&globalThis.VideoStudioSendButton.isSendButton(n.getAttribute('aria-label'),n.getAttribute('data-testid')));
      if(!button||button.disabled)throw Error('Send button unavailable');
      // From here delivery is uncertain even if the tab reloads. Background persisted dispatching first.
      button.click();
      for(let i=0;i<80;i++){await wait(250);if(userText(user())===prompt.trim())break;}
      if(userText(user())!==prompt.trim())throw Error('Exact user-turn receipt missing');
      const sent=await runtime({kind:'sent',id,attempt});if(!sent){retired=true;return;}if(!sent.ok)throw Error('Background rejected send receipt');
      for(let i=0;i<720;i++){
        await wait(500);if(retired)return;const answers=assistants();const node=answers.at(-1);
        if(!node||!user()||!(user().compareDocumentPosition(node)&Node.DOCUMENT_POSITION_FOLLOWING))continue;
        const stop=[...document.querySelectorAll('button')].some(n=>visible(n)&&/stop (generating|response)|stop-button/i.test(`${n.getAttribute('aria-label')} ${n.getAttribute('data-testid')}`));
        const turn=node.closest('[data-talvt-turn-state],[data-testid^="conversation-turn-"],[data-content-search-unit-key]')||node;
        const complete=turn.getAttribute('data-talvt-turn-state')==='complete'||[...turn.querySelectorAll('[role="status"],[aria-live]')].some(n=>/response complete|phản hồi hoàn tất/i.test(text(n)))||[...turn.querySelectorAll('button')].some(n=>/good-response|bad-response|rate response/i.test(`${n.getAttribute('data-testid')} ${n.getAttribute('aria-label')}`));
        if(stop||!complete)continue;
        const codes=[...node.querySelectorAll('pre code')];if(codes.length>1)throw Error('Multiple reply blocks');
        const response=codes.length===1?codes[0].textContent:text(node.querySelector('.markdown,.prose,[data-markdown-text-style="assistant-message"]')||node).replace(/^ChatGPT said:\s*/u,'').trim();
        if(!response||response.length>700000)throw Error('Reply missing or too large');
        const accepted=await runtime({kind:'reply',id,attempt,text:response});if(!accepted){retired=true;return;}if(!accepted.ok)throw Error('Reply correlation rejected');return;
      }
      throw Error('Response completion not verifiable');
    })().catch(e=>{if(!retired)void error(message.id,message.attempt,e.message);});
  });
})();

(()=>{
  if(location.origin!=='https://chatgpt.com'||window.top!==window)return;
  const visible=n=>!!n?.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
  const editor=()=>[...document.querySelectorAll('#prompt-textarea,[contenteditable="true"][role="textbox"],textarea')].find(visible);
  const messages=role=>{
    const nodes=[...document.querySelectorAll(`[data-message-author-role="${role}"],[data-content-search-unit-key$=":${role}"],[data-chatgpt-search-unit-key$=":${role}"]`)].filter(visible);
    return nodes.filter(node=>!nodes.some(other=>other!==node&&other.contains(node)));
  };
  const user=()=>messages('user').at(-1);
  const assistants=()=>messages('assistant');
  const text=n=>n?.innerText?.trim()??n?.textContent?.trim()??'';
  const logicalText=n=>globalThis.VideoStudioLogicalText.logicalText(n);
  const userText=n=>logicalText(n?.querySelector('[data-user-message-bubble] .whitespace-pre-wrap,.whitespace-pre-wrap')||n).replace(/^You said:\s*/u,'').trim();
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  let retired=false,occupied=false;
  const runtime=async message=>{if(retired)return null;try{return await chrome.runtime.sendMessage(message);}catch(e){if(/Extension context invalidated|Receiving end does not exist/i.test(String(e?.message??e)))retired=true;return null;}};
  const error=async (id,attempt,reason)=>{await runtime({kind:'uncertain',id,attempt,reason});};
  const assistantText=node=>{const codes=[...node.querySelectorAll('pre code')];if(codes.length>1)return null;return (codes.length===1?codes[0].textContent:text(node.querySelector('.markdown,.prose,[data-markdown-text-style="assistant-message"]')||node)).replace(/^ChatGPT said:\s*/u,'').trim();};
  const generating=()=>[...document.querySelectorAll('button')].some(n=>visible(n)&&/stop (generating|response)|stop-button|dừng (tạo|phản hồi)/i.test(`${n.getAttribute('aria-label')} ${n.getAttribute('data-testid')}`));
  const completed=node=>{
    const turn=node.closest('[data-talvt-turn-state]')||node.closest('[data-testid^="conversation-turn-"]')||node;
    const state=turn.getAttribute('data-talvt-turn-state');
    if(state)return state==='complete';
    return [...turn.querySelectorAll('[role="status"],[aria-live]')].some(n=>/response complete|phản hồi hoàn tất/i.test(text(n)))||[...turn.querySelectorAll('button')].some(n=>/good-response|bad-response|rate response/i.test(`${n.getAttribute('data-testid')} ${n.getAttribute('aria-label')}`));
  };
  // ChatGPT may truncate or reflow a long user bubble; the immutable request line is
  // the correlation key, with a whitespace-normalised full-text fallback.
  const requestMarker=id=>`Y\u00caU C\u1ea6U STUDIO ${id}`;
  const normalise=s=>String(s||'').replace(/\u00a0/g,' ').replace(/\s+/g,' ').trim();
  const isReceipt=(node,id,prompt)=>{
    const value=userText(node);
    return value.includes(requestMarker(id))||normalise(value)===normalise(prompt);
  };
  // The delivery and reload paths share one correlation/completion rule.
  const inspect=(id,prompt)=>{
    const users=messages('user'),turn=users.at(-1),matches=users.filter(n=>isReceipt(n,id,prompt));
    const result={visibleUser:turn?userText(turn):null,visibleReply:null};
    if(matches.length>1)return {...result,blocked:'Duplicate immutable request marker'};
    if(matches.length!==1||turn!==matches[0]||generating())return result;
    const replies=assistants().filter(node=>turn.compareDocumentPosition(node)&Node.DOCUMENT_POSITION_FOLLOWING);
    if(replies.length!==1)return result;
    const node=replies[0];
    if(completed(node))result.visibleReply=assistantText(node)||null;
    return result;
  };
  chrome.runtime.onMessage.addListener((message,_sender,reply)=>{
    if(retired)return;
    if(message?.kind==='probe'){reply({ok:true});return;}
    if(message?.kind==='inspect'){reply(inspect(message.id,message.prompt));return;}
    if(message?.kind!=='deliver')return;
    if(occupied){reply({ok:false});return;}
    occupied=true;reply({ok:true});
    (async()=>{
      const {id,prompt,attempt}=message;
      if(typeof id!=='string'||!prompt.startsWith(`YÊU CẦU STUDIO ${id}\n`))throw Error('Immutable request marker missing');
      if(/login|auth|challenge|verify/i.test(location.pathname))throw Error('Login or verification required');
      if(user()||assistants().length)throw Error('Dedicated tab is not an empty conversation');
      let input;
      for(let i=0;i<120;i++){
        input=editor();if(input)break;
        if(/login|auth|challenge|verify/i.test(location.pathname))throw Error('Login or verification required');
        await wait(250);if(retired)return;
      }
      if(!input)throw Error('Composer unavailable or occupied');
      // Owner-requested: wipe any leftover draft in this tool-owned tab before a new
      // send, so a previous request's text can never block or pollute this one.
      let existing=logicalText(input).trim();
      if(existing){
        input.focus();
        for(let i=0;i<10&&logicalText(input).trim();i++){
          const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);
          document.execCommand('delete');
          await wait(100);if(retired)return;
        }
        existing=logicalText(input).trim();
        if(existing)throw Error('Composer could not be cleared; nothing sent');
      }
      // Do not change ChatGPT mode. If mode cannot be proved Chat, stop.
      const group=document.querySelector('[role="group"][aria-label="Composer mode"]');
      if(group){const chat=[...group.querySelectorAll('button')].find(n=>text(n)==='Chat');if(chat?.getAttribute('aria-pressed')!=='true')throw Error('Chat mode not confirmed');}
      else if(!/^(ask chatgpt|message chatgpt|hỏi chatgpt|nhắn tin cho chatgpt)$/i.test((input.getAttribute('aria-label')||input.getAttribute('placeholder')||input.querySelector('[data-placeholder]')?.getAttribute('data-placeholder')||'').trim()))throw Error('Chat mode unknown');
      input.focus();
      if(!existing||!existing.includes(requestMarker(id))){
      if(input.tagName==='TEXTAREA'){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,prompt);input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:prompt}));}
      else {const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);if(!document.execCommand('insertText',false,prompt))throw Error('Composer insertion failed');}
      }
      let button;
      for(let i=0;i<40;i++){
        await wait(200);if(retired)return;
        const form=input.closest('form');
        button=[...(form||document).querySelectorAll('button')].find(n=>visible(n)&&!n.disabled&&globalThis.VideoStudioSendButton.isSendButton(n.getAttribute('aria-label'),n.getAttribute('data-testid')));
        if(button&&normalise(logicalText(input))===normalise(prompt))break;
        button=null;
      }
      const diffAt=(a,b)=>{const x=normalise(a),y=normalise(b);let i=0;while(i<Math.min(x.length,y.length)&&x[i]===y[i])i++;return i;};
      // Chrome truncates very large execCommand insertions, so long prompts are
      // written in bounded chunks after selecting the whole composer.
      for(let attempt=0;attempt<2;attempt++){
        if(normalise(logicalText(input))===normalise(prompt))break;
        const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);
        if(attempt===0){document.execCommand('insertText',false,prompt);await wait(400);}
        else{for(let i=0;i<prompt.length;i+=1500){document.execCommand('insertText',false,prompt.slice(i,i+1500));await wait(80);if(retired)return;}}
        if(retired)return;
      }
      const got=logicalText(input);
      if(normalise(got)!==normalise(prompt))throw Error('Composer does not match immutable prompt (got '+normalise(got).length+'/'+normalise(prompt).length+' chars, first diff at '+diffAt(got,prompt)+')');
      if(!button)throw Error('Send button unavailable');
      // From here delivery is uncertain even if the tab reloads. Background persisted dispatching first.
      button.click();
      for(let i=0;i<80;i++){await wait(250);if(isReceipt(user(),id,prompt))break;}
      if(!isReceipt(user(),id,prompt))throw Error('Exact user-turn receipt missing');
      const sent=await runtime({kind:'sent',id,attempt});if(!sent){retired=true;return;}if(!sent.ok)throw Error('Background rejected send receipt');
      let previous=null;
      for(let i=0;i<720;i++){
        await wait(500);if(retired)return;
        const seen=inspect(id,prompt);if(seen.blocked)throw Error(seen.blocked);
        const response=seen.visibleReply;
        if(!response){previous=null;continue;}
        if(response!==previous){previous=response;continue;}
        if(!response||response.length>700000)throw Error('Reply missing or too large');
        const accepted=await runtime({kind:'reply',id,attempt,text:response});if(!accepted){retired=true;return;}if(!accepted.ok)throw Error('Reply correlation rejected');return;
      }
      throw Error('Response completion not verifiable');
    })().catch(e=>{if(!retired)void error(message.id,message.attempt,e.message);});
  });
})();

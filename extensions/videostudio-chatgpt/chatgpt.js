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
  const error=async (id,attempt,reason,send_attempted,composer_diagnostic)=>{await runtime({kind:'uncertain',id,attempt,reason,send_attempted,...(composer_diagnostic?{composer_diagnostic}:{})});};
  function composerMode(){
    const group=document.querySelector('[role="group"][aria-label="Composer mode"],[role="tablist"][aria-label="Composer mode"]');
    const buttons=[...(group||document).querySelectorAll('button,[role="tab"],[role="radio"]')].filter(visible);
    const chat=buttons.find(n=>/^(chat|trò chuyện)$/i.test(text(n))),work=buttons.find(n=>/^(work|công việc)$/i.test(text(n)));
    const selected=n=>!!n&&(['aria-pressed','aria-selected','aria-checked'].some(name=>n.getAttribute(name)==='true')||n.getAttribute('data-state')==='active');
    if(group||(chat&&work))return {mode:selected(chat)&&!selected(work)?'chat':selected(work)&&!selected(chat)?'work':'unknown',chat};
    const input=editor(),label=(input?.getAttribute('aria-label')||input?.getAttribute('placeholder')||input?.querySelector('[data-placeholder]')?.getAttribute('data-placeholder')||'').trim();
    return {mode:/^(ask chatgpt|message chatgpt|hỏi chatgpt|nhắn tin cho chatgpt)$/i.test(label)?'chat':'unknown',chat:null};
  }
  async function ensureChatMode(){
    const deadline=Date.now()+8000;let clicked=false,known=false;
    while(Date.now()<deadline){
      const state=composerMode();if(state.mode==='chat')return;
      known=known||!!state.chat;
      if(state.chat&&!state.chat.disabled&&state.chat.getAttribute('aria-disabled')!=='true'&&!clicked){clicked=true;state.chat.click();}
      await wait(150);if(retired)return;
    }
    throw Error(known?'Chat mode not confirmed':'Chat mode unknown');
  }
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
  const {requestMarker,normalise,receiptMatches}=globalThis.VideoStudioLogicalText;
  function composerMismatch(input,prompt,reason){
    const actual=normalise(logicalText(input)),expected=normalise(prompt);
    let index=0;while(index<Math.min(actual.length,expected.length)&&actual[index]===expected[index])index++;
    const context=value=>value.slice(Math.max(0,index-12),index+24);
    const codepoints=value=>Array.from(context(value),char=>'U+'+char.codePointAt(0).toString(16).toUpperCase().padStart(4,'0')).slice(0,40);
    // Keep only a bounded local excerpt. Never persist the complete prompt as a
    // diagnostic, or silently discard unexplained editor characters to send it.
    const html=input.innerHTML||'';
    const diagnostic={
      expected_length:expected.length,actual_length:actual.length,first_diff:index,
      expected_context:context(expected),actual_context:context(actual),
      expected_codepoints:codepoints(expected),actual_codepoints:codepoints(actual),
      rendered_length:normalise(input.innerText||'').length,textcontent_length:normalise(input.textContent||'').length,
      editor_html_excerpt:html.slice(Math.max(0,index-220),index+620),
      inline_nodes:[...input.querySelectorAll('a,span,br')].slice(0,8).map(node=>({
        tag:node.tagName,contenteditable:node.getAttribute('contenteditable'),aria_hidden:node.getAttribute('aria-hidden'),
        class_name:String(node.className||'').slice(0,100),text_excerpt:(node.textContent||'').slice(0,64),html_excerpt:node.outerHTML.slice(0,240),
      })),
    };
    const failure=Error(reason||'Composer does not match immutable prompt (got '+actual.length+'/'+expected.length+' chars, first diff at '+index+')');
    failure.composer_diagnostic=diagnostic;return failure;
  }
  const isReceipt=(node,id,prompt)=>receiptMatches(userText(node),id,prompt);
  // The delivery and reload paths share one correlation/completion rule.
  const inspect=(id,prompt)=>{
    const users=messages('user'),turn=users.at(-1),matches=users.filter(n=>isReceipt(n,id,prompt));
    const result={visibleUser:turn?userText(turn):null,visibleReply:null,conversationUrl:location.href};
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
    if(message?.kind==='inspect'){
      const seen=inspect(message.id,message.prompt);
      reply(message.match_only&&!receiptMatches(seen.visibleUser,message.id,message.prompt)?{visibleUser:null,visibleReply:null}:seen);return;
    }
    if(message?.kind!=='deliver')return;
    if(occupied){reply({ok:false});return;}
    occupied=true;reply({ok:true});
    let sendAttempted=false;
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
      // This is a fresh tool-owned tab. Select the visible Chat control once and
      // verify its real selection; never submit an unconfirmed Work request.
      await ensureChatMode();if(retired)return;
      input=editor();
      if(!input||logicalText(input).trim()||user()||assistants().length)throw Error('Composer unavailable or occupied');
      input.focus();
      if(!existing||!existing.includes(requestMarker(id))){
      if(input.tagName==='TEXTAREA'){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,prompt);input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:prompt}));}
      else {const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);document.execCommand('insertText',false,prompt);}
      }
      await wait(200);if(retired)return;
      /* TODO: restore and investigate prompt verification/repair tomorrow.
      // Original insertion guard:
      // if(!document.execCommand('insertText',false,prompt))throw Error('Composer insertion failed');
      for(let attempt=0;attempt<2;attempt++){
        if(normalise(logicalText(input))===normalise(prompt))break;
        const selection=getSelection(),range=document.createRange();range.selectNodeContents(input);selection.removeAllRanges();selection.addRange(range);
        if(attempt===0){document.execCommand('insertText',false,prompt);await wait(400);}
        else{for(let i=0;i<prompt.length;){let end=Math.min(i+1500,prompt.length);if(end<prompt.length&&/[\uD800-\uDBFF]/.test(prompt[end-1])&&/[\uDC00-\uDFFF]/.test(prompt[end]))end--;document.execCommand('insertText',false,prompt.slice(i,end));i=end;await wait(80);if(retired)return;}}
        if(retired)return;
      }
      const got=logicalText(input);
      if(normalise(got)!==normalise(prompt))throw composerMismatch(input,prompt);
      */
      // Input once, then click the current enabled Send control.
      const currentSend=()=>{
        const form=editor()?.closest('form');
        return [...(form||document).querySelectorAll('button')].find(n=>visible(n)&&!n.disabled&&n.getAttribute('aria-disabled')!=='true'&&globalThis.VideoStudioSendButton.isSendButton(n.getAttribute('aria-label'),n.getAttribute('data-testid')));
      };
      let button;
      for(let i=0;i<40;i++){
        button=currentSend();
        if(button)break;
        await wait(200);if(retired)return;
      }
      if(!button)throw Error('Send button unavailable');
      /* TODO: re-enable these pre-Send guards after investigating the editor.
      if(editor()!==input||normalise(logicalText(input))!==normalise(prompt))throw composerMismatch(editor()||input,prompt,'Composer changed before Send; nothing sent');
      if(composerMode().mode!=='chat')throw Error('Chat mode not confirmed');
      */
      // From here delivery is uncertain even if the tab reloads. Background persisted dispatching first.
      sendAttempted=true;
      button.click();
      const confirmed=await globalThis.VideoStudioSendButton.confirmSend({
        received:()=>!retired&&isReceipt(user(),id,prompt),
        // No length/full-text comparison: only identify our still-unsent draft.
        // A cleared composer, any turn or generation permanently disables retries.
        canRetry:()=>!retired&&!/login|auth|challenge|verify/i.test(location.pathname)&&!user()&&!assistants().length&&!generating()&&logicalText(editor()).trimStart().startsWith(`YÊU CẦU STUDIO ${id}\n`),
        click:()=>currentSend()?.click(),
        wait,
      });
      if(retired)return;
      if(!confirmed)throw Error('Exact user-turn receipt missing');
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
    })().catch(e=>{if(!sendAttempted)occupied=false;if(!retired)void error(message.id,message.attempt,e.message,sendAttempted,e.composer_diagnostic);});
  });
})();

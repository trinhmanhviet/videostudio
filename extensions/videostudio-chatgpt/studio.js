(()=>{
  const scope=location.pathname.match(/^\/story-video\/projects\/([0-9a-f-]{36})\/production$/i)?.[1];
  if(location.origin!=='http://localhost:8877'||(!scope&&location.pathname!=='/'))return;
  const root=document.createElement('aside');root.dataset.videostudioManager='';
  root.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483647;font:13px system-ui;max-width:calc(100vw - 24px)';
  const shadow=root.attachShadow({mode:'closed'});
  // Static markup only; server and worker values below always use textContent.
  shadow.innerHTML=`<style>
    :host{color-scheme:dark}*{box-sizing:border-box}[hidden]{display:none!important}
    section{background:#142620;color:#f4f9ef;border:1px solid #658366;border-radius:14px;box-shadow:0 3px 20px #0006;width:370px;max-width:calc(100vw - 24px);max-height:calc(100dvh - 24px);overflow:auto;padding:14px}
    header{display:flex;align-items:center;justify-content:space-between;gap:8px}h2{font-size:14px;margin:0}h3{font-size:13px;margin:0;overflow-wrap:anywhere}
    button{margin:3px 3px 3px 0;padding:8px 10px;border:1px solid #a9d890;border-radius:7px;background:#c3ed91;color:#152317;font:600 12px system-ui;cursor:pointer;min-height:34px}
    button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible{outline:3px solid #f8e580;outline-offset:2px}.secondary{background:transparent;color:#f4f9ef}
    #collapse{font-size:19px;line-height:1;padding:4px 10px}p{margin:8px 0;overflow-wrap:anywhere;line-height:1.4}.hint{font-size:11px;color:#bed0c1}
    article{border-top:1px solid #49644c;padding:11px 0 5px}article p{margin:5px 0}.error{color:#ffb7a8}.actions{display:flex;flex-wrap:wrap;gap:2px}
    #badge{position:relative;width:64px;height:64px;border-radius:50%;margin:0;box-shadow:0 3px 20px #0006;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px}
    #count{font-size:19px}#error-badge{position:absolute;right:-2px;top:-2px;border-radius:50%;min-width:20px;height:20px;padding:2px;background:#a62926;color:#fff;border:1px solid #ffb7a8}
  </style><section id="manager" role="region" aria-label="VideoStudio ChatGPT manager">
    <header><h2>VideoStudio · ChatGPT</h2><button id="collapse" class="secondary" aria-label="Collapse video manager" aria-controls="manager">−</button></header>
    <p id="status" role="status" aria-live="polite">Chưa kết nối.</p>
    <div class="actions"><button id="start">Start</button><button id="smoke">Test chữ</button><button id="stop" class="secondary">Stop</button></div>
    <p class="hint">Video xử lý lần lượt. Thu gọn vẫn giữ kết nối. Giữ tab Studio này mở.</p>
    <div id="sessions" role="list" aria-label="Video sessions"></div><p id="empty" class="hint">Chưa có video trong kết nối này.</p>
  </section><button id="badge" aria-label="Open video manager" aria-controls="manager" aria-expanded="false" hidden><span>VS</span><span id="count">0</span><span id="error-badge" hidden>!</span></button>`;
  document.documentElement.append(root);
  const $=selector=>shadow.querySelector(selector),status=$('#status'),startButton=$('#start'),smokeButton=$('#smoke'),stopButton=$('#stop');
  let active=false,busy=false,retired=false,collapsed=false,stopping=false,generation=0,sessions=[],slots=[];
  const intervals=[],listeners=[],cards=new Map(),errors=new Map(),working=new Set(),cancelledLocal=new Set();
  const terminal=item=>['failed','completed','cancelled','canceled'].includes(item?.state);
  const stateLabels={queued:'Đang xếp hàng',running:'Đang xử lý',retrying:'Đang chờ thử lại',failed:'Lỗi',completed:'Hoàn tất',cancelled:'Đã hủy',canceled:'Đã hủy'};
  const phaseLabels={claimed:'Đang chờ gửi',dispatching:'Đang gửi',sent:'Chờ phản hồi',reply:'Đã có phản hồi',uncertain:'Cần kiểm tra',failed:'Lỗi',pending:'Chờ phản hồi',retried:'Đã thử lại',receipt:'Đã nhận phản hồi',blocked:'Cần kiểm tra',exhausted:'Đã hết lượt thử',unresolved:'Chưa tìm thấy phản hồi','foreign-turn':'Cần kiểm tra đúng cuộc trò chuyện','human-or-invalid':'Cần kiểm tra trong ChatGPT'};
  const stageLabels={plan:'Lập kế hoạch',research:'Nghiên cứu',script:'Viết kịch bản',speech:'Tạo giọng đọc',images:'Tạo hình ảnh',subtitles:'Tạo phụ đề',music:'Tạo nhạc',render:'Kết xuất video',verify:'Kiểm tra video'};
  const phaseLabel=value=>phaseLabels[value]||'Chờ yêu cầu';
  try{collapsed=localStorage.getItem('videostudio_manager_collapsed')==='true';}catch{}
  function listen(node,type,fn){node.addEventListener(type,fn);listeners.push([node,type,fn]);}
  function setStatus(text){if(!retired)status.textContent=text;}
  function slotFor(target){return slots.find(slot=>slot.scope===target);}
  function displayFor(item){
    const slot=slotFor(item.scope),retained=slot?.retained?.find(saved=>saved.job_id===item.job_id);
    if(retained)return retained;
    // Root control smoke belongs to the connection, not its legacy video card.
    return slot?.job?.is_smoke||slot?.is_smoke?null:slot;
  }
  function render(){
    startButton.hidden=active;stopButton.hidden=!active;smokeButton.hidden=!active||!scope;
    startButton.disabled=smokeButton.disabled=stopButton.disabled=retired||stopping;
    $('#manager').hidden=collapsed;$('#badge').hidden=!collapsed;$('#badge').setAttribute('aria-expanded',String(!collapsed));
    const count=sessions.filter(item=>!terminal(item)&&!item.cancel_requested).length;
    const errorScopes=new Set(errors.keys());
    for(const item of sessions)if(item.error||displayFor(item)?.job?.reason)errorScopes.add(item.scope);
    for(const slot of slots)if((slot.is_smoke||slot.job?.is_smoke)&&slot.job?.reason)errorScopes.add(slot.scope);
    const errorCount=errorScopes.size;
    $('#count').textContent=String(count);$('#error-badge').hidden=!errorCount;
    $('#badge').setAttribute('aria-label',`Open video manager: ${count} active videos${errorCount?`, ${errorCount} errors`:''}${retired?', reload Studio required':''}`);
    $('#empty').hidden=sessions.length>0;const present=new Set();
    for(const item of sessions){
      present.add(item.scope);let card=cards.get(item.scope);
      if(!card){
        const node=document.createElement('article');node.dataset.sessionScope=item.scope;node.setAttribute('role','listitem');
        const title=document.createElement('h3'),pipeline=document.createElement('p'),phase=document.createElement('p'),error=document.createElement('p'),actions=document.createElement('div');
        error.className='error';actions.className='actions';const buttons={};
        for(const [kind,label] of [['open_chat','Mở chat'],['reconcile','Kiểm tra lại'],['cancel_session','Hủy']]){
          const button=document.createElement('button');button.className='secondary';button.textContent=label;
          listen(button,'click',event=>{if(event.isTrusted)void sessionAction(kind,item.scope);});actions.append(button);buttons[kind]=button;
        }
        node.append(title,pipeline,phase,error,actions);$('#sessions').append(node);card={node,title,pipeline,phase,error,buttons};cards.set(item.scope,card);
      }
      const slot=displayFor(item),job=slot?.job;
      card.node.dataset.requestId=job?.id||'';card.node.dataset.pipelineState=item.state||'';card.node.dataset.phase=job?.phase||'';
      card.title.textContent=item.title||item.job_id||'Video';
      card.pipeline.textContent=`${item.project?item.project+' · ':''}${stateLabels[item.state]||'Chưa rõ trạng thái'}${stageLabels[item.stage]?' · '+stageLabels[item.stage]:''}`;
      card.phase.textContent=item.cancel_requested?'Đã yêu cầu hủy; dừng chờ cục bộ.':job?`ChatGPT: ${phaseLabel(job.phase)}`:slot?.lastReceipt?'ChatGPT: Đã nhận phản hồi.':terminal(item)?'ChatGPT: lưu phiên trước.':'ChatGPT: chờ yêu cầu · hàng đợi xử lý lần lượt.';
      card.error.textContent=errors.get(item.scope)||item.error||job?.reason||'';card.error.hidden=!card.error.textContent;
      const unavailable=retired||working.has(item.scope);
      const chatTab=job?.chatTab??slot?.chatTab;
      card.buttons.open_chat.disabled=unavailable||!Number.isInteger(chatTab)||!slot?.ownedTabs?.includes(chatTab);
      card.buttons.reconcile.disabled=unavailable||!job||!!slot?.cancelled;
      card.buttons.cancel_session.disabled=unavailable||terminal(item)||!!item.cancel_requested;
    }
    for(const [key,card] of cards)if(!present.has(key)){card.node.remove();cards.delete(key);}
  }
  function collapse(value){collapsed=value;try{localStorage.setItem('videostudio_manager_collapsed',String(value));}catch{}render();(value?$('#badge'):$('#collapse')).focus();}
  listen($('#collapse'),'click',()=>collapse(true));listen($('#badge'),'click',()=>collapse(false));
  listen($('#manager'),'keydown',event=>{if(event.key==='Escape'){event.preventDefault();collapse(true);}});
  function retire(){
    if(retired)return;retired=true;active=false;render();for(const timer of intervals)clearInterval(timer);
    for(const [node,type,handler] of listeners)node.removeEventListener(type,handler);
    try{chrome.runtime.onMessage.removeListener(onReply);}catch{}
    status.textContent='Tiện ích đã tải lại. Tải lại trang Studio một lần.';$('#badge').title=status.textContent;
  }
  const invalid=error=>/Extension context invalidated|Receiving end does not exist|Cannot access a chrome\.runtime/i.test(String(error?.message??error));
  const send=async message=>{
    if(retired)return {ok:false,error:'Extension context invalidated'};
    try{const response=await chrome.runtime.sendMessage(message);if(response?.transient){const error=Error(response.error);error.transient=true;throw error;}return response;}
    catch(error){if(invalid(error)){retire();return {ok:false,error:'Extension context invalidated'};}throw error;}
  };
  const requireReply=async message=>{const response=await send(message);if(!response?.ok)throw Error(response?.error||'Extension did not respond');return response;};
  const api=async(path,options)=>{
    let response;try{response=await fetch(path,{credentials:'same-origin',signal:AbortSignal.timeout(15000),...options});}catch(error){error.transient=true;throw error;}
    if(!response.ok){const error=Error(`Studio HTTP ${response.status}`);error.transient=response.status>=500||[408,429].includes(response.status);throw error;}
    return response.json();
  };
  async function heartbeat(){
    if(!scope||retired)return;
    try{await api('/api/connector/status/'+scope,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({build:'videostudio-extension-0.3.0',stage:active?'active':'stopped',connected:active,enabled:active})});}
    catch(error){if(active)showError(error);}
  }
  function hydrate(state){active=state.active===true;slots=Array.isArray(state.sessions)?state.sessions:state.job?[{scope,job:state.job}]:[];render();}
  async function loadSessions(){const result=await api(`/api/connector/bridges/${scope}/sessions`);if(Array.isArray(result.items))sessions=result.items;render();}
  async function syncCancellations(started){
    for(const item of sessions){
      if(retired||started!==generation)break;
      const key=`${item.scope}:${item.job_id}`,video=displayFor(item);
      if(!(item.cancel_requested||['cancelled','canceled'].includes(item.state))||video?.cancelled||cancelledLocal.has(key)||working.has(item.scope))continue;
      try{
        // A POST can commit even when its response is lost. Server state repairs
        // local waiting, including a retained root video beside a control smoke.
        await requireReply({kind:'cancel_session',scope:item.scope,job_id:item.job_id});
        cancelledLocal.add(key);if(video)video.cancelled=true;errors.delete(item.scope);
      }catch(error){showError(error,item.scope);}
    }
  }
  async function importReply(target,job){
    const base=`/api/v1/projects/${target}/runs/${target}/chatgpt-exchanges`,receipt=await api(`${base}/${encodeURIComponent(job.id)}`);
    if(receipt.id!==job.id||receipt.version!==job.version)throw Error('Receipt correlation mismatch');
    if(!receipt.accepted){
      const answer=await api(`${base}/${encodeURIComponent(job.id)}/response`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:job.version,response_text:typeof job.text==='string'?job.text:JSON.stringify(job.text)})});
      if(answer.id!==job.id||answer.version!==job.version||answer.accepted!==true)throw Error('Import receipt mismatch');
    }
    await requireReply({kind:'imported',scope:target,id:job.id,version:job.version,accepted:true});setStatus('Đã nhận phản hồi ChatGPT.');
  }
  function showError(error,target){if(retired)return;const text=error.transient?'Mất kết nối Studio; đang tự kết nối lại.':error.message;errors.set(target||'connection',text);if(!target||target===scope)setStatus(text);render();}
  async function tick(){
    if(!active||busy||retired||!scope)return;busy=true;const started=generation;
    try{
      const state=await requireReply({kind:'snapshot'});if(started!==generation)return;hydrate(state);if(!active){setStatus('Đã dừng');return;}
      await loadSessions();await syncCancellations(started);
      const pending=await api(`/api/connector/bridges/${scope}/pending`),handled=new Set();
      if(errors.delete('connection'))setStatus('Đã kết nối');
      for(const slot of slots){
        if(retired||!active||started!==generation)break;const target=slot.scope,job=slot.job,item=sessions.find(item=>item.scope===target);
        const smoke=target===scope&&(job?.is_smoke===true||slot.is_smoke===true||(pending.items||[]).some(request=>request.is_smoke===true&&request.scope===scope&&request.id===job?.id&&request.version===job?.version));
        if(!job||slot.cancelled||(!smoke&&(item?.cancel_requested||terminal(item)))||working.has(target)||(target!==scope&&!item))continue;
        handled.add(target);
        try{
          if(smoke)setStatus(`Test chữ: ${phaseLabel(job.phase)}${job.reason?' · '+job.reason:''}`);
          if(job.phase==='reply')await importReply(target,job);
          else if(job.phase==='claimed')await requireReply({kind:'claim',scope:target,job_id:smoke?null:item?.job_id,is_smoke:smoke,id:job.id,version:job.version,prompt:job.prompt});
          else if(['uncertain','sent','dispatching'].includes(job.phase)){
            const result=await requireReply({kind:'reconcile',scope:target});
            if(smoke)setStatus(`Test chữ: ${phaseLabel(result.status)}${job.reason?' · '+job.reason:''}`);
          }
          errors.delete(target);
        }catch(error){showError(error,target);}
      }
      for(const item of pending.items||[]){
        if(retired||!active||started!==generation)break;const target=item.scope||scope,session=sessions.find(session=>session.scope===target);
        const smoke=target===scope&&item.is_smoke===true;
        if(handled.has(target)||working.has(target)||(!smoke&&(terminal(session)||session?.cancel_requested))||(target!==scope&&!session))continue;
        try{
          if(!item.id||!Number.isInteger(item.version)||typeof item.prompt!=='string'||item.attachments?.length)throw Error('Unsupported request shape/attachments');
          const result=await requireReply({kind:'claim',scope:target,job_id:item.job_id,is_smoke:smoke,id:item.id,version:item.version,prompt:item.prompt});
          if(smoke)setStatus(`Test chữ: ${phaseLabel(result.phase)}`);errors.delete(target);handled.add(target);
        }catch(error){showError(error,target);}
      }
      render();
    }catch(error){showError(error);}finally{busy=false;}
  }
  async function sessionAction(kind,target){
    if(retired||working.has(target))return;const item=sessions.find(item=>item.scope===target);if(!item)return;working.add(target);render();
    try{
      if(kind==='cancel_session'){
        const updated=await api(`/api/connector/bridges/${scope}/jobs/${encodeURIComponent(item.job_id)}/cancel`,{method:'POST'});
        if((updated.scope&&updated.scope!==target)||(updated.job_id&&updated.job_id!==item.job_id))throw Error('Cancellation scope/job mismatch');
        // The server owns job state; worker cancellation stops only local waiting/tabs.
        Object.assign(item,updated);await requireReply({kind,scope:target,job_id:item.job_id});cancelledLocal.add(`${target}:${item.job_id}`);
        setStatus('Đã yêu cầu hủy video và dừng chờ cục bộ. Tác vụ trên ChatGPT có thể vẫn tiếp tục.');
      }else{
        const id=displayFor(item)?.job?.id;
        const result=await requireReply({kind,scope:target,job_id:item.job_id,id,...(kind==='reconcile'?{inspect_only:true}:{})});
        hydrate(await requireReply({kind:'snapshot'}));
        if(kind==='reconcile')setStatus(`Kiểm tra yêu cầu cũ: ${phaseLabel(result.status)}`);
      }
      errors.delete(target);
    }catch(error){showError(error,target);}finally{working.delete(target);render();}
  }
  listen(startButton,'click',async event=>{
    if(!event.isTrusted||active||retired)return;
    try{
      let target=scope;
      if(!target){const session=await api('/api/connector/sessions',{method:'POST'});if(session.project_id!==session.run_id||session.url!==`/story-video/projects/${session.project_id}/production`)throw Error('Invalid connector scope');target=session.project_id;}
      await requireReply({kind:'start',scope:target});active=true;render();setStatus('Đã kết nối');await heartbeat();
      if(!scope){location.assign(`/story-video/projects/${target}/production`);return;}await tick();
    }catch(error){if(!retired)setStatus(`Không thể Start: ${error.message}`);}
  });
  listen(smokeButton,'click',async event=>{if(!event.isTrusted||!active||!scope||retired)return;try{await api('/api/connector/smoke/'+scope,{method:'POST'});setStatus('Test chữ đã xếp hàng.');await tick();}catch(error){showError(error);}});
  listen(stopButton,'click',async event=>{
    if(!event.isTrusted||retired||stopping)return;
    generation++;stopping=true;active=false;render();
    try{await requireReply({kind:'stop'});await heartbeat();setStatus('Đã dừng kết nối và đóng tab ChatGPT thuộc tiện ích.');}
    catch(error){showError(error);}
    finally{stopping=false;render();}
  });
  function onReply(message,_sender,reply){if(message?.kind!=='reply'||retired)return;if(active)void tick().catch(()=>{});reply({ok:true});}
  chrome.runtime.onMessage.addListener(onReply);
  intervals.push(setInterval(()=>{void tick().catch(()=>{});},1200));intervals.push(setInterval(()=>{if(active)void heartbeat().catch(()=>{});},10000));
  listen(document,'visibilitychange',()=>{if(document.visibilityState==='visible'&&active&&!retired)void heartbeat().then(()=>tick()).catch(()=>{});});
  render();
  if(scope)void requireReply({kind:'snapshot'}).then(async state=>{if(retired)return;hydrate(state);setStatus(active?'Đã kết nối':'Đã dừng');if(active){await heartbeat();void tick();}else await loadSessions();}).catch(error=>showError(error));
})();

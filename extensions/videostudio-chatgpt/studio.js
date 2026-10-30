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
    [data-chat-recovery]{margin-top:8px;padding:10px;border:1px solid #658366;border-radius:9px;background:#1b3026}[data-chat-recovery] label{display:block;font-size:12px}[data-chat-recovery] input{display:block;width:100%;min-width:0;margin:7px 0;padding:9px;border:1px solid #658366;border-radius:6px;background:#101d17;color:#f4f9ef;font:12px system-ui}
    [data-browser-profile],[data-flow-account]{margin-top:8px;padding:10px;border:1px solid #658366;border-radius:9px;background:#1b3026}summary{cursor:pointer;min-height:28px;font-weight:600}summary:focus-visible{outline:3px solid #f8e580}ol{padding-left:20px;line-height:1.5;margin:7px 0}
    #badge{position:relative;width:64px;height:64px;border-radius:50%;margin:0;box-shadow:0 3px 20px #0006;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px}
    #count{font-size:19px}#error-badge{position:absolute;right:-2px;top:-2px;border-radius:50%;min-width:20px;height:20px;padding:2px;background:#a62926;color:#fff;border:1px solid #ffb7a8}
    #dismiss-dialog:focus{outline:none}#dismiss-dialog label{display:flex;align-items:flex-start;gap:8px;line-height:1.5;margin:12px 0}#dismiss-files{margin-top:4px;accent-color:#c3ed91}#dismiss-confirm[data-destructive="true"]{background:#ffb7a8;border-color:#ffb7a8}#dismiss-video{font-weight:600}
  </style><section id="manager" role="region" aria-label="VideoStudio ChatGPT manager">
    <div id="manager-content">
    <header><h2>VideoStudio · ChatGPT</h2><button id="collapse" class="secondary" aria-label="Collapse video manager" aria-controls="manager">−</button></header>
    <p id="status" role="status" aria-live="polite">Chưa kết nối.</p>
    <div class="actions"><button id="start">Start</button><button id="smoke">Test chữ</button><button id="stop" class="secondary">Stop</button></div>
    <p class="hint">Video xử lý lần lượt. Thu gọn vẫn giữ kết nối. Giữ tab Studio này mở.</p>
    <details data-browser-profile><summary>Chrome riêng · Google Flow</summary>
      <p id="browser-state" role="status" aria-live="polite">Đang kiểm tra Chrome riêng…</p>
      <div class="actions"><button id="browser-clean" class="secondary">Mở sạch</button><button id="browser-debug">Mở debug</button><button id="browser-stop" class="secondary">Tắt Chrome riêng</button><button id="browser-refresh" class="secondary">Kiểm tra Chrome</button></div>
      <p class="hint">Mở sạch để đăng nhập Google; mở debug để tạo ảnh. Cùng một profile, giữ tài khoản và dữ liệu. Đổi chế độ sẽ đóng cửa sổ Chrome riêng hiện tại.</p><p id="browser-error" class="error" role="alert" hidden></p>
    </details>
    <div id="sessions" role="list" aria-label="Video sessions"></div><p id="empty" class="hint">Chưa có video trong kết nối này.</p>
    </div><div id="dismiss-dialog" role="dialog" aria-modal="true" aria-labelledby="dismiss-title" aria-describedby="dismiss-video dismiss-warning" tabindex="-1" hidden>
      <h2 id="dismiss-title">Xóa phiên video?</h2><p id="dismiss-video"></p>
      <label><input id="dismiss-files" type="checkbox">Xóa cả file đã tạo</label>
      <p id="dismiss-warning">Giữ lại các file đã tạo. Chỉ xóa phiên khỏi danh sách này.</p>
      <p id="dismiss-error" class="error" role="alert" hidden></p>
      <div class="actions"><button id="dismiss-confirm">Xóa phiên, giữ file</button><button id="dismiss-cancel" class="secondary">Quay lại</button></div>
    </div>
  </section><button id="badge" aria-label="Open video manager" aria-controls="manager" aria-expanded="false" hidden><span>VS</span><span id="count">0</span><span id="error-badge" hidden>!</span></button>`;
  document.documentElement.append(root);
  const runtimeVersion=chrome.runtime.getManifest?.().version;
  if(runtimeVersion)shadow.querySelector('h2').textContent='VideoStudio · ChatGPT '+runtimeVersion;
  const $=selector=>shadow.querySelector(selector),status=$('#status'),startButton=$('#start'),smokeButton=$('#smoke'),stopButton=$('#stop');
  let active=false,busy=false,retired=false,collapsed=false,stopping=false,starting=false,generation=0,sessions=[],slots=[],dismissal=null;
  const intervals=[],listeners=[],cards=new Map(),errors=new Map(),working=new Set(),cancelledLocal=new Set(),reportedDiagnostics=new Set(),autoChecked=new Map(),autoResumed=new Set();
  const recoveries=new Map(),flowAccounts=new Map();
  let browserProfile=null,browserBusy=false,browserReading=false,browserError='';
  const terminal=item=>['failed','completed','cancelled','canceled'].includes(item?.state);
  const cancelled=item=>item?.cancel_requested||['cancelled','canceled'].includes(item?.state);
  const stateLabels={queued:'Đang xếp hàng',running:'Đang xử lý',awaiting_flow_account:'Chờ đổi tài khoản Flow',retrying:'Đang chờ thử lại',failed:'Lỗi',completed:'Hoàn tất',cancelled:'Đã hủy',canceled:'Đã hủy'};
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
    renderBrowser();
    if(dismissal&&!dismissal.pending&&!sessions.some(item=>item.scope===dismissal.scope&&item.job_id===dismissal.job_id))dismissal=null;
    $('#manager-content').hidden=!!dismissal;$('#dismiss-dialog').hidden=!dismissal;
    if(dismissal){
      $('#dismiss-video').textContent=dismissal.title;$('#dismiss-files').checked=dismissal.deleteFiles;
      $('#dismiss-warning').textContent=dismissal.deleteFiles?'Xóa các file đã tạo của video này. Thao tác này không thể hoàn tác.':'Giữ lại các file đã tạo. Chỉ xóa phiên khỏi danh sách này.';
      $('#dismiss-error').textContent=dismissal.error;$('#dismiss-error').hidden=!dismissal.error;
      $('#dismiss-confirm').textContent=dismissal.pending?'Đang xóa…':dismissal.deleteFiles?'Xóa phiên và file':'Xóa phiên, giữ file';
      $('#dismiss-confirm').dataset.destructive=String(dismissal.deleteFiles);
      $('#dismiss-files').disabled=$('#dismiss-confirm').disabled=$('#dismiss-cancel').disabled=retired||dismissal.pending;
    }
    startButton.hidden=active;stopButton.hidden=!active;smokeButton.hidden=!active||!scope;
    startButton.disabled=smokeButton.disabled=stopButton.disabled=retired||stopping||starting;
    $('#manager').hidden=collapsed;$('#badge').hidden=!collapsed;$('#badge').setAttribute('aria-expanded',String(!collapsed));
    const visibleSessions=sessions.filter(item=>!cancelled(item));
    const count=visibleSessions.filter(item=>!terminal(item)).length;
    const hiddenScopes=new Set(sessions.filter(cancelled).map(item=>item.scope));
    const errorScopes=new Set([...errors.keys()].filter(key=>!hiddenScopes.has(key)));
    for(const [target,f] of flowAccounts)if(!hiddenScopes.has(target)&&(f.error||f.state?.phase==='error'))errorScopes.add(target);
    for(const item of visibleSessions)if(item.error||displayFor(item)?.job?.reason)errorScopes.add(item.scope);
    for(const slot of slots)if((slot.is_smoke||slot.job?.is_smoke)&&slot.job?.reason)errorScopes.add(slot.scope);
    const errorCount=errorScopes.size;
    $('#count').textContent=String(count);$('#error-badge').hidden=!errorCount;
    $('#badge').setAttribute('aria-label',`Open video manager: ${count} active videos${errorCount?`, ${errorCount} errors`:''}${retired?', reload Studio required':''}`);
    $('#empty').hidden=visibleSessions.length>0;const present=new Set();
    for(const item of visibleSessions){
      present.add(item.scope);let card=cards.get(item.scope);
      if(!card){
        const node=document.createElement('article');node.dataset.sessionScope=item.scope;node.setAttribute('role','listitem');
        const title=document.createElement('h3'),pipeline=document.createElement('p'),phase=document.createElement('p'),error=document.createElement('p'),actions=document.createElement('div');
        error.className='error';actions.className='actions';const buttons={};
        for(const [kind,label] of [['open_chat','Mở chat'],['reconcile','Kiểm tra lại'],['recover_chat','Khôi phục ChatGPT'],['flow_account','Đổi tài khoản Flow'],['cancel_session','Hủy'],['dismiss_session','×']]){
          const button=document.createElement('button');button.className='secondary';button.textContent=label;
          listen(button,'click',event=>{if(event.isTrusted){if(kind==='dismiss_session')openDismiss(item.scope);else if(kind==='recover_chat')openRecovery(item.scope);else if(kind==='flow_account')openFlowAccount(item.scope);else void sessionAction(kind,item.scope);}});actions.append(button);buttons[kind]=button;
        }
        const panel=document.createElement('div'),notice=document.createElement('p'),label=document.createElement('label'),urlInput=document.createElement('input'),retry=document.createElement('button'),open=document.createElement('button'),close=document.createElement('button');
        panel.dataset.chatRecovery='';panel.hidden=true;panel.setAttribute('role','group');panel.setAttribute('aria-label','Khôi phục kết nối ChatGPT');notice.setAttribute('role','status');notice.setAttribute('aria-live','polite');
        label.textContent='URL cuộc trò chuyện ChatGPT (nếu cần)';urlInput.type='url';urlInput.placeholder='https://chatgpt.com/c/...';label.append(urlInput);
        retry.textContent='Thử khôi phục';open.textContent='Mở ChatGPT';close.textContent='Đóng';open.className=close.className='secondary';
        listen(urlInput,'input',event=>{const r=recoveries.get(item.scope);if(event.isTrusted&&r)r.url=urlInput.value;});
        listen(retry,'click',event=>{if(event.isTrusted)void repairChat(item.scope);});
        listen(open,'click',event=>{if(event.isTrusted)void sessionAction('open_chat',item.scope);});
        listen(close,'click',event=>{if(event.isTrusted){const r=recoveries.get(item.scope);if(r)r.open=false;render();}});
        const flow=document.createElement('div');flow.dataset.flowAccount='';flow.hidden=true;flow.setAttribute('role','group');flow.setAttribute('aria-label','Đổi tài khoản Flow cho video');
        const flowNotice=document.createElement('p'),flowCounts=document.createElement('p'),flowHelp=document.createElement('p'),flowError=document.createElement('p'),flowPrepare=document.createElement('button'),flowContinue=document.createElement('button'),flowRefresh=document.createElement('button'),flowClose=document.createElement('button');
        flowNotice.setAttribute('role','status');flowNotice.setAttribute('aria-live','polite');flowError.className='error';flowError.setAttribute('role','alert');flowCounts.className=flowHelp.className='hint';
        flowPrepare.textContent='Chuẩn bị đổi tài khoản';flowContinue.textContent='Tiếp tục video này';flowRefresh.textContent='Kiểm tra trạng thái';flowClose.textContent='Đóng';flowRefresh.className=flowClose.className='secondary';
        listen(flowPrepare,'click',event=>{if(event.isTrusted)void flowAccountRequest(item.scope,'prepare');});listen(flowContinue,'click',event=>{if(event.isTrusted)void flowAccountRequest(item.scope,'continue');});
        listen(flowRefresh,'click',event=>{if(event.isTrusted)void flowAccountRequest(item.scope);});listen(flowClose,'click',event=>{if(event.isTrusted){const f=flowAccounts.get(item.scope);if(f)f.open=false;render();}});
        flow.append(flowNotice,flowCounts,flowHelp,flowError,flowPrepare,flowContinue,flowRefresh,flowClose);
        panel.append(notice,label,retry,open,close);node.append(title,pipeline,phase,error,actions,panel,flow);$('#sessions').append(node);card={node,title,pipeline,phase,error,buttons,recovery:{panel,notice,urlInput,retry,open,close},flow:{panel:flow,notice:flowNotice,counts:flowCounts,help:flowHelp,error:flowError,prepare:flowPrepare,continue:flowContinue,refresh:flowRefresh,close:flowClose}};cards.set(item.scope,card);
      }
      const slot=displayFor(item),job=slot?.job;
      card.node.dataset.requestId=job?.id||'';card.node.dataset.pipelineState=item.state||'';card.node.dataset.phase=job?.phase||'';
      card.title.textContent=item.title||item.job_id||'Video';
      card.pipeline.textContent=`${item.project?item.project+' · ':''}${stateLabels[item.state]||'Chưa rõ trạng thái'}${stageLabels[item.stage]?' · '+stageLabels[item.stage]:''}`;
      card.phase.textContent=item.cancel_requested?'Đã yêu cầu hủy; dừng chờ cục bộ.':job?`ChatGPT: ${phaseLabel(job.phase)}`:slot?.lastReceipt?'ChatGPT: Đã nhận phản hồi.':terminal(item)?'ChatGPT: lưu phiên trước.':'ChatGPT: chờ yêu cầu · hàng đợi xử lý lần lượt.';
      card.error.textContent=errors.get(item.scope)||item.error||job?.reason||'';card.error.hidden=!card.error.textContent;
      const unavailable=retired||working.has(item.scope);
      const chatTab=job?.recovery_tab??job?.chatTab??slot?.chatTab;
      card.buttons.open_chat.disabled=unavailable||!Number.isInteger(chatTab)||!slot?.ownedTabs?.includes(chatTab);
      card.buttons.reconcile.disabled=unavailable||!job||!!slot?.cancelled;
      const canRecover=!!job||!!slot?.lastReceipt?.accepted;
      card.buttons.recover_chat.hidden=cancelled(item)||item.state==='completed'||!['plan','research','script'].includes(item.stage);
      card.buttons.recover_chat.disabled=unavailable||!active||!canRecover||!!slot?.cancelled;
      const recovery=recoveries.get(item.scope),view=card.recovery;
      view.panel.hidden=!recovery?.open;
      if(recovery){
        view.notice.textContent=recovery.message;view.urlInput.value=recovery.url;
        view.urlInput.disabled=view.retry.disabled=unavailable||recovery.pending||!canRecover;
        view.retry.textContent=recovery.pending?'Đang khôi phục…':'Thử khôi phục';
        view.open.disabled=card.buttons.open_chat.disabled;view.close.disabled=recovery.pending;
      }
      card.buttons.flow_account.hidden=item.image_provider!=='flow'||item.state==='completed';
      card.buttons.flow_account.disabled=unavailable;
      let f=flowAccounts.get(item.scope);
      if(f?.job_id!==item.job_id){flowAccounts.delete(item.scope);f=null;}
      if(!f&&item.image_provider==='flow'&&item.state==='awaiting_flow_account'){f={job_id:item.job_id,open:true,pending:false,state:null,error:''};flowAccounts.set(item.scope,f);}
      const flow=card.flow;flow.panel.hidden=!f?.open||item.image_provider!=='flow';
      if(f){
        const state=f.state,phase=state?.phase;
        flow.notice.textContent=f.pending&&!state?'Đang kiểm tra trạng thái video…':state?.message||'Đang kiểm tra trạng thái đổi tài khoản…';
        flow.counts.hidden=!['ready','running'].includes(phase)||!Number.isFinite(state?.cached_count)||!Number.isFinite(state?.total);
        flow.counts.textContent=`Đã giữ ${state?.cached_count}/${state?.total} ảnh · còn ${state?.missing_count} ảnh.`;
        flow.help.textContent=['pausing','reconciling'].includes(phase)?'Đang chờ bước hiện tại kết thúc và đối chiếu ảnh. Giữ Studio mở; chưa đổi chế độ Chrome.':phase==='ready'?'1. Mở sạch ở mục Chrome riêng và đăng nhập Google. 2. Mở debug. 3. Bấm Tiếp tục video này để tạo các ảnh còn thiếu.':phase==='running'?'Video này đã tiếp tục theo xác nhận của Studio.':'Chuẩn bị để dừng an toàn và kiểm tra ảnh đã có. Giữ nguyên video này; không cần tạo video mới.';
        flow.error.textContent=f.error;flow.error.hidden=!f.error;
        flow.prepare.disabled=retired||unavailable||f.pending||state?.can_prepare!==true;
        flow.continue.disabled=retired||unavailable||f.pending||state?.can_continue!==true||phase!=='ready'||browserBusy||browserProfile?.mode!=='debug'||browserProfile?.debug_ready!==true;
        flow.refresh.disabled=retired||f.pending;flow.close.disabled=f.pending;
      }
      card.buttons.cancel_session.disabled=unavailable||terminal(item)||!!item.cancel_requested;
      card.buttons.dismiss_session.hidden=!terminal(item);card.buttons.dismiss_session.disabled=unavailable;
      card.buttons.dismiss_session.setAttribute('aria-label','Xóa phiên '+(item.title||'video'));
    }
    for(const [key,card] of cards)if(!present.has(key)){
      for(let i=listeners.length-1;i>=0;i--)if(card.node.contains(listeners[i][0])){const [node,type,handler]=listeners[i];node.removeEventListener(type,handler);listeners.splice(i,1);}
      card.node.remove();cards.delete(key);recoveries.delete(key);flowAccounts.delete(key);
    }
  }
  function renderBrowser(){
    const state=browserProfile,handoffPending=[...flowAccounts.values()].some(f=>['pausing','reconciling'].includes(f.state?.phase));
    $('#browser-state').textContent=browserBusy?'Đang thay đổi Chrome riêng…':!state?'Chưa đọc được trạng thái Chrome riêng.':state.mode==='clean'?'Đang mở sạch để đăng nhập. Chọn Mở debug trước khi dùng Flow.':state.mode==='debug'?(state.debug_ready?'Đang mở debug · sẵn sàng cho tool điều khiển.':'Đang mở debug · chờ kết nối sẵn sàng.'):'Chrome riêng đang tắt.';
    if(handoffPending||state?.can_change===false)$('#browser-state').textContent+=' Chờ video dừng an toàn và đối chiếu ảnh; nếu có tác vụ ảnh khác đang chạy, chờ tác vụ đó kết thúc.';
    for(const id of ['clean','debug','stop'])$('#browser-'+id).disabled=retired||browserBusy||handoffPending||!state||state.can_change!==true||state.busy===true||(id==='stop'&&state.running===false);
    $('#browser-refresh').disabled=retired||browserBusy||browserReading;
    $('#browser-error').textContent=browserError;$('#browser-error').hidden=!browserError;
  }
  async function refreshBrowser(){
    if(retired||browserBusy||browserReading)return;browserReading=true;
    try{browserProfile=await api('/api/browser/profile');browserError='';}catch(error){browserError=error.message;}
    finally{browserReading=false;render();}
  }
  async function controlBrowser(mode){
    if(retired||browserBusy)return;browserBusy=true;browserError='';render();
    try{browserProfile=await api('/api/browser/profile/'+(mode==='stop'?'stop':'open'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mode==='stop'?{}:{mode})});}
    catch(error){browserError=error.message;}finally{browserBusy=false;render();}
  }
  function openFlowAccount(target){
    const item=sessions.find(item=>item.scope===target);if(retired||!item||item.image_provider!=='flow'||cancelled(item))return;
    const saved=flowAccounts.get(target);
    if(saved?.job_id===item.job_id)saved.open=true;else flowAccounts.set(target,{job_id:item.job_id,open:true,pending:false,state:null,error:''});
    render();void flowAccountRequest(target);
  }
  async function flowAccountRequest(target,action){
    const item=sessions.find(item=>item.scope===target),f=flowAccounts.get(target);
    if(retired||!item||cancelled(item)||!f||f.pending||f.job_id!==item.job_id)return;
    f.pending=true;if(action)f.error='';render();
    try{
      const state=await api('/api/jobs/'+encodeURIComponent(item.job_id)+'/flow-account'+(action?'/'+action:''),{headers:{'X-Connector-Scope':scope,...(action?{'Content-Type':'application/json'}:{})},...(action?{method:'POST',body:'{}'}:{})});
      if(retired||flowAccounts.get(target)!==f||cancelled(item))return;
      const phase=f.state?.phase;f.state=state;if(action||!f.errorAction||phase!==state.phase){f.error='';f.errorAction='';}
      if(phase!==state.phase||action)await refreshBrowser();
      if(action==='prepare'||action==='continue')await loadSessions();
    }catch(error){f.error=error.message;f.errorAction=action||'';}
    finally{f.pending=false;render();}
  }
  async function pollFlowAccounts(){
    if(retired)return;
    for(const [target,f] of flowAccounts)if(f.open||['pausing','reconciling','ready'].includes(f.state?.phase))await flowAccountRequest(target);
  }
  function openRecovery(target){
    if(retired||working.has(target))return;
    const item=sessions.find(item=>item.scope===target),job=item&&displayFor(item)?.job;
    recoveries.set(target,{open:true,pending:false,url:job?.conversation_url||'',requestId:job?.id,stage:item?.stage,message:'Đang tìm lại phản hồi trong ChatGPT…'});
    render();void repairChat(target);
  }
  async function repairChat(target){
    if(retired||working.has(target))return;
    const item=sessions.find(item=>item.scope===target),r=recoveries.get(target);if(!item||!r)return;
    r.pending=true;r.message='Đang tìm phản hồi; không gửi lại prompt.';working.add(target);render();
    try{
      const job=displayFor(item)?.job;
      if(!job){
        const saved=displayFor(item)?.lastReceipt;
        if(!saved?.accepted)throw Error('Chưa có yêu cầu ChatGPT để khôi phục. Bấm Start rồi thử lại.');
        const receipt=await api(`/api/v1/projects/${target}/runs/${target}/chatgpt-exchanges/${encodeURIComponent(saved.id)}`);
        if(receipt.id!==saved.id||receipt.version!==saved.version||receipt.accepted!==true)throw Error('Phản hồi cũ chưa được xác nhận.');
        const pending=await api(`/api/connector/bridges/${scope}/pending`);
        if((pending.items||[]).some(request=>request.scope===target&&request.id!==saved.id))throw Error('Video đang chờ yêu cầu mới. Giữ Studio mở để kết nối lại, rồi bấm khôi phục khi yêu cầu xuất hiện.');
        r.requestId=saved.id;r.resumeWatch=true;r.message='Phản hồi đã có trong Studio. Đang tiếp tục video…';
      }else{
        const result=await requireReply({kind:'recover_chat',scope:target,job_id:item.job_id,id:job.id,url:r.url});
        hydrate(await requireReply({kind:'snapshot'}));
        if(['reply','receipt'].includes(result.status)){
          const recovered=displayFor(item)?.job;
          if(!recovered||recovered.id!==job.id||recovered.phase!=='reply')throw Error('Phiên vừa đổi yêu cầu. Bấm khôi phục lại.');
          await importReply(target,recovered);r.requestId=recovered.id;r.resumeWatch=true;r.message='Đã nhận phản hồi. Đang tiếp tục video…';
        }else if(result.status==='needs-chat-url'){
          r.message='Dán URL tab ChatGPT đang có phản hồi vào ô bên dưới, rồi bấm Thử khôi phục. Nếu đã đóng tab, có thể mở lại từ Lịch sử Chrome.';
        }else if(result.status==='pending')r.message='Đã nối lại cuộc trò chuyện. ChatGPT còn đang trả lời; Studio sẽ tự nhận khi xong.';
        else r.message='Chưa đọc được phản hồi. Bấm Mở ChatGPT để đăng nhập hoặc kiểm tra tab, rồi bấm Thử khôi phục. Chỉ giữ một tab cho cuộc trò chuyện này.';
      }
      errors.delete(target);setStatus(r.message);
    }catch(error){r.message=error.transient?'Mất kết nối Studio. Chờ một chút rồi bấm Thử khôi phục.':error.message;showError(error,target);}
    finally{r.pending=false;working.delete(target);render();void tick();}
  }
  async function resumeRecoveredVideos(){
    for(const [target,r] of recoveries){
      if(!r.resumeWatch||r.pending||working.has(target))continue;
      const item=sessions.find(item=>item.scope===target);
      if(!item||cancelled(item)||item.state==='completed'||item.stage!==r.stage){r.resumeWatch=false;continue;}
      if(item.state!=='failed')continue;
      r.resumeWatch=false;
      if(!/Chrome connector response unavailable|(?:connector|ChatGPT).*(?:timeout|unavailable|connection|delivery_indeterminate)|403|delivery_indeterminate/i.test(item.error||'')){
        r.message='Đã nhận phản hồi ChatGPT. Video còn lỗi khác; xem thông báo và nút tiếp tục ở lịch sử tác vụ.';continue;
      }
      const key=target+':'+r.requestId;if(autoResumed.has(key))continue;
      try{
        const updated=await api('/api/jobs/'+item.job_id+'/retry',{method:'POST'});autoResumed.add(key);Object.assign(item,updated);
        r.message='Đã khôi phục ChatGPT và cho video tiếp tục từ bước đang lỗi.';setStatus(r.message);
      }catch(error){r.resumeWatch=error.transient===true;showError(error,target);}
    }
  }
  function collapse(value){collapsed=value;try{localStorage.setItem('videostudio_manager_collapsed',String(value));}catch{}render();(value?$('#badge'):$('#collapse')).focus();}
  function openDismiss(target){
    if(retired||working.has(target))return;const item=sessions.find(item=>item.scope===target);if(!item||!terminal(item))return;
    dismissal={scope:target,job_id:item.job_id,title:item.title||item.job_id||'Video',deleteFiles:false,error:'',pending:false};render();$('#dismiss-cancel').focus();
  }
  function closeDismiss(){
    if(!dismissal||dismissal.pending)return;const target=dismissal.scope;dismissal=null;render();cards.get(target)?.buttons.dismiss_session.focus();
  }
  listen($('#dismiss-files'),'change',event=>{if(event.isTrusted&&dismissal&&!dismissal.pending){dismissal.deleteFiles=event.target.checked;render();}});
  listen($('#dismiss-cancel'),'click',event=>{if(event.isTrusted)closeDismiss();});
  listen($('#dismiss-confirm'),'click',event=>{if(event.isTrusted)void confirmDismiss();});
  listen($('#dismiss-dialog'),'keydown',event=>{
    if(!dismissal)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeDismiss();}
    if(event.key==='Tab'){
      const controls=[$('#dismiss-files'),$('#dismiss-confirm'),$('#dismiss-cancel')].filter(node=>!node.disabled);
      const current=controls.indexOf(shadow.activeElement);event.preventDefault();(controls.length?controls[(current+(event.shiftKey?-1:1)+controls.length)%controls.length]:$('#dismiss-dialog')).focus();
    }
  });
  listen($('#collapse'),'click',()=>collapse(true));listen($('#badge'),'click',()=>collapse(false));
  listen($('#manager'),'keydown',event=>{if(event.key==='Escape'){event.preventDefault();collapse(true);}});
  function retire(){
    if(retired)return;retired=true;active=false;render();for(const timer of intervals)clearInterval(timer);
    for(const [node,type,handler,capture] of listeners)node.removeEventListener(type,handler,capture);
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
    let response;try{response=await fetch(path,{credentials:'same-origin',signal:AbortSignal.timeout(path.startsWith('/api/browser/profile')?45000:15000),...options});}catch(error){error.transient=true;throw error;}
    if(!response.ok){let detail;try{const body=await response.json();detail=typeof body.detail==='string'?body.detail:typeof body.error==='string'?body.error:null;}catch{}const error=Error(`Studio HTTP ${response.status}${detail?': '+detail:''}`);error.transient=response.status>=500||[408,429].includes(response.status);throw error;}
    return response.json();
  };
  async function heartbeat(){
    if(!scope||retired)return;
    try{
      const status={build:'videostudio-extension-0.3.0',stage:active?'active':'stopped',connected:active,enabled:active};
      if(runtimeVersion)status.runtime_version=runtimeVersion;
      const connection=slotFor(scope);
      if((connection?.is_smoke||connection?.job?.is_smoke)&&connection.job?.phase==='uncertain'&&connection.job.reason)status.error={code:'connection_test',message:connection.job.reason};
      await api('/api/connector/status/'+scope,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(status)});
    }
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
    const recovery=recoveries.get(target);if(recovery?.requestId===job.id)recovery.resumeWatch=true;
  }
  function showError(error,target){if(retired)return;const text=error.transient?'Mất kết nối Studio; đang tự kết nối lại.':error.message;errors.set(target||'connection',text);if(!target||target===scope)setStatus(text);render();}
  async function tick(){
    if(!active||busy||retired||!scope)return;busy=true;const started=generation;
    try{
      const state=await requireReply({kind:'snapshot'});if(started!==generation)return;hydrate(state);if(!active){setStatus('Đã dừng');return;}
      await loadSessions();await syncCancellations(started);await resumeRecoveredVideos();
      for(const saved of slots.flatMap(slot=>[slot,...(slot.retained||[])])){
        if(!saved.job_id||sessions.some(item=>item.job_id===saved.job_id))continue;
        try{
          const info=await api(`/api/connector/bridges/${scope}/jobs/${encodeURIComponent(saved.job_id)}`);
          if(info.dismissed===true)await requireReply({kind:'dismiss_session',scope:saved.scope,job_id:saved.job_id});
        }catch(error){if(error.transient)showError(error);}
      }
      const pending=await api(`/api/connector/bridges/${scope}/pending`),handled=new Set();
      if(errors.delete('connection'))setStatus('Đã kết nối');
      for(const slot of slots){
        if(retired||!active||started!==generation)break;const target=slot.scope,job=slot.job,item=sessions.find(item=>item.scope===target);
        if(job?.composer_diagnostic&&item?.job_id&&!job.is_smoke&&!slot.is_smoke){
          const key=target+':'+job.id+':'+job.attempt;
          if(!reportedDiagnostics.has(key))try{
            await api('/api/jobs/'+encodeURIComponent(item.job_id)+'/composer-diagnostics',{method:'POST',headers:{'Content-Type':'application/json','X-Connector-Scope':scope},body:JSON.stringify({request_id:job.id,version:job.version,attempt:job.attempt,diagnostic:job.composer_diagnostic})});reportedDiagnostics.add(key);
          }catch(error){showError(error,target);}
        }
        const smoke=target===scope&&(job?.is_smoke===true||slot.is_smoke===true||(pending.items||[]).some(request=>request.is_smoke===true&&request.scope===scope&&request.id===job?.id&&request.version===job?.version));
        if(job&&!working.has(target)&&!slot.cancelled&&item?.state==='failed'&&!item.cancel_requested&&['plan','research','script'].includes(item.stage)){
          const key=target+':'+job.id;
          if(Date.now()-(autoChecked.get(key)||0)>=15000)try{
            autoChecked.set(key,Date.now());
            const checked=await requireReply({kind:'reconcile',scope:target,id:job.id,job_id:item.job_id,inspect_only:true});
            if(['reply','receipt'].includes(checked.status)){
              const fresh=await requireReply({kind:'snapshot'});hydrate(fresh);
              const recovered=displayFor(item)?.job;
              if(recovered?.phase==='reply'){
                await importReply(target,recovered);
                if(!autoResumed.has(key)&&/403|connector|response unavailable|delivery_indeterminate|timeout|ChatGPT/i.test(item.error||'')){
                  autoResumed.add(key);await api('/api/jobs/'+item.job_id+'/retry',{method:'POST'});
                }
              }
            }
          }catch(error){showError(error,target);}
          continue;
        }
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
  async function confirmDismiss(){
    const choice=dismissal;if(!choice||choice.pending||retired||working.has(choice.scope))return;
    const item=sessions.find(item=>item.scope===choice.scope&&item.job_id===choice.job_id);if(!item||!terminal(item))return;
    choice.pending=true;choice.error='';working.add(choice.scope);render();
    try{
      const result=await api(`/api/connector/bridges/${scope}/jobs/${encodeURIComponent(choice.job_id)}/dismiss`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_files:choice.deleteFiles,confirm:true})});
      if(choice.deleteFiles&&result.files_deleted!==true)throw Error('Backend chưa xác nhận xóa file; hãy cập nhật server và kiểm tra lại.');
      await requireReply({kind:'dismiss_session',scope:choice.scope,job_id:choice.job_id});
      sessions=sessions.filter(row=>row.job_id!==choice.job_id);errors.delete(choice.scope);dismissal=null;
      setStatus(result.cleanup_pending?'Đã gỡ phiên; một số file đang chờ xóa do bị khóa.':result.files_deleted===true?'Đã xóa phiên và các file đã tạo.':'Đã xóa phiên; giữ các file đã tạo.');
    }catch(error){choice.error=error.transient?'Mất kết nối Studio; đang kiểm tra lại trạng thái.':error.message;showError(error,choice.scope);}
    finally{choice.pending=false;working.delete(choice.scope);render();if(!dismissal)$('#collapse').focus();}
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
    if(!event.isTrusted||active||retired||starting)return;
    starting=true;render();
    try{
      const saved=await requireReply({kind:'connection'});
      let target=saved.scope||scope;
      if(saved.scope){
        if(!/^[0-9a-f-]{36}$/i.test(saved.scope)||saved.url!==`/story-video/projects/${saved.scope}/production`)throw Error('Invalid saved bridge');
        // Attest the saved root still exists before handing the owner tab over.
        await api(`/api/connector/bridges/${encodeURIComponent(saved.scope)}/sessions`);
      }
      if(!target){const session=await api('/api/connector/sessions',{method:'POST'});if(session.project_id!==session.run_id||session.url!==`/story-video/projects/${session.project_id}/production`)throw Error('Invalid connector scope');target=session.project_id;}
      await requireReply({kind:'start',scope:target,...(saved.scope?{reconnect:true}:{})});
      if(target!==scope){
        // The old page must not emit a heartbeat for its unrelated scope.
        active=false;generation++;setStatus('Đang nối lại kết nối đã lưu…');
        location.assign(`/story-video/projects/${target}/production`);return;
      }
      active=true;render();setStatus('Đã kết nối');await heartbeat();await tick();
    }catch(error){if(!retired)setStatus(`Không thể Start: ${error.message}`);}
    finally{starting=false;render();}
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
  for(const mode of ['clean','debug','stop'])listen($('#browser-'+mode),'click',event=>{if(event.isTrusted)void controlBrowser(mode);});
  listen($('#browser-refresh'),'click',event=>{if(event.isTrusted)void refreshBrowser();});
  const createForm=document.querySelector('#create');
  if(createForm){
    const guard=event=>{
      const needsBrowser=['flow','chatgpt'].includes(document.querySelector('#imageProvider')?.value);
      if(!browserBusy&&!browserProfile?.busy&&!(needsBrowser&&browserProfile?.mode==='clean'))return;
      event.preventDefault();event.stopImmediatePropagation();
      browserError=browserBusy||browserProfile?.busy?'Chờ Chrome riêng đổi chế độ xong rồi tạo video.':'Chrome riêng đang mở sạch. Bấm Mở debug trước khi tạo ảnh Flow/ChatGPT; tài khoản đã đăng nhập được giữ nguyên.';
      const notice=document.querySelector('#submitError');if(notice)notice.textContent=browserError;
      collapsed=false;$('[data-browser-profile]').open=true;render();$('#browser-debug').focus();
    };
    // Capture runs before the page's job-creation handler.
    createForm.addEventListener('submit',guard,true);
    listeners.push([createForm,'submit',guard,true]);
  }
  intervals.push(setInterval(()=>{void pollFlowAccounts();},1200));intervals.push(setInterval(()=>{void refreshBrowser();},10000));
  intervals.push(setInterval(()=>{void tick().catch(()=>{});},1200));intervals.push(setInterval(()=>{if(active)void heartbeat().catch(()=>{});},10000));
  listen(document,'visibilitychange',()=>{if(document.visibilityState==='visible'&&active&&!retired)void heartbeat().then(()=>tick()).catch(()=>{});});
  render();void refreshBrowser();
  if(scope)void requireReply({kind:'snapshot'}).then(async state=>{if(retired)return;hydrate(state);setStatus(active?'Đã kết nối':'Đã dừng');if(active){await heartbeat();void tick();}else await loadSessions();}).catch(error=>showError(error));
})();

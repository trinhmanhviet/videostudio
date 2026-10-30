import {start,claim,beginAttempt,retryAttempt,result,studioScope,acknowledge,receiptPath,archivePrevious,migrateBridge,syncBridge,sessionSlot,callbackSlot,bridgeSnapshot,allSlots,receiptMatches} from './protocol.mjs';
const KEY='videostudio_bridge_v2';
const get=async()=>migrateBridge((await chrome.storage.local.get(KEY))[KEY]??null);
const put=async state=>chrome.storage.local.set({[KEY]:syncBridge(state)});
const validSender=(sender,origin)=>{try{return sender.frameId===0&&Number.isInteger(sender.tab?.id)&&new URL(sender.url).origin===origin;}catch{return false;}};
const studioSender=sender=>validSender(sender,'http://localhost:8877');
const studioPage=sender=>studioSender(sender)&&(/^\/$|^\/story-video\/projects\/[0-9a-f-]{36}\/production$/i.test(new URL(sender.url).pathname));
const chatSender=sender=>validSender(sender,'https://chatgpt.com');
const modeReason=reason=>reason==='Chat mode not confirmed'||reason==='Chat mode unknown';
const isOwner=(state,sender)=>studioSender(sender)&&sender.tab.id===state.studioTab&&studioScope(sender.url,state.scope,state.scope);
const closeOwned=async slot=>{for(const id of slot.ownedTabs??[])try{await chrome.tabs.remove(id);}catch{}slot.ownedTabs=[];slot.chatTab=null;};
function conversationUrl(value){
  try{const url=new URL(value);return url.origin==='https://chatgpt.com'&&/^\/(?:g\/[^/]+\/)?c\/[0-9a-f-]{36}\/?$/i.test(url.pathname)?url.origin+url.pathname.replace(/\/$/,''):null;}catch{return null;}
}
async function inspect(tab,id,prompt,matchOnly=false){
  let timer;
  try{const seen=await Promise.race([
    chrome.tabs.sendMessage(tab,{kind:'inspect',id,prompt,...(matchOnly?{match_only:true}:{})}),
    new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('ChatGPT inspection timed out')),3000);}),
  ]);return seen&&typeof seen==='object'&&'visibleUser' in seen?seen:{visibleUser:null,visibleReply:null,unavailable:true};}catch{return {visibleUser:null,visibleReply:null,unavailable:true};}
  finally{clearTimeout(timer);}
}
async function replacementTab(state,slot){
  if(!chrome.tabs.query)return null;
  const expected=conversationUrl(slot.job.conversation_url);
  const reserved=new Set(allSlots(state).filter(other=>other!==slot).flatMap(other=>other.ownedTabs??[]));
  const tabs=(await chrome.tabs.query({url:'https://chatgpt.com/*'})).filter(tab=>
    Number.isInteger(tab.id)&&tab.id!==slot.job.chatTab&&!reserved.has(tab.id)&&conversationUrl(tab.url)&&(!expected||conversationUrl(tab.url)===expected)
  ).sort((a,b)=>(b.lastAccessed??b.id)-(a.lastAccessed??a.id)).slice(0,30);
  const inspected=await Promise.all(tabs.map(async tab=>({tab,seen:await inspect(tab.id,slot.job.id,slot.job.prompt,true)})));
  const matches=inspected.filter(({seen})=>!seen.blocked&&receiptMatches(seen.visibleUser,slot.job.id,slot.job.prompt));
  if(matches.length>1)return {blocked:'Multiple replacement tabs match this request'};
  if(matches.length!==1)return null;
  const {tab,seen}=matches[0];
  slot.job.chatTab=tab.id;slot.chatTab=tab.id;
  if(!slot.ownedTabs.includes(tab.id))slot.ownedTabs.push(tab.id);
  slot.job.conversation_url=conversationUrl(tab.url);slot.job.recovered_tab_at=Date.now();
  await put(state);
  return seen;
}
async function closePreviousRecoveryTabs(slot){
  const current=slot.job.chatTab;
  for(const tab of slot.ownedTabs??[])if(tab!==current)try{await chrome.tabs.remove(tab);}catch{}
  slot.ownedTabs=Number.isInteger(current)?[current]:[];delete slot.job.recovery_tab;delete slot.job.recovery_url;
}
async function recoverChat(state,slot,message){
  if(!state.active||!slot.active||slot.cancelled)throw Error('Bấm Start để kết nối trước khi khôi phục.');
  if(slot.job_id==null&&typeof message.job_id==='string'){
    const membership=await member(state,{scope:slot.scope,job_id:message.job_id},slot.scope===state.scope);
    slot.job_id=membership?.job_id;
  }
  if(slot.job_id!==message.job_id)throw Error('Phiên khôi phục không thuộc video này.');
  const supplied=typeof message.url==='string'?message.url.trim():'';
  const requested=supplied?conversationUrl(supplied):null;
  if(supplied&&!requested)throw Error('Dán URL cuộc trò chuyện dạng https://chatgpt.com/c/...');
  const status=slot.job.phase==='reply'?'reply':await reconcile(state,slot,true);
  if(['reply','receipt'].includes(status)){
    await closePreviousRecoveryTabs(slot);await put(state);return {status};
  }
  if(status==='human-or-invalid')return {status:'needs-user'};
  const url=requested||conversationUrl(slot.job.conversation_url);
  if(!url)return {status:'needs-chat-url'};
  let tab;
  if(slot.job.recovery_url===url&&Number.isInteger(slot.job.recovery_tab)){
    try{tab=await chrome.tabs.get(slot.job.recovery_tab);}catch{}
  }
  if(!tab){
    tab=await chrome.tabs.create({url,active:false});
    slot.job.recovery_tab=tab.id;slot.job.recovery_url=url;
    if(!slot.ownedTabs.includes(tab.id))slot.ownedTabs.push(tab.id);
    await put(state);
  }
  try{await ready(tab.id);}catch{return {status:'open-chat'};}
  const seen=await inspect(tab.id,slot.job.id,slot.job.prompt,true);
  if(seen.blocked||!receiptMatches(seen.visibleUser,slot.job.id,slot.job.prompt))return {status:'open-chat'};
  slot.job.chatTab=tab.id;slot.chatTab=tab.id;slot.job.conversation_url=url;
  slot.job.send_attempted=true;slot.job.reason=null;slot.job.recovered_tab_at=Date.now();
  slot.job.phase=seen.visibleReply?'reply':'sent';
  if(seen.visibleReply)slot.job.text=seen.visibleReply;
  await closePreviousRecoveryTabs(slot);await put(state);
  return {status:seen.visibleReply?'reply':'pending'};
}
async function serverJson(path){
  let response;
  try{response=await fetch(`http://localhost:8877${path}`,{signal:AbortSignal.timeout(15000)});}
  catch(error){error.transient=true;throw error;}
  if(!response.ok){const error=Error('Server receipt or membership unavailable');error.transient=response.status>=500||[408,429].includes(response.status);throw error;}
  return response.json();
}
async function receipt(slot){
  const data=await serverJson(receiptPath(slot.scope,slot.job.id));
  if(data.id!==slot.job.id||data.version!==slot.job.version||typeof data.accepted!=='boolean')throw Error('Receipt mismatch');return data;
}
async function member(state,message,includeRoot=false){
  if(message.scope===state.scope&&!includeRoot)return null;
  const data=await serverJson(`/api/connector/bridges/${encodeURIComponent(state.scope)}/sessions`);
  const matches=Array.isArray(data.items)?data.items.filter(item=>item.scope===message.scope):[];
  if(matches.length!==1||typeof matches[0].job_id!=='string'||!matches[0].job_id||
    (message.job_id!=null&&message.job_id!==matches[0].job_id))throw Error('Scope/job does not belong to this bridge');
  return matches[0];
}
async function attestSmoke(state,message,slot){
  if(message.scope!==state.scope||message.job_id!=null)throw Error('Connection smoke must use its bridge root');
  const data=await serverJson(`/api/connector/bridges/${encodeURIComponent(state.scope)}/pending`);
  const matches=Array.isArray(data.items)?data.items.filter(item=>item.scope===state.scope&&item.id===message.id):[];
  const pending=matches[0];
  if(matches.length!==1||pending.is_smoke!==true||pending.job_id!==null||pending.version!==message.version||pending.prompt!==message.prompt||!Array.isArray(pending.attachments)||pending.attachments.length)throw Error('Connection smoke not attested by server');
  if(!slot||slot.job?.id===message.id)return;
  if(slot.is_smoke&&slot.job)throw Error('Previous connection smoke still pending');
  if(!slot.is_smoke&&(slot.job||slot.lastReceipt||slot.job_id)){
    const video=await member(state,{scope:state.scope},true);
    if(!video.cancel_requested&&!['failed','completed','cancelled','canceled'].includes(video.state))throw Error('Legacy root video is still active');
    const previous={...slot,job_id:video.job_id,retained:[]};
    slot.retained=[...(slot.retained??[]),previous];
    slot.job=null;slot.job_id=null;slot.chatTab=null;slot.ownedTabs=[];slot.lastReceipt=null;
  }
  slot.cancelled=false;slot.active=true;
}
function resumeRootVideo(state,message,slot,membership){
  if(!slot)return slot;
  if(slot.is_smoke){
    if(slot.job)throw Error('Previous connection smoke still pending');
    const retained=slot.retained??[],matches=retained.filter(item=>item.job?.id===message.id);
    const prior=matches[0];
    if(matches.length>1||(prior&&(prior.is_smoke||prior.job_id!==membership.job_id||prior.job.version!==message.version||prior.job.prompt!==message.prompt)))throw Error('Retained video request mismatch');
    const video=prior??{...start({studioTab:state.studioTab,scope:state.scope}),lastReceipt:null};
    const history=retained.filter(item=>item!==prior);
    if(slot.lastReceipt)history.push({...slot,retained:[]});
    // Promotion changes routing only: the immutable request's phase, attempt,
    // reply and owned tab are preserved, so it is never sent again by moving.
    video.retained=history;video.job_id=membership.job_id;video.is_smoke=false;
    video.active=true;video.cancelled=false;video.studioTab=state.studioTab;
    if(video.job)delete video.job.is_smoke;
    state.sessions[state.sessions.indexOf(slot)]=video;
    return video;
  }
  if(slot.job_id!=null&&slot.job_id!==membership.job_id)throw Error('Root video job mismatch');
  slot.job_id=membership.job_id;slot.is_smoke=false;slot.active=true;slot.cancelled=false;
  if(slot.job)delete slot.job.is_smoke;
  return slot;
}
async function ready(tabId){
  for(let i=0;i<120;i++){
    const current=await chrome.tabs.get(tabId);
    if(current.status==='complete'){
      try{if((await chrome.tabs.sendMessage(tabId,{kind:'probe'}))?.ok)return;}catch{}
    }
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw Error('ChatGPT content script not ready; no delivery dispatched');
}
async function dispatch(state,slot){
  try{const response=await chrome.tabs.sendMessage(slot.job.chatTab,{kind:'deliver',id:slot.job.id,attempt:slot.job.attempt,prompt:slot.job.prompt});if(!response?.ok)throw Error('Delivery rejected');}
  catch(error){slot.job.phase='uncertain';slot.job.reason=String(error.message??error);await put(state);}
}
async function launch(state,slot){
  const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:false});
  if(!beginAttempt(slot,tab.id)){try{await chrome.tabs.remove(tab.id);}catch{}throw Error('Attempt transition rejected');}
  slot.job.startedAt=Date.now();await put(state);
  try{await ready(tab.id);await dispatch(state,slot);}catch(error){slot.job.phase='uncertain';slot.job.reason=String(error.message??error);await put(state);}
}
async function reconcile(state,slot,inspectOnly=false){
  // These two historical errors occur before clicking Send. All other mode
  // errors still require human inspection, as does an explicit attempted send.
  const unsentMode=slot.job.phase==='uncertain'&&modeReason(slot.job.reason)&&slot.job.send_attempted!==true;
  if(!inspectOnly&&(/login|auth|challenge|verify|captcha|immutable request marker|unsupported/i.test(slot.job.reason??'')||
    (!unsentMode&&/mode unknown|mode not confirmed/i.test(slot.job.reason??''))))return 'human-or-invalid';
  const data=await receipt(slot);
  if(data.accepted){slot.job.phase='reply';slot.job.text=data.response_text??slot.job.text??'';await put(state);return 'receipt';}
  let seen=await inspect(slot.job.chatTab,slot.job.id,slot.job.prompt);
  const currentUrl=conversationUrl(seen.conversationUrl);
  if(currentUrl&&receiptMatches(seen.visibleUser,slot.job.id,slot.job.prompt)&&!slot.job.conversation_url){slot.job.conversation_url=currentUrl;await put(state);}
  if(seen.unavailable||(!seen.visibleReply&&Date.now()-(slot.job.startedAt??Date.now())>45000)){
    const recovered=await replacementTab(state,slot);
    if(recovered)seen=recovered;
  }
  if(seen.blocked)return 'human-or-invalid';
  const matched=receiptMatches(seen.visibleUser,slot.job.id,slot.job.prompt);
  if(matched&&seen.visibleReply){slot.job.phase='reply';slot.job.text=seen.visibleReply;await put(state);return 'reply';}
  if(seen.visibleUser!==null&&!matched)return 'foreign-turn';
  if(matched&&Date.now()-(slot.job.startedAt??Date.now())<360000)return 'pending';
  if(slot.job.phase==='dispatching'&&Date.now()-(slot.job.startedAt??Date.now())<30000)return 'pending';
  if(inspectOnly)return 'unresolved';
  if(seen.unavailable&&slot.job.send_attempted===true)return 'awaiting-replacement';
  if(slot.job.attempt>=2)return 'exhausted';
  const priorTab=slot.job.chatTab;
  const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:false});
  if(!retryAttempt(slot,{id:data.id,version:data.version,accepted:data.accepted,visibleUser:null},tab.id)){await chrome.tabs.remove(tab.id);return 'blocked';}
  delete slot.job.send_attempted;
  delete slot.job.conversation_url;delete slot.job.recovery_tab;delete slot.job.recovery_url;
  slot.job.startedAt=Date.now();await put(state);
  try{await chrome.tabs.remove(priorTab);}catch{}
  slot.ownedTabs=slot.ownedTabs.filter(id=>id!==priorTab);await put(state);
  try{await ready(tab.id);await dispatch(state,slot);}catch(error){slot.job.phase='uncertain';slot.job.reason=String(error.message??error);await put(state);}
  return 'retried';
}
// MV3 listeners overlap at every await. Serialize all bridge writes so a late
// delivery cannot undo Stop, cancellation, or a different slot's reply.
let transitions=Promise.resolve();
const HEARTBEAT_ALARM='videostudio-bridge-heartbeat';
const inspectedRequests=new Map(),INSPECT_INTERVAL=25000;
const serialize=operation=>{const pending=transitions.then(operation);transitions=pending.catch(()=>{});return pending;};
async function ensureHeartbeatAlarm(){
  if(!chrome.alarms?.get||!chrome.alarms?.create)return;
  // Chrome may clear an alarm on restart/update. Check every worker startup.
  const alarm=await chrome.alarms.get(HEARTBEAT_ALARM);
  if(!alarm||alarm.periodInMinutes!==0.5)await chrome.alarms.create(HEARTBEAT_ALARM,{periodInMinutes:0.5});
}
async function heartbeat(state){
  const status={build:'videostudio-extension-0.3.0',stage:'active',connected:true,enabled:true};
  const runtimeVersion=chrome.runtime.getManifest?.().version;
  if(runtimeVersion)status.runtime_version=runtimeVersion;
  const root=sessionSlot(state,state.scope);
  if((root?.is_smoke===true||root?.job?.is_smoke===true)&&modeReason(root.job?.reason))status.error={code:'chat_mode',message:root.job.reason};
  const response=await fetch(`http://localhost:8877/api/connector/status/${encodeURIComponent(state.scope)}`,{
    method:'POST',headers:{'Content-Type':'application/json','X-VS-Client':'videostudio-extension'},body:JSON.stringify(status),signal:AbortSignal.timeout(15000)
  });
  if(!response.ok)throw Error('Bridge heartbeat unavailable');
}
async function pulse(){
  const state=await get();
  if(state?.active!==true||!Number.isInteger(state.studioTab))return;
  let owner;try{owner=await chrome.tabs.get(state.studioTab);}catch{return;}
  if(owner.url!==`http://localhost:8877/story-video/projects/${state.scope}/production`)return;
  // Heartbeat and each inspection are independent: a failed receipt must not
  // interrupt bridge renewal or another video's exact request recovery.
  try{await heartbeat(state);}catch{}
  const pending=allSlots(state).filter(slot=>slot.active&&!slot.cancelled&&
    ['sent','uncertain','dispatching'].includes(slot.job?.phase)&&Number.isInteger(slot.job.chatTab)&&slot.ownedTabs?.includes(slot.job.chatTab));
  const keys=new Set();
  for(const slot of pending){
    const key=JSON.stringify([slot.scope,slot.job.id,slot.job.version,slot.job.attempt,slot.job.chatTab]);keys.add(key);
    if(Date.now()-(inspectedRequests.get(key)??-Infinity)<INSPECT_INTERVAL)continue;
    inspectedRequests.set(key,Date.now());
    // Inspection can read a completed turn after a prior auth/mode error, but
    // never clicks Send, creates tabs, changes gates, or accepts foreign turns.
    try{await reconcile(state,slot,true);}catch{}
  }
  for(const key of inspectedRequests.keys())if(!keys.has(key))inspectedRequests.delete(key);
}
async function dismissSession(state,scope,jobId){
  if(typeof jobId!=='string'||!jobId)throw Error('Dismissal requires exact video job identity');
  const video=await serverJson(`/api/connector/bridges/${encodeURIComponent(state.scope)}/jobs/${encodeURIComponent(jobId)}`);
  if(!video||video.scope!==scope||video.job_id!==jobId||video.dismissed!==true||!['failed','completed','cancelled','canceled'].includes(video.state))throw Error('Video dismissal not attested by server');
  const slot=sessionSlot(state,scope);
  if(!slot)return;
  let removed=[];
  if(scope!==state.scope){
    if(slot.job_id!==jobId)throw Error('Dismissal job mismatch');
    removed=[slot,...(slot.retained??[])];state.sessions=state.sessions.filter(item=>item!==slot);
  }else{
    const smoke=item=>item.is_smoke===true||item.job?.is_smoke===true;
    const selected=item=>!smoke(item)&&(item.job_id===jobId||item===slot&&item.job_id==null);
    const history=[slot,...(slot.retained??[])];removed=history.filter(selected);
    const preserved=history.filter(item=>!selected(item));
    if(removed.includes(slot)){
      const replacement=preserved.find(smoke)??preserved[0];
      if(replacement){replacement.retained=preserved.filter(item=>item!==replacement);state.sessions[state.sessions.indexOf(slot)]=replacement;}
      else state.sessions=state.sessions.filter(item=>item!==slot);
    }else slot.retained=preserved.filter(item=>item!==slot);
  }
  await put(state);
  for(const item of removed)await closeOwned(item);
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  const operation=serialize(async()=>{
    if(message?.kind==='connection'){
      if(!studioPage(sender))throw Error('Studio page required');
      const saved=await get();
      return {ok:true,scope:saved?.scope??null,url:saved?`/story-video/projects/${saved.scope}/production`:null,active:saved?.active===true};
    }
    if(message?.kind==='start'){
      const old=await get();
      const reconnect=message.reconnect===true&&old?.scope===message.scope&&studioPage(sender);
      if(message.reconnect===true&&!reconnect)throw Error('Saved bridge changed; reload Studio to reconnect');
      if(!studioSender(sender)||(!studioScope(sender.url,message.scope,message.scope)&&!reconnect))throw Error('Studio origin/scope mismatch');
      if(old?.scope===message.scope){
        old.studioTab=sender.tab.id;old.active=true;
        for(const slot of allSlots(old)){slot.studioTab=sender.tab.id;slot.active=!slot.cancelled;}
        await put(old);return {ok:true,active:true};
      }
      if(old){
        // Root-only legacy Start keeps its historical archive behavior. Full
        // receipts remain persisted and reconnecting restores their budget.
        // Child videos stay attached to their root until their request clears.
        if(old.sessions.some(slot=>slot.scope!==old.scope&&slot.job))throw Error('Existing video sessions must be preserved; reconnect to their bridge');
        const previous=archivePrevious(old);
        await put(old);
        if(previous)await chrome.storage.local.set({videostudio_bridge_last_abandoned:previous});
        for(const slot of allSlots(old))await closeOwned(slot);
        await chrome.storage.local.set({[`videostudio_bridge_archive_${old.scope}`]:syncBridge(old)});
      }
      const archiveKey=`videostudio_bridge_archive_${message.scope}`;
      const archived=(await chrome.storage.local.get(archiveKey))[archiveKey];
      const state=migrateBridge(archived?.scope===message.scope?archived:start({studioTab:sender.tab.id,scope:message.scope}));
      state.studioTab=sender.tab.id;state.active=true;
      for(const slot of allSlots(state)){slot.studioTab=sender.tab.id;slot.active=!slot.cancelled;}
      await put(state);return {ok:true,active:true};
    }
    const state=await get();if(!state)throw Error('Bridge not configured');
    if(message?.kind==='snapshot'){
      if(!isOwner(state,sender))throw Error('Not owner');await put(state);return bridgeSnapshot(state);
    }
    if(['stop','imported','claim','reconcile','open_chat','recover_chat','cancel_session','dismiss_session'].includes(message?.kind)){
      if(!isOwner(state,sender))throw Error('Not owner');
      if(message.kind==='stop'){
        state.active=false;
        // Persist pause before closing tabs, keeping every pending receipt.
        for(const slot of allSlots(state))slot.active=false;
        await put(state);for(const slot of allSlots(state))await closeOwned(slot);await put(state);return {ok:true};
      }
      const scope=message.scope??state.scope;
      if(message.kind==='dismiss_session'){
        await dismissSession(state,scope,message.job_id);return {ok:true,scope,status:'dismissed'};
      }
      let slot=sessionSlot(state,scope);
      if(message.kind==='claim'){
        if(!state.active)throw Error('Bridge not active');
        const rootVideo=scope===state.scope&&message.is_smoke!==true&&message.job_id!=null;
        if(scope===state.scope&&slot?.is_smoke&&message.is_smoke!==true&&!rootVideo)throw Error('Resumed root video requires its job identity');
        const membership=await member(state,{...message,scope},rootVideo);
        if(membership&&(membership.cancel_requested||!['queued','running','retrying'].includes(membership.state)))throw Error('Video is cancelled or no longer active');
        if(message.is_smoke===true)await attestSmoke(state,{...message,scope},slot);
        if(rootVideo)slot=resumeRootVideo(state,{...message,scope},slot,membership);
        if(!slot){slot={...start({studioTab:state.studioTab,scope}),cancelled:false,job_id:membership?.job_id??null,lastReceipt:null};state.sessions.push(slot);}
        if(slot.cancelled||!slot.active||(membership&&slot.job_id!==membership.job_id)||
          !claim(slot,{...message,studioTab:sender.tab.id,scope}))throw Error('Unowned or conflicting request');
        if(message.is_smoke===true){slot.is_smoke=true;slot.job.is_smoke=true;}
        await put(state);if(slot.job.phase==='claimed')await launch(state,slot);return {ok:true,scope,phase:slot.job.phase};
      }
      if(message.kind==='cancel_session'){
        if(scope===state.scope&&(message.job_id!=null||!slot||slot.is_smoke)){
          const membership=await member(state,{...message,scope},true);
          if(slot?.is_smoke){
            let video=(slot.retained??[]).find(item=>item.job_id===membership.job_id);
            if(!video){video={...start({studioTab:state.studioTab,scope}),cancelled:false,job_id:membership.job_id,lastReceipt:null};slot.retained=[...(slot.retained??[]),video];}
            slot=video;
          }else if(slot){
            if(slot.job_id!=null&&slot.job_id!==membership.job_id)throw Error('Cancellation job mismatch');
            slot.job_id=membership.job_id;
          }else{slot={...start({studioTab:state.studioTab,scope}),cancelled:false,job_id:membership.job_id,lastReceipt:null};state.sessions.push(slot);}
        }else if(!slot){
          const membership=await member(state,{...message,scope});
          slot={...start({studioTab:state.studioTab,scope}),cancelled:false,job_id:membership.job_id,lastReceipt:null};state.sessions.push(slot);
        }else if(message.job_id!=null&&slot.job_id!==message.job_id)throw Error('Cancellation job mismatch');
      }
      if(!slot)throw Error('Unknown video session');
      if(message.kind==='cancel_session'){
        slot.active=false;slot.cancelled=true;await put(state);await closeOwned(slot);await put(state);return {ok:true,scope,status:'cancelled'};
      }
      if(['open_chat','reconcile','recover_chat'].includes(message.kind)&&message.id!=null&&slot.job?.id!==message.id){
        const retained=(slot.retained??[]).filter(item=>item.job?.id===message.id);
        if(retained.length!==1||(message.kind==='reconcile'&&message.inspect_only!==true))throw Error('Historical request requires exact read-only recovery');
        slot=retained[0];
      }
      if(message.kind==='open_chat'){
        const tab=slot.job?.recovery_tab??slot.job?.chatTab;
        if(!Number.isInteger(tab)||!slot.ownedTabs.includes(tab))throw Error('No owned ChatGPT tab available');
        await chrome.tabs.get(tab);await chrome.tabs.update(tab,{active:true});return {ok:true,scope,tabId:tab};
      }
      if(message.kind==='recover_chat'){
        if(!slot.job)throw Error('Chưa có yêu cầu ChatGPT cần khôi phục.');
        return {ok:true,scope,...await recoverChat(state,slot,message)};
      }
      if(message.kind==='imported'){
        const previous=slot.job?.chatTab,job=slot.job;
        if(!acknowledge(slot,message))throw Error('Uncorrelated import receipt');
        slot.lastReceipt={id:job.id,version:job.version,accepted:true,text:job.text??'',attempt:job.attempt};
        slot.ownedTabs=slot.ownedTabs.filter(id=>id!==previous);await put(state);try{await chrome.tabs.remove(previous);}catch{}return {ok:true,scope};
      }
      if(!slot.job)throw Error('No pending request');
      if(message.inspect_only!==true&&(!state.active||!slot.active||slot.cancelled))throw Error('Bridge or video session not active');
      return {ok:true,scope,status:await reconcile(state,slot,message.inspect_only===true)};
    }
    if(!state.active)throw Error('Bridge not active');
    const slot=chatSender(sender)?callbackSlot(state,message,sender.tab.id):null;
    if(!slot)throw Error('Uncorrelated ChatGPT callback');
    if(message?.kind==='sent'){
      if(slot.job.phase!=='dispatching')throw Error('Uncorrelated send');
      const conversation=conversationUrl(sender.url);if(conversation)slot.job.conversation_url=conversation;
      slot.job.phase='sent';slot.job.send_attempted=true;await put(state);return {ok:true,scope:slot.scope};
    }
    if(message?.kind==='uncertain'){
      if(slot.job.phase==='reply')return {ok:true,scope:slot.scope};
      if(message.composer_diagnostic&&typeof message.composer_diagnostic==='object'){
        const raw=JSON.stringify(message.composer_diagnostic);
        const diagnostic=raw.length<=16000?JSON.parse(raw):{expected_length:message.composer_diagnostic.expected_length,actual_length:message.composer_diagnostic.actual_length,first_diff:message.composer_diagnostic.first_diff};
        slot.job.composer_diagnostic=diagnostic;
        await chrome.storage.local.set({videostudio_last_composer_diagnostic:{scope:slot.scope,request_id:slot.job.id,attempt:slot.job.attempt,diagnostic}});
      }
      if(typeof message.send_attempted==='boolean'&&slot.job.send_attempted!==true)slot.job.send_attempted=message.send_attempted;
      slot.job.phase='uncertain';slot.job.reason=String(message.reason??'Unknown').slice(0,200);await put(state);return {ok:true,scope:slot.scope};
    }
    if(message?.kind==='reply'){
      if(!result(slot,{chatTab:sender.tab.id,id:message.id,attempt:message.attempt,text:message.text}))throw Error('Uncorrelated reply');
      await put(state);try{await chrome.tabs.sendMessage(state.studioTab,{kind:'reply',scope:slot.scope,id:message.id});}catch{}return {ok:true,scope:slot.scope};
    }
    throw Error('Unknown message');
  });
  operation.then(reply,error=>reply({ok:false,error:String(error.message??error),transient:error.transient===true}));return true;
});
chrome.tabs.onUpdated?.addListener((tabId,change)=>{
  const url=conversationUrl(change.url);if(!url)return;
  void serialize(async()=>{
    const state=await get();if(!state)return;
    let changed=false;
    for(const slot of allSlots(state))if(slot.job?.chatTab===tabId&&slot.ownedTabs?.includes(tabId)&&!slot.job.conversation_url){
      const seen=await inspect(tabId,slot.job.id,slot.job.prompt,true);
      if(receiptMatches(seen.visibleUser,slot.job.id,slot.job.prompt)){slot.job.conversation_url=url;changed=true;}
    }
    if(changed)await put(state);
  }).catch(()=>{});
});
if(chrome.alarms?.onAlarm){
  chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name===HEARTBEAT_ALARM)void serialize(pulse).catch(()=>{});});
  void serialize(ensureHeartbeatAlarm).catch(()=>{});
}

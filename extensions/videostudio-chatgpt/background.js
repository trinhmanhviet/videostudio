import {start,claim,beginAttempt,retryAttempt,result,studioScope,canStart,acknowledge,receiptPath,stop,archivePrevious} from './protocol.mjs';
const KEY='videostudio_bridge_v2';
const get=async()=> (await chrome.storage.local.get(KEY))[KEY]??null;
const put=async state=>chrome.storage.local.set({[KEY]:state});
const studioSender=sender=>sender.frameId===0&&Number.isInteger(sender.tab?.id)&&new URL(sender.url).origin==='http://localhost:8877';
const chatSender=sender=>sender.frameId===0&&Number.isInteger(sender.tab?.id)&&new URL(sender.url).origin==='https://chatgpt.com';
const closeOwned=async state=>{for(const id of state.ownedTabs??[])try{await chrome.tabs.remove(id);}catch{}};
async function inspect(tab,id,prompt){
  try{return await chrome.tabs.sendMessage(tab,{kind:'inspect',id,prompt});}catch{return {visibleUser:null,visibleReply:null};}
}
async function receipt(state){const response=await fetch(`http://localhost:8877${receiptPath(state.scope,state.job.id)}`);if(!response.ok)throw Error('Server receipt unavailable');const data=await response.json();if(data.id!==state.job.id||data.version!==state.job.version||typeof data.accepted!=='boolean')throw Error('Receipt mismatch');return data;}
async function ready(tabId){
  const current=await chrome.tabs.get(tabId);if(current.status==='complete')return;
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{chrome.tabs.onUpdated.removeListener(onUpdate);reject(Error('ChatGPT tab load timed out'));},30000);function onUpdate(id,change){if(id!==tabId||change.status!=='complete')return;clearTimeout(timer);chrome.tabs.onUpdated.removeListener(onUpdate);resolve();}chrome.tabs.onUpdated.addListener(onUpdate);});
}
async function launch(state){const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:true});if(!beginAttempt(state,tab.id))throw Error('Attempt transition rejected');state.job.startedAt=Date.now();await put(state);try{await ready(tab.id);await dispatch(state);}catch(error){state.job.phase='uncertain';state.job.reason=String(error.message??error);await put(state);}}
async function dispatch(state){
  try{const response=await chrome.tabs.sendMessage(state.job.chatTab,{kind:'deliver',id:state.job.id,attempt:state.job.attempt,prompt:state.job.prompt});if(!response?.ok)throw Error('Delivery rejected');}
  catch(error){state.job.phase='uncertain';state.job.reason=String(error.message??error);await put(state);}
}
async function reconcile(state){
  if(/login|auth|challenge|verify|captcha|immutable request marker|unsupported|mode unknown/i.test(state.job.reason??''))return 'human-or-invalid';
  const data=await receipt(state),seen=await inspect(state.job.chatTab,state.job.id,state.job.prompt);
  if(data.accepted){state.job.phase='reply';state.job.text=data.response_text??state.job.text??'';await put(state);return 'receipt';}
  if(seen.visibleUser===state.job.prompt&&seen.visibleReply){state.job.phase='reply';state.job.text=seen.visibleReply;await put(state);return 'reply';}
  if(seen.visibleUser!==null&&seen.visibleUser!==state.job.prompt)return 'foreign-turn';
  if(seen.visibleUser===state.job.prompt&&Date.now()-(state.job.startedAt??Date.now())<360000)return 'pending';
  if(state.job.phase==='dispatching'&&Date.now()-(state.job.startedAt??Date.now())<30000)return 'pending';
  if(state.job.attempt>=2)return 'exhausted';
  const priorTab=state.job.chatTab;
  const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:true});
  if(!retryAttempt(state,{id:data.id,version:data.version,accepted:data.accepted,visibleUser:null},tab.id)){await chrome.tabs.remove(tab.id);return 'blocked';}
  state.job.startedAt=Date.now();await put(state);
  try{await chrome.tabs.remove(priorTab);}catch{}
  state.ownedTabs=state.ownedTabs.filter(id=>id!==priorTab);await put(state);
  try{await ready(tab.id);await dispatch(state);}catch(error){state.job.phase='uncertain';state.job.reason=String(error.message??error);await put(state);}
  return 'retried';
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  (async()=>{
    if(message?.kind==='start'){
      if(!studioSender(sender)||!studioScope(sender.url,message.scope,message.scope))throw Error('Studio origin/scope mismatch');
      const old=await get();if(old?.active&&old.studioTab===sender.tab.id&&old.scope===message.scope)return {ok:true,active:true};
      if(old){
        const previous=archivePrevious(old);
        await put(old);
        if(previous)await chrome.storage.local.set({videostudio_bridge_last_abandoned:previous});
        await closeOwned(old);
      }
      const state=start({studioTab:sender.tab.id,scope:message.scope});await put(state);return {ok:true,active:true};
    }
    const state=await get();if(!state)throw Error('Bridge not configured');
    if(message?.kind==='snapshot'){if(!studioSender(sender)||sender.tab.id!==state.studioTab||!studioScope(sender.url,state.scope,state.scope))throw Error('Not owner');return {ok:true,active:state.active,job:state.job};}
    if(message?.kind==='stop'){
      if(!studioSender(sender)||sender.tab.id!==state.studioTab||!studioScope(sender.url,state.scope,state.scope))throw Error('Not owner');
      state.active=false;await put(state);await closeOwned(state);stop(state);await put(state);return {ok:true};
    }
    if(message?.kind==='imported'){
      if(!studioSender(sender)||sender.tab.id!==state.studioTab||!studioScope(sender.url,state.scope,state.scope)||state.job?.id!==message.id)throw Error('Uncorrelated import receipt');
      const previous=state.job.chatTab;if(!acknowledge(state,message))throw Error('Uncorrelated import receipt');
      state.ownedTabs=state.ownedTabs.filter(id=>id!==previous);await put(state);try{await chrome.tabs.remove(previous);}catch{}return {ok:true};
    }
    if(!state.active)throw Error('Bridge not active');
    if(message?.kind==='claim'){
      if(!studioSender(sender)||sender.tab.id!==state.studioTab||!studioScope(sender.url,state.scope,state.scope)||!claim(state,{...message,studioTab:sender.tab.id,scope:state.scope}))throw Error('Unowned or conflicting request');
      await put(state);if(state.job.phase==='claimed')await launch(state);return {ok:true,phase:state.job.phase};
    }
    if(message?.kind==='reconcile'){
      if(!studioSender(sender)||sender.tab.id!==state.studioTab||!studioScope(sender.url,state.scope,state.scope)||!state.job)throw Error('Not owner');
      return {ok:true,status:await reconcile(state)};
    }
    if(message?.kind==='sent'){
      if(!chatSender(sender)||sender.tab.id!==state.job?.chatTab||state.job.id!==message.id||state.job.attempt!==message.attempt||state.job.phase!=='dispatching')throw Error('Uncorrelated send');
      state.job.phase='sent';await put(state);return {ok:true};
    }
    if(message?.kind==='uncertain'){
      if(!chatSender(sender)||sender.tab.id!==state.job?.chatTab||state.job.id!==message.id||state.job.attempt!==message.attempt)throw Error('Uncorrelated uncertainty');
      state.job.phase='uncertain';state.job.reason=String(message.reason??'Unknown').slice(0,200);await put(state);return {ok:true};
    }
    if(message?.kind==='reply'){
      if(!chatSender(sender)||!result(state,{chatTab:sender.tab.id,id:message.id,attempt:message.attempt,text:message.text}))throw Error('Uncorrelated reply');
      await put(state);try{await chrome.tabs.sendMessage(state.studioTab,{kind:'reply',id:message.id});}catch{}return {ok:true};
    }
    throw Error('Unknown message');
  })().then(reply,error=>reply({ok:false,error:String(error.message??error)}));return true;
});

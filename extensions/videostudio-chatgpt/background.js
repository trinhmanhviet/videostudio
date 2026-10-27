import {start,claim,result,studioScope,canStart,acknowledge} from './protocol.mjs';
const KEY='videostudio_bridge_v1';
const get=async()=> (await chrome.storage.local.get(KEY))[KEY]??null;
const put=async state=>chrome.storage.local.set({[KEY]:state});
const studioSender=(sender,scope)=>sender.frameId===0&&Number.isInteger(sender.tab?.id)&&studioScope(sender.url,scope,scope);
const chatSender=sender=>sender.frameId===0&&new URL(sender.url).origin==='https://chatgpt.com'&&Number.isInteger(sender.tab?.id);
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  (async()=>{
    if(message?.kind==='start'){
      if(!studioSender(sender,message.scope))throw Error('Studio origin/scope mismatch');
      const old=await get();if(!canStart(old))throw Error('Previous request is active or unresolved; inspect its receipt before starting another');
      const tab=await chrome.tabs.create({url:'https://chatgpt.com/',active:true});
      const state={...start({studioTab:sender.tab.id,chatTab:tab.id,scope:message.scope}),active:true};await put(state);return {ok:true};
    }
    const state=await get();if(!state?.active)throw Error('Bridge not active');
    if(message?.kind==='stop'){
      if(!studioSender(sender,state.scope)||sender.tab.id!==state.studioTab)throw Error('Not owner');
      await put({...state,active:false});return {ok:true};
    }
    if(message?.kind==='imported'){
      if(!studioSender(sender,state.scope)||sender.tab.id!==state.studioTab||!acknowledge(state,message))throw Error('Uncorrelated import receipt');
      await put(state);return {ok:true};
    }
    if(message?.kind==='claim'){
      if(!studioSender(sender,state.scope)||!claim(state,{...message,studioTab:sender.tab.id,chatTab:state.chatTab,scope:state.scope}))throw Error('Unowned or conflicting request');
      await put(state);
      if(state.job.phase==='claimed'){
        // Persist uncertainty BEFORE any dispatch. A worker restart can never resend this request.
        state.job.phase='dispatching';await put(state);
        try {await chrome.tabs.sendMessage(state.chatTab,{kind:'deliver',id:state.job.id,prompt:state.job.prompt});}
        catch {return {ok:false,error:'Delivery uncertain; inspect owned ChatGPT tab, never resend automatically'};}
      }
      return {ok:true,phase:state.job.phase};
    }
    if(message?.kind==='sent'){
      if(!chatSender(sender)||sender.tab.id!==state.chatTab||state.job?.id!==message.id||state.job.phase!=='dispatching')throw Error('Uncorrelated send');
      state.job.phase='sent';await put(state);return {ok:true};
    }
    if(message?.kind==='uncertain'){
      if(!chatSender(sender)||sender.tab.id!==state.chatTab||state.job?.id!==message.id)throw Error('Uncorrelated uncertainty');
      state.job.phase='uncertain';state.job.reason=String(message.reason??'Unknown').slice(0,200);await put(state);return {ok:true};
    }
    if(message?.kind==='reply'){
      if(!chatSender(sender)||!result(state,{chatTab:sender.tab.id,id:message.id,text:message.text}))throw Error('Uncorrelated reply');
      await put(state);await chrome.tabs.sendMessage(state.studioTab,{kind:'reply',id:message.id,text:message.text});return {ok:true};
    }
    if(message?.kind==='snapshot'){
      if(!studioSender(sender,state.scope)||sender.tab.id!==state.studioTab)throw Error('Not owner');
      return {ok:true,job:state.job};
    }
    throw Error('Unknown message');
  })().then(reply,error=>reply({ok:false,error:String(error.message??error)}));return true;
});

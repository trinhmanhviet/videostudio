import './logical-text.js';
export const receiptMatches=globalThis.VideoStudioLogicalText.receiptMatches;
export const ORIGIN='http://localhost:8877';
export function studioScope(url,project,run){
  try {const u=new URL(url);return u.origin===ORIGIN&&project===run&&/^[0-9a-f-]{36}$/i.test(project)&&(u.pathname==='/'||u.pathname===`/story-video/projects/${project}/production`);}catch{return false;}
}
export const receiptPath=(scope,id)=>`/api/v1/projects/${encodeURIComponent(scope)}/runs/${encodeURIComponent(scope)}/chatgpt-exchanges/${encodeURIComponent(id)}`;
export const start=({studioTab,scope,chatTab=null})=>({studioTab,scope,chatTab,ownedTabs:chatTab?[chatTab]:[],active:true,job:null});
export const canStart=state=>!state?.active&&!state?.job;
export const canDiscard=(state,{studioTab,scope})=>!!state&&!state.active&&['dispatching','uncertain'].includes(state.job?.phase)&&state.studioTab===studioTab&&state.scope===scope;
export function archivePrevious(state){
  state.active=false;
  const job=state.job??state.suspendedJob;
  return job?{scope:state.scope,id:job.id,version:job.version,attempt:job.attempt,phase:job.phase}:null;
}
export function stop(state){state.active=false;state.ownedTabs=[];state.chatTab=null;state.suspendedJob=state.job??state.suspendedJob??null;state.job=null;return state;}
export function claim(state,{studioTab,scope,id,version,prompt}){
  if(state.studioTab!==studioTab||state.scope!==scope||typeof id!=='string'||!id||!Number.isInteger(version)||typeof prompt!=='string'||!prompt.startsWith(`YÊU CẦU STUDIO ${id}\n`))return false;
  if(state.job)return state.job.id===id&&state.job.version===version&&state.job.prompt===prompt;
  state.job={id,version,prompt,phase:'claimed',attempt:0,chatTab:null,reason:null};return true;
}
export function beginAttempt(state,tab){if(!state.active||state.job?.phase!=='claimed'||!Number.isInteger(tab))return false;state.job.attempt++;state.job.chatTab=tab;state.chatTab=tab;state.ownedTabs.push(tab);state.job.phase='dispatching';return true;}
export function retryAttempt(state,receipt,tab){
  const job=state.job;if(!state.active||!job||job.attempt!==1||!['dispatching','sent','uncertain'].includes(job.phase)||receipt?.id!==job.id||receipt.version!==job.version||receipt.accepted!==false||receipt.visibleUser!==null||!Number.isInteger(tab))return false;
  job.attempt=2;job.chatTab=tab;state.chatTab=tab;state.ownedTabs.push(tab);job.phase='dispatching';job.reason='One retry; previous dispatch may have been delivered';return true;
}
export function acknowledge(state,{id,version,accepted}){
  if(state.job?.phase!=='reply'||state.job.id!==id||state.job.version!==version||accepted!==true)return false;
  state.job=null;state.chatTab=null;return true;
}
export function result(state,{chatTab,id,attempt,text}){
  if(state.job?.chatTab!==chatTab||state.job?.id!==id||(attempt!=null&&state.job.attempt!==attempt)||state.job.phase!=='sent'||typeof text!=='string')return false;
  state.job.phase='reply';state.job.text=text;return true;
}

// Keep the original single-request helpers usable on individual slots. The
// bridge owns the controller; each slot owns its request and ChatGPT tabs.
export function migrateBridge(state){
  if(!state)return null;
  if(!Array.isArray(state.sessions)){
    const job=state.job??state.suspendedJob??null;
    state.sessions=job?[{scope:state.scope,studioTab:state.studioTab,active:state.active,job,
      chatTab:state.chatTab??job.chatTab,ownedTabs:[...(state.ownedTabs??[])],cancelled:false,job_id:null,lastReceipt:null}]:[];
  }
  return syncBridge(state);
}
export function syncBridge(state){
  const root=state.sessions.find(slot=>slot.scope===state.scope);
  state.job=state.active?(root?.job??null):null;
  state.suspendedJob=!state.active?(root?.job??null):null;
  state.chatTab=root?.chatTab??null;
  state.ownedTabs=[...new Set(allSlots(state).flatMap(slot=>slot.ownedTabs??[]))];
  return state;
}
export function sessionSlot(state,scope=state.scope){return state.sessions.find(slot=>slot.scope===scope)??null;}
export function allSlots(state){return state.sessions.flatMap(slot=>[slot,...(slot.retained??[])]);}
export function callbackSlot(state,{scope,id,attempt},tab){
  const matches=allSlots(state).filter(slot=>slot.active&&!slot.cancelled&&(scope==null||slot.scope===scope)&&
    slot.ownedTabs.includes(tab)&&slot.job?.chatTab===tab&&slot.job.id===id&&slot.job.attempt===attempt);
  return matches.length===1?matches[0]:null;
}
export function bridgeSnapshot(state){
  const summary=slot=>({
    scope:slot.scope,job:slot.job,active:slot.active,cancelled:slot.cancelled,job_id:slot.job_id,
    chatTab:slot.chatTab,ownedTabs:slot.ownedTabs,lastReceipt:slot.lastReceipt??null,is_smoke:slot.is_smoke===true,
    retained:(slot.retained??[]).map(summary)});
  return {ok:true,active:state.active,job:state.job,sessions:state.sessions.map(summary)};
}

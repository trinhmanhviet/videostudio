export const ORIGIN='http://localhost:8877';
export function studioScope(url,project,run){
  try {const u=new URL(url);return u.origin===ORIGIN&&project===run&&/^[0-9a-f-]{36}$/i.test(project)&&u.pathname===`/story-video/projects/${project}/production`;}catch{return false;}
}
export const receiptPath=(scope,id)=>`/api/v1/projects/${encodeURIComponent(scope)}/runs/${encodeURIComponent(scope)}/chatgpt-exchanges/${encodeURIComponent(id)}`;
export const start=({studioTab,chatTab,scope})=>({studioTab,chatTab,scope,job:null});
export const canStart=state=>!state?.active&&!state?.job;
export function claim(state,{studioTab,chatTab,scope,id,version,prompt}){
  if(state.studioTab!==studioTab||state.chatTab!==chatTab||state.scope!==scope||typeof id!=='string'||!id||!Number.isInteger(version)||typeof prompt!=='string')return false;
  if(state.job)return state.job.id===id&&state.job.version===version&&state.job.prompt===prompt;
  state.job={id,version,prompt,phase:'claimed'};return true;
}
export function acknowledge(state,{id,version,accepted}){
  if(state.job?.phase!=='reply'||state.job.id!==id||state.job.version!==version||accepted!==true)return false;
  state.job=null;return true;
}
export function result(state,{chatTab,id,text}){
  if(state.chatTab!==chatTab||state.job?.id!==id||state.job.phase!=='sent'||typeof text!=='string')return false;
  state.job.phase='reply';state.job.text=text;return true;
}

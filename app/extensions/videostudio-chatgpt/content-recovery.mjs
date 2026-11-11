/* Reattach public content scripts only; never submit a prompt or navigate a user tab. */
const studio=url=>{try{const u=new URL(url);return u.origin==='http://localhost:8877'&&(u.pathname==='/'||/^\/story-video\/projects\/[0-9a-f-]{36}\/production$/i.test(u.pathname));}catch{return false;}};
export async function ensureStudioScripts(chrome){
  if(!chrome.scripting?.executeScript||!chrome.tabs?.query)return;
  const version=chrome.runtime.getManifest().version;
  for(const tab of await chrome.tabs.query({url:'http://localhost:8877/*'})){
    if(!Number.isInteger(tab.id)||!studio(tab.url))continue;
    let seen,timer;try{seen=await Promise.race([chrome.tabs.sendMessage(tab.id,{kind:'connection_ping'}),new Promise(resolve=>{timer=setTimeout(()=>resolve(null),3000);})]);}catch{}finally{clearTimeout(timer);}
    if(seen?.ok&&seen.version===version)continue;
    try{await chrome.scripting.executeScript({target:{tabId:tab.id},files:['studio.js']});}catch{}
  }
}
export async function ensureChatScript(chrome,tabId){
  if(!chrome.scripting?.executeScript||!Number.isInteger(tabId))return false;
  const tab=await chrome.tabs.get(tabId);let url;try{url=new URL(tab.url);}catch{return false;}
  if(url.origin!=='https://chatgpt.com'||url.username||url.password)return false;
  await chrome.scripting.executeScript({target:{tabId},files:['send-button.js','logical-text.js','chatgpt.js']});return true;
}

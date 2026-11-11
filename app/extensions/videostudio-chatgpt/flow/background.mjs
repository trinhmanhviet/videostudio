import {flowSessionInfo,runFlowRpc,readFlowReceipt,forgetFlowVerification} from './page.mjs';
const KEY='videostudio_flow_bridge_v1',JOURNAL='videostudio_flow_pending_v1';
const SERVERS=new Set(['http://localhost:8877','http://127.0.0.1:8877','http://localhost:8878','http://127.0.0.1:8878']);
let busy=false,timer=null;
const get=async key=>(await chrome.storage.local.get(key))[key];
async function api(config,path,body,paired=true){
  if(!SERVERS.has(config.server))throw Error('Máy chủ không hợp lệ');
  const response=await fetch(config.server+'/api/flow-request'+path,{method:'POST',signal:AbortSignal.timeout(10000),
    headers:{'Content-Type':'application/json',...(paired?{'Authorization':'Bearer '+config.key,'X-Flow-Client':config.client_id}:{})},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Máy chủ từ chối kết nối');return data;
}
async function info(config){
  try{
    const tab=await chrome.tabs.get(config.tab);
    if(!tab.url?.startsWith('https://flow.google.com/'))throw Error('not Flow');
    await chrome.scripting.executeScript({target:{tabId:config.tab},world:'MAIN',files:['flow/session.js']});
    const values=await chrome.scripting.executeScript({target:{tabId:config.tab},world:'MAIN',func:flowSessionInfo});
    return {...values[0].result,enabled:config.enabled,version:chrome.runtime.getManifest().version};
  }catch{return {tab_open:false,session_ready:false,enabled:config.enabled,version:chrome.runtime.getManifest().version};}
}
async function savePending(pending){
  await chrome.storage.local.set({[JOURNAL]:{...pending,result:pending.result?.verification_token?null:pending.result}});
}
async function flush(config,current){
  const pending=current||await get(JOURNAL);if(!pending)return true;
  if(pending.client_id!==config.client_id)throw Error('Còn biên nhận thuộc kết nối cũ; không gửi request mới.');
  if(!pending.result){
    try{
      const values=await chrome.scripting.executeScript({target:{tabId:pending.tab},world:'MAIN',func:readFlowReceipt,args:[pending.id]});
      if(values[0].result?.in_flight)return false;
      pending.result=values[0].result||{transport_error:'extension_interrupted'};
    }catch{pending.result={transport_error:'extension_interrupted'};}
    await savePending(pending);
  }
  await api(config,`/commands/${pending.id}/result`,{dispatch:pending.dispatch,result:pending.result});
  if(pending.result?.verification_token)try{await chrome.scripting.executeScript({target:{tabId:pending.tab},world:'MAIN',func:forgetFlowVerification,args:[pending.id]});}catch{}
  await chrome.storage.local.remove(JOURNAL);return true;
}
async function cycle(){
  if(busy)return;busy=true;
  try{
    const config=await get(KEY);if(!config)return;
    if(!await flush(config))return;
    const status=await info(config);
    const {command}=await api(config,'/poll',status);
    await chrome.storage.local.set({flow_status:{...status,last_sync:Date.now(),error:null}});
    if(!command||!config.enabled)return;
    const pending={id:command.id,dispatch:command.dispatch,client_id:config.client_id,tab:config.tab,result:null};
    await chrome.storage.local.set({[JOURNAL]:pending});
    try{
      if(!(await get(KEY))?.enabled)pending.result={transport_error:'extension_paused'};
      else{
        const values=await chrome.scripting.executeScript({target:{tabId:config.tab},world:'MAIN',func:runFlowRpc,args:[command]});
        pending.result=values[0].result||{transport_error:'extension_interrupted'};
      }
    }catch{pending.result={transport_error:'extension_interrupted'};}
    await savePending(pending);await flush(config,pending);
  }catch(error){await chrome.storage.local.set({flow_status:{last_sync:Date.now(),error:error.message}});}
  finally{busy=false;}
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(!message?.kind?.startsWith('flow:')||sender.id!==chrome.runtime.id||sender.url!==chrome.runtime.getURL('flow/popup.html'))return false;
  const kind=message.kind.slice(5);
  (async()=>{
    if(kind==='status')return {config:await get(KEY)?{...(await get(KEY)),key:undefined}:null,status:await get('flow_status')};
    if(kind==='connect'){
      if(busy||await get(JOURNAL))throw Error('Đang có request/biên nhận cần đối chiếu. Hãy chờ đồng bộ xong.');
      const server=message.server;if(!SERVERS.has(server)||!Number.isInteger(message.tab))throw Error('Thông tin kết nối không hợp lệ');
      const tab=await chrome.tabs.get(message.tab);if(!tab.url?.startsWith('https://flow.google.com/'))throw Error('Chọn một tab Flow đang mở.');
      const previous=await get(KEY);
      const paired=!message.code&&previous?.server===server?{client_id:previous.client_id,key:previous.key}:await api({server},'/pair',{code:message.code},false);
      await chrome.storage.local.set({[KEY]:{...paired,server,tab:message.tab,enabled:true}});
      await schedule();await cycle();return {ok:true};
    }
    if(kind==='stop'){
      const config=await get(KEY);if(config)await chrome.storage.local.set({[KEY]:{...config,enabled:false}});
      await cycle();if(timer){clearInterval(timer);timer=null;}await chrome.alarms.clear('flow-request');return {ok:true};
    }
    if(kind==='sync'){await cycle();return {ok:true};}
    throw Error('Lệnh không hợp lệ');
  })().then(reply,error=>reply({error:error.message}));return true;
});
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='flow-request')cycle();});
async function schedule(){
  // Flow remains opt-in. ChatGPT users need no extra permissions or polling.
  if(!await chrome.permissions.contains({permissions:['scripting'],origins:['https://flow.google.com/*']}))return;
  const registered=await chrome.scripting.getRegisteredContentScripts({ids:['videostudio-flow-session']});
  if(!registered.length)await chrome.scripting.registerContentScripts([{id:'videostudio-flow-session',matches:['https://flow.google.com/*'],js:['flow/session.js'],runAt:'document_start',world:'MAIN'}]);
  await chrome.alarms.create('flow-request',{periodInMinutes:0.5});
  if(!timer)timer=setInterval(cycle,5000);
}
async function initialize(){const config=await get(KEY);if(config?.enabled||await get(JOURNAL)){await schedule();await cycle();}}
chrome.runtime.onInstalled.addListener(()=>{initialize().catch(()=>{});});
chrome.runtime.onStartup.addListener(()=>{initialize().catch(()=>{});});
initialize().catch(()=>{});

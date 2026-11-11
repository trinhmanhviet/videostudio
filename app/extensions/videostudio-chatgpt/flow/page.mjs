// These functions are passed by value to chrome.scripting; keep them closure-free.
export function flowSessionInfo(){
  if(location.origin!=='https://flow.google.com')return {tab_open:false,session_ready:false};
  const state=globalThis[Symbol.for('videostudio.flow.session.v1')];
  const wiz=globalThis.WIZ_global_data;
  // Frontend bootstrap values are optional; observed requests take priority.
  if(state&&wiz){state.at ||= wiz.SNlM0e;state.sid ||= wiz.FdrFJe;state.build ||= wiz.cfb2h;}
  // Public integration metadata only. Use the SDK already loaded by Flow;
  // do not inject another SDK/widget or reach into its private client state.
  const keys=new Set();
  if(typeof document!=='undefined')for(const element of document.querySelectorAll('script[src],iframe[src],[data-sitekey]')){
    try{
      let key=element.getAttribute('data-sitekey');
      const src=element.getAttribute('src');
      if(src){
        const url=new URL(src,location.href);
        if(['www.google.com','www.recaptcha.net','recaptcha.google.com'].includes(url.hostname)&&url.pathname.startsWith('/recaptcha/'))key=url.searchParams.get('render')||url.searchParams.get('k')||key;
      }
      if(typeof key==='string'&&/^[A-Za-z0-9_-]{20,200}$/.test(key))keys.add(key);
    }catch{}
  }
  if(state)state.verificationSiteKey=keys.size===1?[...keys][0]:null;
  let guarded=false;
  try{guarded=Function.prototype.toString.call(globalThis.grecaptcha?.enterprise?.execute).includes('extension_hijack_detected');}catch{}
  const project=location.pathname.match(/^\/project\/([0-9a-f-]{36})(?:\/|$)/i)?.[1]||'';
  return {tab_open:true,session_ready:!!(state?.at&&state?.sid&&state?.build),project_id:project,build:typeof state?.build==='string'?state.build:'',
    verification_sdk:typeof globalThis.grecaptcha?.enterprise?.execute==='function',verification_key_available:!!state?.verificationSiteKey,
    verification_guard_detected:guarded};
}

export function readFlowReceipt(id){
  if(location.origin!=='https://flow.google.com')return {transport_error:'extension_interrupted'};
  const memory=globalThis[Symbol.for('videostudio.flow.requests.v1')];
  if(memory?.has(id))return memory.get(id).result||{in_flight:true};
  try{
    const saved=JSON.parse(sessionStorage.getItem('videostudio.flow.request:'+id)||'null');
    return saved?.result||{transport_error:'previous_attempt'};
  }catch{return {transport_error:'previous_attempt'};}
}

export function forgetFlowVerification(id){
  globalThis[Symbol.for('videostudio.flow.requests.v1')]?.delete(id);
}

export async function runFlowRpc(command){
  const allowed={list_projects:'UpteDb',list_characters:'ngNC2',create_project:'jHPbke',create_character:'C4BZMd',rename_character:'rzMKMb',generate_image:'ogiZ0b',prepare_generation:'__flow_verify__'};
  if(location.origin!=='https://flow.google.com'||allowed[command.operation]!==command.rpcid||!Array.isArray(command.payload)||
    !/^[0-9a-f-]{36}$/i.test(command.id)||JSON.stringify(command.payload).length>128000)return {transport_error:'session_unavailable'};
  const symbol=Symbol.for('videostudio.flow.requests.v1');
  const requests=globalThis[symbol]||(globalThis[symbol]=new Map());
  const identity=JSON.stringify([command.rpcid,command.source_path,command.payload,...(command.operation==='prepare_generation'?[command.arguments?.handoff_hash]:[])]);
  if(requests.has(command.id)){
    const previous=requests.get(command.id);
    return previous.identity===identity?previous.promise:{transport_error:'previous_attempt'};
  }
  const key='videostudio.flow.request:'+command.id;
  let old;
  try{old=JSON.parse(sessionStorage.getItem(key)||'null');}catch{return {transport_error:'previous_attempt'};}
  if(old)return old.identity===identity&&old.result?old.result:{transport_error:'previous_attempt'};
  const state=globalThis[Symbol.for('videostudio.flow.session.v1')];
  if(!state?.at||!state?.sid||!state?.build)return {transport_error:'session_unavailable'};
  const wanted=command.source_path.match(/^\/project\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
  const current=location.pathname.match(/^\/project\/([0-9a-f-]{36})(?:\/|$)/i)?.[1];
  if(wanted&&wanted.toLowerCase()!==current?.toLowerCase())return {transport_error:'wrong_project'};
  const entry={identity,result:null,promise:null};
  requests.set(command.id,entry);
  // The browser journal is durable before fetch. Reload/suspension cannot turn an
  // uncertain write into permission to submit the same prompt again.
  try{sessionStorage.setItem(key,JSON.stringify({identity,attempted:true}));}
  catch{requests.delete(command.id);return {transport_error:'session_unavailable'};}
  entry.promise=(async()=>{
    let result;
    const payload=JSON.parse(JSON.stringify(command.payload));
    if(['generate_image','prepare_generation'].includes(command.operation)){
      const sdk=globalThis.grecaptcha?.enterprise;
      let guarded=false;
      try{guarded=Function.prototype.toString.call(sdk?.execute).includes('extension_hijack_detected');}catch{}
      if(guarded)result={transport_error:'verification_guarded'};
      else if(!state.verificationSiteKey||typeof sdk?.ready!=='function'||typeof sdk?.execute!=='function')result={transport_error:'verification_unavailable'};
      else{
        const bounded=async(promise,ms)=>{let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('verification timeout')),ms);})]);}finally{clearTimeout(timer);}};
        try{
          await bounded(new Promise(resolve=>sdk.ready(resolve)),5000);
          const token=await bounded(sdk.execute(state.verificationSiteKey,{action:'IMAGE_GENERATION'}),20000);
          if(typeof token!=='string'||token.length<100||token.length>32000)throw Error('verification not completed');
          if(command.operation==='prepare_generation')result={request_id:command.id,verification_token:token,user_agent:navigator.userAgent};
          else{
          if(!Array.isArray(payload[1]?.[0]?.[7])||!Array.isArray(payload[3]))throw Error('invalid generation envelope');
          // The same fresh proof goes in both context fields, as in the native
          // HAR. It stays in this call; neither journal nor desktop gets it.
          payload[1][0][7][10]=[token,1];payload[3][10]=[token,1];
          }
        }catch{result={transport_error:'verification_failed'};}
      }
    }
    if(!result){
    try{
      const params=new URLSearchParams({rpcids:command.rpcid,'source-path':command.source_path,bl:state.build,'f.sid':state.sid,hl:state.language||'vi',_reqid:String(Date.now()%900000000),rt:'c'});
      const form=new URLSearchParams({'f.req':JSON.stringify([[[command.rpcid,JSON.stringify(payload),null,'generic']]]),at:state.at});
      const response=await state.nativeFetch('/_/AiSandboxAngularFrontend/data/batchexecute?'+params,{method:'POST',credentials:'include',redirect:'error',
        headers:{'Content-Type':'application/x-www-form-urlencoded;charset=utf-8','X-Same-Domain':'1'},body:form.toString(),signal:AbortSignal.timeout(command.operation==='generate_image'?90000:20000)});
      const reader=response.body?.getReader();
      let size=0,body='';const decoder=new TextDecoder();
      if(!reader)throw Error('empty response');
      while(true){
        const part=await reader.read();if(part.done)break;size+=part.value.byteLength;
        if(size>2*1024*1024){await reader.cancel();throw Error('response too large');}
        body+=decoder.decode(part.value,{stream:true});
      }
      body+=decoder.decode();result={http_status:response.status,body};
    }catch{result={transport_error:'network_uncertain'};}
    }
    entry.result=result;
    const saved=result?.verification_token?{transport_error:'verification_handoff_uncertain'}:result;
    try{sessionStorage.setItem(key,JSON.stringify({identity,attempted:true,result:saved}));}catch{}
    return result;
  })();
  return entry.promise;
}

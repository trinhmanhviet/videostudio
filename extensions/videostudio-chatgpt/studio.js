(()=>{
  const scope=location.pathname.match(/^\/story-video\/projects\/([0-9a-f-]{36})\/production$/i)?.[1];
  if(location.origin!=='http://localhost:8877'||(!scope&&location.pathname!=='/'))return;
  const root=document.createElement('aside');root.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483647;font:13px system-ui';
  const shadow=root.attachShadow({mode:'closed'});shadow.innerHTML='<style>section{background:#142620;color:#fff;padding:12px;border-radius:8px;box-shadow:0 3px 20px #0006}button{margin:4px;padding:6px}p{max-width:300px}</style><section><strong>VideoStudio · ChatGPT</strong><p id="status">Chưa kết nối.</p><button id="start">Start</button><button id="smoke">Test chữ</button><button id="stop">Stop</button></section>';
  document.documentElement.append(root);
  const status=shadow.querySelector('#status');let active=false,busy=false,retired=false;const intervals=[];const listeners=[];
  function retire(){if(retired)return;retired=true;active=false;for(const timer of intervals)clearInterval(timer);for(const [node,type,handler] of listeners)node.removeEventListener?.(type,handler);chrome.runtime.onMessage.removeListener?.(onReply);status.textContent='Tiện ích đã tải lại. Tải lại trang Studio một lần.';}
  const invalid=error=>/Extension context invalidated|Receiving end does not exist|Cannot access a chrome\.runtime/i.test(String(error?.message??error));
  const send=async message=>{if(retired)return {ok:false,error:'Extension context invalidated'};try{return await chrome.runtime.sendMessage(message);}catch(error){if(invalid(error)){retire();return {ok:false,error:'Extension context invalidated'};}throw error;}};
  const api=async(path,options)=>{const response=await fetch(path,{credentials:'same-origin',...options});if(!response.ok)throw Error(`Studio HTTP ${response.status}`);return response.json();};
  async function heartbeat(){if(!scope||retired)return;try{await api('/api/connector/status/'+scope,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({build:'videostudio-extension-0.2.0',stage:active?'active':'stopped',connected:active,enabled:active})});}catch(error){if(active){active=false;status.textContent='Heartbeat lỗi; kết nối tạm dừng';}}}
  async function importReply(job){
    const base=`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges`;
    const receipt=await api(`${base}/${encodeURIComponent(job.id)}`);
    if(receipt.id!==job.id||receipt.version!==job.version)throw Error('Receipt correlation mismatch');
    if(!receipt.accepted){const answer=await api(`${base}/${encodeURIComponent(job.id)}/response`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:job.version,response_text:job.text})});if(answer.id!==job.id||answer.version!==job.version||answer.accepted!==true)throw Error('Import receipt mismatch');}
    const ack=await send({kind:'imported',id:job.id,version:job.version,accepted:true});if(!ack.ok)throw Error(ack.error);status.textContent=`Đã nhận ${job.id}`;
  }
  async function tick(){
    if(!active||busy||retired||!scope)return;busy=true;
    try{
      const state=await send({kind:'snapshot'});if(!state.ok)throw Error(state.error);
      if(state.job?.phase==='reply'){await importReply(state.job);return;}
      if(state.job){if(['uncertain','sent','dispatching'].includes(state.job.phase)){const result=await send({kind:'reconcile'});if(!result.ok)throw Error(result.error);status.textContent=`${state.job.id}: ${result.status}`;}return;}
      const pending=await api(`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges`);const item=pending.items?.[0];if(!item)return;
      if(!item.id||!Number.isInteger(item.version)||typeof item.prompt!=='string'||item.attachments?.length)throw Error('Unsupported request shape/attachments');
      const response=await send({kind:'claim',id:item.id,version:item.version,prompt:item.prompt});if(!response.ok)throw Error(response.error);
      status.textContent=`${item.id}: ${response.phase}`;
    }catch(error){if(!retired){status.textContent=`Tạm dừng: ${error.message}`;active=false;}}finally{busy=false;}
  }
  function listen(node,type,fn){node.addEventListener(type,fn);listeners.push([node,type,fn]);}
  listen(shadow.querySelector('#start'),'click',async event=>{
    if(!event.isTrusted||active||retired)return;
    try{
      let target=scope;
      if(!target){const session=await api('/api/connector/sessions',{method:'POST'});if(session.project_id!==session.run_id||session.url!==`/story-video/projects/${session.project_id}/production`)throw Error('Invalid connector scope');target=session.project_id;}
      const response=await send({kind:'start',scope:target});if(!response.ok)throw Error(response.error);
      active=true;status.textContent='Đã kết nối';await heartbeat();if(!scope){location.assign(`/story-video/projects/${target}/production`);return;}await tick();
    }catch(error){if(!retired)status.textContent=`Không thể Start: ${error.message}`;}
  });
  listen(shadow.querySelector('#smoke'),'click',async event=>{if(!event.isTrusted||!active||!scope||retired)return;try{const result=await api('/api/connector/smoke/'+scope,{method:'POST'});status.textContent=`Test chữ đã xếp hàng: ${result.exchange_id}`;await tick();}catch(error){if(!retired)status.textContent=`Test chữ lỗi: ${error.message}`;}});
  listen(shadow.querySelector('#stop'),'click',async event=>{if(!event.isTrusted||retired)return;try{const response=await send({kind:'stop'});if(!response.ok)throw Error(response.error);active=false;await heartbeat();status.textContent='Đã dừng và đóng tab ChatGPT thuộc tiện ích';}catch(error){if(!retired)status.textContent=`Stop lỗi: ${error.message}`;}});
  function onReply(message,_sender,reply){if(message?.kind!=='reply'||retired)return;if(active)void tick().catch(()=>{});reply({ok:true});}
  chrome.runtime.onMessage.addListener(onReply);
  intervals.push(setInterval(()=>{void tick().catch(()=>{});},1200));
  intervals.push(setInterval(()=>{if(active)void heartbeat().catch(()=>{});},10000));
  if(scope)void send({kind:'snapshot'}).then(state=>{if(retired)return;if(state.ok){active=state.active;status.textContent=active?'Đã kết nối':'Đã dừng';if(active)void tick();}}).catch(()=>{});
})();

(()=>{
  const scope=location.pathname.match(/^\/story-video\/projects\/([0-9a-f-]{36})\/production$/i)?.[1];
  if(location.origin!=='http://localhost:8877'||(!scope&&location.pathname!=='/'))return;
  const root=document.createElement('aside');root.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483647;font:13px system-ui';
  const shadow=root.attachShadow({mode:'closed'});shadow.innerHTML='<style>section{background:#142620;color:#fff;padding:12px;border-radius:8px;box-shadow:0 3px 20px #0006}button{margin:4px;padding:6px}p{max-width:300px}</style><section><strong>VideoStudio · ChatGPT</strong><p id="status">Idle — click Start to open a dedicated ChatGPT tab.</p><button id="start">Start</button><button id="stop">Stop</button></section>';
  document.documentElement.append(root);
  const status=shadow.querySelector('#status');let active=false,busy=false;
  const api=async(path,options)=>{const response=await fetch(path,{credentials:'same-origin',...options});if(!response.ok)throw Error(`Studio HTTP ${response.status}`);return response.json();};
  const send=message=>chrome.runtime.sendMessage(message);
  async function importReply(job){
    const base=`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges`;
    const receipt=await api(`${base}/${encodeURIComponent(job.id)}`);
    if(receipt.id!==job.id||receipt.version!==job.version)throw Error('Receipt correlation mismatch');
    if(!receipt.accepted){
      const answer=await api(`${base}/${encodeURIComponent(job.id)}/response`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:job.version,response_text:job.text})});
      if(answer.id!==job.id||answer.version!==job.version||answer.accepted!==true)throw Error('Import receipt mismatch');
    }
    const ack=await send({kind:'imported',id:job.id,version:job.version,accepted:true});
    if(!ack.ok)throw Error('Import acknowledgement failed; inspect receipt before continuing');
    status.textContent=`Imported ${job.id}`;
  }
  async function tick(){
    if(!active||busy)return;busy=true;
    try{
      const state=await send({kind:'snapshot'});if(!state.ok)throw Error(state.error);
      if(state.job?.phase==='reply'){await importReply(state.job);return;}
      if(state.job){status.textContent=`${state.job.id}: ${state.job.phase}; no automatic resend`;return;}
      const pending=await api(`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges`);
      const item=pending.items?.[0];if(!item)return;
      if(!item.id||!Number.isInteger(item.version)||typeof item.prompt!=='string'||item.attachments?.length)throw Error('Unsupported request shape/attachments');
      const claim=await send({kind:'claim',id:item.id,version:item.version,prompt:item.prompt});
      if(!claim.ok)throw Error(claim.error);
      status.textContent=`${item.id}: ${claim.phase}`;
    }catch(error){status.textContent=`Paused: ${error.message}`;active=false;}finally{busy=false;}
  }
  shadow.querySelector('#start').addEventListener('click',async event=>{
    if(!event.isTrusted||active)return;
    try{if(sessionStorage.getItem('videostudio:authorized-scope')!==scope){
        const session=await api('/api/connector/sessions',{method:'POST'});
        if(session.project_id!==session.run_id||session.url!==`/story-video/projects/${session.project_id}/production`)throw Error('Invalid connector scope');
        sessionStorage.setItem('videostudio:authorized-scope',session.project_id);
        location.assign(session.url);return;
      }
      sessionStorage.removeItem('videostudio:authorized-scope');
      const response=await send({kind:'start',scope});if(!response.ok)throw Error(response.error);
      active=true;status.textContent='Connected; awaiting one text request';await tick();
    }catch(error){status.textContent=`Not started: ${error.message}`;}
  });
  shadow.querySelector('#stop').addEventListener('click',async event=>{if(!event.isTrusted)return;active=false;const response=await send({kind:'stop'});status.textContent=response.ok?'Stopped':`Stop failed: ${response.error}`;});
  chrome.runtime.onMessage.addListener((message,_sender,reply)=>{if(message?.kind!=='reply')return;if(active)tick();reply({ok:true});});
  setInterval(tick,1200);
})();

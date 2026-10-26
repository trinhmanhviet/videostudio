/* VideoStudio Per-Scene Visual Editor - Dedicated Page View */
(() => {
  'use strict';
  const style = document.createElement('style');
  style.textContent = `
  #viewSceneEditor {
    width: 100%;
    max-width: 1500px;
    margin: 0 auto;
    padding-bottom: 60px;
  }
  .se-page-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(12, 17, 14, 0.95);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    padding: 8px 0;
    border-bottom: 1px solid var(--line);
    margin-bottom: 12px;
  }
  @media(max-width: 640px) {
    .se-page-header {
      padding: 6px 0;
      gap: 6px !important;
    }
    .se-page-header h2 {
      font-size: 15px !important;
    }
    .se-page-header button, .se-page-header select {
      font-size: 12px !important;
      padding: 6px 8px !important;
      min-height: 36px;
    }
    .se-page-header .badge {
      font-size: 11px !important;
    }
  }
  .se-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr));
    gap: 16px;
    margin-top: 14px;
  }
  @media(max-width: 680px) {
    .se-grid {
      grid-template-columns: 1fr;
      gap: 14px;
    }
  }
  .se-card {
    background: #0d1410;
    border: 1px solid #1f2e24;
    border-radius: 12px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  }
  .se-card-header {
    font-size: 14.5px;
    font-weight: 700;
    color: #f3f4f6;
    margin-bottom: 2px;
    letter-spacing: -0.01em;
  }
  .se-card-top {
    display: grid;
    grid-template-columns: 1fr 130px;
    gap: 14px;
    align-items: start;
  }
  @media(max-width: 380px) {
    .se-card-top {
      grid-template-columns: 1fr 115px;
      gap: 10px;
    }
  }
  .se-card-img-wrap {
    width: 100%;
    aspect-ratio: 9/16;
    background: #000;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid #233529;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .se-main-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    background: #000;
  }
  .se-card-ctrls {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .se-btn-green {
    background: #16a34a;
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
    padding: 9px 12px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    text-align: center;
    transition: background 0.15s ease, transform 0.1s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 40px;
    box-shadow: 0 2px 6px rgba(22, 163, 74, 0.3);
  }
  .se-btn-green:hover:not(:disabled) {
    background: #15803d;
    transform: translateY(-1px);
  }
  .se-btn-green:disabled {
    opacity: 0.55;
    cursor: not-allowed;
    transform: none;
  }
  .se-provider-radios {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 4px;
    background: #080d0a;
    padding: 8px 10px;
    border-radius: 6px;
    border: 1px solid #1a271e;
  }
  .se-provider-note {
    display: block;
    color: #9ca3af;
    font-size: 10.5px;
    line-height: 1.35;
    margin: 0 2px 3px;
  }
  .se-radio-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 13.5px;
    color: #e5e7eb;
    cursor: pointer;
    user-select: none;
  }
  .se-radio-item input[type="radio"] {
    margin: 0;
    accent-color: #16a34a;
    cursor: pointer;
    width: 15px;
    height: 15px;
  }
  .se-radio-item.is-disabled {
    color: #6b7280;
    cursor: not-allowed;
  }
  .se-radio-item.is-disabled input {
    cursor: not-allowed;
    opacity: 0.5;
  }
  .se-prompt-toggle {
    background: none;
    border: none;
    color: var(--muted);
    font-size: 11.5px;
    cursor: pointer;
    padding: 2px 0;
    text-align: left;
    text-decoration: underline;
    opacity: 0.85;
  }
  .se-prompt-toggle:hover {
    color: var(--accent);
    opacity: 1;
  }
  .se-prompt-box {
    margin-top: 4px;
  }
  .se-prompt-input {
    width: 100%;
    min-height: 60px;
    font-size: 12px;
    background: #080d0a;
    border: 1px solid #233529;
    color: #e5e7eb;
    border-radius: 4px;
    padding: 6px;
    resize: vertical;
  }
  .se-narration {
    font-size: 13.5px;
    line-height: 1.5;
    color: #d1d5db;
    margin: 2px 0;
    min-height: 38px;
  }
  .se-audio {
    width: 100%;
    height: 36px;
    border-radius: 6px;
    margin: 2px 0;
  }
  .se-history-select {
    width: 100%;
    font-size: 12.5px;
    background: #080d0a;
    border: 1px solid #233529;
    color: #e5e7eb;
    border-radius: 6px;
    padding: 6px 8px;
  }
  .se-thumbs-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    max-height: 185px;
    overflow-y: auto;
    padding-right: 2px;
    scrollbar-width: thin;
    scrollbar-color: #233529 #080d0a;
  }
  .se-thumb-wrap {
    position: relative;
    aspect-ratio: 9/16;
    border-radius: 4px;
    overflow: hidden;
    cursor: pointer;
    border: 2px solid #1a271e;
    background: #000;
    transition: border-color 0.15s ease, transform 0.1s ease;
  }
  .se-thumb-wrap:hover {
    transform: scale(1.03);
    border-color: #2e4737;
  }
  .se-thumb-wrap.is-active {
    border-color: #16a34a;
    box-shadow: 0 0 8px rgba(22, 163, 74, 0.4);
  }
  .se-thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .se-thumb-badge {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    font-size: 8.5px;
    background: rgba(0,0,0,0.75);
    color: #e5e7eb;
    text-align: center;
    padding: 1px 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .se-card-status {
    font-size: 12px;
    color: var(--accent);
    min-height: 18px;
  }
  .se-card-status.is-error {
    color: #fca5a5;
  }
  `;
  style.textContent += `
  body.scene-editor-active main{width:80vw;max-width:none;margin-inline:auto;padding-inline:0}
  #viewSceneEditor{max-width:none;width:100%}
  .se-grid{grid-template-columns:repeat(4,minmax(0,1fr));align-items:start}
  .se-card{min-width:0;padding:12px;box-shadow:none}
  .se-card-top{grid-template-columns:minmax(0,1fr) minmax(82px,34%);gap:10px}
  .se-card-img-wrap{min-width:0}.se-provider-radios{padding:8px}
  .se-btn-green{font-size:13px;padding:8px;min-height:40px}
  .se-prompt-input{min-height:100px;box-sizing:border-box;font-size:13px}
  .se-prompt-toggle{min-height:32px}.se-pager{display:flex;justify-content:center;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}
  .se-narration{min-height:0}.se-card-status:empty{display:none}
  .se-page-header{z-index:10}.se-history-select{min-width:0}
  @media(max-width:1100px){body.scene-editor-active main{width:94vw}.se-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media(max-width:600px){body.scene-editor-active main{width:calc(100% - 24px)}.se-grid{grid-template-columns:minmax(0,1fr)}}
  `;
  document.head.append(style);

  const $=id=>document.getElementById(id);
  const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
  const uid=()=>globalThis.crypto?.randomUUID?.()||('vs-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2));
  const clock=s=>{const n=Math.max(0,Math.floor(Number(s)||0));return Math.floor(n/60)+':'+String(n%60).padStart(2,'0');};
  const caches=new Map(), PAGE_SIZE=12;
  let job=null,state=null,busy=false,epoch=0,timers=new Set(),priorView='viewGallery',workspaceScroll=0;
  const base=(id=job)=>'/api/jobs/'+encodeURIComponent(id)+'/scene-editor';
  const cache=()=>{if(!caches.has(job))caches.set(job,{page:0,filter:'all',scroll:0,drafts:new Map(),expanded:new Set(),tasks:new Map(),requestKeys:new Map(),providers:new Map(),providersAvailable:['chatgpt','comfy']});return caches.get(job);};
  function message(text,error=false){$('sePageMessage').textContent=text;$('sePageMessage').style.color=error?'#fca5a5':'var(--accent)';}
  async function request(path,opts={}){const r=await fetch(path,{...opts,headers:{'Content-Type':'application/json',...opts.headers},signal:AbortSignal.timeout(120000)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail||d));return d;}
  const imageURL=(s,edit)=>base()+'/scenes/'+encodeURIComponent(s.scene_id)+'/image?edit='+encodeURIComponent(edit)+'&thumb=true';
  function clearPolling(){epoch++;for(const t of timers)clearTimeout(t);timers.clear();}
  function controls(){
    const view=$('viewSceneEditor');
    view.querySelectorAll('button,select,input,textarea').forEach(e=>{if(e.id==='btnBackFromEditor')return;e.disabled=busy||e.dataset.permDisabled==='true'||(e.dataset.requiresEdit==='true'&&!state?.editable)||e.dataset.pending==='true'||e.dataset.boundary==='true';});
  }
  function pager(){
    let p=$('sePagination');if(p)return p;
    p=node('nav',undefined,'se-pager');p.id='sePagination';p.setAttribute('aria-label','Phân trang cảnh');$('sePageGrid').after(p);return p;
  }
  function schedule(fn,ms){const t=setTimeout(()=>{timers.delete(t);fn();},ms);timers.add(t);}
  async function mutate(path,payload,s,card,preview,value){
    if(busy||!state?.editable)return false;
    const jid=job,token=epoch,img=card.querySelector('.se-main-image'),select=card.querySelector('.se-history-select');
    const oldSrc=img.getAttribute('src'),oldValue=s.edit_id;
    busy=true;controls();if(preview)img.src=preview;if(value)select.value=value;
    const status=card.querySelector('.se-card-status');status.textContent='Đang lưu lựa chọn…';message('Đang lưu lựa chọn ảnh…');
    try{
      const result=await request(base(jid)+path,{method:'POST',body:JSON.stringify({...payload,version:state.version})});
      if(job!==jid)return true;
      state=result;cache().state=result;cache().exportKey=null;
      const row=result.scenes.find(x=>x.scene_id===s.scene_id);
      if(card.isConnected&&epoch===token&&row){
        Object.assign(s,row);img.src=s.image_url+(s.image_url.includes('?')?'&':'?')+'thumb=true';img.style.objectFit=s.fit==='contain'?'contain':'cover';
        if(path.endsWith('/apply'))cache().tasks.delete(s.scene_id);
        card.updateOptions();status.textContent='Đã lưu';
      }
      $('sePageCount').textContent=state.scenes.length+' cảnh';message('Đã lưu ảnh đã chọn.');return true;
    }catch(e){
      if(card.isConnected&&epoch===token){img.src=oldSrc;select.value=oldValue;status.textContent='Chưa lưu: '+e.message;}
      message('Không lưu được lựa chọn: '+e.message,true);return false;
    }finally{busy=false;controls();}
  }
  function render(){
    clearPolling();const token=epoch,jid=job,c=cache();
    const filtered=state.scenes.filter(s=>c.filter!=='edited'||s.edit_id!=='original');const pages=Math.max(1,Math.ceil(filtered.length/PAGE_SIZE));c.page=Math.min(Math.max(c.page,0),pages-1);
    $('sePageTitle').textContent='Ảnh từng cảnh';$('sePageCount').textContent=state.scenes.length+' cảnh';$('sePageFilter').value=c.filter;
    const grid=$('sePageGrid');grid.replaceChildren(...filtered.slice(c.page*PAGE_SIZE,(c.page+1)*PAGE_SIZE).map(makeCard));
    const p=pager(),prev=node('button','← Trước','secondary'),next=node('button','Sau →','secondary');prev.type=next.type='button';prev.id='sePrevPage';next.id='seNextPage';prev.dataset.boundary=String(c.page===0);next.dataset.boundary=String(c.page===pages-1);
    const pageText=node('span',`Trang ${c.page+1} / ${pages} · ${filtered.length?c.page*PAGE_SIZE+1:0}-${Math.min((c.page+1)*PAGE_SIZE,filtered.length)} / ${filtered.length} cảnh`);pageText.id='sePageNumber';
    const change=n=>{if(busy)return;c.page=n;render();$('viewSceneEditor').scrollIntoView({block:'start'});};prev.onclick=()=>change(c.page-1);next.onclick=()=>change(c.page+1);p.replaceChildren(prev,pageText,next);controls();
    // Mount before starting network reads. Only visible page cards request candidates.
    for(const card of grid.children)card.loadCandidates();
    function makeCard(s){
      const card=node('article',undefined,'se-card');card.dataset.sceneId=s.scene_id;const alive=()=>job===jid&&epoch===token&&card.isConnected&&!$('viewSceneEditor').hidden;
      const path='/scenes/'+encodeURIComponent(s.scene_id),endpoint=base(jid)+path+'/generations';
      card.append(node('div',`Cảnh ${s.index+1} · ${clock(s.start)} - ${clock(s.start+s.duration)} (${Number(s.duration).toFixed(2)}s)`,'se-card-header'));
      const top=node('div',undefined,'se-card-top'),wrap=node('div',undefined,'se-card-img-wrap'),img=node('img',undefined,'se-main-image');img.loading='lazy';img.decoding='async';img.src=s.image_url+(s.image_url.includes('?')?'&':'?')+'thumb=true';img.alt='Ảnh cảnh '+(s.index+1);img.style.objectFit=s.fit==='contain'?'contain':'cover';wrap.append(img);top.append(wrap);
      const side=node('div',undefined,'se-card-ctrls'),file=node('input');file.type='file';file.accept='image/png,image/jpeg,image/webp';file.hidden=true;file.setAttribute('aria-label','Tải ảnh cảnh '+(s.index+1));
      const browse=node('button','Browse','se-btn-green'),regen=node('button','Vẽ lại','se-btn-green');browse.type=regen.type='button';browse.dataset.requiresEdit=regen.dataset.requiresEdit='true';browse.onclick=()=>file.click();side.append(file,browse,regen);
      const radios=node('div',undefined,'se-provider-radios');for(const [provider,label] of [['flow','Flow'],['chatgpt','ChatGPT'],['comfy','Comfy']]){const disabled=!c.providersAvailable.includes(provider),l=node('label',undefined,'se-radio-item'+(disabled?' is-disabled':'')),r=node('input');r.type='radio';r.name='provider_'+s.scene_id;r.value=provider;r.checked=(c.providers?.get(s.scene_id)||'flow')===provider;if(disabled){r.dataset.permDisabled='true';r.disabled=true;l.title=provider==='flow'?'Google Flow chưa khả dụng trên máy chủ này':'Provider chưa khả dụng';}r.onchange=()=>{if(r.checked)c.providers.set(s.scene_id,provider);};l.append(document.createTextNode(label),r);radios.append(l);}const providerNote=node('small',undefined,'se-provider-note'),providerNotes={flow:'Flow chỉ tạo khi Tác nhân tắt và trang xác nhận chi phí 0 tín dụng; ảnh tải về 2K.',chatgpt:'Dùng ChatGPT trong Chrome riêng theo hạn mức tài khoản.',comfy:'Dùng Qwen Image 2.1; tác vụ bulk vẫn kiểm tra hàng đợi và VRAM.'},updateProviderNote=()=>{providerNote.textContent=providerNotes[radios.querySelector('input:checked')?.value||'flow'];};radios.addEventListener('change',updateProviderNote);updateProviderNote();side.append(radios,providerNote);top.append(side);card.append(top,node('p',s.narration,'se-narration'));
      const audio=node('audio',undefined,'se-audio');audio.controls=true;audio.preload='none';audio.src=s.audio_url;card.append(audio);
      const select=node('select',undefined,'se-history-select');select.setAttribute('aria-label','Chọn ảnh cảnh '+(s.index+1));select.dataset.requiresEdit='true';card.append(select);
      const toggle=node('button','Sửa mô tả vẽ','se-prompt-toggle'),box=node('div',undefined,'se-prompt-box'),prompt=node('textarea',undefined,'se-prompt-input');toggle.type='button';prompt.value=c.drafts.get(s.scene_id)??s.visual_prompt??'';prompt.maxLength=12000;prompt.setAttribute('aria-label','Mô tả vẽ cảnh '+(s.index+1));box.hidden=!c.expanded.has(s.scene_id);toggle.setAttribute('aria-expanded',String(!box.hidden));prompt.oninput=()=>c.drafts.set(s.scene_id,prompt.value);toggle.onclick=()=>{box.hidden=!box.hidden;toggle.setAttribute('aria-expanded',String(!box.hidden));if(box.hidden)c.expanded.delete(s.scene_id);else c.expanded.add(s.scene_id);};box.append(prompt);card.append(toggle,box);
      const status=node('div',undefined,'se-card-status');status.setAttribute('role','status');card.append(status);
      card.updateOptions=()=>{
        select.replaceChildren(new Option('Ảnh gốc','original'));
        for(const h of s.history||[])select.append(new Option(new Date(h.created*1000).toLocaleString()+' · '+(h.provider==='chatgpt'?'ChatGPT':h.provider==='comfy'?'ComfyUI':'Tải lên'),h.id));
        for(const t of c.tasks.get(s.scene_id)||[])if(t.state==='completed'&&t.image_url)select.append(new Option((t.provider==='comfy'?'ComfyUI · ':t.provider==='flow'?'Google Flow · ':'ChatGPT · ')+new Date(t.created*1000).toLocaleString(),'candidate:'+t.id));
        select.value=s.edit_id;
      };card.updateOptions();
      select.onchange=async()=>{const value=select.value;if(value===s.edit_id)return;let preview,pathSuffix,data;
        if(value.startsWith('candidate:')){const id=value.slice(10),task=(c.tasks.get(s.scene_id)||[]).find(t=>t.id===id);if(!task){select.value=s.edit_id;return;}preview=task.image_url;pathSuffix=path+'/generations/'+encodeURIComponent(id)+'/apply';data={fit:'cover'};}
        else{preview=imageURL(s,value);pathSuffix=path+'/restore';data={edit_id:value};}
        const ok=await mutate(pathSuffix,data,s,card,preview,value);if(ok&&alive())card.loadCandidates();
      };
      file.onchange=async()=>{
        const f=file.files[0];if(!f||busy||!state?.editable)return;if(f.size>20*1024*1024){status.textContent='Ảnh tối đa 20 MB';return;}
        busy=true;controls();status.textContent='Đang tải ảnh…';const old=img.src,url=URL.createObjectURL(f);img.src=url;
        try{const v=await request(base(jid)+path+'/image?fit=cover&version='+state.version,{method:'POST',headers:{'Content-Type':f.type||'application/octet-stream'},body:f});if(job===jid){state=v;c.state=v;c.exportKey=null;const row=v.scenes.find(x=>x.scene_id===s.scene_id);if(alive()){Object.assign(s,row);img.src=imageURL(s,s.edit_id);card.updateOptions();status.textContent='Đã lưu ảnh tải lên';}}}catch(e){if(alive()){img.src=old;status.textContent='Không tải được: '+e.message;}}finally{URL.revokeObjectURL(url);busy=false;controls();file.value='';}
      };
      let loading=false;
      card.loadCandidates=async()=>{
        if(!alive()||loading)return;loading=true;
        try{const d=await request(endpoint);if(!alive())return;if(busy){schedule(card.loadCandidates,300);return;}c.tasks.set(s.scene_id,d.items||[]);c.providersAvailable=d.providers||c.providersAvailable;for(const r of radios.querySelectorAll('input[type=radio]')){const available=c.providersAvailable.includes(r.value);r.disabled=!available;r.dataset.permDisabled=String(!available);r.parentElement.classList.toggle('is-disabled',!available);if(!available&&r.checked){const fallback=radios.querySelector('input[value="chatgpt"]');fallback.checked=true;c.providers.set(s.scene_id,'chatgpt');updateProviderNote();}}card.updateOptions();
          const pending=(d.items||[]).find(t=>['queued','running','uncertain','needs_auth','needs_comfy_idle','needs_zero_credit','needs_flow_check'].includes(t.state));regen.dataset.pending=String(!!pending);
          card.querySelectorAll('.se-recovery').forEach(e=>e.remove());
          if(pending){status.textContent=pending.error|| (pending.state==='needs_comfy_idle'?'ComfyUI đang bận; chọn thử lại khi rảnh.':pending.state==='needs_zero_credit'?'Flow chưa xác nhận 0 tín dụng; chưa gửi yêu cầu tạo.':pending.state==='needs_flow_check'?'Flow cần kiểm tra lại; không tự gửi trùng.':(['queued','running'].includes(pending.state)?'Đang tạo ảnh…':'Yêu cầu cần kiểm tra, không tự gửi lại'));
            if(['uncertain','needs_auth','needs_comfy_idle','needs_zero_credit','needs_flow_check'].includes(pending.state))for(const [action,label] of [['resume','Kiểm tra yêu cầu cũ'],['cancel','Dừng chờ']]){const b=node('button',label,'secondary se-recovery');b.type='button';b.onclick=async()=>{if(busy)return;busy=true;controls();try{await request(endpoint+'/'+pending.id+'/'+action,{method:'POST',body:'{}'});}catch(e){status.textContent=e.message;}finally{busy=false;controls();card.loadCandidates();}};card.append(b);}
            if(['queued','running'].includes(pending.state))schedule(card.loadCandidates,3000);
          }else if((d.items||[]).some(t=>t.state==='completed'))status.textContent='Ảnh tạo lại sẵn sàng trong dropdown';
          controls();
        }catch(e){if(alive())status.textContent=e.message;}finally{loading=false;}
      };
      regen.onclick=async()=>{if(busy||!state?.editable||regen.dataset.pending==='true')return;const text=prompt.value.trim();if(!text){status.textContent='Nhập mô tả trước khi vẽ';return;}
        const provider=radios.querySelector('input:checked')?.value||'chatgpt';const identity=JSON.stringify({prompt:text,version:state.version,provider}),saved=c.requestKeys.get(s.scene_id);const key=saved?.identity===identity?saved.key:uid();c.requestKeys.set(s.scene_id,{identity,key});busy=true;controls();status.textContent=provider==='flow'?'Đang kiểm tra Flow, cấu hình và chi phí 0 tín dụng…':provider==='comfy'?'Đang xếp ảnh vào ComfyUI…':'Đang gửi yêu cầu tới ChatGPT…';
        try{await request(endpoint,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({prompt:text,provider,version:state.version})});c.requestKeys.delete(s.scene_id);regen.dataset.pending='true';if(alive())schedule(card.loadCandidates,500);}catch(e){if(alive())status.textContent=e.message;}finally{busy=false;controls();}
      };
      return card;
    }
  }
  async function refresh(){if(busy||!job)return;const jid=job;busy=true;controls();message('Đang nạp cảnh…');try{const v=await request(base(jid));if(job!==jid)return;state=v;cache().state=v;render();message('Chọn ảnh bằng dropdown. Ảnh tạo lại chỉ được dùng khi bạn chọn.');}catch(e){message(e.message,true);}finally{busy=false;controls();}}
  window.openSceneEditor=async jid=>{
    if(busy)return;const visible=!$('viewSceneEditor').hidden;if(visible&&jid===job)return;
    if(visible&&job)cache().scroll=window.scrollY;
    if(!visible){workspaceScroll=window.scrollY;priorView=!$('viewWorkspace').hidden?'viewWorkspace':'viewGallery';}
    clearPolling();job=jid;const c=cache();state=c.state||null;
    $('viewGallery').hidden=$('viewWorkspace').hidden=true;$('viewSceneEditor').hidden=false;document.body.classList.add('scene-editor-active');
    const hash='#/editor/'+encodeURIComponent(jid);if(location.hash!==hash)location.hash=hash;
    if(state){render();await request(base(jid)).then(v=>{if(job===jid&&v.version!==state.version){state=v;c.state=v;render();}}).catch(()=>{});}else await refresh();
    requestAnimationFrame(()=>window.scrollTo(0,c.scroll||0));
  };
  function close(){if(busy)return;cache().scroll=window.scrollY;clearPolling();$('viewSceneEditor').querySelectorAll('audio').forEach(a=>a.pause());$('viewSceneEditor').hidden=true;document.body.classList.remove('scene-editor-active');$(priorView).hidden=false;window.scrollTo(0,workspaceScroll);if(location.hash.startsWith('#/editor/'))history.back();}
  $('btnBackFromEditor').onclick=close;$('sePageReload').onclick=refresh;$('sePageFilter').onchange=()=>{if(busy)return;cache().filter=$('sePageFilter').value;cache().page=0;render();};
  $('sePageExport').onclick=async()=>{if(busy||!state?.editable)return;const c=cache(),identity=String(state.version);if(c.exportKey?.identity!==identity)c.exportKey={identity,key:uid()};busy=true;controls();try{const result=await request(base()+'/export',{method:'POST',headers:{'Idempotency-Key':c.exportKey.key},body:JSON.stringify({version:state.version,confirm_all:true})});message('Đã tạo phiên bản '+result.id.slice(0,8)+', đang dựng video.');}catch(e){message(e.message,true);}finally{busy=false;controls();}};
  window.addEventListener('hashchange',()=>{const m=location.hash.match(/^#\/editor\/([^?&]+)/);if(m)window.openSceneEditor(decodeURIComponent(m[1]));else if(!$('viewSceneEditor').hidden)close();});
  const initial=()=>{const m=location.hash.match(/^#\/editor\/([^?&]+)/);if(m)window.openSceneEditor(decodeURIComponent(m[1]));};
  if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',initial);else initial();
})();

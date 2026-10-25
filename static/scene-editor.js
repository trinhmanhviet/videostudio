/* Per-scene visual editor. Never requests TTS, script generation, or GPU images. */
(() => {
  'use strict';
  const style=document.createElement('style');style.textContent=`
  .se-overlay{position:fixed;inset:0;background:#000b;z-index:1100;padding:clamp(8px,2vw,24px);display:flex;justify-content:center;align-items:center}
  .se-shell{width:100%;max-width:1500px;max-height:94vh;overflow:auto;border:1px solid var(--line);background:var(--bg);border-radius:14px;padding:18px}
  .se-overlay[hidden]{display:none}
  .se-shell{overscroll-behavior:contain;-webkit-overflow-scrolling:touch;min-width:0}
  .se-top{position:sticky;top:-18px;z-index:2;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}
  .se-heading{display:flex;align-items:center;gap:8px}.se-heading h2{font-size:20px;margin:0;flex:1;min-width:0}.se-heading button{min-height:44px;justify-content:center}
  .se-top #seCount{display:block;margin:2px 0;font-size:12px}.se-settings{padding:12px 0;border-bottom:1px solid var(--line)}
  .se-message:empty{display:none}
  @media(max-width:640px),(max-height:500px){
    .se-overlay{padding:0;align-items:stretch}
    .se-shell{max-height:100vh;max-height:100dvh;width:100%;border-radius:0;border:0;padding:12px;padding-top:max(8px,env(safe-area-inset-top));padding-bottom:max(12px,env(safe-area-inset-bottom))}
    .se-top{top:-12px;padding:8px 0}.se-heading{gap:6px}.se-heading h2{font-size:16px;line-height:1.2;white-space:nowrap}.se-heading button{font-size:12px;padding:8px}
    .se-shell .se-grid{grid-template-columns:minmax(0,1fr);margin-top:8px}.se-card{padding:10px;min-width:0}.se-card .se-image{height:56vh;height:56svh;max-height:620px;aspect-ratio:auto;object-fit:contain}
    .se-card button,.se-card select{min-height:44px;font-size:14px}.se-card input[type=file]{min-height:44px}.se-card h3{font-size:14px}.se-message{font-size:12px;margin:6px 0}
    .se-settings .se-toolbar{gap:8px}.se-settings label{margin:4px 0}.se-settings .se-toolbar select{flex:1;min-width:0}.se-settings .se-confirm{font-size:12px}.se-settings .se-confirm input{flex-shrink:0}
  }
  .se-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.se-toolbar h2{margin:0;flex:1}.se-toolbar select{width:auto;max-width:100%}
  .se-summary{font-size:13px;color:var(--muted);margin:8px 0}.se-message{white-space:pre-wrap;margin:8px 0}.se-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr));gap:14px;margin-top:14px}
  .se-card{border:1px solid var(--line);border-radius:10px;padding:12px;background:var(--card)}.se-card h3{margin:0 0 8px;font-size:15px}
  .se-image{display:block;width:100%;height:auto;aspect-ratio:9/16;object-fit:contain;background:#080808;border-radius:6px}.se-card p{font-size:13px;line-height:1.5;min-height:38px}.se-card audio{width:100%;height:36px}
  .se-card input[type=file]{width:100%;font-size:12px;padding:8px 0}.se-card select{font-size:12px}.se-card button{font-size:12px;padding:7px 9px}.se-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}
  .se-approval{display:inline-block;font-size:12px;margin:8px 0;color:var(--accent)}.se-confirm{display:flex;gap:8px;align-items:center;font-size:13px;max-width:700px}.se-confirm input{width:auto}
  .se-generation{margin-top:12px;border-top:1px solid var(--line);padding-top:8px}.se-generation summary{cursor:pointer;min-height:44px;display:list-item;padding:10px 0;font-weight:600;color:var(--accent)}
  .se-generation-body{display:grid;gap:8px}.se-generation-body p{min-height:0}.se-generation-note{display:block;font-size:12px;line-height:1.4}.se-generation-status{font-size:12px;overflow-wrap:anywhere}
  .se-generation-result{display:grid;gap:8px;border-top:1px solid var(--line);padding:12px 0}.se-generated-image{width:100%;max-height:55svh;object-fit:contain;background:#080808;border-radius:8px}.se-generation textarea{min-height:110px;font-size:14px;resize:vertical}
  `;document.head.append(style);
  const overlay=document.createElement('div');overlay.className='se-overlay';overlay.hidden=true;
  overlay.innerHTML=`<section class="se-shell" role="dialog" aria-modal="true" aria-labelledby="seTitle"><div class="se-top"><div class="se-heading"><h2 id="seTitle">Ảnh từng cảnh</h2><button type="button" id="seOptionsToggle" class="secondary" aria-expanded="false" aria-controls="seSettings">Tùy chọn / Xuất</button><button type="button" id="seClose" class="secondary">Đóng</button></div><span id="seCount" class="se-summary"></span></div><div id="seSettings" class="se-settings" hidden><button type="button" id="seReload" class="secondary">Làm mới cảnh</button><p class="se-summary">Đổi ảnh giữ nguyên lời đọc, thời lượng, phụ đề và nhạc. Video gốc không bị ghi đè.</p><div class="se-toolbar"><label for="seMode">Chế độ</label><select id="seMode"><option value="quick">Nhanh</option><option value="careful">Kiểm kỹ (duyệt thủ công)</option></select><select id="seFilter" aria-label="Lọc cảnh"><option value="all">Tất cả cảnh</option><option value="pending">Chưa duyệt</option><option value="edited">Đã thay ảnh</option></select></div><div class="se-toolbar"><label class="se-confirm"><input id="seKeepAll" type="checkbox">Tôi đồng ý giữ các ảnh hiện tại còn lại khi xuất bản Kiểm kỹ.</label><button type="button" id="seExport">Xuất phiên bản mới</button></div><small class="se-summary">Duyệt ở đây là lựa chọn của bạn, không phải AI chứng nhận đúng lịch sử/khoa học.</small></div><div id="seMessage" class="se-message" role="status"></div><div id="seGrid" class="se-grid"></div></section>`;
  document.body.append(overlay);
  const el=id=>overlay.querySelector('#'+id);
  let state=null,busy=false,job=null,exportIdentity=null,objectURLs=[],previousBodyOverflow='';
  function showSettings(open){el('seSettings').hidden=!open;el('seOptionsToggle').setAttribute('aria-expanded',String(open));if(open)overlay.querySelector('.se-shell').scrollTop=0;}
  el('seOptionsToggle').onclick=()=>showSettings(el('seSettings').hidden);
  const node=(tag,content,cls)=>{const e=document.createElement(tag);if(content!==undefined)e.textContent=content;if(cls)e.className=cls;return e;};
  const clock=s=>{const n=Math.max(0,Math.floor(Number(s)||0));return Math.floor(n/60)+':'+String(n%60).padStart(2,'0');};
  const base=()=>'/api/jobs/'+encodeURIComponent(job)+'/scene-editor';
  function message(s,error=false){el('seMessage').textContent=s;el('seMessage').style.color=error?'#fca5a5':'var(--accent)';}
  function controls(){overlay.querySelectorAll('button,select,input').forEach(e=>e.disabled=busy);if(state&&!state.editable){el('seMode').disabled=true;el('seKeepAll').disabled=true;el('seExport').disabled=true;el('seGrid').querySelectorAll('button,select,input').forEach(e=>e.disabled=true);}}
  async function jsonRequest(path,options={}){
    const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})},signal:AbortSignal.timeout(120000)});
    const data=await r.json().catch(()=>({detail:'Phản hồi không hợp lệ'}));if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));return data;
  }
  async function mutation(path,payload){
    if(busy||!state?.editable)return;busy=true;controls();message('Đang lưu...');
    try{state=await jsonRequest(base()+path,{method:'POST',body:JSON.stringify({...payload,version:state.version})});el('seKeepAll').checked=false;exportIdentity=null;render();message('Đã lưu. Lời đọc và thời lượng không thay đổi.');}
    catch(e){message(e.message+' Nếu dữ liệu đã đổi ở cửa sổ khác, bấm Làm mới cảnh.',true);}finally{busy=false;controls();}
  }
  function render(){
    objectURLs.forEach(u=>URL.revokeObjectURL(u));objectURLs=[];
    const shell=overlay.querySelector('.se-shell'),scroll=shell.scrollTop;
    el('seMode').value=state.mode;
    const pending=state.scenes.filter(s=>s.review_status!=='user_approved').length;
    el('seCount').textContent=`${state.scenes.length} cảnh · ${pending} chưa duyệt · bản biên tập ${state.version}`;
    const filter=el('seFilter').value;
    const rows=state.scenes.filter(s=>filter==='all'||(filter==='pending'&&s.review_status!=='user_approved')||(filter==='edited'&&s.edit_id!=='original'));
    const cards=rows.map(s=>{
      const c=node('article',undefined,'se-card');c.dataset.sceneId=s.scene_id;
      c.append(node('h3',`Cảnh ${s.index+1} · ${clock(s.start)} - ${clock(s.start+s.duration)} (${Number(s.duration).toFixed(2)}s)`));
      const img=node('img',undefined,'se-image');img.loading='lazy';img.src=s.image_url+'&thumb=true';img.alt=`Ảnh cảnh ${s.index+1}`;c.append(img);
      c.append(node('p',s.narration));const audio=node('audio');audio.controls=true;audio.preload='none';audio.src=s.audio_url;audio.setAttribute('aria-label',`Lời đọc cảnh ${s.index+1}`);c.append(audio);
      c.append(node('span',s.review_status==='user_approved'?'Bạn đã chọn / duyệt ảnh này':'Chưa được bạn duyệt','se-approval'));
      const file=node('input');file.type='file';file.accept='image/png,image/jpeg,image/webp';file.setAttribute('aria-label',`Thay ảnh cảnh ${s.index+1}`);c.append(file);
      const fit=node('select');fit.setAttribute('aria-label',`Cách đặt ảnh cảnh ${s.index+1}`);fit.append(new Option('Cắt vừa khung (không kéo méo)','cover'),new Option('Giữ toàn ảnh, thêm viền','contain'));fit.value=s.fit==='contain'?'contain':'cover';c.append(fit);
      const actions=node('div',undefined,'se-actions');const use=node('button','Dùng ảnh này');use.type='button';use.className='secondary';
      file.onchange=()=>{const f=file.files[0];if(!f)return;if(f.size>20*1024*1024){message('Ảnh tối đa 20 MB.',true);file.value='';return;}const u=URL.createObjectURL(f);objectURLs.push(u);img.src=u;img.style.objectFit=fit.value;};
      fit.onchange=()=>img.style.objectFit=fit.value;
      use.onclick=async()=>{
        const f=file.files[0];if(!f){message('Chọn ảnh PNG, JPEG hoặc WebP trước.',true);return;}if(busy)return;busy=true;controls();message('Đang tải và chuẩn hóa ảnh...');
        try{state=await jsonRequest(base()+'/scenes/'+encodeURIComponent(s.scene_id)+'/image?fit='+fit.value+'&version='+state.version,{method:'POST',headers:{'Content-Type':f.type||'application/octet-stream'},body:f});exportIdentity=null;el('seKeepAll').checked=false;render();message('Đã thay ảnh. Lời đọc và timeline vẫn giữ nguyên.');}
        catch(e){message(e.message,true);}finally{busy=false;controls();}
      };
      const approve=node('button','Duyệt ảnh hiện tại','secondary');approve.type='button';approve.onclick=()=>mutation('/scenes/'+encodeURIComponent(s.scene_id)+'/approve',{image_sha256:s.image_sha256});
      const large=node('button','Xem ảnh lớn','secondary');large.type='button';large.onclick=()=>{img.src=s.image_url;img.style.height=img.style.height?'':'min(70vh, 650px)';};actions.append(use,approve,large);c.append(actions);
      const history=node('select');history.setAttribute('aria-label',`Lịch sử ảnh cảnh ${s.index+1}`);history.append(new Option('Ảnh gốc','original'));for(const h of s.history)history.append(new Option(new Date(h.created*1000).toLocaleString()+' · '+(h.fit==='contain'?'toàn ảnh':'cắt vừa'),h.id));history.value=s.edit_id;c.append(history);
      const restore=node('button','Khôi phục bản ảnh đã chọn','secondary');restore.type='button';restore.onclick=()=>mutation('/scenes/'+encodeURIComponent(s.scene_id)+'/restore',{edit_id:history.value});c.append(restore);
      if(window.createSceneGenerationPanel)c.append(window.createSceneGenerationPanel(s,fit,{base:base(),request:jsonRequest,version:()=>state.version,editable:()=>state?.editable&&!busy,isOpen:()=>!overlay.hidden,apply:path=>mutation(path,{fit:fit.value})}));
      if(!state.editable)c.querySelectorAll('button,select,input').forEach(x=>x.disabled=true);
      return c;
    });
    el('seGrid').replaceChildren(...cards);shell.scrollTop=scroll;controls();
  }
  async function refresh(){if(busy)return;busy=true;controls();message('Đang nạp cảnh...');try{state=await jsonRequest(base());render();message(state.editable?'Chọn cảnh cần sửa; có thể chuyển mode mà không mất ảnh đã thay.':'Job đang chạy. Chờ tạo ảnh xong trước khi sửa.');}catch(e){message(e.message,true);}finally{busy=false;controls();}}
  window.openSceneEditor=async jid=>{if(busy)return;job=jid;state=null;exportIdentity=null;if(overlay.hidden)previousBodyOverflow=document.body.style.overflow;document.body.style.overflow='hidden';overlay.hidden=false;showSettings(false);overlay.querySelector('.se-shell').scrollTop=0;el('seKeepAll').checked=false;el('seGrid').replaceChildren();await refresh();};
  function close(){if(busy)return;overlay.querySelectorAll('audio').forEach(a=>a.pause());objectURLs.forEach(u=>URL.revokeObjectURL(u));objectURLs=[];overlay.hidden=true;document.body.style.overflow=previousBodyOverflow;}
  el('seClose').onclick=close;el('seReload').onclick=refresh;el('seFilter').onchange=()=>state&&render();
  el('seMode').onchange=()=>mutation('/mode',{mode:el('seMode').value});
  overlay.addEventListener('play',e=>overlay.querySelectorAll('audio').forEach(a=>{if(a!==e.target)a.pause();}),true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!overlay.hidden)close();});
  el('seExport').onclick=async()=>{
    if(busy||!state?.editable)return;
    const confirm=el('seKeepAll').checked;
    if(state.mode==='careful'&&!confirm&&state.scenes.some(s=>s.review_status!=='user_approved')){message('Hãy duyệt các cảnh còn lại, hoặc đánh dấu đồng ý giữ ảnh hiện tại.',true);return;}
    const identity=JSON.stringify({job,version:state.version,confirm});if(!exportIdentity||exportIdentity.identity!==identity)exportIdentity={identity,key:crypto.randomUUID()};
    busy=true;controls();message('Đang chốt ảnh và tạo phiên bản xuất mới...');
    try{const child=await jsonRequest(base()+'/export',{method:'POST',headers:{'Idempotency-Key':exportIdentity.key},body:JSON.stringify({version:state.version,confirm_all:confirm})});message('Đã tạo phiên bản '+child.id.slice(0,8)+'. Chỉ dựng lại phần hình và xuất MP4; video gốc vẫn giữ nguyên.');if(typeof loadJobs==='function')await loadJobs();}
    catch(e){message(e.message,true);}finally{busy=false;controls();}
  };
})();

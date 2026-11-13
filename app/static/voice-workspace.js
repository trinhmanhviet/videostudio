(function (global) {
  'use strict';
  const normalize=v=>String(v??'').toLowerCase().normalize('NFD').replace(/\p{M}/gu,'').replace(/đ/g,'d').trim();
  const isPrivate=v=>v.kind==='clone'||String(v.id).startsWith('clone:');
  const voiceHelp=message=>{message=String(message||'');if(/exact.*transcript|reference transcript/i.test(message))return 'Giọng này chưa có lời của bản thu mẫu. Nhập lời chính xác trong Cài đặt nâng cao, hoặc thêm mẫu sắc thái có lời đi kèm.';if(/checksum|reference changed/i.test(message))return 'Bản thu mẫu đã thay đổi. Hãy chọn lại hoặc tải lại mẫu tham chiếu.';if(/runtime|snapshot|model.*unavailable/i.test(message))return 'Bộ đọc cục bộ chưa sẵn sàng. Kiểm tra phần Kết nối & hệ thống.';return message;};
  function filterVoices(rows,query,filter,favorites){
    const words=normalize(query).split(/\s+/).filter(Boolean);
    return rows.filter(v=>words.every(w=>normalize([v.name,v.id,v.gender,v.region].join(' ')).includes(w)))
      .filter(v=>filter==='favorites'?favorites.includes(v.id):filter==='private'?isPrivate(v):true);
  }
  function pageItems(items,page,size){const pages=Math.max(1,Math.ceil(items.length/size));page=Math.min(Math.max(1,page),pages);return {items:items.slice((page-1)*size,page*size),page,pages,total:items.length};}
  function buildRequest(settings){
    const text=String(settings.text??'').trim();
    if(!text||text.length>20000)throw new Error('Nhập 1–20.000 ký tự cần đọc.');
    if(!settings.voice_id)throw new Error('Chọn một giọng có sẵn trong thư viện.');
    const speed=Number(settings.speech_speed??1);
    if(!Number.isFinite(speed)||speed<.5||speed>2)throw new Error('Tốc độ cần từ 0,5 đến 2.');
    const engine=settings.speech_engine||'vieneu',rhythm=settings.speech_rhythm||'natural';
    if(!['vieneu','khanhtts'].includes(engine)||!['natural','story'].includes(rhythm))throw new Error('Bộ đọc hoặc nhịp đọc không hợp lệ.');
    const request={text,voice_id:settings.voice_id,speech_engine:engine,speech_rhythm:rhythm,speech_speed:speed};
    if(engine==='khanhtts'){const steps=Number(settings.khanh_steps??32);if(![16,32].includes(steps))throw new Error('Chọn 16 hoặc 32 bước.');request.khanh_steps=steps;}
    if(settings.speech_reference_id)request.speech_reference_id=settings.speech_reference_id;
    if(engine==='khanhtts'&&!settings.speech_reference_id&&settings.speech_reference_text?.trim())request.speech_reference_text=settings.speech_reference_text.trim();
    if(settings.title?.trim())request.title=settings.title.trim();
    return request;
  }
  function pendingRequest(body,previous,newKey=()=>global.crypto.randomUUID()){
    const fingerprint=JSON.stringify(body);
    return previous?.fingerprint===fingerprint?previous:{fingerprint,body,key:newKey()};
  }
  function reuseSettings(task){const request=task.request||{};return {...buildRequest(request),title:task.title||''};}
  global.VoiceWorkspace={filterVoices,pageItems,buildRequest,pendingRequest,reuseSettings,mount};
  if(typeof document==='undefined')return;

  function mount(root,opts={}){
    if(root.__voiceWorkspace)return root.__voiceWorkspace;
    const storage=opts.storage||global.localStorage;
    function read(key,fallback){try{return JSON.parse(storage.getItem('voice-workspace:'+key))??fallback;}catch{return fallback;}}
    function write(key,value){try{storage.setItem('voice-workspace:'+key,JSON.stringify(value));}catch{notice('Trình duyệt chưa lưu được thiết lập. Giữ cửa sổ này để theo dõi bản đọc.',true);}}
    const owner=read('owner',null)||global.crypto.randomUUID();
    const defaults={text:'',voice_id:'',speech_engine:'vieneu',speech_speed:1,speech_rhythm:'natural',khanh_steps:32,speech_reference_id:'',speech_reference_text:'',title:''};
    const state={...defaults,...read('settings',{}),...read('draft',{}),voices:[],references:[],favorites:read('favorites',[]),filter:'all',query:'',page:1,historyPage:1,saved:false,history:[],total:0,active:null,activeId:read('active',null),pending:read('pending',null),visible:true,destroyed:false,loading:false,submitting:false,engineReady:false};
    let timer=null,statusTimer=null,statusSequence=0,loadingPromise=null,referenceURL=null,historySequence=0;
    const uiEvents=new AbortController();
    const controllers=new Set();
    root.classList.add('voice-workspace');
    root.innerHTML=`
      <header class="vw-heading"><div><h2>Phòng thử giọng</h2><p>Nhập chữ, chọn giọng và tạo bản đọc riêng</p></div><button type="button" data-action="clone">＋ Thêm giọng từ bản thu</button></header>
      <div class="vw-notice" role="status" aria-live="polite" data-role="notice"></div>
      <div class="vw-columns">
        <section class="vw-panel vw-library" aria-label="Thư viện giọng"><h3>Thư viện giọng</h3>
          <input type="search" data-field="query" placeholder="Tìm tên giọng…" aria-label="Tìm tên giọng">
          <div class="vw-filters" role="group" aria-label="Lọc giọng"><button type="button" data-filter="all">Tất cả</button><button type="button" data-filter="favorites">Yêu thích</button><button type="button" data-filter="private">Giọng riêng</button></div>
          <div data-role="voices" class="vw-voices"></div>
          <div class="vw-pagination"><small data-role="voiceCount"></small><button type="button" data-action="voicePrev" aria-label="Trang giọng trước">‹</button><span data-role="voicePage"></span><button type="button" data-action="voiceNext" aria-label="Trang giọng sau">›</button></div>
          <audio data-role="voicePlayer" controls preload="none" hidden aria-label="Mẫu giọng có sẵn"></audio>
        </section>
        <section class="vw-panel vw-editor" aria-label="Tạo bản đọc">
          <div class="vw-engine"><strong>Bộ đọc</strong><div class="vw-segment" role="group" aria-label="Bộ đọc"><button type="button" data-engine="vieneu">VieNeu</button><button type="button" data-engine="khanhtts">KhanhTTS</button></div><div class="vw-selected">Giọng đang chọn: <strong data-role="selectedVoice">Chưa chọn</strong></div></div>
          <p class="vw-engine-status" data-role="engineStatus" aria-live="polite">Đang kiểm tra bộ đọc…</p>
          <div class="vw-text-heading"><h3>Nội dung cần đọc</h3><button type="button" data-action="import">Nhập TXT</button><input type="file" data-role="txtFile" accept=".txt,text/plain" hidden></div>
          <textarea data-field="text" maxlength="20000" rows="10" placeholder="Nhập nội dung muốn nghe thử…" aria-label="Nội dung cần đọc"></textarea>
          <div class="vw-text-meta"><small data-role="textCount"></small><button type="button" data-action="clear" class="vw-link">Xóa nội dung</button></div>
          <div class="vw-controls"><label>Nhịp đọc<select data-field="speech_rhythm"><option value="natural">Tự nhiên · nhịp A</option><option value="story">Kể chuyện · nhịp B</option></select></label><label>Tốc độ<select data-field="speech_speed"><option value="0.5">0,5×</option><option value="0.75">0,75×</option><option value="0.9">0,9×</option><option value="1">1,0×</option><option value="1.1">1,1×</option><option value="1.25">1,25×</option><option value="1.5">1,5×</option><option value="2">2,0×</option></select></label><label data-role="quality">Chất lượng KhanhTTS<select data-field="khanh_steps"><option value="16">Nhanh · 16 bước</option><option value="32">Chuẩn · 32 bước</option></select></label></div>
          <div class="vw-reference"><label>Sắc thái theo tham chiếu<select data-field="speech_reference_id"><option value="">Theo mẫu của giọng</option></select></label><button type="button" data-action="addReference">＋ Thêm mẫu sắc thái</button><button type="button" data-action="removeReference" hidden>Xóa mẫu</button></div>
          <small class="vw-muted">Sắc thái phụ thuộc bản thu tham chiếu. Nhịp B điều chỉnh khoảng nghỉ.</small>
          <audio data-role="referencePlayer" controls preload="none" hidden aria-label="Nghe mẫu sắc thái"></audio>
          <details class="vw-advanced"><summary>Cài đặt nâng cao</summary><label>Tên bản đọc<input data-field="title" maxlength="160" placeholder="Tự lấy từ nội dung"></label><label>Lời chính xác trong mẫu của giọng<textarea rows="3" data-field="speech_reference_text" maxlength="10000" placeholder="Chỉ điền khi mẫu của giọng chưa có lời đã xác minh"></textarea></label><small class="vw-muted">KhanhTTS cần lời đúng với bản thu tham chiếu. Mẫu sắc thái đã thêm dùng lời riêng của mẫu đó.</small></details>
          <div class="vw-primary-actions"><button type="button" class="vw-primary" data-action="generate">▶ Tạo bản đọc thử</button><button type="button" data-action="settings">Lưu thiết lập</button></div>
          <section class="vw-result" data-role="result" hidden><div class="vw-result-heading"><h3 data-role="resultTitle">Bản đọc vừa tạo</h3><small>Bản đọc riêng, không cần tạo video</small></div><p data-role="resultStatus" aria-live="polite"></p><audio data-role="resultPlayer" controls preload="metadata" hidden aria-label="Bản đọc đã tạo"></audio><div class="vw-result-actions" data-role="resultActions"></div></section>
        </section>
        <section class="vw-panel vw-history" aria-label="Các bản đã tạo"><div class="vw-history-heading"><h3>Các bản đã tạo</h3><button type="button" data-action="refresh" aria-label="Tải lại lịch sử">↻</button></div><p class="vw-muted">Lịch sử chung · nghe và tải trên mọi browser</p><label class="vw-history-filter">Hiển thị<select data-field="saved"><option value="recent">Tất cả bản đọc</option><option value="saved">Đã lưu vào thư viện</option></select></label><div data-role="history" class="vw-history-list"></div><div class="vw-pagination"><button type="button" data-action="historyPrev" aria-label="Lịch sử trang trước">‹</button><span data-role="historyPage"></span><button type="button" data-action="historyNext" aria-label="Lịch sử trang sau">›</button></div></section>
      </div>
      <dialog class="vw-dialog" data-role="referenceDialog"><form data-role="referenceForm"><h3>Thêm mẫu sắc thái</h3><p>Chọn bản thu WAV PCM 16-bit dài 1–60 giây (tối đa 12 MB), cùng lời đọc chính xác. Mẫu riêng này không thay giọng gốc.</p><label>Tên mẫu<input name="name" required maxlength="100"></label><label>Bản thu WAV<input name="audio" type="file" accept=".wav,audio/wav" required></label><audio data-role="uploadPlayer" controls hidden></audio><label>Lời chính xác trong bản thu<textarea name="transcript" required maxlength="10000" rows="5"></textarea></label><p data-role="referenceError" role="alert"></p><div class="vw-primary-actions"><button type="submit" class="vw-primary">Lưu mẫu tham chiếu</button><button type="button" data-action="closeReference">Hủy</button></div></form></dialog>`;
    const $=s=>root.querySelector(s),role=s=>$(`[data-role="${s}"]`),field=s=>$(`[data-field="${s}"]`);
    function notice(text,error=false){role('notice').textContent=text;role('notice').dataset.error=String(error);}
    write('owner',owner);
    function element(tag,text,className){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(className)n.className=className;return n;}
    function button(label,fn,className){const b=element('button',label,className);b.type='button';b.onclick=()=>action(fn);return b;}
    async function request(path,options={}){
      const controller=new AbortController();controllers.add(controller);
      try{const response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-Voice-Owner':owner,...options.headers},signal:controller.signal});const data=await response.json().catch(()=>({}));if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:`Không thực hiện được (${response.status})`);error.status=response.status;throw error;}return data;}
      finally{controllers.delete(controller);}
    }
    async function action(fn){try{await fn();}catch(e){if(e.name!=='AbortError')notice(e.message,true);}}
    function saveDraft(){const draft={};Object.keys(defaults).forEach(k=>draft[k]=state[k]);write('draft',draft);}
    function audioURL(task,ext,download=false){return `/api/voice-studio/tasks/${encodeURIComponent(task.id)}/audio/${ext}?owner=${encodeURIComponent(owner)}${download?'&download=true':''}`;}
    function stopAudio(){root.querySelectorAll('audio').forEach(a=>a.pause());}
    function play(audio,url){stopAudio();if(audio.getAttribute('src')!==url)audio.src=url;audio.hidden=false;audio.play().catch(e=>notice('Không phát được âm thanh: '+e.message,true));}
    function download(task,ext){const a=element('a',`↓ ${ext.toUpperCase()}`);a.href=audioURL(task,ext,true);a.download=task.title+'.'+ext;a.className='vw-download';return a;}
    function fillFields(){for(const key of Object.keys(defaults)){const n=field(key);if(n){if(n.tagName==='SELECT'&&!Array.from(n.options).some(o=>o.value===String(state[key]))&&key==='speech_speed'){const o=element('option',`${state[key]}×`);o.value=state[key];n.append(o);}n.value=state[key];}}updateEditor();}
    function updateEditor(){
      const selected=state.voices.find(v=>v.id===state.voice_id);role('selectedVoice').textContent=selected?.name||selected?.id||'Chưa chọn';
      root.querySelectorAll('[data-engine]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.engine===state.speech_engine)));
      role('quality').hidden=state.speech_engine!=='khanhtts';
      field('speech_reference_text').disabled=Boolean(state.speech_reference_id)||state.speech_engine!=='khanhtts';
      const words=state.text.trim()?state.text.trim().split(/\s+/).length:0;role('textCount').textContent=`${words} từ · ${state.text.length.toLocaleString('vi-VN')}/20.000 ký tự`;
      const active=state.active&&['queued','running'].includes(state.active.state);
      $('[data-action="generate"]').disabled=state.submitting||Boolean(active)||!selected||selected.available===false||!state.engineReady||!state.text.trim();
      $('[data-action="generate"]').textContent=state.submitting?'Đang gửi…':active?'Đang chờ / tạo bản đọc':'▶ Tạo bản đọc thử';
      $('[data-action="removeReference"]').hidden=!state.speech_reference_id;
    }
    function renderVoices(){
      const visible=pageItems(filterVoices(state.voices,state.query,state.filter,state.favorites),state.page,8);state.page=visible.page;
      root.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===state.filter)));
      role('voices').replaceChildren();
      for(const voice of visible.items){
        const row=element('div',null,'vw-voice');row.dataset.selected=String(voice.id===state.voice_id);
        const initials=(voice.name||voice.id).split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
        const select=button('',()=>{state.voice_id=voice.id;saveDraft();renderVoices();updateEditor();checkEngine();},'vw-voice-select');select.disabled=voice.available===false;select.setAttribute('aria-pressed',String(voice.id===state.voice_id));
        select.append(element('span',initials,'vw-avatar'));
        const text=element('span',null,'vw-voice-name');text.append(element('strong',voice.name||voice.id));
        const gender={male:'Nam',female:'Nữ',custom:''}[voice.gender]??voice.gender,region={Nam:'Miền Nam',Bắc:'Miền Bắc',Trung:'Miền Trung',custom:''}[voice.region]??voice.region;
        text.append(element('small',[gender,region,isPrivate(voice)?'Giọng riêng':'Có sẵn',voice.available===false?'Không khả dụng':''].filter(Boolean).join(' · ')));select.append(text);row.append(select);
        const preview=button('▶',()=>{if(voice.sample_url)play(role('voicePlayer'),voice.sample_url);},'vw-icon');preview.disabled=!voice.sample_url;preview.title=voice.sample_url?'Nghe mẫu có sẵn':'Giọng này chưa có mẫu nghe';preview.setAttribute('aria-label',`Nghe mẫu ${voice.name||voice.id}`);
        const favorite=button(state.favorites.includes(voice.id)?'★':'☆',()=>{state.favorites=state.favorites.includes(voice.id)?state.favorites.filter(id=>id!==voice.id):[...state.favorites,voice.id];write('favorites',state.favorites);renderVoices();},'vw-icon');favorite.title='Yêu thích';favorite.setAttribute('aria-pressed',String(state.favorites.includes(voice.id)));favorite.setAttribute('aria-label',`Yêu thích ${voice.name||voice.id}`);
        row.append(preview,favorite);role('voices').append(row);
      }
      if(!visible.total)role('voices').append(element('p','Không có giọng phù hợp.','vw-empty'));
      role('voiceCount').textContent=`${visible.total} giọng`;role('voicePage').textContent=`${visible.page} / ${visible.pages}`;
      $('[data-action="voicePrev"]').disabled=visible.page<=1;$('[data-action="voiceNext"]').disabled=visible.page>=visible.pages;
    }
    function renderReferences(){
      const select=field('speech_reference_id');select.replaceChildren();const base=element('option','Theo mẫu của giọng');base.value='';select.append(base);
      for(const reference of state.references){const o=element('option',reference.name);o.value=reference.id;select.append(o);}
      if(state.speech_reference_id&&!state.references.some(r=>r.id===state.speech_reference_id)){state.speech_reference_id='';notice('Mẫu sắc thái đã lưu không còn trong thư viện; hãy chọn lại.',true);}
      select.value=state.speech_reference_id;
      const audio=role('referencePlayer');audio.hidden=!state.speech_reference_id;
      if(state.speech_reference_id){const url=`/api/voice-studio/references/${state.speech_reference_id}/audio?owner=${encodeURIComponent(owner)}`;if(audio.getAttribute('src')!==url)audio.src=url;}
      else{audio.pause();audio.removeAttribute('src');}
      updateEditor();
    }
    function voiceName(id){return state.voices.find(v=>v.id===id)?.name||id;}
    function duration(task){const n=task.result?.duration_seconds;return Number.isFinite(n)?`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`:'';}
    function taskButtons(task,container,result=false){
      if(task.state==='completed'){
        if(!result)container.append(button('▶ Nghe',()=>{state.active=task;state.activeId=task.id;write('active',task.id);renderResult(true);}));
        container.append(download(task,'mp3'),download(task,'wav'));
        container.append(button(task.saved?'Đã lưu · Bỏ lưu':'Lưu vào thư viện',async()=>{await request(`/api/voice-studio/tasks/${task.id}`,{method:'PATCH',body:JSON.stringify({version:task.version,saved:!task.saved})});await refreshHistory();}));
      }
      container.append(button('Dùng lại thiết lập',()=>{Object.assign(state,reuseSettings(task));saveDraft();fillFields();renderReferences();renderVoices();checkEngine();field('text').focus();notice('Đã khôi phục nội dung và thiết lập của bản đọc.');}));
      if(['queued','running'].includes(task.state))container.append(button('Dừng',async()=>{await request(`/api/voice-studio/tasks/${task.id}/cancel`,{method:'POST',body:JSON.stringify({version:task.version})});await refreshHistory();}));
      if(['failed','cancelled'].includes(task.state))container.append(button('Thử lại',async()=>{state.active=await request(`/api/voice-studio/tasks/${task.id}/retry`,{method:'POST',body:JSON.stringify({version:task.version})});state.activeId=task.id;write('active',task.id);await refreshHistory();}));
      if(!result){
        container.append(button('Đổi tên',async()=>{const title=global.prompt('Tên bản đọc',task.title);if(title===null)return;await request(`/api/voice-studio/tasks/${task.id}`,{method:'PATCH',body:JSON.stringify({version:task.version,title})});await refreshHistory();}));
        if(!['queued','running'].includes(task.state))container.append(button('Xóa',async()=>{if(!global.confirm(`Xóa bản đọc “${task.title}”?`))return;await request(`/api/voice-studio/tasks/${task.id}`,{method:'DELETE',body:JSON.stringify({version:task.version})});if(state.activeId===task.id){role('resultPlayer').pause();role('resultPlayer').removeAttribute('src');state.activeId=null;state.active=null;write('active',null);}await refreshHistory();},'vw-danger'));
      }
      if(task.can_manage===false){
        for(const control of container.querySelectorAll('button')){
          const text=control.textContent||'';
          const readAction=text.includes('Nghe')||(text==='Dùng lại thiết lập'&&!task.request.speech_reference_id);
          if(!readAction){control.disabled=true;control.title='Bản đọc dùng chung để nghe/tải. Sửa hoặc xóa tại browser đã tạo bản đọc.';}
        }
      }
    }
    function renderResult(autoplay=false){
      const task=state.active;role('result').hidden=!task;if(!task){updateEditor();return;}
      role('resultTitle').textContent=task.title;role('resultStatus').textContent=`${voiceName(task.request.voice_id)} · ${task.request.speech_engine==='khanhtts'?'KhanhTTS':'VieNeu'}${task.request.khanh_steps?' · '+task.request.khanh_steps+' bước':''} · ${task.message||task.state}${duration(task)?' · '+duration(task):''}`;
      const audio=role('resultPlayer');audio.hidden=task.state!=='completed';
      if(task.state==='completed'){const url=audioURL(task,'wav');if(audio.getAttribute('src')!==url)audio.src=url;if(autoplay)play(audio,url);}
      else{audio.pause();audio.removeAttribute('src');}
      role('resultActions').replaceChildren();taskButtons(task,role('resultActions'),true);updateEditor();
    }
    function renderHistory(){
      role('history').replaceChildren();
      const labels={queued:'Chờ GPU rảnh',running:'Đang tạo',completed:'Sẵn sàng',failed:'Lỗi',cancelled:'Đã dừng'};
      for(const task of state.history){const card=element('article',null,'vw-history-card');card.append(element('strong',task.title),element('small',`${voiceName(task.request.voice_id)} · ${task.request.speech_engine==='khanhtts'?'KhanhTTS':'VieNeu'} · ${duration(task)||labels[task.state]||task.state}`));if(['failed','queued','running'].includes(task.state))card.append(element('p',task.message,'vw-task-message'));const controls=element('div',null,'vw-history-actions');taskButtons(task,controls);card.append(controls);role('history').append(card);}
      if(!state.history.length)role('history').append(element('p',state.saved?'Chưa có bản đọc lưu vào thư viện.':'Chưa có bản đọc. Nội dung mới sẽ chờ GPU rảnh.','vw-empty'));
      const pages=Math.max(1,Math.ceil(state.total/10));role('historyPage').textContent=`${state.historyPage} / ${pages}`;
      $('[data-action="historyPrev"]').disabled=state.historyPage<=1;$('[data-action="historyNext"]').disabled=state.historyPage>=pages;
    }
    async function refreshHistory(){
      const sequence=++historySequence;
      const history=await request(`/api/voice-studio/tasks?page=${state.historyPage}&page_size=10&saved=${state.saved}`);
      if(state.destroyed||sequence!==historySequence)return;state.history=history.items;state.total=history.total;
      if(state.historyPage>Math.max(1,Math.ceil(state.total/10))){state.historyPage=Math.max(1,Math.ceil(state.total/10));return refreshHistory();}
      if(state.activeId){const currentId=state.activeId;const active=state.history.find(t=>t.id===currentId)||await request('/api/voice-studio/tasks/'+currentId).catch(error=>{if(error.status===404)return null;throw error;});if(sequence!==historySequence||state.activeId!==currentId)return;state.active=active;if(!state.active){state.activeId=null;write('active',null);}}
      renderHistory();renderResult();
    }
    async function refresh(){
      if(loadingPromise)return loadingPromise;
      loadingPromise=(async()=>{
        const outcomes=await Promise.allSettled([request('/api/voices'),request('/api/voice-studio/references'),refreshHistory()]);
        if(state.destroyed)return;
        if(outcomes[0].status==='fulfilled'){const data=outcomes[0].value;state.voices=data.items||data.voices||[];if(!state.voice_id)state.voice_id=state.voices.find(v=>v.available!==false)?.id||'';}
        if(outcomes[1].status==='fulfilled')state.references=outcomes[1].value.items||[];
        const failed=outcomes.filter(x=>x.status==='rejected');
        if(failed.length)notice(failed.map(x=>x.reason.message).join(' · '),true);
        else if(state.pending)notice('Có yêu cầu gửi trước đó. Bấm Tạo bản đọc thử với cùng nội dung để đối soát an toàn.');
        else notice('Bản đọc chạy lần lượt khi video và ảnh đã rảnh.');
        fillFields();renderReferences();renderVoices();renderHistory();renderResult();await checkEngine();
      })().finally(()=>{loadingPromise=null;});return loadingPromise;
    }
    async function checkEngine(){
      clearTimeout(statusTimer);const seq=++statusSequence;state.engineReady=false;updateEditor();
      if(!state.voice_id){role('engineStatus').textContent='Chọn giọng để kiểm tra bộ đọc.';return;}
      role('engineStatus').textContent='Đang kiểm tra bộ đọc cục bộ…';
      try{const body=buildRequest({...state,text:state.text||'Kiểm tra cấu hình'});const status=await request('/api/voice-studio/status',{method:'POST',body:JSON.stringify(body)});if(seq!==statusSequence||state.destroyed)return;state.engineReady=status.ready===true;role('engineStatus').textContent=status.ready?(status.needs_reference_prepare?'Lượt đọc đầu sẽ chuẩn bị mẫu giọng cục bộ · chờ GPU rảnh':'Bộ đọc cục bộ sẵn sàng · sẽ chờ GPU rảnh'):voiceHelp(status.reason)||'Bộ đọc chưa sẵn sàng.';}
      catch(e){if(seq===statusSequence){state.engineReady=false;role('engineStatus').textContent=e.message;}}
      updateEditor();
    }
    async function generate(){
      if(state.submitting)return;const body=buildRequest(state);
      state.pending=pendingRequest(body,state.pending);write('pending',state.pending);state.submitting=true;updateEditor();
      try{const task=await request('/api/voice-studio/tasks',{method:'POST',headers:{'Idempotency-Key':state.pending.key},body:JSON.stringify(state.pending.body)});state.activeId=task.id;state.active=task;write('active',task.id);state.pending=null;write('pending',null);state.historyPage=1;state.saved=false;field('saved').value='recent';notice(task.message||'Đã xếp hàng bản đọc.');await refreshHistory();}
      catch(e){notice(e.message+' · Bấm lại để gửi cùng mã yêu cầu, tránh tạo trùng.',true);}
      finally{state.submitting=false;updateEditor();}
    }
    async function uploadReference(event){
      event.preventDefault();const form=role('referenceForm'),submit=form.querySelector('[type="submit"]');if(submit.disabled)return;
      const file=form.elements.audio.files[0];if(!file)throw new Error('Chọn mẫu WAV.');
      if(file.size>12_000_000){role('referenceError').textContent='Mẫu WAV tối đa 12 MB.';return;}
      submit.disabled=true;role('referenceError').textContent='Đang lưu mẫu…';
      try{const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Không đọc được bản thu'));reader.readAsDataURL(file);});
        const ref=await request('/api/voice-studio/references',{method:'POST',body:JSON.stringify({name:form.elements.name.value,transcript:form.elements.transcript.value,audio_base64:encoded})});state.references.unshift(ref);state.speech_reference_id=ref.id;saveDraft();renderReferences();closeReference();await checkEngine();notice('Đã lưu mẫu và lời đọc tham chiếu.');
      }catch(e){role('referenceError').textContent=e.message;}finally{submit.disabled=false;}
    }
    function closeReference(){role('referenceDialog').close();role('uploadPlayer').pause();if(referenceURL){URL.revokeObjectURL(referenceURL);referenceURL=null;}role('uploadPlayer').removeAttribute('src');}
    root.addEventListener('input',event=>{const key=event.target.dataset.field;if(!key||key==='saved')return;if(key==='query'){state.query=event.target.value;state.page=1;renderVoices();return;}if(!(key in defaults))return;state[key]=event.target.value;saveDraft();updateEditor();if(key==='speech_reference_text'){clearTimeout(statusTimer);statusTimer=setTimeout(()=>action(checkEngine),500);}},{signal:uiEvents.signal});
    root.addEventListener('change',event=>{const key=event.target.dataset.field;if(key==='saved'){state.saved=event.target.value==='saved';state.historyPage=1;action(refreshHistory);}else if(key&&key!=='text'&&key!=='query'&&key!=='title'){state[key]=event.target.value;saveDraft();if(key==='speech_reference_id')renderReferences();action(checkEngine);}},{signal:uiEvents.signal});
    root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||!root.contains(b))return;
      if(b.dataset.filter){state.filter=b.dataset.filter;state.page=1;renderVoices();return;}
      if(b.dataset.engine){state.speech_engine=b.dataset.engine;saveDraft();updateEditor();action(checkEngine);return;}
      const commands={generate,refresh,settings:()=>{const settings={};Object.keys(defaults).filter(k=>!['text','title'].includes(k)).forEach(k=>settings[k]=state[k]);write('settings',settings);notice('Đã lưu thiết lập cho lần mở tiếp theo.');},
        clone:async()=>{if(typeof opts.onOpenClone!=='function')throw new Error('Chưa kết nối hộp thoại thêm giọng.');await opts.onOpenClone();},
        import:()=>role('txtFile').click(),clear:()=>{state.text='';field('text').value='';saveDraft();updateEditor();},
        voicePrev:()=>{state.page--;renderVoices();},voiceNext:()=>{state.page++;renderVoices();},historyPrev:async()=>{state.historyPage--;await refreshHistory();},historyNext:async()=>{state.historyPage++;await refreshHistory();},
        addReference:()=>{role('referenceError').textContent='';role('referenceForm').reset();role('uploadPlayer').hidden=true;role('referenceDialog').showModal();},closeReference,
        removeReference:async()=>{const ref=state.references.find(r=>r.id===state.speech_reference_id);if(!ref||!global.confirm(`Xóa mẫu sắc thái “${ref.name}”?`))return;await request('/api/voice-studio/references/'+ref.id,{method:'DELETE'});state.references=state.references.filter(r=>r.id!==ref.id);state.speech_reference_id='';saveDraft();renderReferences();await checkEngine();}};
      if(commands[b.dataset.action])action(commands[b.dataset.action]);
    },{signal:uiEvents.signal});
    role('txtFile').onchange=()=>action(async()=>{const file=role('txtFile').files[0];if(!file)return;if(file.size>150000)throw new Error('Tệp TXT quá lớn. Tối đa 20.000 ký tự.');const text=(await file.text()).replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n');if(text.length>20000)throw new Error('Tệp TXT tối đa 20.000 ký tự.');state.text=text;field('text').value=text;saveDraft();updateEditor();role('txtFile').value='';notice('Đã nhập TXT. Kiểm tra nội dung trước khi tạo bản đọc.');});
    role('referenceForm').onsubmit=event=>action(()=>uploadReference(event));
    role('referenceForm').elements.audio.onchange=()=>{if(referenceURL)URL.revokeObjectURL(referenceURL);const file=role('referenceForm').elements.audio.files[0];if(file){referenceURL=URL.createObjectURL(file);role('uploadPlayer').src=referenceURL;role('uploadPlayer').hidden=false;}};
    role('referenceDialog').addEventListener('cancel',()=>{role('uploadPlayer').pause();if(referenceURL){URL.revokeObjectURL(referenceURL);referenceURL=null;}});
    root.addEventListener('play',event=>{root.querySelectorAll('audio').forEach(a=>{if(a!==event.target)a.pause();});},{capture:true,signal:uiEvents.signal});
    role('resultPlayer').addEventListener('error',()=>{if(role('resultPlayer').getAttribute('src'))notice('Không tải được âm thanh. Bấm tải lại lịch sử rồi thử nghe/tải lại.',true);});
    function schedule(){clearTimeout(timer);if(!state.visible||state.destroyed)return;timer=setTimeout(async()=>{try{await refreshHistory();}catch(e){if(e.name!=='AbortError')notice('Chưa cập nhật được lịch sử: '+e.message+' · Có thể bấm ↻ để thử lại.',true);}schedule();},2500);}
    const controller={refresh:async()=>{await refresh();schedule();},setVisible:visible=>{state.visible=Boolean(visible);root.hidden=!state.visible;if(state.visible){action(refresh);schedule();}else{clearTimeout(timer);clearTimeout(statusTimer);stopAudio();if(role('referenceDialog').open)closeReference();}},destroy:()=>{state.destroyed=true;uiEvents.abort();clearTimeout(timer);clearTimeout(statusTimer);controllers.forEach(c=>c.abort());stopAudio();if(referenceURL)URL.revokeObjectURL(referenceURL);delete root.__voiceWorkspace;root.replaceChildren();}};
    root.__voiceWorkspace=controller;action(refresh);schedule();return controller;
  }
})(typeof window==='undefined'?globalThis:window);

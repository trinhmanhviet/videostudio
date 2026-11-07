/* The shell reuses the established project, admission and editor actions. */
(function (global) {
  'use strict';
  const PENDING_KEY = 'videostudio.factory.pending.v1';
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  function normalizeItem(value, index) {
    const item = typeof value === 'string' ? {text:value} : value;
    if (!item || typeof item !== 'object' || typeof item.text !== 'string' || !item.text.trim()) throw Error('Mục '+(index+1)+' chưa có nội dung.');
    if (item.text.trim().length > 100000) throw Error('Mục '+(index+1)+' quá dài (tối đa 100.000 ký tự).');
    const result = {text:item.text.trim()};
    if (item.title != null && String(item.title).trim()) result.title = String(item.title).trim().slice(0,200);
    if (item.duration_seconds != null && item.duration_seconds !== '') {
      const duration = Number(item.duration_seconds);
      if (!Number.isFinite(duration) || duration <= 0) throw Error('Thời lượng mục '+(index+1)+' phải lớn hơn 0.');
      result.duration_seconds = duration;
    }
    return result;
  }
  function parseImport(value, filename) {
    const clean = String(value).replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').trim();
    let items;
    if (/\.json$/i.test(filename || '')) {
      let parsed;try {parsed=JSON.parse(clean);} catch {throw Error('File JSON chưa đúng định dạng.');}
      items = Array.isArray(parsed) ? parsed : parsed?.items;
      if (!Array.isArray(items)) throw Error('JSON cần là một danh sách hoặc đối tượng có danh sách items.');
    } else if (/\.txt$/i.test(filename || '')) items = clean ? clean.split(/\n[\t ]*\n+/) : [];
    else throw Error('Chọn file TXT hoặc JSON.');
    if (!items.length) throw Error('File chưa có nội dung.');
    if (items.length > 100) throw Error('Mỗi lần nhập tối đa 100 video.');
    return items.map(normalizeItem);
  }
  function pendingRequest(storage, payload, makeUUID, scope='') {
    const identity = JSON.stringify(payload);
    let pending;try {pending=JSON.parse(storage.getItem(PENDING_KEY)||'null');}catch{}
    if (!pending || pending.identity !== identity || (pending.scope||'')!==scope || !pending.key) pending={identity,scope,key:(makeUUID||(()=>global.crypto.randomUUID()))()};
    storage.setItem(PENDING_KEY,JSON.stringify(pending));
    return pending;
  }
  function resolveScope(pathname, bridge) {
    const match = String(pathname).match(/^\/story-video\/projects\/([0-9a-f-]{36})\/production\/?$/i);
    if (match && uuidPattern.test(match[1])) return match[1];
    return bridge?.connected === true && bridge?.validated === true && uuidPattern.test(bridge.scope || '') ? bridge.scope : null;
  }
  async function discoverScope(pathname, read) {
    const current=resolveScope(pathname);if(current)return current;
    const data=await read('/api/connector/status');
    const ids=[...new Set((data.items||[]).map(item=>item.scope).filter(scope=>uuidPattern.test(scope||'')))];
    const results=await Promise.allSettled(ids.map(async scope=>{const status=await read('/api/connector/bridges/'+encodeURIComponent(scope)+'/status');const h=status.heartbeat||{};return status.bridge===scope&&status.ready===true&&h.connected===true&&h.fresh===true&&h.supported_build===true&&h.build==='videostudio-extension-0.3.0'?scope:null;}));
    const live=results.filter(result=>result.status==='fulfilled'&&result.value).map(result=>result.value);
    if(live.length>1)throw Error('Có nhiều phiên kết nối đang mở. Hãy mở trang tạo video của phiên bạn muốn dùng.');
    return live[0]||null;
  }
  async function scopeForTransport(pathname, transport, read) {return transport==='extension'?discoverScope(pathname,read):null;}
  function filterQuery(filters) {
    const query = new URLSearchParams();
    for (const [key,value] of Object.entries(filters)) if (value !== '' && value != null) query.set(key,String(value));
    return query.toString();
  }
  function schedulePayload(video, fields) {
    if (!video?.job_id || !video?.version_id || !(video.approved === true || video.review_state === 'approved')) throw Error('Hãy duyệt đúng bản video trước khi lên lịch.');
    if (!fields.channel_id || !fields.publish_at || !Number.isFinite(Date.parse(fields.publish_at))) throw Error('Chọn kênh và giờ đăng hợp lệ.');
    return {job_id:video.job_id,version_id:video.version_id,channel_id:fields.channel_id,title:video.title || '',publish_at:fields.publish_at,caption:fields.caption || ''};
  }
  global.ContentStudio = {parseImport,pendingRequest,resolveScope,discoverScope,scopeForTransport,filterQuery,schedulePayload};
  if (typeof document === 'undefined') return;

  const $ = selector => document.querySelector(selector);
  const el = (tag, cls, value) => {const node=document.createElement(tag);if(cls)node.className=cls;if(value!=null)node.textContent=value;return node;};
  const button = (label, action, cls='secondary') => {const node=el('button',cls,label);node.type='button';node.onclick=action;return node;};
  const append = (node,...children) => {node.append(...children.filter(Boolean));return node;};
  const state = {page:'projects',batch:false,batchItems:[],queue:null,library:{q:'',style:'',project:'',review_state:'',status:'',page:1,page_size:10},libraryData:null,channels:[],schedules:[],week:new Date(),scheduleView:'week',drawerFocus:null,request:0,loading:false};
  const labels = {pending:'Đang chờ',waiting:'Chờ điều kiện chạy',dispatching:'Đang chuẩn bị',queued:'Đang chờ',running:'Đang tạo',retrying:'Đang thử lại',completed:'Hoàn tất',succeeded:'Hoàn tất',failed:'Có lỗi',cancelled:'Đã hủy',skipped:'Đã bỏ qua',awaiting_visual_review:'Chờ duyệt hình',awaiting_flow_account:'Chờ tài khoản tạo ảnh',scheduled:'Đã lên lịch',blocked:'Cần kết nối',publishing:'Đang đăng',published:'Đã đăng',unknown:'Cần kiểm tra',draft:'Bản nháp'};
  const styleLabels = {news:'Tin tức',case:'Vụ án',meme:'Meme hài'};
  const paths = {projects:'M3 6h7l2 2h9v12H3z',queue:'m3 7 9-5 9 5-9 5zm0 5 9 5 9-5m-18 5 9 5 9-5',library:'M3 4h18v16H3zm7 5 6 3-6 3z',calendar:'M4 5h16v16H4zm0 5h16M8 2v6m8-6v6',resources:'M3 4h18v16H3zm0 12 6-6 5 5 3-3 4 4M15 8h.01',settings:'m9 3 1-2h4l1 2 3 2 2 1v4l-2 1-2 3-1 2h-4l-1-2-3-2-2-1V7l2-1zm3 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8'};
  function icon(name) {const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[name]);svg.append(p);return svg;}
  function localURL(value) {try {const u=new URL(value,location.href);return u.origin===location.origin ? u.href : null;} catch {return null;}}
  async function request(path, options={}) {
    const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers},signal:AbortSignal.timeout(60000)});
    const data=await response.json().catch(()=>({detail:'Không đọc được phản hồi. Hãy thử lại.'}));
    if(!response.ok){let detail=data.detail??data.message??data.error;throw Error(typeof detail==='string'?detail:'Không thể thực hiện thao tác này ('+response.status+').');}
    return data;
  }
  function toast(message) {let node=$('#studioToast');if(!node){node=el('div','studio-toast');node.id='studioToast';node.setAttribute('role','status');document.body.append(node);}node.textContent=message;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.hidden=true,6000);}
  function pageHeader(title, description, action) {const root=el('div','studio-page-header');const heading=append(el('div'),el('h2','',title),el('p','',description));append(root,heading,action);return root;}
  function empty(title, description, action) {return append(el('div','studio-empty'),el('strong','',title),el('p','',description),action);}
  function errorNode(root,error) {const node=el('p','studio-error',error.message || String(error));node.setAttribute('role','alert');root.replaceChildren(node,button('Thử lại',()=>refreshPage()));}
  function stateBadge(value) {return el('span','studio-state '+value,labels[value] || value || 'Chưa có trạng thái');}
  function prettyDate(value) {if(!value)return '';const date=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(date.getTime())?date.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';}

  function installShell() {
    document.body.classList.add('studio-ready');
    const sidebar=el('aside','studio-sidebar');sidebar.setAttribute('aria-label','Điều hướng chính');
    const brand=append(el('a','studio-brand'),el('span','studio-brand-mark','▶'),el('span','','VideoStudio'));brand.href='/';sidebar.append(brand);
    const nav=el('nav','studio-nav');
    for(const [name,label] of [['projects','Dự án'],['queue','Hàng đợi'],['library','Kho video'],['calendar','Lịch đăng'],['resources','Kho tài nguyên'],['settings','Cài đặt']]) {
      const node=name==='resources'?el('a'):button('',()=>navigate(name),'');node.dataset.studioNav=name;
      if(name==='resources')node.href='/resources';append(node,icon(name),el('span','',label));nav.append(node);
    }
    sidebar.append(nav);const footer=el('div','studio-sidebar-footer');footer.append(el('p','notice','Không gian sáng tạo của bạn'));sidebar.append(footer);document.body.prepend(sidebar);
    const header=$('main>header');header.classList.add('studio-topbar');$('#globalRefresh').textContent='Làm mới';
    const system=button('',()=>navigate('settings'),'secondary studio-system-button');system.id='studioSystem';append(system,el('span','studio-system-dot'),el('span','','Kết nối & hệ thống'));header.querySelector('.row').prepend(system);
    for(const name of ['queue','library','calendar','settings']) {const view=el('section','studio-view');view.id='studio-'+name;view.hidden=true;$('main').append(view);}
    const existingGlobalRefresh=$('#globalRefresh').onclick;$('#globalRefresh').onclick=()=>{existingGlobalRefresh?.();refreshPage();};
    const existingOpenProject=global.openProject;
    // Top-level function declarations are shared with the existing classic script.
    global.openProject=function(name){navigate('projects',false);existingOpenProject(name);$('#studioNewVideo').hidden=false;};
    $('#btnBackToGallery').addEventListener('click',()=>$('#studioNewVideo').hidden=true);
    const projectHeader=$('#viewWorkspace').firstElementChild;const createButton=button('+ Tạo video',openDrawer);createButton.id='studioNewVideo';projectHeader.append(createButton);
    const oldCreate=$('#btnConfirmProjectModal').onclick;$('#btnConfirmProjectModal').onclick=async()=>{await oldCreate();if($('#projectModal').hidden)openDrawer();};
    $('#tabProjects').onclick=()=>navigate('projects');$('#tabClone').onclick=()=>navigate('settings');
    $('#viewGallery h2').textContent='Dự án';$('#viewGallery p').textContent='Tiếp tục câu chuyện của bạn';
    installDrawer();installSettings();
    const requested=new URLSearchParams(location.search).get('view');
    const initial=requested==='videos'?'library':requested;
    navigate(['queue','library','calendar','settings'].includes(initial)?initial:'projects',true);
    setInterval(()=>{if(!document.hidden&&['queue','calendar'].includes(state.page)&&!state.loading)refreshPage();updateSystemIndicator();},5000);
    updateSystemIndicator();initializeConnection();
  }
  function navigate(name, reload=true) {
    state.page=name;closeDrawer(false);
    $('#paneProjects').hidden=name!=='projects';$('#paneClone').hidden=true;
    for(const view of document.querySelectorAll('.studio-view'))view.hidden=view.id!=='studio-'+name;
    for(const node of document.querySelectorAll('[data-studio-nav]')) {if(node.dataset.studioNav===name)node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');}
    if(reload)refreshPage();
  }
  async function refreshPage() {if(state.loading){state.refreshPending=true;return;}state.loading=true;const page=state.page;try {if(page==='queue')await loadQueue();if(page==='library')await loadLibrary();if(page==='calendar')await loadCalendar();if(page==='settings')await loadChannels($('#studioSettingsChannels'));}finally{state.loading=false;if(state.refreshPending||state.page!==page){state.refreshPending=false;await refreshPage();}}}
  async function factoryScope() {
    const health=await request('/api/health');
    if(health.text_transport!=='extension')return null;
    const scope=await scopeForTransport(location.pathname,health.text_transport,request);
    if(!scope)throw Error('Chưa có phiên kết nối sẵn sàng. Mở bảng kết nối, chọn Bắt đầu và kiểm tra kết nối trước khi tạo video.');
    global.selectStudioConnectorScope?.(scope);return scope;
  }
  async function initializeConnection() {try{await factoryScope();}catch(error){$('#connectorStatus').textContent=error.message;}}
  function updateSystemIndicator() {const checks=$('#checks');const ready=checks?.querySelectorAll('.error').length===0&&checks?.querySelector('.pass');$('#studioSystem .studio-system-dot')?.classList.toggle('ready',!!ready);}

  function installDrawer() {
    const backdrop=el('div','studio-drawer-backdrop');backdrop.id='studioDrawerBackdrop';backdrop.hidden=true;backdrop.onclick=()=>closeDrawer();
    const drawer=el('section','studio-drawer');drawer.id='studioDrawer';drawer.hidden=true;drawer.setAttribute('role','dialog');drawer.setAttribute('aria-modal','true');drawer.setAttribute('aria-labelledby','studioDrawerTitle');
    const head=append(el('div','studio-drawer-head'),el('h2','','Tạo video'),button('×',()=>closeDrawer()));head.querySelector('h2').id='studioDrawerTitle';head.querySelector('button').setAttribute('aria-label','Đóng form tạo video');
    const body=el('div','studio-drawer-body');body.append(el('h2','','Bạn muốn kể chuyện gì?'));
    const form=$('#create');body.append(form);append(drawer,head,body);document.body.append(backdrop,drawer);
    const segments=el('div','studio-segments');segments.setAttribute('role','group');segments.setAttribute('aria-label','Số video');
    for(const [batch,label] of [[false,'▷  Một video'],[true,'▱  Nhập nhiều']]){const node=button(label,()=>setBatchMode(batch),'');node.dataset.batch=String(batch);node.setAttribute('aria-pressed',String(!batch));segments.append(node);}form.prepend(segments);
    const source=el('div','studio-segments');source.setAttribute('role','group');source.setAttribute('aria-label','Nguồn nội dung');
    for(const [value,label] of [['script','Tôi đã có kịch bản'],['idea','Phát triển ý tưởng']]){const node=button(label,()=>{form.dataset.inputMode=value;syncWorkflow();for(const b of source.children)b.setAttribute('aria-pressed',String(b===node));},'');node.dataset.input=value;node.setAttribute('aria-pressed',String(value==='idea'));source.append(node);}segments.after(source);form.dataset.inputMode='idea';
    const styleLabel=el('label','','Phong cách');styleLabel.htmlFor='studioStyle';const style=el('select');style.id='studioStyle';for(const [value,label] of Object.entries(styleLabels)){const o=el('option','',label);o.value=value;style.append(o);}style.onchange=syncWorkflow;$('#idea').after(styleLabel,style);
    const importBox=el('div','studio-import');importBox.id='studioImport';importBox.hidden=true;
    const label=el('label','','Nhập nội dung từ file');label.htmlFor='studioImportFile';const file=el('input');file.id='studioImportFile';file.type='file';file.accept='.txt,.json,text/plain,application/json';
    file.onchange=async()=>{if(!file.files?.[0])return;try{state.batchItems=parseImport(await file.files[0].text(),file.files[0].name);renderBatchItems();$('#submitError').textContent='';}catch(error){$('#submitError').textContent=error.message;}finally{file.value='';}};
    append(importBox,label,file,el('p','','TXT: mỗi video cách nhau một dòng trống. JSON: danh sách chuỗi hoặc mục có text, title, duration_seconds.'));
    const rows=el('div');rows.id='studioBatchRows';const add=button('+ Thêm nội dung',()=>{state.batchItems=readBatchItems(false);state.batchItems.push({text:''});renderBatchItems();});append(importBox,rows,add);style.after(importBox);
    const advanced=el('details','studio-advanced');advanced.append(el('summary','','Cài đặt nâng cao'));
    for(const selector of ['label[for=textProvider]','#textProvider','#textProviderNote','#imageProviderLabel','#imageProvider','#imageProviderNote','#flowBatchSizeLabel','#flowBatchSize','#flowBatchNote','#musicVolumeLabel','#musicVolume','label[for=createPitch]']){const node=$(selector);if(node)advanced.append(node);}
    advanced.append($('#createPitch').parentElement);$('#limits').before(advanced);
    $('#limits').textContent='Video dọc 9:16 · Thời lượng được kiểm tra trước khi nhận';
    form.onsubmit=async event=>{
      event.preventDefault();if(form.dataset.submitting==='true')return;$('#submitError').textContent='';
      try {
        const items=state.batch?readBatchItems(true):[normalizeItem({text:$('#idea').value},0)];const voice=$('#voice').value;if(!voice)throw Error('Chọn giọng đọc trước khi tạo video.');
        const duration=Number($('#duration').value)*Number($('#unit').value);if(!Number.isFinite(duration)||duration<=0)throw Error('Nhập thời lượng hợp lệ.');
        const payload={project:$('#projectInput').value||'Dự án mặc định',style:$('#studioStyle').value,input_mode:form.dataset.inputMode,defaults:{duration_seconds:duration,voice_id:voice,text_provider:$('#textProvider').value,image_provider:$('#imageProvider').value,flow_batch_size:Number($('#flowBatchSize').value),music_volume:Number($('#musicVolume').value)/100,pitch:Number($('#createPitch').value)||0,quality_mode:'quick'},items};
        if(payload.style==='meme'){payload.defaults.image_provider='comfy';payload.defaults.flow_batch_size=1;payload.defaults.music_volume=0;}
        const scope=await factoryScope();const pending=pendingRequest(sessionStorage,payload,undefined,scope||'');
        form.dataset.submitting='true';$('#submit').disabled=true;
        await request('/api/factory/batches',{method:'POST',headers:{'Idempotency-Key':pending.key,...(scope?{'X-Connector-Scope':scope}:{})},body:pending.identity});
        sessionStorage.removeItem(PENDING_KEY);state.batchItems=[];renderBatchItems();closeDrawer();navigate('queue');toast('Đã thêm '+items.length+' video vào hàng đợi.');
      } catch(error) {$('#submitError').textContent=error.message;}
      finally {delete form.dataset.submitting;if(typeof global.enable==='function')global.enable();}
    };
    document.addEventListener('keydown',event=>{if(drawer.hidden)return;if(event.key==='Escape'){event.preventDefault();closeDrawer();}if(event.key==='Tab'){const nodes=[...drawer.querySelectorAll('button,input,select,textarea,summary,a[href]')].filter(n=>!n.disabled&&n.getClientRects().length);if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
    syncWorkflow();
  }
  function syncWorkflow() {const form=$('#create');$('#workflowMode').value=$('#studioStyle').value==='meme'?'meme':form.dataset.inputMode==='script'?'provided_narration':'research';if(typeof global.onWorkflowModeChange==='function')global.onWorkflowModeChange();$('#ideaLabel').textContent=form.dataset.inputMode==='script'?'Kịch bản của bạn':'Ý tưởng của bạn';$('#idea').placeholder=form.dataset.inputMode==='script'?'Nhập lời đọc của video, mỗi dòng là một câu.':'Nhập chủ đề, câu chuyện hoặc điều bạn muốn chia sẻ…';$('#workflowModeNote').textContent=form.dataset.inputMode==='script'?'Giữ nguyên lời đọc bạn nhập; tự chuẩn bị hình ảnh theo từng cảnh.':'Từ ý tưởng của bạn, phát triển kịch bản và hình ảnh theo phong cách đã chọn.';$('#durationControls').hidden=false;$('#durationLabel').textContent='Độ dài mong muốn';$('#unit').disabled=false;$('#duration').required=true;}
  function setBatchMode(batch) {state.batch=batch;$('#studioImport').hidden=!batch;$('#idea').hidden=batch;$('#idea').required=!batch;$('#ideaLabel').hidden=batch;for(const node of document.querySelectorAll('[data-batch]'))node.setAttribute('aria-pressed',String(node.dataset.batch===String(batch)));$('#submit').textContent=batch?'Thêm vào hàng đợi':'Tạo video';if(batch&&!state.batchItems.length){state.batchItems=[{text:''}];renderBatchItems();}}
  function openDrawer() {if(!$('#projectInput').value){global.openProjectModal?.();return;}state.drawerFocus=document.activeElement;$('#studioDrawerTitle').textContent=$('#projectInput').value;$('#studioDrawer').hidden=false;$('#studioDrawerBackdrop').hidden=false;document.body.style.overflow='hidden';$('#studioDrawer .studio-drawer-head button').focus();}
  function closeDrawer(restore=true) {if(!$('#studioDrawer'))return;const wasOpen=!$('#studioDrawer').hidden;$('#studioDrawer').hidden=true;$('#studioDrawerBackdrop').hidden=true;document.body.style.overflow='';if(wasOpen&&restore&&state.drawerFocus?.isConnected)state.drawerFocus.focus();}
  function readBatchItems(validate) {const items=[...document.querySelectorAll('.studio-batch-item')].map(node=>({text:node.querySelector('textarea').value,title:node.querySelector('input[type=text]').value,duration_seconds:node.querySelector('input[type=number]').value}));if(!validate)return items;if(!items.length)throw Error('Thêm ít nhất một nội dung trước khi tạo.');return items.map(normalizeItem);}
  function renderBatchItems() {const root=$('#studioBatchRows');root.replaceChildren(el('p','studio-batch-summary',state.batchItems.length+' video · Có thể sửa nội dung và thời lượng từng mục'));
    state.batchItems.forEach((item,index)=>{const row=el('div','studio-batch-item');const title=el('input');title.type='text';title.value=item.title||'';title.placeholder='Tiêu đề video '+(index+1);title.maxLength=200;title.setAttribute('aria-label','Tiêu đề video '+(index+1));const remove=button('×',()=>{state.batchItems=readBatchItems(false);state.batchItems.splice(index,1);renderBatchItems();});remove.setAttribute('aria-label','Xóa mục '+(index+1));const area=el('textarea');area.value=item.text||'';area.maxLength=100000;area.setAttribute('aria-label','Nội dung video '+(index+1));const duration=el('input');duration.type='number';duration.min='0.1';duration.step='0.1';duration.placeholder='Mặc định';duration.value=item.duration_seconds||'';duration.setAttribute('aria-label','Thời lượng riêng video '+(index+1));const label=append(el('label'),el('span','','Thời lượng riêng (giây)'),duration);append(row,append(el('div','studio-batch-item-head'),title,remove),area,label);root.append(row);});
  }

  function installSettings() {const root=$('#studio-settings');root.append(pageHeader('Cài đặt','Kết nối công cụ, quản lý giọng đọc và tài khoản đăng video.'));const grid=el('div','studio-settings-grid');
    const connection=$('#viewWorkspace>.layout>aside');connection.classList.add('studio-connection');connection.hidden=false;connection.querySelector('h2').textContent='Kết nối tạo video';grid.append(connection);
    const voices=el('section','card');append(voices,el('h3','','Giọng đọc'),el('p','notice','Chọn giọng có sẵn khi tạo video hoặc thêm giọng mới từ một bản thu.'),button('Tạo giọng từ bản thu',()=>{const pane=$('#paneClone');pane.hidden=!pane.hidden;pane.scrollIntoView({behavior:'smooth',block:'start'});}));grid.append(voices);
    const channels=el('section','card');channels.id='studioSettingsChannels';channels.append(el('h3','','Tài khoản đăng video'));grid.append(channels);
    const tools=el('section','card');append(tools,el('h3','','Công cụ & trợ giúp'),el('p','notice','Dùng bảng kết nối nổi để kết nối tài khoản tạo nội dung. Khi gặp lỗi, kiểm tra điều kiện chạy và thử lại.'));const resourceLink=el('a','','Mở kho tài nguyên →');resourceLink.href='/resources';tools.append(resourceLink,document.createElement('br'),button('Xem nhật ký khi cần',()=>{$('#inlineConsole').hidden=false;navigate('projects',false);if($('#viewWorkspace').hidden&&$('#galleryContainer .project-card'))$('#galleryContainer .project-card').click();global.loadConsoleLogs?.();$('#inlineConsole').scrollIntoView({behavior:'smooth'});}));grid.append(tools);root.append(grid);
  }

  async function loadQueue() {const root=$('#studio-queue');try {const data=await request('/api/factory/queue');state.queue=data;root.replaceChildren(pageHeader('Hàng đợi','Tạo lần lượt, theo dõi từng video và điều chỉnh các mục đang chờ.',button(data.paused?'Tiếp tục hàng đợi':'Tạm dừng sau video này',async()=>{try{await request('/api/factory/queue/pause',{method:'POST',body:JSON.stringify({paused:!data.paused})});await loadQueue();}catch(error){toast(error.message);}})));
      const items=data.items||[];const metrics=el('div','studio-metrics');const counts=[['Đang tạo',items.filter(i=>['running','dispatching','queued','retrying'].includes(i.state)).length],['Đang chờ',items.filter(i=>['pending','waiting'].includes(i.state)).length],['Hoàn tất',items.filter(i=>i.state==='completed').length],['Cần chú ý',items.filter(i=>['failed','awaiting_visual_review','awaiting_flow_account'].includes(i.state)).length]];for(const [label,value] of counts)metrics.append(append(el('div','studio-metric'),el('strong','',value),el('span','',label)));root.append(metrics);
      if(data.paused)root.append(el('p','studio-create-note','Hàng đợi đang tạm dừng. Video hiện tại vẫn tiếp tục cho đến khi xong.'));
      const list=el('div','studio-queue-list');list.setAttribute('aria-label','Danh sách video trong hàng đợi');if(!items.length)list.append(empty('Hàng đợi đang trống','Mở một dự án và chọn Tạo video hoặc Nhập nhiều để bắt đầu.',button('Mở dự án',()=>navigate('projects'))));
      for(const [index,item] of items.entries()){const active=['running','dispatching','queued','retrying'].includes(item.state);const row=el('article','studio-queue-row'+(active?' active':''));const body=append(el('div'),el('h3','',item.title||item.content?.slice(0,70)||'Video '+(index+1)),el('p','',[item.project,styleLabels[item.style]||'',item.job?.stage?stageLabel(item.job.stage):''].filter(Boolean).join(' · ')));body.append(stateBadge(item.state));
        if(item.job?.progress!=null){const progress=el('progress','studio-progress');progress.max=100;progress.value=Number(item.job.progress)<=1?Number(item.job.progress)*100:Number(item.job.progress);progress.setAttribute('aria-label','Tiến độ video');body.append(progress);}
        if(item.message)body.append(el('p','studio-error',item.message));const actions=el('div','studio-queue-actions');
        if(['pending','waiting'].includes(item.state)){const pending=items.filter(i=>['pending','waiting'].includes(i.state));const pos=pending.findIndex(i=>i.id===item.id);for(const [delta,label] of [[-1,'↑'],[1,'↓']]){const b=button(label,()=>reorderQueue(item.id,delta));b.disabled=pos+delta<0||pos+delta>=pending.length;b.setAttribute('aria-label',delta<0?'Đưa lên trước':'Đưa xuống sau');actions.append(b);}actions.append(button('Bỏ qua',()=>queueAction(item,'skip')));}
        if(['failed','cancelled','skipped','waiting'].includes(item.state))actions.append(button(item.state==='cancelled'&&item.job_id?'Tiếp tục video':'Thử lại',()=>queueAction(item,'retry')));
        if(active)actions.append(button('Hủy video',()=>queueAction(item,'cancel')));
        if(item.job_id)actions.append(button('Mở dự án',()=>global.openProject(item.project||'Dự án mặc định')));
        append(row,el('div','studio-queue-number',String(index+1).padStart(2,'0')),body,actions);list.append(row);}
      root.append(list);
    }catch(error){errorNode(root,error);}}
  function stageLabel(stage) {return {plan:'Chuẩn bị câu chuyện',research:'Tìm hiểu nội dung',script:'Viết kịch bản',speech:'Tạo lời đọc',images:'Tạo hình ảnh',subtitles:'Chuẩn bị phụ đề',music:'Tạo nhạc',render:'Dựng video',verify:'Kiểm tra thành phẩm'}[stage]||'Đang xử lý';}
  async function queueAction(item,action) {try{const scope=action==='retry'?await factoryScope():resolveScope(location.pathname);await request('/api/factory/items/'+encodeURIComponent(item.id)+'/'+action,{method:'POST',headers:scope?{'X-Connector-Scope':scope}:{},body:'{}'});await loadQueue();}catch(error){toast(error.message);}}
  async function reorderQueue(id,delta) {const ids=(state.queue?.items||[]).filter(i=>['pending','waiting'].includes(i.state)).map(i=>i.id);const index=ids.indexOf(id);if(index<0||index+delta<0||index+delta>=ids.length)return;[ids[index],ids[index+delta]]=[ids[index+delta],ids[index]];try{await request('/api/factory/queue/reorder',{method:'POST',body:JSON.stringify({item_ids:ids})});await loadQueue();}catch(error){toast(error.message);}}

  function filterControl(label,name,options) {const wrapper=el('label');wrapper.append(el('span','',label));const node=name==='q'||name==='project'?el('input'):el('select');node.name=name;if(node.tagName==='INPUT'){node.type=name==='q'?'search':'text';node.placeholder=name==='q'?'Tìm video…':'Tên dự án';node.value=state.library[name];}else for(const [value,title] of options){const option=el('option','',title);option.value=value;option.selected=state.library[name]===value;node.append(option);}node.onchange=()=>{state.library[name]=node.value;state.library.page=1;loadLibrary();};if(node.tagName==='INPUT')node.oninput=()=>{clearTimeout(node.searchTimer);node.searchTimer=setTimeout(()=>node.onchange(),350);};wrapper.append(node);return wrapper;}
  async function loadLibrary() {const root=$('#studio-library');const ticket=++state.request;try{const data=await request('/api/factory/videos?'+filterQuery(state.library));if(ticket!==state.request)return;state.libraryData=data;
      const focused=document.activeElement;const focusName=root.contains(focused)?focused.name:null;const selection=focusName&&typeof focused.selectionStart==='number'?focused.selectionStart:null;
      root.replaceChildren(pageHeader('Kho video','Chọn bản xuất, duyệt thành phẩm và chuẩn bị lịch đăng.'));
      const filters=el('div','studio-filters');append(filters,filterControl('Tìm kiếm','q'),filterControl('Phong cách','style',[['','Mọi phong cách'],...Object.entries(styleLabels)]),filterControl('Dự án','project'),filterControl('Duyệt video','review_state',[['','Tất cả'],['pending','Chưa duyệt'],['approved','Đã duyệt']]));root.append(filters);
      const grid=el('div','studio-video-grid');if(!data.items?.length)grid.append(empty('Chưa có video phù hợp','Thành phẩm đã kiểm tra sẽ xuất hiện ở đây. Bạn có thể đổi bộ lọc hoặc tạo video trong một dự án.',button('Mở dự án',()=>navigate('projects'))));for(const video of data.items||[])grid.append(videoCard(video));root.append(grid);
      const pages=Math.max(1,data.total_pages||1);const previous=button('← Trước',()=>{state.library.page--;loadLibrary();});previous.disabled=state.library.page<=1;const next=button('Sau →',()=>{state.library.page++;loadLibrary();});next.disabled=state.library.page>=pages;root.append(append(el('div','studio-pagination'),previous,el('span','','Trang '+state.library.page+' / '+pages+' · '+(data.total||0)+' video'),next));
      if(focusName){const replacement=root.querySelector('[name="'+focusName+'"]');replacement?.focus();if(selection!=null)replacement?.setSelectionRange?.(selection,selection);}
    }catch(error){if(ticket===state.request)errorNode(root,error);}}
  function videoCard(video) {const card=el('article','studio-video-card');const thumb=el('div','studio-video-thumb');const src=video.thumbnail&&localURL(video.thumbnail);if(src){const img=el('img');img.src=src;img.alt='';img.loading='lazy';thumb.append(img);}else thumb.append(el('span','','▷'));thumb.append(stateBadge(video.status||video.state));
    const body=append(el('div','studio-video-body'),el('h3','',video.title||'Video'),el('div','studio-video-meta',[video.project,styleLabels[video.style],video.duration_seconds?Math.round(video.duration_seconds)+' giây':''].filter(Boolean).join(' · ')));
    const versions=Array.isArray(video.versions)?video.versions:[];const select=el('select');select.setAttribute('aria-label','Bản xuất của '+(video.title||'video'));for(const [i,v] of versions.entries()){const option=el('option','',(v.name||'Bản '+(versions.length-i))+(v.latest?' · Mới nhất':'')+(v.approved?' · Đã duyệt':''));option.value=v.version_id||v.id;select.append(option);}if(!versions.length){const option=el('option','','Chưa có bản xuất');select.append(option);select.disabled=true;}body.append(select);
    const review=el('p','notice');const actions=el('div','studio-video-actions');const renderActions=()=>{actions.replaceChildren();const version=versions.find(v=>(v.version_id||v.id)===select.value);const versionId=version?.version_id||version?.id;const approved=version?.approved===true;review.textContent=approved?'✓ Đã duyệt bản này để lên lịch':'Kiểm tra video và duyệt đúng bản trước khi lên lịch.';
      const output=localURL(version?.url||video.output_url);if(output){const play=el('a','button secondary','Xem video');play.href=output;play.target='_blank';play.rel='noopener';actions.append(play);}
      if(versionId){const download=el('a','button secondary','Tải MP4');download.href='/api/factory/videos/'+encodeURIComponent(video.job_id||video.id)+'/versions/'+encodeURIComponent(versionId)+'/file';download.download='';actions.append(download);const pack=el('a','button secondary','Tải trọn bộ');pack.href='/api/factory/videos/'+encodeURIComponent(video.job_id||video.id)+'/pack?'+filterQuery({version_id:versionId,include:'video,captions,sidecar'});pack.download='';actions.append(pack);
        if(!approved)actions.append(button('Duyệt bản này',async()=>{try{await request('/api/factory/videos/'+encodeURIComponent(video.job_id||video.id)+'/approve',{method:'POST',body:JSON.stringify({version_id:versionId,sha256:version.sha256})});await loadLibrary();toast('Đã duyệt bản video đã chọn.');}catch(error){toast(error.message);}}));
        const schedule=button('Lên lịch',()=>openSchedule({job_id:video.job_id||video.id,version_id:versionId,approved,title:video.title}));schedule.disabled=!approved;actions.append(schedule);
      }
      if(video.style==='meme'){const edit=el('a','button secondary','Chỉnh sửa');edit.href='/meme-editor?job='+encodeURIComponent(video.job_id||video.id);actions.append(edit);}else actions.append(button('Chỉnh sửa',()=>global.openOptionalWorkspace?.(video.job_id||video.id)));
    };select.onchange=renderActions;renderActions();append(body,review,actions);append(card,thumb,body);return card;
  }

  async function loadChannels(root) {
    if(!root)return;
    try {
      const data=await request('/api/publishing/channels');
      state.channels=Array.isArray(data)?data:data.items||[];
      root.replaceChildren(el('h3','','Tài khoản đăng video'));
      const grid=el('div','studio-channel-grid');
      for(const channel of state.channels) {
        const card=el('div','studio-channel');
        append(card,el('h3','',channel.name||channel.platform||'Kênh đăng'),stateBadge(channel.connected===true?'connected':'blocked'),el('p','',channel.error||channel.message||(channel.connected?'Tài khoản đã kết nối.':'Cần kết nối tài khoản và cấp quyền đăng video.')));
        grid.append(card);
      }
      if(!state.channels.some(channel=>channel.connected))root.append(el('p','notice','Chưa có kênh sẵn sàng đăng. Kết nối YouTube hoặc Facebook Page để bắt đầu.'));
      root.append(grid);
      if(root.id==='studioSettingsChannels')renderPublishingSetup(root,data);
      else root.append(button('Quản lý kết nối YouTube / Facebook Page',()=>navigate('settings')));
    } catch(error) {root.replaceChildren(el('h3','','Tài khoản đăng video'),el('p','studio-error',error.message),button('Thử lại',()=>loadChannels(root)));}
  }
  function renderPublishingSetup(root,data) {
    const youtube=el('details','studio-advanced');youtube.append(el('summary','','Kết nối YouTube'));
    youtube.append(el('p','notice','Đăng nhập Google để cấp quyền tải và lên lịch video trên kênh của bạn.'));
    if(!data.youtube_configured) {
      const form=el('form');const label=el('label','','File cấu hình ứng dụng Google (.json)');label.htmlFor='studioYoutubeConfig';
      const file=el('input');file.id='studioYoutubeConfig';file.type='file';file.accept='.json,application/json';file.required=true;
      const error=el('p','studio-error');error.setAttribute('role','alert');const save=el('button','','Lưu cấu hình YouTube');save.type='submit';
      append(form,label,file,el('p','notice','Dùng ứng dụng OAuth của bạn trong Google Cloud. Cấu hình chỉ được lưu trên máy này.'),error,save);
      if(data.callback_url)form.append(el('p','notice','Địa chỉ chuyển hướng: '+data.callback_url));
      form.onsubmit=async event=>{event.preventDefault();error.textContent='';save.disabled=true;try{let client;try{client=JSON.parse(await file.files[0].text());}catch{throw Error('File cấu hình Google chưa đúng định dạng JSON.');}await request('/api/publishing/youtube/config',{method:'POST',body:JSON.stringify({client_json:client})});file.value='';await loadChannels(root);toast('Đã lưu cấu hình. Bạn có thể kết nối YouTube.');}catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
      youtube.append(form);
    } else {
      const error=el('p','studio-error');error.setAttribute('role','alert');const connect=button('Đăng nhập và kết nối YouTube',async()=>{connect.disabled=true;error.textContent='';try{const result=await request('/api/publishing/youtube/connect',{method:'POST',body:'{}'});const url=new URL(result.url);if(url.protocol!=='https:'||url.hostname!=='accounts.google.com')throw Error('Không nhận được địa chỉ đăng nhập Google hợp lệ.');const link=el('a','button','Mở Google để cấp quyền');link.href=url.href;link.target='_blank';link.rel='noopener';connect.replaceWith(link);link.click();}catch(e){error.textContent=e.message;}finally{connect.disabled=false;}});
      append(youtube,connect,error,button('Kiểm tra kết nối',()=>loadChannels(root)));
    }
    const facebook=el('details','studio-advanced');facebook.append(el('summary','','Kết nối Facebook Page'));
    const form=el('form');const pageLabel=el('label','','ID Facebook Page');pageLabel.htmlFor='studioFacebookPage';const page=el('input');page.id='studioFacebookPage';page.required=true;page.autocomplete='off';page.inputMode='numeric';page.placeholder='ID trang bạn quản lý';
    const tokenLabel=el('label','','Mã truy cập của Page');tokenLabel.htmlFor='studioFacebookToken';const token=el('input');token.id='studioFacebookToken';token.type='password';token.required=true;token.autocomplete='new-password';
    const error=el('p','studio-error');error.setAttribute('role','alert');const submit=el('button','','Xác nhận và kết nối Page');submit.type='submit';
    append(form,el('p','notice','Dùng mã truy cập của Facebook Page có quyền đăng video. Thông tin kết nối được lưu trên máy này.'),pageLabel,page,tokenLabel,token,error,submit);
    form.onsubmit=async event=>{event.preventDefault();error.textContent='';submit.disabled=true;const secret=token.value;try{await request('/api/publishing/facebook/connect',{method:'POST',body:JSON.stringify({page_id:page.value.trim(),access_token:secret})});token.value='';await loadChannels(root);toast('Đã xác nhận kết nối Facebook Page.');}catch(e){error.textContent=String(e.message).split(secret).join('[đã ẩn]');}finally{token.value='';submit.disabled=false;}};
    facebook.append(form);append(root,youtube,facebook);
  }
  async function loadCalendar() {const root=$('#studio-calendar');try{const data=await request('/api/publishing/schedules');state.schedules=Array.isArray(data)?data:data.items||[];root.replaceChildren(pageHeader('Lịch đăng','Lên kế hoạch cho bản video đã duyệt · Giờ Việt Nam (UTC+7)',button('+ Chọn video để lên lịch',()=>navigate('library'))));
      root.append(el('p','studio-create-note','Giữ máy đang bật và ứng dụng đang chạy để gửi video theo lịch. Kênh hỗ trợ hẹn giờ sẽ nhận video trước giờ công khai.'));
      const channels=el('section');root.append(channels);await loadChannels(channels);
      const toolbar=el('div','studio-calendar-toolbar');const week=weekDays(state.week);const controls=el('div','row');append(controls,button('←',()=>shiftWeek(-7)),button('Hôm nay',()=>{state.week=new Date();loadCalendar();}),button('→',()=>shiftWeek(7)),el('span','muted',week[0].toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit'})+' — '+week[6].toLocaleDateString('vi-VN',{day:'2-digit',month:'2-digit',year:'numeric'})));controls.querySelector('button').setAttribute('aria-label','Tuần trước');controls.querySelectorAll('button')[2].setAttribute('aria-label','Tuần sau');const modes=el('div','row');append(modes,button('Tuần',()=>{state.scheduleView='week';loadCalendar();}),button('Danh sách',()=>{state.scheduleView='list';loadCalendar();}));append(toolbar,controls,modes);root.append(toolbar);
      const filtered=state.schedules.filter(item=>{const key=localDay(item.scheduled_at||item.publish_at);return week.some(date=>dayKey(date)===key);});
      const calendar=el('div','studio-calendar-week');calendar.hidden=state.scheduleView!=='week';for(const date of week){const day=el('section','studio-calendar-day'+(dayKey(date)===localDay(new Date().toISOString())?' today':''));append(day,append(el('h3'),el('span','',date.toLocaleDateString('vi-VN',{weekday:'short'})),el('strong','',date.getDate())));for(const item of filtered.filter(i=>localDay(i.scheduled_at||i.publish_at)===dayKey(date))){const event=button('',()=>scheduleDetail(item),'studio-calendar-event');append(event,el('time','',prettyDate(item.scheduled_at||item.publish_at).split(' ')[0]),el('span','',item.title||item.video_title||'Video'));day.append(event);}calendar.append(day);}root.append(calendar);
      const list=el('div','studio-schedule-list'+(state.scheduleView==='week'?' studio-calendar-list-mobile':''));if(state.scheduleView==='week')list.style.display='none';if(!filtered.length)list.append(empty('Tuần này chưa có lịch đăng','Chọn một video đã duyệt trong Kho video để tạo lịch mới.'));for(const item of filtered.sort((a,b)=>Date.parse(a.publish_at)-Date.parse(b.publish_at)))list.append(scheduleRow(item));root.append(list);
    }catch(error){errorNode(root,error);}}
  function dayKey(date) {return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');}
  function localDay(value) {try{return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}catch{return '';}}
  function weekDays(value) {const local=localDay(value.toISOString());const start=new Date(local+'T12:00:00');start.setDate(start.getDate()-((start.getDay()+6)%7));return Array.from({length:7},(_,index)=>{const date=new Date(start);date.setDate(start.getDate()+index);return date;});}
  function shiftWeek(delta) {state.week.setDate(state.week.getDate()+delta);loadCalendar();}
  function scheduleRow(item) {const channel=state.channels.find(c=>c.id===item.channel_id);const body=append(el('div'),el('h3','',item.title||item.video_title||'Video đã lên lịch'),el('p','',prettyDate(item.scheduled_at||item.publish_at)+' · '+(channel?.name||channel?.platform||item.platform||'Kênh đăng')),stateBadge(item.state||item.status));if(item.message||item.error)body.append(el('p','studio-error',item.message||item.error));const row=append(el('article','studio-schedule-row'),body,button('Chi tiết',()=>scheduleDetail(item)));return row;}
  function dialog(title) {const backdrop=el('div','studio-dialog');const box=el('section','studio-dialog-box');box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');const heading=el('h2','',title);heading.id='studioDialogTitle';box.setAttribute('aria-labelledby',heading.id);const focus=document.activeElement;const close=()=>{backdrop.remove();document.removeEventListener('keydown',key);focus?.focus();};const key=event=>{if(event.key==='Escape')close();if(event.key==='Tab'){const nodes=[...box.querySelectorAll('button,input,select,textarea,a[href]')].filter(n=>!n.disabled);if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}};document.addEventListener('keydown',key);backdrop.onclick=event=>{if(event.target===backdrop)close();};const closeButton=button('×',close);closeButton.setAttribute('aria-label','Đóng');box.append(append(el('header'),heading,closeButton));backdrop.append(box);document.body.append(backdrop);closeButton.focus();return {box,close};}
  async function openSchedule(video) {if(!video.approved){toast('Duyệt đúng bản video trước khi lên lịch.');return;}const modal=dialog('Lên lịch đăng video');modal.box.append(el('p','notice',video.title||'Bản video đã duyệt'));const form=el('form');const error=el('p','studio-error');error.setAttribute('role','alert');modal.box.append(form);
    const channelLabel=el('label','','Kênh đăng · YouTube hoặc Facebook Page');channelLabel.htmlFor='studioScheduleChannel';const channel=el('select');channel.id='studioScheduleChannel';channel.required=true;const timeLabel=el('label','','Thời gian đăng · Giờ Việt Nam (UTC+7)');timeLabel.htmlFor='studioScheduleTime';const time=el('input');time.id='studioScheduleTime';time.type='datetime-local';time.required=true;const captionLabel=el('label','','Lời đăng');captionLabel.htmlFor='studioScheduleCaption';const caption=el('textarea');caption.id='studioScheduleCaption';caption.maxLength=5000;const preview=el('div','studio-create-note');const previewText=el('p','',video.title||'');append(preview,el('strong','','Xem trước lời đăng'),previewText);caption.oninput=()=>previewText.textContent=caption.value||video.title||'Chưa có lời đăng.';const submit=el('button','','Lưu lịch đăng');submit.type='submit';append(form,channelLabel,channel,timeLabel,time,captionLabel,caption,preview,el('p','notice','Lịch giữ nguyên bản video bạn đã duyệt. Máy cần bật và ứng dụng cần chạy để gửi video đúng lịch. Nếu kênh chưa kết nối, lịch sẽ chờ bạn hoàn tất kết nối.'),error,submit);
    try{const data=await request('/api/publishing/channels');state.channels=Array.isArray(data)?data:data.items||data.channels||[];for(const item of state.channels){const option=el('option','',(item.name||item.platform||item.id)+(item.connected===true?'':' · Cần kết nối'));option.value=item.id;channel.append(option);}if(!state.channels.length){submit.disabled=true;error.textContent='Chưa có kênh đăng. Mở Cài đặt để kết nối tài khoản.';form.append(button('Mở cài đặt',()=>{modal.close();navigate('settings');}));}}catch(e){error.textContent=e.message;submit.disabled=true;}
    const scheduleStorage={getItem:()=>form.dataset.pendingSchedule||null,setItem:(_key,value)=>{form.dataset.pendingSchedule=value;}};
    form.onsubmit=async event=>{event.preventDefault();if(form.dataset.sending==='true')return;error.textContent='';submit.disabled=true;form.dataset.sending='true';try{const payload=schedulePayload(video,{channel_id:channel.value,publish_at:time.value+':00+07:00',caption:caption.value});const pending=pendingRequest(scheduleStorage,payload);await request('/api/publishing/schedules',{method:'POST',headers:{'Idempotency-Key':pending.key},body:pending.identity});modal.close();navigate('calendar');toast('Đã lưu lịch đăng.');}catch(e){error.textContent=e.message;}finally{delete form.dataset.sending;submit.disabled=false;}};
  }
  function scheduleDetail(item) {const modal=dialog(item.title||item.video_title||'Chi tiết lịch đăng');append(modal.box,el('p','notice',prettyDate(item.publish_at)+' · Giờ Việt Nam'),stateBadge(item.state||item.status),el('p','',item.caption||'Chưa có lời đăng.'));if(item.message||item.error)modal.box.append(el('p','studio-error',item.message||item.error));if(item.remote_url){try{const url=new URL(item.remote_url);if(url.protocol==='https:'&&/^(www\.)?(youtube\.com|youtu\.be|facebook\.com)$/.test(url.hostname)){const link=el('a','button secondary','Mở bài đã đăng');link.href=url.href;link.target='_blank';link.rel='noopener';modal.box.append(link);}}catch{}}if(['blocked','needs_attention'].includes(item.state))modal.box.append(button('Thử lại',async()=>{try{await request('/api/publishing/schedules/'+encodeURIComponent(item.id)+'/retry',{method:'POST',body:'{}'});modal.close();loadCalendar();}catch(error){toast(error.message);}}));if(['scheduled','blocked'].includes(item.state))modal.box.append(button('Hủy lịch đăng',async()=>{try{await request('/api/publishing/schedules/'+encodeURIComponent(item.id),{method:'DELETE'});modal.close();loadCalendar();toast('Đã hủy lịch đăng.');}catch(error){toast(error.message);}}));}
  labels.connected='Đã kết nối';
  Object.assign(labels,{uploading:'Đang tải lên',processing:'Đang xử lý trên kênh',scheduled_remote:'Kênh đã nhận lịch',needs_attention:'Cần bạn kiểm tra'});
  global.ContentStudio.navigate=navigate;
  installShell();
})(globalThis);

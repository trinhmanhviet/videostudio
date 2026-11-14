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
    // Optional per-video settings for the batch page: style news|case|meme (or Vietnamese names), input idea|script.
    if (item.style != null && String(item.style).trim()) {
      const raw = String(item.style).trim().toLowerCase();
      const style = {news:'news',case:'case',meme:'meme','tin tức':'news','vụ án':'case','meme hài':'meme','hài':'meme'}[raw];
      if (!style) throw Error('Phong cách mục '+(index+1)+' không hợp lệ (news, case hoặc meme).');
      result.style = style;
    }
    if (item.input_mode != null && String(item.input_mode).trim()) {
      const mode = String(item.input_mode).trim().toLowerCase();
      if (!['idea','script'].includes(mode)) throw Error('Nguồn nội dung mục '+(index+1)+' phải là idea hoặc script.');
      result.input_mode = mode;
    }
    if(item.speech_batch_size!=null){const size=Number(item.speech_batch_size);if(!Number.isInteger(size)||size<1||size>512)throw Error('Batch giọng đọc mục '+(index+1)+' phải là số nguyên từ 1 đến 512.');result.speech_batch_size=size;}
    if(item.image_provider!=null){if(!['comfy','flow','chatgpt','meta'].includes(item.image_provider))throw Error('Dịch vụ ảnh mục '+(index+1)+' không hợp lệ.');result.image_provider=item.image_provider;}
    for(const [key,values] of [['speech_engine',['vieneu','khanhtts']],['speech_rhythm',['natural','story']]])if(item[key]!=null){if(!values.includes(item[key]))throw Error('Thiết lập '+key+' của mục '+(index+1)+' không hợp lệ.');result[key]=item[key];}
    if(item.khanh_steps!=null){if(![16,32].includes(item.khanh_steps))throw Error('KhanhTTS hỗ trợ 16 hoặc 32 bước.');result.khanh_steps=item.khanh_steps;}
    if(item.speech_speed!=null){if(typeof item.speech_speed!=='number'||!Number.isFinite(item.speech_speed)||item.speech_speed<.5||item.speech_speed>2)throw Error('Tốc độ đọc phải từ 0,5 đến 2.');result.speech_speed=item.speech_speed;}
    if(item.speech_reference_text!=null){if(typeof item.speech_reference_text!=='string'||!item.speech_reference_text.trim()||item.speech_reference_text.length>10000)throw Error('Lời mẫu tham chiếu không hợp lệ.');result.speech_reference_text=item.speech_reference_text.trim();}
    if(item.voice_id!=null){if(typeof item.voice_id!=='string'||!item.voice_id.trim()||item.voice_id.length>200)throw Error('Giọng đọc không hợp lệ.');result.voice_id=item.voice_id;}
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
  // One raw .txt story per video: a short first line followed by a blank line is the post heading, not narration.
  function parseStoryFile(value, filename) {
    const base = String(filename||'').split('/').pop().split('\\').pop();
    if (/^(INDEX|all_cases.*)\.txt$/i.test(base)) return null;
    const clean = String(value).replace(/^﻿/,'').replace(/\r\n?/g,'\n').trim();
    if (!clean) return null;
    const match = clean.match(/^([^\n]{1,120})\n[\t ]*\n([\s\S]+)$/);
    return match ? {heading:match[1].trim(), text:match[2].trim()} : {heading:'', text:clean};
  }
  function pendingRequest(storage, payload, makeUUID, scope='', pinAutoDuration=false) {
    let identity = JSON.stringify(payload);
    let pending;try {pending=JSON.parse(storage.getItem(PENDING_KEY)||'null');}catch{}
    if(pinAutoDuration&&pending?.key&&(pending.scope||'')===scope){try{const previous=JSON.parse(pending.identity);const seconds=previous.defaults?.duration_seconds;if(Number.isFinite(seconds)&&seconds>0&&payload.defaults){const candidate={...payload,defaults:{...payload.defaults,duration_seconds:seconds}};if(JSON.stringify(candidate)===pending.identity)identity=pending.identity;}}catch{}}
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
    return {job_id:video.job_id,version_id:video.version_id,channel_id:fields.channel_id,title:video.title || '',publish_at:fields.publish_at,caption:fields.caption || '',...(fields.tags?.length?{tags:fields.tags}:{}),...(fields.ai_label===false?{ai_label:false}:{})};
  }
  const PUBLICATION_PLATFORMS = {youtube:'YouTube',facebook:'Facebook Page',tiktok:'TikTok',other:'Khác'};
  const postedReceiptKey = id => 'videostudio.posted-cleanup.v1.'+id;
  function httpsPostURL(value) {
    const raw=String(value||'').trim();if(!/^https:\/\//i.test(raw))return null;
    try{const url=new URL(raw);return url.protocol==='https:'&&url.hostname&&!url.username&&!url.password?url.href:null;}catch{return null;}
  }
  function localPublicationTime(now=new Date()) {return new Date(now.getTime()+7*3600000).toISOString().slice(0,16);}
  function postedCleanupPayload(video, fields) {return {confirm:true};}
  function postedCleanupRequest(storage, jobId, payload, makeUUID) {
    const key=postedReceiptKey(jobId);let saved;try{saved=JSON.parse(storage.getItem(key)||'null');}catch{}
    if(saved?.key&&typeof saved.identity==='string'){try{if(JSON.parse(saved.identity)?.confirm===true)return saved;}catch{}}
    const pending={key:(makeUUID||(()=>global.crypto.randomUUID()))(),identity:JSON.stringify(payload)};
    storage.setItem(key,JSON.stringify(pending));return pending;
  }
  function publicationSummary(entry) {
    const pending=entry.cleanup_state==='pending';
    return {title:entry.title||'Video đã đăng',platform:PUBLICATION_PLATFORMS[entry.platform]||'Khác',channel:entry.channel_name||'',url:httpsPostURL(entry.post_url),cleanup:pending?'Chờ dọn tệp':entry.cleanup_state==='completed'?'Đã xóa job/tệp':'Cần kiểm tra dọn tệp',pending};
  }
  const STAGE_LABELS = {plan:'Chuẩn bị câu chuyện',research:'Tìm hiểu nội dung',script:'Viết kịch bản',speech:'Tạo lời đọc',images:'Tạo hình ảnh',subtitles:'Chuẩn bị phụ đề',music:'Tạo nhạc',render:'Dựng video',verify:'Kiểm tra thành phẩm'};
  const KEPT_LABELS = {script:'Kịch bản',speech:'Lời đọc',images:'Hình ảnh',subtitles:'Phụ đề',music:'Nhạc',render:'Video đã dựng'};
  // Kể truyện runs the same stages with different meaning (no AI writing, no image generation).
  const STORY_STAGE_LABELS = {plan:'Chốt nội dung truyện',research:'Bỏ qua tìm hiểu',script:'Chia cụm đọc',speech:'Tạo lời đọc',images:'Chuẩn bị gameplay',subtitles:'Chuẩn bị phụ đề',music:'Bỏ qua nhạc',render:'Dựng video ngang/dọc',verify:'Kiểm tra và xuất tệp'};
  const STORY_KEPT_LABELS = {script:'Cụm đọc',speech:'Lời đọc',images:'Gameplay',subtitles:'Phụ đề',render:'Video đã dựng'};
  const isStory = item => (item?.job?.request||item?.request||{}).workflow_mode==='story_narration'||item?.style==='story';
  const labelsFor = item => isStory(item) ? STORY_STAGE_LABELS : STAGE_LABELS;
  const keptFor = item => isStory(item) ? STORY_KEPT_LABELS : KEPT_LABELS;
  const QUEUE_ACTIVE = ['running','dispatching','queued','retrying'], QUEUE_WAITING = ['pending','waiting'];
  const QUEUE_ATTENTION = ['failed','awaiting_visual_review','awaiting_flow_account'];
  const RERUN_FIELDS = ['voice_id','speech_batch_size','speech_engine','khanh_steps','speech_rhythm','speech_speed','speech_reference_text','duration_seconds','music_volume','pitch','quality_mode','image_provider','flow_batch_size','meta_batch_size','text_provider','edit_preset','references_enabled','captions_enabled','music_enabled','sfx_enabled'];
  const contentKey = item => String(item.content || '').replace(/\s+/g,' ').trim();
  // items arrive in run order. A failure whose story was queued again later is history, not work to do.
  function queueGroups(items) {
    const latest = new Map();
    for (const item of items) {const key=contentKey(item), current=latest.get(key);if(!current || (item.created||0) >= (current.created||0)) latest.set(key,item);}
    const groups = {active:[],waiting:[],attention:[],done:[]};
    for (const item of items) {
      const superseded = latest.get(contentKey(item)) !== item && !QUEUE_ACTIVE.includes(item.state) && !QUEUE_WAITING.includes(item.state);
      if (superseded) groups.done.push({...item,superseded:true});
      else if(item.job_id&&item.job?.state==='queued')groups.waiting.push(item);
      else if (QUEUE_ACTIVE.includes(item.state) && (item.job_id || item.state !== 'dispatching')) groups.active.push(item);
      else if (QUEUE_WAITING.includes(item.state) || item.state === 'dispatching') groups.waiting.push(item);
      else if (QUEUE_ATTENTION.includes(item.state)) groups.attention.push(item);
      else groups.done.push(item);
    }
    groups.done.sort((a,b)=>(b.updated||b.created||0)-(a.updated||a.created||0));
    return groups;
  }
  function explainQueueError(item) {
    const job = item.job || {}, message = String(item.message || job.error || ''), stage = job.stage;
    const STAGE_LABELS = labelsFor(item), KEPT_LABELS = keptFor(item);
    const rules = [
      [/Gemini/i, 'Gemini không phản hồi đúng cách. Chạy lại bằng ChatGPT.', 'chatgpt'],
      [/delivery_indeterminate/, 'Không chắc ChatGPT đã nhận câu hỏi. Xem tab ChatGPT trong Chrome riêng rồi bấm Thử lại; tool không tự gửi lại để tránh trùng.', 'retry'],
      [/Flow/, 'Google Flow không tạo được ảnh. Chạy lại bằng ComfyUI.', 'comfy'],
      [/browser_unavailable|connector scope|Chrome|CDP/i, 'Chrome riêng chưa sẵn sàng. Kiểm tra Chrome riêng rồi thử lại.', 'retry'],
      [/Service Unavailable|actively refused|WinError|ECONNREFUSED|timed? ?out|Comfy/i, stage === 'images' ? 'ComfyUI không phản hồi. Thử lại khi ComfyUI đã chạy.' : 'Dịch vụ tạm không phản hồi. Thử lại sau ít phút.', 'retry'],
      [/caption area|Utterance exceeds/i, 'Có câu quá dài cho phụ đề. Mở chi tiết video để tách câu rồi thử lại.', 'open'],
      [/naturally (fit|match)|Natural-duration/i, 'Lời đọc không khớp thời lượng đã chọn. Mở chi tiết video để sửa nội dung hoặc thời lượng.', 'open'],
      [/retry budget exhausted|Invalid .*(plan|storyboard)/i, 'Kịch bản chưa qua kiểm tra chất lượng sau nhiều lần viết lại. Thử lại để viết lại.', 'retry'],
      [/Không đọc được nguồn/, 'Không đọc được nguồn tham khảo. Thử lại sau ít phút.', 'retry'],
      [/Silent or clipped audio/i, 'Âm thanh bị câm hoặc rè. Thử lại để tạo lại.', 'retry'],
    ];
    const rule = rules.find(([pattern]) => pattern.test(message));
    const text = rule ? rule[1] : isStory(item) && message ? message : (item.state === 'awaiting_flow_account' ? 'Đang chờ đổi tài khoản tạo ảnh.' : 'Lỗi ở bước '+(STAGE_LABELS[stage] || 'xử lý').toLocaleLowerCase('vi')+'. Thử lại để chạy tiếp.');
    const action = rule ? rule[2] : 'retry';
    const done = Object.keys(KEPT_LABELS).filter(key => key in (job.checkpoints || {})).map(key => KEPT_LABELS[key]);
    const kept = action === 'retry' || action === 'open' ? (done.length ? 'Đã giữ: '+done.join(', ')+'. ' : '')+(stage ? 'Thử lại sẽ chạy tiếp từ bước '+STAGE_LABELS[stage]+'.' : '') : 'Chạy lại từ đầu với cài đặt mới.';
    return {text, action, kept, detail:message};
  }
  // Measured on finished user scripts: Vietnamese narration reads about 4.2 syllables per second.
  const READING_SYLLABLES_PER_SECOND = 4.2;
  const readingProfiles=new Map();
  function setVoiceProfiles(voices) {for(const voice of voices||[])if(voice?.id&&voice.reading_profile)readingProfiles.set(voice.id,voice.reading_profile);}
  function voiceRate(voice,style) {const profile=readingProfiles.get(voice);const rate=Number(profile?.syllables_per_second);return (Number.isFinite(rate)&&rate>=.5&&rate<=12?rate:READING_SYLLABLES_PER_SECOND)*(style==='meme'?1.15:1);}
  function estimateNarrationSeconds(text,voice,style) {const words=(String(text||'').match(/\S+/g)||[]).length;return words?Math.max(5,Math.ceil(words/voiceRate(voice,style))):0;}
  function textMetrics(text) {text=String(text||'');return {words:(text.match(/\S+/g)||[]).length,characters:Array.from(text).length};}
  function autoDuration(style, inputMode) {return style !== 'meme' && inputMode === 'script';}
  function rowAutoDuration(row) {return row.duration_mode==='auto'||(row.duration_mode!=='manual'&&autoDuration(row.style,row.input));}
  function durationForRow(row) {if(Number.isFinite(row.submitted_duration_seconds)&&row.submitted_duration_seconds>0)return row.submitted_duration_seconds;return rowAutoDuration(row)?Math.max(5,estimateNarrationSeconds(row.text,row.voice,row.style)/(Number(row.speech_speed)||1)):Number(row.seconds)*Number(row.unit);}
  function durationText(seconds) {return seconds >= 90 ? Math.round(seconds/60)+' phút' : Math.round(seconds)+' giây';}
  function rerunPayload(item, overrides) {
    const defaults = {};
    for (const key of RERUN_FIELDS) if (item.request && item.request[key] !== undefined) defaults[key] = item.request[key];
    return {project:item.project, style:item.style, input_mode:item.input_mode, defaults:{...defaults, ...overrides}, items:[{text:item.content, title:item.title}]};
  }
  async function collectDroppedFiles(transfer) {
    // Entry handles must be captured synchronously while the drop event is active.
    const entries=Array.from(transfer.items||[]).filter(item=>item.kind==='file').map(item=>item.webkitGetAsEntry?.()).filter(Boolean);
    if(!entries.length)return Array.from(transfer.files||[]);
    const files=[];
    async function visit(entry,parent='') {
      if(entry.isFile){const file=await new Promise((resolve,reject)=>entry.file(resolve,reject));if(/\.(txt|json)$/i.test(file.name)){const path=parent+file.name;files.push({name:file.name,webkitRelativePath:path,text:()=>file.text()});}return;}
      if(entry.isDirectory){const reader=entry.createReader();let batch;do{batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));for(const child of batch)await visit(child,parent+entry.name+'/');}while(batch.length);}
    }
    for(const entry of entries)await visit(entry);
    return files;
  }
  function bindStoryDrop(target,importFiles,onError) {
    let depth=0;
    const hasFiles=event=>Array.from(event.dataTransfer?.types||[]).includes('Files')||event.dataTransfer?.files?.length>0;
    const reset=()=>{depth=0;target.classList.remove('studio-file-dragging');};
    target.addEventListener('dragenter',event=>{if(!hasFiles(event))return;event.preventDefault();depth++;target.classList.add('studio-file-dragging');});
    target.addEventListener('dragover',event=>{if(!hasFiles(event))return;event.preventDefault();event.dataTransfer.dropEffect='copy';});
    target.addEventListener('dragleave',event=>{if(depth&&--depth===0)reset();});
    target.addEventListener('drop',async event=>{if(!hasFiles(event))return;event.preventDefault();event.stopPropagation();reset();try{await importFiles(await collectDroppedFiles(event.dataTransfer));}catch(error){onError(error);}finally{reset();}});
  }
  global.ContentStudio = {parseImport,pendingRequest,resolveScope,discoverScope,scopeForTransport,filterQuery,schedulePayload,postedCleanupPayload,postedCleanupRequest,httpsPostURL,localPublicationTime,publicationSummary,queueGroups,explainQueueError,rerunPayload,estimateNarrationSeconds,autoDuration,durationText,parseStoryFile,bindStoryDrop,collectDroppedFiles,setVoiceProfiles,durationForRow,textMetrics};
  if (typeof document === 'undefined') return;

  const $ = selector => document.querySelector(selector);
  const el = (tag, cls, value) => {const node=document.createElement(tag);if(cls)node.className=cls;if(value!=null)node.textContent=value;return node;};
  const button = (label, action, cls='secondary') => {const node=el('button',cls,label);node.type='button';node.onclick=action;return node;};
  const append = (node,...children) => {node.append(...children.filter(Boolean));return node;};
  const state = {page:'projects',batch:false,batchItems:[],batchRows:[],batchSubmitting:false,queue:null,libraryView:'videos',publication:{q:'',platform:'',page:1,page_size:10},library:{q:'',style:'',project:'',review_state:'',status:'',page:1,page_size:10},libraryData:null,channels:[],schedules:[],week:new Date(),scheduleView:'week',drawerFocus:null,request:0,loading:false};
  const labels = {pending:'Đang chờ',waiting:'Chờ điều kiện chạy',dispatching:'Đang chuẩn bị',queued:'Đang chờ',running:'Đang tạo',retrying:'Đang thử lại',completed:'Hoàn tất',succeeded:'Hoàn tất',failed:'Có lỗi',cancelled:'Đã hủy',skipped:'Đã bỏ qua',awaiting_visual_review:'Chờ duyệt hình',awaiting_flow_account:'Chờ tài khoản tạo ảnh',scheduled:'Đã lên lịch',blocked:'Cần kết nối',publishing:'Đang đăng',published:'Đã đăng',unknown:'Cần kiểm tra',draft:'Bản nháp'};
  const styleLabels = {news:'Tin tức',case:'Vụ án',meme:'Meme hài'};
  const filterStyleLabels = {...styleLabels,story:'Kể truyện'};
  const paths = {story:'M3 5c3-1 6-1 9 1v14c-3-2-6-2-9-1zm18 0c-3-1-6-1-9 1v14c3-2 6-2 9-1z',projects:'M3 6h7l2 2h9v12H3z',batch:'M4 8h12v12H4zm4-4h12v12M10 11v6m-3-3h6',queue:'m3 7 9-5 9 5-9 5zm0 5 9 5 9-5m-18 5 9 5 9-5',library:'M3 4h18v16H3zm7 5 6 3-6 3z',calendar:'M4 5h16v16H4zm0 5h16M8 2v6m8-6v6',resources:'M3 4h18v16H3zm0 12 6-6 5 5 3-3 4 4M15 8h.01',settings:'m9 3 1-2h4l1 2 3 2 2 1v4l-2 1-2 3-1 2h-4l-1-2-3-2-2-1V7l2-1zm3 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8'};
  function icon(name) {const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',paths[name]);svg.append(p);return svg;}
  function localURL(value) {try {const u=new URL(value,location.href);return u.origin===location.origin ? u.href : null;} catch {return null;}}
  async function request(path, options={}, timeoutMs=60000) {
    const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers},signal:AbortSignal.timeout(timeoutMs)});
    const data=await response.json().catch(()=>({detail:'Không đọc được phản hồi. Hãy thử lại.'}));
    if(!response.ok){let detail=data.detail??data.message??data.error;const error=Error(typeof detail==='string'?detail:'Không thể thực hiện thao tác này ('+response.status+').');error.status=response.status;throw error;}
    return data;
  }
  async function postedCleanupWithRecovery(id, pending, progress) {
    const path='/api/jobs/'+encodeURIComponent(id)+'/posted-cleanup',headers={'Idempotency-Key':pending.key},deadline=Date.now()+180000;
    const uncertain=error=>['TimeoutError','AbortError','TypeError'].includes(error.name)||(error.status>=500&&error.status<600);
    for(let attempt=0;attempt<3&&Date.now()<deadline;attempt++){
      try{
        // Reserve time to read the receipt even when the final POST loses its response.
        return await request(path,{method:'POST',headers,body:pending.identity},Math.max(1,Math.min(60000,deadline-Date.now()-5000)));
      }catch(error){if(!uncertain(error))throw error;}
      progress('Đang kiểm tra kết quả đã lưu; yêu cầu của bạn vẫn được giữ nguyên.');
      if(Date.now()<deadline){
        try{
          const result=await request(path,{method:'GET',headers},Math.max(1,Math.min(5000,deadline-Date.now())));
          if(result.ok===true&&result.entry?.id)return result;
        }catch{/* An unavailable receipt check does not change the frozen request. */}
      }
      if(attempt<2&&deadline-Date.now()>1000){
        progress('Đang thử lại yêu cầu đã lưu, vui lòng chờ…');
        await new Promise(resolve=>setTimeout(resolve,1000));
      }else break;
    }
    throw Error('Chưa xác nhận được kết quả. Yêu cầu đã được lưu; hãy thử lại để kiểm tra cùng yêu cầu.');
  }
  function toast(message) {let node=$('#studioToast');if(!node){node=el('div','studio-toast');node.id='studioToast';node.setAttribute('role','status');document.body.append(node);}node.textContent=message;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.hidden=true,6000);}
  function pageHeader(title, description, action) {const root=el('div','studio-page-header');const heading=append(el('div'),el('h2','',title),el('p','',description));append(root,heading,action);return root;}
  function empty(title, description, action) {return append(el('div','studio-empty'),el('strong','',title),el('p','',description),action);}
  function errorNode(root,error) {const node=el('p','studio-error',error.message || String(error));node.setAttribute('role','alert');root.replaceChildren(node,button('Thử lại',()=>refreshPage()));}
  function stateBadge(value) {return el('span','studio-state '+value,labels[value] || value || 'Chưa có trạng thái');}
  function prettyDate(value) {if(!value)return '';const date=new Date(typeof value==='number'?value*1000:value);return Number.isFinite(date.getTime())?date.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'';}

  function installGlobalStoryDrop() {
    bindStoryDrop(document.body,async files=>{navigate('batch',false);loadBatchPage();await global.ContentStudio.importStoryFiles(files);},error=>{const status=$('#studioBatchStatus');if(status)status.textContent=error.message;else toast(error.message);});
  }
  function installShell() {
    document.body.classList.add('studio-ready');
    const sidebar=el('aside','studio-sidebar');sidebar.setAttribute('aria-label','Điều hướng chính');
    const brand=append(el('a','studio-brand'),el('span','studio-brand-mark','▶'),el('span','','VideoStudio'));brand.href='/';sidebar.append(brand);
    const nav=el('nav','studio-nav');
    for(const [name,label] of [['batch','Tạo video'],['story','Kể truyện'],['queue','Hàng đợi'],['library','Kho video'],['calendar','Lịch đăng'],['resources','Kho tài nguyên'],['settings','Cài đặt']]) {
      const node=name==='resources'?el('a'):button('',()=>navigate(name),'');node.dataset.studioNav=name;
      if(name==='resources')node.href='/resources';append(node,icon(name),el('span','',label));nav.append(node);
    }
    sidebar.append(nav);const footer=el('div','studio-sidebar-footer');footer.append(el('p','notice','Không gian sáng tạo của bạn'));sidebar.append(footer);document.body.prepend(sidebar);
    const header=$('main>header');header.classList.add('studio-topbar');$('#globalRefresh').textContent='Làm mới';
    const system=button('',()=>navigate('settings'),'secondary studio-system-button');system.id='studioSystem';append(system,el('span','studio-system-dot'),el('span','','Kết nối & hệ thống'));header.querySelector('.row').prepend(system);
    for(const name of ['batch','story','queue','library','calendar','settings','details']) {const view=el('section','studio-view');view.id='studio-'+name;view.hidden=true;$('main').append(view);}
    const existingGlobalRefresh=$('#globalRefresh').onclick;$('#globalRefresh').onclick=()=>{existingGlobalRefresh?.();if(state.page==='details')state.details?.refresh(true);else refreshPage();};
    const existingOpenProject=global.openProject;
    // Top-level function declarations are shared with the existing classic script.
    global.openProject=function(name,jobId=null){state.detailReturn=state.page==='queue'?'queue':'library';if(jobId&&global.StudioDetails){state.detailJobId=jobId;navigate('details',false);state.details?.destroy?.();state.details=global.StudioDetails.open($('#studio-details'),{jobId,request,onBack:()=>navigate(state.detailReturn),toast,openEditWorkspace:id=>global.openOptionalWorkspace?.(id)});return;}navigate('library');};
    const back=$('#btnBackToGallery'),existingBack=back.onclick;back.textContent='← Quay lại';back.onclick=()=>{existingBack?.();$('#studioNewVideo').hidden=true;navigate(state.detailReturn||'library');};
    const projectHeader=$('#viewWorkspace').firstElementChild;const createButton=button('+ Tạo video',openDrawer);createButton.id='studioNewVideo';const headerActions=el('div','studio-project-actions');const workflowEntry=$('#optionalWorkflowEntry');const consoleToggle=$('#btnToggleInlineLog');append(headerActions,consoleToggle,workflowEntry,createButton);projectHeader.append(headerActions);
    const oldCreate=$('#btnConfirmProjectModal').onclick;$('#btnConfirmProjectModal').onclick=async()=>{await oldCreate();if($('#projectModal').hidden)openDrawer();};
    $('#tabProjects').onclick=()=>navigate('projects');$('#tabClone').onclick=()=>navigate('settings');
    $('#viewGallery h2').textContent='Dự án';$('#viewGallery p').textContent='Tiếp tục câu chuyện của bạn';
    installDrawer();installSettings();
    const requested=new URLSearchParams(location.search).get('view');
    const initial=requested==='videos'?'library':requested;
    navigate(['batch','story','queue','library','calendar','settings'].includes(initial)?initial:'batch',true);
    let ticks=0;setInterval(()=>{if(!document.hidden&&['queue','calendar','details'].includes(state.page)&&!state.loading)refreshPage();updateSystemIndicator();if(!document.hidden&&++ticks%4===0)refreshQueueBadge();},5000);refreshQueueBadge();
    installGlobalStoryDrop();
    updateSystemIndicator();initializeConnection();loadReadingProfiles();
  }
  let readingProfilesLoaded=0,readingProfilesRequest=null;
  async function loadReadingProfiles() {if(readingProfilesRequest||Date.now()-readingProfilesLoaded<60000)return readingProfilesRequest;readingProfilesRequest=(async()=>{try{const data=await request('/api/voices');setVoiceProfiles(data.voices||data.items||[]);readingProfilesLoaded=Date.now();renderBatchRows();syncAutoDuration();}catch{/* A labelled fallback keeps video creation available if timing metadata cannot load. */}finally{readingProfilesRequest=null;}})();return readingProfilesRequest;}
  function navigate(name, reload=true) {
    if(name==='projects')name='library';  // the old project pages are gone
    if(state.page==='batch')state.createController?.save();
    if(state.page==='story'&&name!=='story')state.storyController?.save?.();
    state.details?.setVisible?.(name==='details');
    state.page=name;closeDrawer(false);
    $('#paneProjects').hidden=name!=='projects';$('#paneClone').hidden=true;
    for(const view of document.querySelectorAll('.studio-view'))view.hidden=view.id!=='studio-'+name;
    for(const node of document.querySelectorAll('[data-studio-nav]')) {if(node.dataset.studioNav===(name==='details'?(state.detailReturn||'library'):name))node.setAttribute('aria-current','page');else node.removeAttribute('aria-current');}
    const view=$('#studio-'+name);if(reload&&view&&!view.children.length)view.replaceChildren(el('div','studio-loading','Đang tải…'));
    if(reload)refreshPage();
  }
  async function refreshPage() {if(state.loading){state.refreshPending=true;return;}state.loading=true;const page=state.page;try {if(page==='batch')loadBatchPage();if(page==='story')loadStoryPage();if(page==='queue')await loadQueue();if(page==='details')await state.details?.refresh();if(page==='library')await loadLibrary();if(page==='calendar')await loadCalendar();if(page==='settings')await loadChannels($('#studioSettingsChannels'));}finally{state.loading=false;if(state.refreshPending||state.page!==page){state.refreshPending=false;await refreshPage();}}}
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
    const source=el('div','studio-segments');source.setAttribute('role','group');source.setAttribute('aria-label','Nguồn nội dung');
    for(const [value,label] of [['script','Tôi đã có kịch bản'],['idea','Phát triển ý tưởng']]){const node=button(label,()=>{form.dataset.inputMode=value;syncWorkflow();for(const b of source.children)b.setAttribute('aria-pressed',String(b===node));},'');node.dataset.input=value;node.setAttribute('aria-pressed',String(value==='idea'));source.append(node);}form.prepend(source);form.dataset.inputMode='idea';
    const storyInput=el('input');storyInput.type='file';storyInput.accept='.txt,text/plain';storyInput.hidden=true;
    storyInput.onchange=async()=>{const f=storyInput.files?.[0];storyInput.value='';if(!f)return;const story=parseStoryFile(await f.text(),f.name);if(!story){$('#submitError').textContent='File trống hoặc là file mục lục.';return;}
      source.querySelector('[data-input="script"]')?.click();$('#idea').value=story.text;$('#idea').dispatchEvent(new Event('input',{bubbles:true}));$('#submitError').textContent='';};
    const openStory=button('Mở file truyện (.txt)',()=>storyInput.click());openStory.classList.add('studio-open-story');$('#ideaLabel').before(openStory,storyInput);
    const styleLabel=el('label','','Phong cách');styleLabel.htmlFor='studioStyle';const style=el('select');style.id='studioStyle';for(const [value,label] of Object.entries(styleLabels)){const o=el('option','',label);o.value=value;style.append(o);}style.value='case';style.onchange=syncWorkflow;$('#idea').after(styleLabel,style);
    const importBox=el('div','studio-import');importBox.id='studioImport';importBox.hidden=true;
    const label=el('label','','Nhập nội dung từ file');label.htmlFor='studioImportFile';const file=el('input');file.id='studioImportFile';file.type='file';file.accept='.txt,.json,text/plain,application/json';
    file.onchange=async()=>{if(!file.files?.[0])return;try{state.batchItems=parseImport(await file.files[0].text(),file.files[0].name);renderBatchItems();$('#submitError').textContent='';}catch(error){$('#submitError').textContent=error.message;}finally{file.value='';}};
    append(importBox,label,file,el('p','','TXT: mỗi video cách nhau một dòng trống. JSON: danh sách chuỗi hoặc mục có text, title, duration_seconds.'));
    const rows=el('div');rows.id='studioBatchRows';const add=button('+ Thêm nội dung',()=>{state.batchItems=readBatchItems(false);state.batchItems.push({text:''});renderBatchItems();});append(importBox,rows,add);style.after(importBox);
    const speechLabel=el('label','','Batch giọng đọc (câu mỗi lượt)');speechLabel.htmlFor='studioSpeechBatchSize';
    const speechBatch=el('input');speechBatch.id='studioSpeechBatchSize';speechBatch.type='number';speechBatch.min='1';speechBatch.max='512';speechBatch.step='1';speechBatch.required=true;speechBatch.value=String(rememberedRow().speech_batch_size??256);
    const speechField=append(el('div','studio-speech-batch'),speechLabel,speechBatch);$('#voice').after(speechField);
    speechBatch.onchange=()=>{try{localStorage.setItem('videostudio.batch.last',JSON.stringify({...rememberedRow(),speech_batch_size:Number(speechBatch.value)}));}catch{}};
    const advanced=el('details','studio-advanced');advanced.append(el('summary','','Cài đặt nâng cao'));
    for(const selector of ['label[for=textProvider]','#textProvider','#textProviderNote','#flowBatchSizeLabel','#flowBatchSize','#flowBatchNote','#metaBatchSizeLabel','#metaBatchSize','#musicVolumeLabel','#musicVolume','label[for=createPitch]']){const node=$(selector);if(node)advanced.append(node);}
    advanced.append($('#createPitch').parentElement);$('#limits').before(advanced);
    const durationMode=selectNode([['auto','Tự tính theo giọng'],['manual','Tự nhập thời lượng']],'auto','Cách tính thời lượng',value=>{form.dataset.durationMode=value;syncAutoDuration();});
    durationMode.id='studioDurationMode';$('#durationLabel').after(durationMode);
    $('#limits').textContent='Video dọc 9:16 · Thời lượng được kiểm tra trước khi nhận';
    form.onsubmit=async event=>{
      event.preventDefault();if(form.dataset.submitting==='true')return;$('#submitError').textContent='';
      try {
        const items=state.batch?readBatchItems(true):[normalizeItem({text:$('#idea').value},0)];const voice=$('#voice').value;if(!voice)throw Error('Chọn giọng đọc trước khi tạo video.');
        const duration=form.dataset.autoDuration==='true'?estimateNarrationSeconds($('#idea').value,voice,$('#studioStyle').value):Number($('#duration').value)*Number($('#unit').value);if(!Number.isFinite(duration)||duration<=0)throw Error('Nhập thời lượng hợp lệ.');
        const speechSize=Number($('#studioSpeechBatchSize').value);if(!Number.isInteger(speechSize)||speechSize<1||speechSize>512)throw Error('Batch giọng đọc phải là số nguyên từ 1 đến 512.');
        const payload={project:$('#projectInput').value||'Dự án mặc định',style:$('#studioStyle').value,input_mode:form.dataset.inputMode,defaults:{duration_seconds:duration,voice_id:voice,speech_batch_size:speechSize,text_provider:$('#textProvider').value,image_provider:$('#imageProvider').value,flow_batch_size:Number($('#flowBatchSize').value),...($('#imageProvider').value==='meta'?{meta_batch_size:Number($('#metaBatchSize').value)}:{}),music_volume:Number($('#musicVolume').value)/100,pitch:Number($('#createPitch').value)||0,quality_mode:'quick'},items};
        if(payload.style==='meme'){payload.defaults.image_provider='comfy';payload.defaults.flow_batch_size=1;payload.defaults.music_volume=0;}
        const scope=await factoryScope();const pending=pendingRequest(sessionStorage,payload,undefined,scope||'',form.dataset.autoDuration==='true');
        form.dataset.submitting='true';$('#submit').disabled=true;
        await request('/api/factory/batches',{method:'POST',headers:{'Idempotency-Key':pending.key,...(scope?{'X-Connector-Scope':scope}:{})},body:pending.identity});
        sessionStorage.removeItem(PENDING_KEY);state.batchItems=[];renderBatchItems();closeDrawer();navigate('queue');toast('Đã thêm '+items.length+' video vào hàng đợi.');
      } catch(error) {$('#submitError').textContent=error.message;}
      finally {delete form.dataset.submitting;if(typeof global.enable==='function')global.enable();}
    };
    document.addEventListener('keydown',event=>{if(drawer.hidden)return;if(event.key==='Escape'){event.preventDefault();closeDrawer();}if(event.key==='Tab'){const nodes=[...drawer.querySelectorAll('button,input,select,textarea,summary,a[href]')].filter(n=>!n.disabled&&n.getClientRects().length);if(!nodes.length)return;const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}});
    $('#idea').addEventListener('input',syncAutoDuration);
    $('#voice').addEventListener('change',syncAutoDuration);
    syncWorkflow();
  }
  function syncWorkflow() {const form=$('#create');$('#workflowMode').value=$('#studioStyle').value==='meme'?'meme':form.dataset.inputMode==='script'?'provided_narration':'research';if(typeof global.onWorkflowModeChange==='function')global.onWorkflowModeChange();$('#ideaLabel').textContent=form.dataset.inputMode==='script'?'Kịch bản của bạn':'Ý tưởng của bạn';$('#idea').placeholder=form.dataset.inputMode==='script'?'Nhập lời đọc của video, mỗi dòng là một câu.':'Nhập chủ đề, câu chuyện hoặc điều bạn muốn chia sẻ…';$('#workflowModeNote').textContent=form.dataset.inputMode==='script'?'Giữ nguyên lời đọc bạn nhập; tự chuẩn bị hình ảnh theo từng cảnh.':'Từ ý tưởng của bạn, phát triển kịch bản và hình ảnh theo phong cách đã chọn.';$('#durationControls').hidden=false;$('#durationLabel').textContent='Độ dài mong muốn';$('#unit').disabled=false;$('#duration').required=true;syncAutoDuration();}
  function estimateNote(voice) {return readingProfiles.get(voice)?.source&&readingProfiles.get(voice).source!=='default'?'theo giọng đã đo':'ước tính chung · giọng chưa đủ dữ liệu';}
  function syncAutoDuration() {const form=$('#create');if(!form)return;const eligible=form.dataset.inputMode==='script'&&!state.batch;const selected=form.dataset.durationMode||(autoDuration($('#studioStyle')?.value,form.dataset.inputMode)?'auto':'manual');const auto=eligible&&selected==='auto';form.dataset.autoDuration=String(auto);const mode=$('#studioDurationMode');if(mode){mode.hidden=!eligible;mode.value=selected;}if(!auto){$('#durationControls').hidden=false;$('#duration').required=true;$('#durationLabel').textContent='Độ dài mong muốn';return;}
    const seconds=estimateNarrationSeconds($('#idea').value,$('#voice').value,$('#studioStyle').value);$('#durationControls').hidden=true;$('#duration').required=false;$('#durationLabel').textContent=seconds?'Độ dài: khoảng '+durationText(seconds)+' ('+estimateNote($('#voice').value)+')':'Độ dài: tự tính khi bạn dán kịch bản';}
  function setBatchMode(batch) {state.batch=batch;syncAutoDuration();$('#studioImport').hidden=!batch;$('#idea').hidden=batch;$('#idea').required=!batch;$('#ideaLabel').hidden=batch;for(const node of document.querySelectorAll('[data-batch]'))node.setAttribute('aria-pressed',String(node.dataset.batch===String(batch)));$('#submit').textContent=batch?'Thêm vào hàng đợi':'Tạo video';if(batch&&!state.batchItems.length){state.batchItems=[{text:''}];renderBatchItems();}}
  function openDrawer() {if(!$('#projectInput').value){global.openProjectModal?.();return;}state.drawerFocus=document.activeElement;$('#studioDrawerTitle').textContent=$('#projectInput').value;$('#studioDrawer').hidden=false;$('#studioDrawerBackdrop').hidden=false;document.body.style.overflow='hidden';$('#studioDrawer .studio-drawer-head button').focus();}
  function closeDrawer(restore=true) {if(!$('#studioDrawer'))return;const wasOpen=!$('#studioDrawer').hidden;$('#studioDrawer').hidden=true;$('#studioDrawerBackdrop').hidden=true;document.body.style.overflow='';if(wasOpen&&restore&&state.drawerFocus?.isConnected)state.drawerFocus.focus();}
  function readBatchItems(validate) {const items=[...document.querySelectorAll('.studio-batch-item')].map(node=>({text:node.querySelector('textarea').value,title:node.querySelector('input[type=text]').value,duration_seconds:node.querySelector('input[type=number]').value}));if(!validate)return items;if(!items.length)throw Error('Thêm ít nhất một nội dung trước khi tạo.');return items.map(normalizeItem);}
  function renderBatchItems() {const root=$('#studioBatchRows');root.replaceChildren(el('p','studio-batch-summary',state.batchItems.length+' video · Có thể sửa nội dung và thời lượng từng mục'));
    state.batchItems.forEach((item,index)=>{const row=el('div','studio-batch-item');const title=el('input');title.type='text';title.value=item.title||'';title.placeholder='Tiêu đề video '+(index+1);title.maxLength=200;title.setAttribute('aria-label','Tiêu đề video '+(index+1));const remove=button('×',()=>{state.batchItems=readBatchItems(false);state.batchItems.splice(index,1);renderBatchItems();});remove.setAttribute('aria-label','Xóa mục '+(index+1));const area=el('textarea');area.value=item.text||'';area.maxLength=100000;area.setAttribute('aria-label','Nội dung video '+(index+1));const duration=el('input');duration.type='number';duration.min='0.1';duration.step='0.1';duration.placeholder='Mặc định';duration.value=item.duration_seconds||'';duration.setAttribute('aria-label','Thời lượng riêng video '+(index+1));const label=append(el('label'),el('span','','Thời lượng riêng (giây)'),duration);append(row,append(el('div','studio-batch-item-head'),title,remove),area,label);root.append(row);});
  }

  // ---- Tạo video: one or more rows, each with its own settings and internal project.
  const inputLabels = {idea:'Phát triển ý tưởng',script:'Đã có kịch bản'};
  function voiceOptions() {return [...($('#voice')?.options||[])].filter(o=>o.value).map(o=>[o.value,o.textContent]);}
  let voicePreviewPlayer;
  async function previewVoice(id) {try{const data=await request('/api/voices');const voice=(data.voices||data.items||[]).find(v=>v.id===id);const url=voice?.sample_url&&localURL(voice.sample_url);if(!url){toast('Giọng này chưa có mẫu nghe. Mở Kho tài nguyên → Giọng đọc để tạo bản thử riêng.');return;}voicePreviewPlayer?.pause();voicePreviewPlayer=new Audio(url);await voicePreviewPlayer.play();}catch(error){toast(error.message||'Chưa phát được mẫu giọng.');}}
  // Per-viewer convenience: start new rows with the style, source and voice used last time.
  function rememberedRow() {try{return JSON.parse(localStorage.getItem('videostudio.batch.last')||'{}')||{};}catch{return {};}}
  function rememberRow(row) {state.createController?.rememberSettings(row);try{localStorage.setItem('videostudio.batch.last',JSON.stringify(global.StudioCreate?global.StudioCreate.settingsOf(row):{style:row.style,input:row.input,voice:row.voice,image_provider:row.image_provider,speech_batch_size:row.speech_batch_size??256}));}catch{}}
  function newBatchRow(base={}) {const last=state.batchRows.at(-1)||state.createController?.common||rememberedRow();if(global.StudioCreate)return global.StudioCreate.createRow({...last,voice:last.voice||$('#voice')?.value||voiceOptions()[0]?.[0]||''},base,(text,voice,style,row)=>estimateNarrationSeconds(text,voice,style)/(Number(row?.speech_speed)||1));return {key:global.crypto.randomUUID(),title:'',text:'',style:last.style||'case',input:last.input||'idea',voice:last.voice||$('#voice')?.value||voiceOptions()[0]?.[0]||'',image_provider:last.image_provider||$('#imageProvider')?.value||'comfy',speech_batch_size:last.speech_batch_size??256,seconds:last.seconds||60,unit:last.unit||'1',uncertain:false,error:'',...base};}
  function touchRow(row) {row.error='';if(!row.uncertain){row.key=global.crypto.randomUUID();delete row.submitted_duration_seconds;}}
  function selectNode(options,value,label,onchange) {const node=el('select');node.setAttribute('aria-label',label);for(const [v,text] of options){const o=el('option','',text);o.value=v;node.append(o);}node.value=value;if(node.value!==value&&options.length)node.value=options[0][0];node.onchange=()=>onchange(node.value);return node;}
  function batchRowNode(row,index) {
    const node=el('article','studio-batch-row');if(row.error)node.classList.add('has-error');
    const head=el('div','studio-batch-row-head');const number=el('span','studio-batch-index',String(index+1).padStart(2,'0'));
    const title=el('input');title.type='text';title.maxLength=200;title.value=row.title;title.placeholder='Tên video (để trống: AI tự đặt)';title.setAttribute('aria-label','Tên video '+(index+1));title.oninput=()=>{row.title=title.value;touchRow(row);};
    const copy=button('Nhân bản',()=>{state.batchRows.splice(index+1,0,newBatchRow({...row,key:global.crypto.randomUUID(),title:row.title?row.title+' (2)':'',uncertain:false,error:'',submitted_duration_seconds:undefined}));renderBatchRows();});copy.setAttribute('aria-label','Nhân bản video '+(index+1));
    const remove=button('×',()=>{state.batchRows.splice(index,1);renderBatchRows();});remove.setAttribute('aria-label','Xóa video '+(index+1));
    append(head,number,title,copy,remove);
    const settings=el('div','studio-batch-settings');
    const field=(label,control)=>append(el('label'),el('span','',label),control);
    const style=selectNode(Object.entries(styleLabels),row.style,'Phong cách video '+(index+1),v=>{row.style=v;touchRow(row);syncDuration();syncImage();});
    const input=selectNode(Object.entries(inputLabels),row.input,'Nguồn nội dung video '+(index+1),v=>{row.input=v;touchRow(row);area.placeholder=placeholder();syncDuration();});
    const voices=voiceOptions();if(voices.length&&!voices.some(([v])=>v===row.voice))row.voice=voices[0][0];
    const voice=selectNode(voices.length?voices:[['','Đang tải giọng…']],row.voice,'Giọng đọc video '+(index+1),v=>{row.voice=v;touchRow(row);syncDuration();});
    // The voice list loads after the page; refresh the rows once it is there.
    voice.onfocus=()=>{if(!voices.length&&voiceOptions().length)renderBatchRows();};
    const image=selectNode([['comfy','ComfyUI'],['flow','Google Flow'],['chatgpt','ChatGPT'],['meta','Meta AI']],row.image_provider||'comfy','Dịch vụ tạo ảnh video '+(index+1),value=>{row.image_provider=value;touchRow(row);});
    const speechBatch=el('input');speechBatch.type='number';speechBatch.min='1';speechBatch.max='512';speechBatch.step='1';speechBatch.value=String(row.speech_batch_size??256);speechBatch.setAttribute('aria-label','Batch giọng đọc video '+(index+1));speechBatch.oninput=()=>{row.speech_batch_size=speechBatch.value;touchRow(row);};
    const imageNote=el('small','notice','Meme dùng kho asset có sẵn.');
    const syncImage=()=>{image.disabled=row.style==='meme';imageNote.hidden=row.style!=='meme';};syncImage();
    const seconds=el('input');seconds.type='number';seconds.min='0.1';seconds.step='0.1';seconds.value=row.seconds;seconds.setAttribute('aria-label','Độ dài video '+(index+1));seconds.oninput=()=>{row.seconds=seconds.value;touchRow(row);};
    const unit=selectNode([['1','giây'],['60','phút']],row.unit,'Đơn vị độ dài video '+(index+1),v=>{row.unit=v;touchRow(row);});
    const manual=append(el('div','studio-batch-duration'),seconds,unit),estimate=el('span','studio-batch-estimate');
    const durationMode=selectNode([['auto','Tự tính theo giọng'],['manual','Tự nhập thời lượng']],rowAutoDuration(row)?'auto':'manual','Cách tính thời lượng video '+(index+1),value=>{row.duration_mode=value;touchRow(row);syncDuration();});
    const syncDuration=()=>{const auto=rowAutoDuration(row),value=auto?durationForRow(row):estimateNarrationSeconds(row.text,row.voice,row.style);durationMode.hidden=row.input!=='script';durationMode.value=auto?'auto':'manual';manual.hidden=auto;estimate.hidden=row.input!=='script';estimate.textContent=value?'≈ '+durationText(value)+' ('+estimateNote(row.voice)+')':'Tự tính khi có kịch bản';};
    append(settings,field('Phong cách',style),field('Nguồn nội dung',input),field('Giọng đọc',voice),field('Tạo ảnh bằng',append(el('div'),image,imageNote)),field('Batch giọng đọc (câu/lượt)',speechBatch),field('Độ dài',append(el('div','studio-duration-choice'),durationMode,manual,estimate)));
    const placeholder=()=>row.input==='script'?'Dán lời đọc của video, mỗi dòng là một câu.':'Nhập ý tưởng hoặc câu chuyện…';
    const count=el('small','studio-text-count');count.setAttribute('aria-live','polite');
    const syncCount=()=>{const metrics=textMetrics(row.text);count.textContent=metrics.words.toLocaleString('vi-VN')+' từ · '+metrics.characters.toLocaleString('vi-VN')+' ký tự';};
    const area=el('textarea');area.value=row.text;area.maxLength=100000;area.placeholder=placeholder();area.setAttribute('aria-label','Nội dung video '+(index+1));area.oninput=()=>{row.text=area.value;touchRow(row);syncDuration();syncCount();};syncDuration();syncCount();
    append(node,head,settings,area,count);if(row.error){const error=el('p','studio-error',row.error);error.setAttribute('role','alert');node.append(error);}
    return node;
  }
  function renderBatchRows() {if(state.createController)return state.createController.refresh();const list=$('#studioBatchList');if(!list)return;list.replaceChildren(...state.batchRows.map(batchRowNode));
    $('#studioBatchSubmit').textContent=state.batchRows.length?'Thêm '+state.batchRows.length+' video vào hàng đợi':'Thêm video vào hàng đợi';$('#studioBatchSubmit').disabled=!state.batchRows.length||state.batchSubmitting;}
  function batchPayload(row) {
    const text=row.text.trim();if(!text)throw Error('Chưa có nội dung.');if(!row.voice)throw Error('Chọn giọng đọc.');
    const duration=durationForRow(row);if(!Number.isFinite(duration)||duration<=0)throw Error('Nhập độ dài hợp lệ.');
    const speechSize=Number(row.speech_batch_size??256);if(!Number.isInteger(speechSize)||speechSize<1||speechSize>512)throw Error('Batch giọng đọc phải là số nguyên từ 1 đến 512.');
    const name=(row.title.trim()||text.split('\n')[0]).slice(0,80).trim();
    const provider=row.style==='meme'?'comfy':(row.image_provider||$('#imageProvider')?.value||'comfy');
    const defaults={duration_seconds:duration,voice_id:row.voice,speech_batch_size:speechSize,speech_engine:row.speech_engine||'vieneu',khanh_steps:Number(row.khanh_steps||32),speech_rhythm:row.speech_rhythm||'natural',speech_speed:Number(row.speech_speed)||1,...(row.speech_reference_text?{speech_reference_text:row.speech_reference_text}:{}),text_provider:row.text_provider||$('#textProvider')?.value||'chatgpt',image_provider:provider,flow_batch_size:provider==='flow'?Number(row.flow_batch_size??$('#flowBatchSize')?.value??1):1,...(provider==='meta'?{meta_batch_size:Number(row.meta_batch_size??$('#metaBatchSize')?.value??8)}:{}),music_volume:row.style==='meme'?0:(row.music_volume??Number($('#musicVolume')?.value||0)/100),pitch:row.pitch??(Number($('#createPitch')?.value)||0),quality_mode:row.quality_mode||'quick'};
    for(const field of ['edit_preset','references_enabled','captions_enabled','music_enabled','sfx_enabled'])if(row[field]!=null)defaults[field]=row[field];
    return {project:name,style:row.style,input_mode:row.input,defaults,items:[{text,title:name}],...(row.title.trim()?{}:{auto_name:true})};
  }
  async function submitBatch() {
    if(state.batchSubmitting)return;const status=$('#studioBatchStatus');status.textContent='';
    for(const row of state.batchRows){try{batchPayload(row);row.error='';}catch(error){row.error=error.message;}}
    if(state.batchRows.some(row=>row.error)){renderBatchRows();status.textContent='Sửa các video đang báo lỗi trước khi thêm.';return;}
    state.batchSubmitting=true;renderBatchRows();let added=0;
    try{
      const scope=await factoryScope();
      // One request per video, in order: each video becomes its own project and the queue keeps this order.
      while(state.batchRows.length){const row=state.batchRows[0];status.textContent='Đang thêm video '+(added+1)+'…';
        try{row.submitted_duration_seconds=durationForRow(row);await request('/api/factory/batches',{method:'POST',headers:{'Idempotency-Key':row.key,...(scope?{'X-Connector-Scope':scope}:{})},body:JSON.stringify(batchPayload(row))});rememberRow(row);state.batchRows.shift();added++;}
        catch(error){row.uncertain=error instanceof TypeError||['TimeoutError','AbortError'].includes(error.name);row.error=row.uncertain?'Mất kết nối khi gửi; bấm thêm lại để tiếp tục (không bị tạo trùng).':error.message;break;}}
    }catch(error){status.textContent=error.message;}
    finally{state.batchSubmitting=false;renderBatchRows();}
    if(added)toast('Đã thêm '+added+' video vào hàng đợi.');
    if(!state.batchRows.length&&added){state.batchRows=[newBatchRow()];renderBatchRows();navigate('queue');}
    else if(added)status.textContent='Đã thêm '+added+' video; các video còn lại bên dưới chưa được thêm.';
  }
  async function addStoryFiles(files) {
    const MAX=100;files=files.filter(f=>/\.(txt|json)$/i.test(f.name)).sort((a,b)=>(a.webkitRelativePath||a.name).localeCompare(b.webkitRelativePath||b.name,'vi',{numeric:true}));
    if(!files.length)throw Error('Không có file .txt hoặc .json nào.');
    const blank=state.batchRows.length===1&&!state.batchRows[0].text.trim()&&!state.batchRows[0].title.trim();if(blank)state.batchRows=[];
    let added=0,skipped=0;
    for(const f of files){if(added>=MAX)break;
      if(/\.json$/i.test(f.name)){for(const item of parseImport(await f.text(),f.name)){if(added>=MAX)break;const row=newBatchRow({text:item.text,title:item.title||''});if(item.style)row.style=item.style;if(item.input_mode)row.input=item.input_mode;if(item.image_provider)row.image_provider=item.image_provider;if(item.speech_batch_size!=null)row.speech_batch_size=item.speech_batch_size;if(item.voice_id&&item.voice_id!==row.voice&&!item.speech_reference_text)delete row.speech_reference_text;if(item.voice_id)row.voice=item.voice_id;for(const field of ['speech_engine','khanh_steps','speech_rhythm','speech_speed','speech_reference_text'])if(item[field]!=null)row[field]=item[field];if(item.duration_seconds){row.seconds=item.duration_seconds;row.unit='1';row.duration_mode='manual';}state.batchRows.push(row);added++;}continue;}
      const story=parseStoryFile(await f.text(),f.name);if(!story){skipped++;continue;}
      const row=newBatchRow({text:story.text,title:''});row.input='script';state.batchRows.push(row);added++;}
    if(!state.batchRows.length)state.batchRows=[newBatchRow()];
    renderBatchRows();
    const rest=files.length-added-skipped;
    toast('Đã thêm '+added+' video'+(skipped?', bỏ qua '+skipped+' file trống/mục lục':'')+(rest>0?'. Mỗi lần tối đa '+MAX+' video; chọn tiếp phần còn lại sau.':'.'));
  }
  function loadStoryPage() {
    const root=$('#studio-story');
    if(!global.StoryWorkspace){root.replaceChildren(el('p','studio-error','Chưa tải được màn Kể truyện. Tải lại trang.'));return;}
    if(state.storyController)return state.storyController.refresh();
    state.storyController=global.StoryWorkspace.mount(root,{toast,openQueue:()=>navigate('queue')});
  }
  function loadBatchPage() {loadReadingProfiles();const root=$('#studio-batch');if(global.StudioCreate){if(state.createController)return state.createController.refresh();state.createController=global.StudioCreate.mount(root,{state,voiceOptions,estimateNarrationSeconds:(text,voice,style,row)=>estimateNarrationSeconds(text,voice,style)/(Number(row?.speech_speed)||1),durationText,textMetrics,styleLabels,importFiles:addStoryFiles,submit:submitBatch,toast,collectDroppedFiles,previewVoice});global.ContentStudio.importStoryFiles=files=>state.createController.importFiles(files);return;}if(root.querySelector('[data-batch-page]'))return renderBatchRows();
    if(!state.batchRows.length)state.batchRows=[newBatchRow()];
    const page=el('div');page.dataset.batchPage='true';
    const tools=el('div','studio-batch-tools');
    const file=el('input');file.type='file';file.multiple=true;file.accept='.txt,.json,text/plain,application/json';file.id='studioBatchFile';file.hidden=true;
    const folder=el('input');folder.type='file';folder.multiple=true;const folderSupported='webkitdirectory' in folder;folder.webkitdirectory=true;folder.hidden=true;
    const importError=error=>{$('#studioBatchStatus').textContent=error.message;};
    let importQueue=Promise.resolve();
    const importFiles=files=>{const work=importQueue.catch(()=>{}).then(()=>{if(state.batchSubmitting)throw Error('Đang thêm video vào hàng đợi; chờ hoàn tất rồi thả file.');$('#studioBatchStatus').textContent='';return addStoryFiles(files);});importQueue=work;return work;};
    global.ContentStudio.importStoryFiles=importFiles;
    for(const input of [file,folder])input.onchange=async()=>{try{await importFiles([...input.files||[]]);}catch(error){importError(error);}finally{input.value='';}};
    const drop=button('Thả file / Bấm chọn',()=>file.click(),'secondary studio-file-drop');
    drop.setAttribute('aria-label','Kéo thả một hoặc nhiều file hoặc thư mục, hoặc bấm chọn file');
    drop.title='Thả một hoặc nhiều file TXT/JSON, hoặc cả thư mục. Bấm để chọn một/nhiều file.';
    const pickFolder=button('Chọn thư mục',()=>{if(folderSupported)folder.click();else{importError(Error('Trình duyệt này chưa hỗ trợ chọn thư mục. Hãy chọn một hoặc nhiều file.'));file.click();}});
    append(tools,drop,pickFolder,file,folder,el('p','notice','Thả file hoặc thư mục; trên điện thoại bấm chọn file/thư mục. Mỗi TXT là một video; nội dung hiện bên dưới để sửa trước khi xếp hàng.'));
    const list=el('div','studio-batch-list');list.id='studioBatchList';
    const footer=el('div','studio-batch-footer');const add=button('+ Thêm video',()=>{state.batchRows.push(newBatchRow());renderBatchRows();list.lastElementChild?.querySelector('textarea')?.focus();});
    const submit=button('Thêm video vào hàng đợi',submitBatch,'');submit.id='studioBatchSubmit';const status=el('p','notice');status.id='studioBatchStatus';status.setAttribute('role','status');
    append(footer,add,submit);
    append(page,pageHeader('Tạo video','Nhập một hoặc nhiều kịch bản. Mỗi video có cài đặt riêng; hàng đợi xử lý lần lượt theo thứ tự bên dưới.'),tools,list,footer,status);
    root.replaceChildren(page);renderBatchRows();
    // Voices load after the page; fill rows still showing "Đang tải giọng…" once they arrive.
    const voiceSelect=$('#voice');if(voiceSelect&&global.MutationObserver)new MutationObserver(()=>{if(voiceOptions().length&&document.querySelector('.studio-batch-settings select option[value=""]'))renderBatchRows();}).observe(voiceSelect,{childList:true});
  }

  async function renderNotify(card) {
    // Settings → Báo qua Telegram: the user's own bot sends "video xong / lỗi" to their phone.
    let info;try{info=await request('/api/notify');}catch(error){card.replaceChildren(el('h3','','Báo qua Telegram'),el('p','studio-error',error.message));return;}
    const token=el('input');token.type='password';token.placeholder=info.has_token?'Đã lưu token (nhập lại để đổi)':'Token bot, dạng 123456789:ABC…';token.autocomplete='off';
    const saveToken=button('Lưu token',async()=>{try{await request('/api/notify',{method:'PUT',body:JSON.stringify({token:token.value})});toast('Đã lưu token.');renderNotify(card);}catch(error){toast(error.message);}},'');
    const detect=button('Lấy chat ID tự động',async()=>{try{await request('/api/notify/detect-chat',{method:'POST',body:'{}'});toast('Đã nhận chat ID.');renderNotify(card);}catch(error){toast(error.message);}},'secondary');
    const test=button('Gửi thử',async()=>{try{await request('/api/notify/test',{method:'POST',body:'{}'});toast('Đã gửi, xem Telegram trên điện thoại.');}catch(error){toast(error.message);}},'secondary');
    const on=el('input');on.type='checkbox';on.checked=info.enabled;on.onchange=async()=>{await request('/api/notify',{method:'PUT',body:JSON.stringify({enabled:on.checked})});};
    card.replaceChildren(stHead('Báo qua Telegram',info.configured?(info.enabled?'Đang bật':'Đang tắt'):'Chưa kết nối',info.configured&&info.enabled?'ok':'warn'),
      el('p','notice','Tool nhắn vào Telegram khi video làm xong hoặc bị lỗi, và khi biên tập xong một truyện.'),
      append(el('details','st-help'),el('summary','','Cách lấy token'),el('p','','Trong Telegram mở @BotFather → /newbot → đặt tên → nhận token, dán vào đây và Lưu. Sau đó nhắn một chữ bất kỳ cho bot vừa tạo rồi bấm "Lấy chat ID tự động".')),
      append(el('div','studio-output-row'),token,saveToken),append(el('div','studio-drive-row'),detect,test),
      stSwitch(info.enabled,'Bật thông báo','Tắt thì tool không nhắn gì.',async(value,input)=>{try{await request('/api/notify',{method:'PUT',body:JSON.stringify({enabled:value})});renderNotify(card);}catch(error){input.checked=!value;toast(error.message);}}),
      el('p','notice',info.configured?'Đã kết nối, chat ID '+info.chat+'.':(info.has_token?'Đã có token, còn thiếu chat ID.':'Chưa kết nối.')));
  }
  function stHead(title,pill,tone){const head=el('div','st-head');head.append(el('h3','',title));if(pill)head.append(el('span','st-pill'+(tone?' is-'+tone:''),pill));return head;}
  function stSize(bytes){bytes=Math.max(0,Number(bytes)||0);return bytes>=2**30?(bytes/2**30).toFixed(2).replace('.',',')+' GB':bytes>=10*2**20?Math.round(bytes/2**20)+' MB':bytes>=2**20?(bytes/2**20).toFixed(1).replace('.',',')+' MB':Math.round(bytes/1024)+' KB';}
  function stWait(seconds){if(seconds==null)return '';const m=Math.round(seconds/60);return seconds<60?'còn dưới 1 phút':m<60?`còn khoảng ${m} phút`:`còn khoảng ${Math.floor(m/60)} giờ ${m%60} phút`;}
  function stBar(value,total,cls){const bar=el('div','st-bar'+(cls?' '+cls:''));const fill=el('span');fill.style.width=(total>0?Math.min(100,value/total*100):0).toFixed(1)+'%';bar.append(fill);bar.setAttribute('role','progressbar');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');bar.setAttribute('aria-valuenow',String(total>0?Math.round(value/total*100):0));return bar;}
  function stSwitch(checked,label,hint,onchange){const box=el('label','st-switch');const input=el('input');input.type='checkbox';input.checked=!!checked;input.onchange=()=>onchange(input.checked,input);append(box,input,el('span','st-knob'),append(el('span','st-switch-text'),el('strong','',label),hint?el('small','',hint):null));return box;}
  const drivePhases={scan:'Đang tìm video cần đưa lên',hash:'Đang tính mã kiểm tra',upload:'Đang tải lên',verify:'Đang so khớp với Drive',delete:'Đang xoá bản trên máy'};
  function renderDriveSync(panel,sync,info){
    // Live sync panel: overall bytes, the video and file in hand, step, speed and time left; then the last finished videos.
    const parts=[];
    if(sync?.running){
      const pct=sync.bytes_total>0?Math.min(100,Math.round(sync.bytes_done/sync.bytes_total*100)):0;
      parts.push(append(el('div','st-sync-top'),el('strong','','Đang đưa video lên Drive'),el('span','st-sync-pct',sync.phase==='scan'?'…':pct+'%')));
      parts.push(stBar(sync.bytes_done,sync.bytes_total,'is-main'));
      const facts=[sync.jobs_total?`Video ${Math.min(sync.jobs_done+1,sync.jobs_total)}/${sync.jobs_total}`:'',sync.bytes_total?`${stSize(sync.bytes_done)} / ${stSize(sync.bytes_total)}`:'',(sync.average||sync.speed)>1024?stSize(sync.average||sync.speed)+'/giây':'',stWait(sync.eta)].filter(Boolean);
      parts.push(el('p','st-sync-facts',facts.join(' · ')||drivePhases[sync.phase]||''));
      const file=sync.file;
      if(file){
        const box=el('div','st-sync-file');
        append(box,append(el('div','st-sync-step'),el('span','st-dot'),el('span','',(drivePhases[sync.phase]||'Đang xử lý')+(file.count>1?` · tệp ${file.index}/${file.count}`:''))),
          el('strong','st-sync-job',file.job||file.project),el('span','st-sync-name',file.name),
          stBar(file.done,file.size,sync.phase==='hash'?'is-soft':''),el('small','',`${stSize(file.done)} / ${stSize(file.size)}`));
        parts.push(box);
      }else if(sync.phase){parts.push(el('p','st-muted',drivePhases[sync.phase]||''));}
    }else{
      const last=sync?.result;
      parts.push(append(el('div','st-sync-top'),el('strong','','Đồng bộ'),el('span','st-pill is-ok','Đang chờ')));
      parts.push(el('p','st-sync-facts',last?`Lần chạy gần nhất ${new Date((sync.last||0)*1000).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})}: đưa lên ${last.uploaded} video (${stSize(last.bytes)})${last.failed?`, ${last.failed} video lỗi`:''}.`:'Tool tự kiểm tra mỗi phút và đưa video mới làm xong lên Drive.'));
    }
    if(sync?.recent?.length){
      const list=el('ul','st-recent');
      for(const item of sync.recent)list.append(append(el('li'),el('span','st-check','✓'),el('span','st-recent-name',item.job),el('small','',stSize(item.size))));
      parts.push(el('small','st-label','Vừa xong'),list);
    }
    for(const f of info?.failures||[])parts.push(el('p','studio-error',`Chưa đưa được ${f.title?'“'+f.title+'”':'một video'} lên Drive: ${f.message}`));
    const run=button(sync?.running?'Đang chạy…':'Đồng bộ ngay',async()=>{run.disabled=true;try{await request('/api/drive/sync',{method:'POST',body:'{}'});pollDrive(panel,info,true);}catch(error){toast(error.message);run.disabled=false;}},'secondary');
    run.disabled=!!sync?.running;
    parts.push(append(el('div','st-actions'),run,el('span','st-muted',`Đã lưu ${info.uploaded_videos} video · ${String(info.uploaded_gb).replace('.',',')} GB trên Drive`)));
    panel.replaceChildren(...parts);
  }
  function pollDrive(panel,info,soon){
    clearTimeout(panel._timer);const token=panel._token=(panel._token||0)+1;
    const tick=async()=>{
      if(!panel.isConnected||token!==panel._token)return;
      let sync;try{sync=await request('/api/drive/progress');}catch{panel._timer=setTimeout(tick,10000);return;}
      if(token!==panel._token)return;
      if(panel._wasRunning&&!sync.running){panel._wasRunning=false;const card=panel.closest('.studio-drive');if(card){renderDrive(card);return;}}
      panel._wasRunning=sync.running;
      renderDriveSync(panel,sync,info);
      panel._timer=setTimeout(tick,sync.running?1200:document.hidden?30000:8000);
    };
    panel._timer=setTimeout(tick,soon?400:0);
  }
  async function renderDrive(card) {
    // Settings → Google Drive: several accounts; finished videos move there (first account with room, then the next).
    if(!card.childElementCount)card.replaceChildren(stHead('Google Drive'),el('p','st-muted','Đang đọc…'));
    let info;try{info=await request('/api/drive/status');}catch(error){card.replaceChildren(stHead('Google Drive','Lỗi','bad'),el('p','studio-error',error.message));return;}
    const help=append(el('details','st-help'),el('summary','','Cách hoạt động'),
      el('p','','Video xong được đưa lên Drive vào thư mục Video/vu-an/<vụ án>, Video/truyen-doc/<tên truyện>… Tool so mã kiểm tra (MD5) với bản trên máy rồi mới xoá bản trên máy. Tool không bao giờ xoá gì trên Drive.'),
      el('p','','Tài khoản đứng đầu danh sách được dùng trước; sắp đầy thì tự sang tài khoản kế tiếp.'),
      el('p','','Địa chỉ chuyển hướng cần có trong OAuth client (Web application): '+location.origin+'/api/drive/oauth/callback'));
    if(!info.has_client){
      const file=el('input');file.type='file';file.accept='.json,application/json';file.hidden=true;
      file.onchange=async()=>{try{const raw=JSON.parse(await file.files[0].text());await request('/api/drive/client',{method:'PUT',body:JSON.stringify(raw)});toast('Đã lưu OAuth client.');renderDrive(card);}catch(error){toast(error.message);}finally{file.value='';}};
      card.replaceChildren(stHead('Google Drive','Chưa thiết lập','warn'),el('p','st-muted','Tải tệp OAuth client JSON tạo trong Google Cloud Console (đã bật Google Drive API).'),file,button('Chọn tệp OAuth client JSON',()=>file.click(),''),help);return;
    }
    const n=info.accounts.length;
    const list=el('div','st-accounts');
    for(const [i,a] of info.accounts.entries()){
      const row=el('div','st-account');
      const used=a.total_gb?a.total_gb-a.free_gb:0;
      const up=button('↑',async()=>{const ids=info.accounts.map(x=>x.id);ids.splice(i-1,0,ids.splice(i,1)[0]);await request('/api/drive/accounts/order',{method:'POST',body:JSON.stringify({ids})});renderDrive(card);},'st-icon');up.disabled=i===0;up.title='Dùng trước';up.setAttribute('aria-label','Đưa '+a.email+' lên đầu');
      const remove=button('Gỡ',async()=>{if(!confirm('Gỡ '+a.email+' khỏi tool? Tệp trên Drive vẫn giữ nguyên.'))return;await request('/api/drive/accounts/'+encodeURIComponent(a.id),{method:'DELETE'});renderDrive(card);},'st-link');
      append(row,append(el('div','st-account-top'),el('span','st-avatar',String(a.email||'?')[0].toUpperCase()),append(el('div','st-account-name'),el('strong','',a.email),el('small','',i===0?'Dùng trước':'Dự phòng '+i)),n>1?up:null,remove));
      if(a.ok&&a.total_gb){row.append(stBar(used,a.total_gb,used/a.total_gb>.9?'is-warn':''),el('small','st-muted',`Còn trống ${String(a.free_gb).replace('.',',')} GB / ${String(a.total_gb).replace('.',',')} GB`));}
      else row.append(el('small',a.ok?'st-muted':'studio-error',a.ok?'Dung lượng không giới hạn':'Lỗi: '+(a.error||'')));
      list.append(row);
    }
    if(!n)list.append(el('p','st-muted','Chưa có tài khoản nào. Thêm một tài khoản Google để bắt đầu.'));
    const add=button('+ Thêm tài khoản',async()=>{try{const r=await request('/api/drive/accounts/start',{method:'POST',body:'{}'});window.open(r.url,'_blank','noopener');toast('Đăng nhập Google trong tab mới, xong quay lại đây.');}catch(error){toast(error.message);}},'secondary');
    const set=(key)=>async(value,input)=>{try{await request('/api/drive/settings',{method:'PATCH',body:JSON.stringify({[key]:value})});}catch(error){input.checked=!value;toast(error.message);}};
    const switches=append(el('div','st-switches'),
      stSwitch(info.auto_upload,'Tự đưa video xong lên Drive','Video làm xong được đưa lên trong vòng một phút.',set('auto_upload')),
      stSwitch(info.delete_local,'Xoá bản trên máy sau khi lên Drive','Chỉ xoá khi tệp trên Drive khớp mã kiểm tra.',set('delete_local')),
      stSwitch(info.include_old,'Đưa cả video làm trước khi kết nối','Bật để dọn ổ đĩa: tool đưa dần cả video cũ lên.',set('include_old')),
      stSwitch(info.delete_after_post,'Xoá trên Drive sau khi đăng xong','Khi mọi bài đăng của video đã công khai, tool chuyển bản trên Drive vào Thùng rác (khôi phục được trong 30 ngày).',set('delete_after_post')));
    const panel=el('div','st-sync');
    const columns=append(el('div','st-drive-cols'),append(el('div','st-drive-left'),el('small','st-label','Tài khoản'),list,add,el('small','st-label','Tự động'),switches),panel);
    card.replaceChildren(stHead('Google Drive',n?`${n} tài khoản`:'Chưa có tài khoản',n?'ok':'warn'),columns,help);
    renderDriveSync(panel,info.sync,info);pollDrive(panel,info);
  }
  async function renderOutputRoot(card) {
    // Settings → Nơi lưu video: new videos go to <folder>\<project>\…; earlier videos stay where they are.
    card.replaceChildren(stHead('Nơi lưu video'),el('p','notice','Đang đọc…'));
    let info;try{info=await request('/api/settings/output-root');}catch(error){card.replaceChildren(el('h3','','Nơi lưu video'),el('p','studio-error',error.message));return;}
    const input=el('input');input.type='text';input.value=info.root;input.setAttribute('aria-label','Thư mục lưu video');input.placeholder='Ví dụ D:\\Videos';
    const drives=el('div','studio-drive-list');
    for(const drive of info.drives||[]){const chip=button(`${drive.drive} · ${drive.free_gb} GB trống`,()=>{input.value=drive.drive+'\\Videos';input.focus();},'secondary');chip.title=`Dùng ${drive.drive}\\Videos`;drives.append(chip);}
    const save=button('Lưu nơi lưu',async()=>{save.disabled=true;try{const next=await request('/api/settings/output-root',{method:'PUT',body:JSON.stringify({path:input.value})});toast('Video mới sẽ lưu vào '+next.root+'.');renderOutputRoot(card);}catch(error){toast(error.message);}finally{save.disabled=false;}},'');
    const free=info.free_gb==null?'':` · còn trống ${info.free_gb} GB / ${info.total_gb} GB`;
    card.querySelector('.st-head').append(el('span','st-pill is-ok',info.free_gb==null?'Đã chọn':`còn ${info.free_gb} GB`));
    append(card,el('p','notice',`Đang lưu vào ${info.root}${free}.`),
      el('p','notice','Video mới lưu theo cấu trúc <thư mục>\\<tên dự án hoặc tên truyện>\\…, giống hiện tại. Video đã làm trước đó giữ nguyên chỗ cũ, vẫn xem, tải và xoá được trong Kho video.'),
      drives,append(el('div','studio-output-row'),input,save));
    card.querySelector('.notice').remove();
    if(info.previous?.length)card.append(el('p','notice','Thư mục cũ vẫn được theo dõi: '+info.previous.join(', ')));
  }
  async function openLogs() {
    // Latest job events (newest first) and the ComfyUI GPU log, read-only.
    const modal=dialog('Nhật ký');const out=el('pre','st-log','Đang đọc…');const reload=button('Làm mới',()=>load(),'secondary');
    append(modal.box,out,append(el('div','st-actions'),reload));
    const load=async()=>{try{const d=await request('/api/system/logs');const lines=(d.events||[]).map(ev=>`[${new Date(ev.at*1000).toLocaleTimeString('vi-VN')}] ${String(ev.job||'').slice(0,8)} · ${ev.stage||'INIT'} · ${ev.event}: ${ev.detail??''}`);
      out.textContent=(lines.length?lines.join('\n'):'Chưa có sự kiện nào.')+(d.comfy_log?'\n\n— ComfyUI —\n'+d.comfy_log:'');}catch(error){out.textContent='Không đọc được nhật ký: '+error.message;}};
    load();
  }
  function installSettings() {const root=$('#studio-settings');root.classList.add('st-page');root.append(pageHeader('Cài đặt','Lưu trữ, đăng bài, thông báo và kết nối tạo video.'));
    const group=(title,...cards)=>{const box=el('section','st-group');box.append(el('h2','st-group-title',title),append(el('div','st-grid'),...cards));root.append(box);return box;};
    const connection=$('#viewWorkspace>.layout>aside');connection.classList.add('studio-connection','st-card');connection.hidden=false;connection.querySelector('h2').textContent='Kết nối tạo video';
    // The long list of runtime checks folds into one line: "14/14 đạt"; it opens by itself when something fails.
    const checks=$('#checks'),connector=$('#connectorStatus');
    if(checks&&!checks.closest('.st-checks')){
      const fold=el('details','st-checks st-help');const summary=el('summary','','Kiểm tra hệ thống');fold.append(summary);checks.before(fold);fold.append(checks);if(connector)fold.append(connector);
      const count=()=>{const pass=checks.querySelectorAll('.check.pass').length,bad=checks.querySelectorAll('.check.error').length;
        summary.textContent=pass+bad?(bad?`Kiểm tra hệ thống: ${bad} mục cần xử lý`:`Kiểm tra hệ thống: ${pass}/${pass} mục đạt`):'Kiểm tra hệ thống';fold.classList.toggle('is-bad',bad>0);if(bad)fold.open=true;};
      new MutationObserver(count).observe(checks,{childList:true,subtree:true});count();
      for(const note of connection.querySelectorAll(':scope>p.notice'))if(note!==connector)note.hidden=true;
    }
    const channels=el('section','card st-card st-wide');channels.id='studioSettingsChannels';channels.append(el('h3','','Tài khoản đăng video'));
    const storage=el('section','card st-card studio-output-root');storage.id='studioSettingsOutput';renderOutputRoot(storage);
    const driveCard=el('section','card st-card studio-drive st-wide');driveCard.id='studioSettingsDrive';renderDrive(driveCard);
    const notifyCard=el('section','card st-card studio-notify');notifyCard.id='studioSettingsNotify';renderNotify(notifyCard);
    const tools=el('section','card st-card');tools.id='studioSettingsTools';const resourceLink=el('a','','Mở kho tài nguyên →');resourceLink.href='/resources';
    append(tools,stHead('Công cụ & trợ giúp'),el('p','notice','Khi gặp lỗi, xem nhật ký hoặc kiểm tra hệ thống trong thẻ Kết nối tạo video.'),append(el('div','st-actions'),resourceLink),append(el('div','st-actions'),button('Xem nhật ký',openLogs,'secondary')));
    group('Lưu trữ video',driveCard,storage);
    group('Đăng bài và thông báo',channels,notifyCard);
    group('Tạo video',connection,tools);
  }

  function clock(seconds) {const s=Math.max(0,Math.round(Number(seconds)||0));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),r=String(s%60).padStart(2,'0');return h?h+':'+String(m).padStart(2,'0')+':'+r:String(m).padStart(2,'0')+':'+r;}
  function queueMatches(item) {const f=state.queueFilter;if(f.style&&item.style!==f.style)return false;const q=f.q.trim().toLocaleLowerCase('vi');if(!q)return true;return [item.title,item.content,item.project].some(v=>String(v||'').toLocaleLowerCase('vi').includes(q));}
  function queueControls(root) {
    const controls=el('div','studio-queue-controls');controls.dataset.queueControls='true';const chips=el('div','studio-chips');chips.setAttribute('role','group');chips.setAttribute('aria-label','Lọc theo phong cách');
    for(const [value,label] of [['','Tất cả'],...Object.entries(filterStyleLabels)]){const chip=button(label,()=>{state.queueFilter.style=value;for(const node of chips.children)node.setAttribute('aria-pressed',String(node===chip));renderQueueList(root);});chip.className='studio-chip';chip.setAttribute('aria-pressed',String(state.queueFilter.style===value));chips.append(chip);}
    const search=el('input','studio-queue-search');search.type='search';search.placeholder='Tìm video, kịch bản...';search.setAttribute('aria-label','Tìm video trong hàng đợi');search.value=state.queueFilter.q;search.oninput=()=>{state.queueFilter.q=search.value;renderQueueList(root);};
    return append(controls,chips,search);
  }
  const providerLabels = {chatgpt:'ChatGPT',gemini:'Gemini'};
  function confirmAction(title,text,label,action) {const modal=dialog(title);const go=button(label,async()=>{go.disabled=true;try{await action();modal.close();}catch(error){go.disabled=false;toast(error.message);}},'');append(modal.box,el('p','notice',text),append(el('div','studio-dialog-actions'),button('Thôi',modal.close),go));}
  function queueThumb(item) {const thumb=el('div','studio-queue-thumb');const src=item.thumbnail&&localURL(item.thumbnail);if(src){const img=el('img');img.src=src;img.alt='';img.loading='lazy';thumb.append(img);}else thumb.append(el('span','','▷'));return thumb;}
  function queueMeta(item) {const req=item.job?.request||item.request||item.defaults||{};return [filterStyleLabels[item.style],req.voice_id,req.speech_engine==='khanhtts'?'KhanhTTS':'VieNeu'].filter(Boolean).join(' · ');}
  function queueRow(item,kind,number,waiting) {
    const STAGE_LABELS = labelsFor(item), KEPT_LABELS = keptFor(item), stageLabel = stage => STAGE_LABELS[stage]||'Đang xử lý';
    const row=el('article','studio-queue-row studio-queue-'+kind);
    const body=append(el('div','studio-queue-body'),el('h3','',item.title||item.content?.slice(0,70)||'Video'));
    const actions=el('div','studio-queue-actions');const open=()=>global.openProject(item.project||'Dự án mặc định',item.job_id);
    if(kind==='active'){
      const stages=Object.keys(STAGE_LABELS),step=stages.indexOf(item.job?.stage);
      body.append(el('p','',[queueMeta(item),item.job?.stage?'Bước '+(step+1)+'/'+stages.length+' · '+stageLabel(item.job.stage):'Đang chuẩn bị'].filter(Boolean).join(' · ')));
      const progress=el('progress','studio-progress');progress.max=100;const value=Number(item.job?.progress||0);progress.value=value<=1?value*100:value;progress.setAttribute('aria-label','Tiến độ video');body.append(progress);
      const current=item.job?.latest_event?.message||item.job?.latest_event?.detail;if(current)body.append(el('p','studio-queue-current',current));
      const kept=Object.keys(KEPT_LABELS).filter(key=>key in (item.job?.checkpoints||{}));if(kept.length)body.append(el('p','studio-queue-kept','Đã lưu: '+kept.map(key=>KEPT_LABELS[key]).join(', ')));
      if(item.job_id)actions.append(button('Chi tiết',open));
      if(item.job?.cancel){body.append(el('p','notice','Đang hủy… video sẽ dừng sau vài giây.'));const wait=button('Đang hủy…',()=>{});wait.disabled=true;actions.append(wait);}
      else actions.append(button('Dừng video',()=>confirmAction('Dừng video đang chạy?','Các bước đã xong được giữ lại; bạn có thể tiếp tục sau trong mục Đã xong.','Dừng video',()=>queueAction(item,'cancel'))));
    } else if(kind==='waiting'){
      body.append(el('p','',[queueMeta(item),item.state==='waiting'?'Chờ điều kiện chạy':''].filter(Boolean).join(' · ')));
      const pos=waiting.indexOf(item);for(const [delta,label,hint] of [[-1,'↑','Chạy sớm hơn'],[1,'↓','Chạy muộn hơn']]){const b=button(label,()=>reorderQueue(item.id,delta));b.disabled=Boolean(item.job_id)||pos+delta<0||pos+delta>=waiting.length;b.title=item.job_id?'Video đã được nhận; chỉ đổi thứ tự mục chưa bắt đầu':hint;b.setAttribute('aria-label',hint);actions.append(b);}
      if(item.job_id)actions.append(button('Chi tiết',open),button('Dừng video',()=>queueAction(item,'cancel')));else actions.append(button('Bỏ qua',()=>queueAction(item,'skip')));
    } else if(kind==='attention'){
      const why=explainQueueError(item);body.append(el('p','',queueMeta(item)),el('p','studio-error',why.text));
      if(item.retry_requested)body.append(el('p','notice','Sẽ thử lại ngay sau video đang chạy.'));else if(why.kept){const kept=Object.keys(KEPT_LABELS).filter(key=>key in (item.job?.checkpoints||{})).map(key=>KEPT_LABELS[key]);const note=['chatgpt','comfy'].includes(why.action)&&item.job_id?(kept.length?'Đã giữ: '+kept.join(', ')+'. ':'')+'Tiếp tục sẽ dùng các bước hợp lệ đã có. Tạo lượt mới là một tác vụ riêng.':why.kept;body.append(el('p','notice',note));}
      if(why.detail){const more=el('details','studio-queue-detail');state.queueDetailOpen??=new Set();more.open=state.queueDetailOpen.has(item.id);more.ontoggle=()=>{if(more.open)state.queueDetailOpen.add(item.id);else state.queueDetailOpen.delete(item.id);};append(more,el('summary','','Chi tiết'),el('code','',why.detail));body.append(more);}
      if(!item.retry_requested){
        if(item.job_id)actions.append(button('Tiếp tục từ bước '+(STAGE_LABELS[item.job?.stage]||'bị gián đoạn').toLocaleLowerCase('vi'),()=>queueAction(item,'retry'),''));
        else actions.append(button('Thử lại',()=>queueAction(item,'retry'),''));
        if(why.action==='chatgpt')actions.append(button('Tạo lượt mới bằng ChatGPT',()=>rerunItem(item,{text_provider:'chatgpt'})));
        else if(why.action==='comfy')actions.append(button('Tạo lượt mới bằng ComfyUI',()=>rerunItem(item,{image_provider:'comfy',flow_batch_size:1})));
      }
      if(item.job_id)actions.append(button('Chi tiết',open));
      if(item.job_id&&!item.retry_requested)actions.append(button('Xóa',()=>confirmAction('Xóa video lỗi?','Video này và các file tạm của nó sẽ bị xóa khỏi máy. Không hoàn tác được.','Xóa',()=>deleteQueueJob(item))));
    } else {
      body.append(el('p','',[queueMeta(item),item.superseded?'Đã chạy lại':labels[item.state]||item.state].filter(Boolean).join(' · ')));
      if(item.job_id&&item.state==='completed')actions.append(button('Chi tiết',open));
      else if(!item.superseded&&['skipped','cancelled'].includes(item.state))actions.append(button(item.state==='cancelled'&&item.job_id?'Tiếp tục':'Đưa lại vào hàng',()=>queueAction(item,'retry')));
    }
    const duration=el('div','studio-queue-duration',item.duration_seconds?clock(item.duration_seconds):'—');duration.title='Độ dài';
    return append(row,el('div','studio-queue-number',number?String(number):''),queueThumb(item),body,duration,actions);
  }
  function queueSection(title,count,rows,cls) {const section=el('section','studio-queue-section '+(cls||''));append(section,el('h3','studio-queue-section-title',title+(count!=null?' · '+count:'')),...rows);return section;}
  function renderQueueList(root,force=true) {
    const all=state.queue?.items||[];
    // Skip identical refreshes so open menus, hover and focus survive the 5-second poll.
    const signature=JSON.stringify([state.queue?.paused,state.queueFilter,all.map(i=>[i.id,i.state,i.updated,i.retry_requested,i.message,i.thumbnail,i.duration_seconds,i.job?.stage,i.job?.progress,i.job?.cancel])]);
    if(!force&&signature===state.queueSignature&&root.querySelector('.studio-queue-list'))return;state.queueSignature=signature;const groups=queueGroups(all.filter(queueMatches));
    const list=el('div','studio-queue-list');list.setAttribute('aria-label','Danh sách video trong hàng đợi');
    if(!all.length)list.append(empty('Hàng đợi đang trống','Dùng Tạo video để thêm một hoặc nhiều kịch bản.',button('Tạo video',()=>navigate('batch'))));
    else{
      list.append(queueSection('Đang chạy',null,groups.active.length?groups.active.map(i=>queueRow(i,'active')):[el('p','notice',state.queue.paused?'Hàng đợi đang tạm dừng.':groups.waiting.length?'Video kế tiếp sẽ bắt đầu trong giây lát.':'Không có video nào đang chạy.')],'running'));
      if(groups.attention.length)list.append(queueSection('Cần xử lý',groups.attention.length,groups.attention.map(i=>queueRow(i,'attention')),'attention'));
      if(groups.waiting.length)list.append(queueSection('Chờ chạy',groups.waiting.length,groups.waiting.map((i,n)=>queueRow(i,'waiting',n+1,groups.waiting)),'waiting'));
      if(groups.done.length){const done=el('details','studio-queue-section studio-queue-done');done.open=!!state.queueDoneOpen;done.append(el('summary','studio-queue-section-title','Đã xong · '+groups.done.length));const fill=()=>{if(done.children.length===1)done.append(...groups.done.slice(0,60).map(i=>queueRow(i,'done')));};if(done.open)fill();done.ontoggle=()=>{state.queueDoneOpen=done.open;if(done.open)fill();};list.append(done);}
    }
    const old=root.querySelector('.studio-queue-list');if(old)old.replaceWith(list);else root.append(list);
  }
  async function loadQueue() {const root=$('#studio-queue');try {const data=await request('/api/factory/queue');state.queue=data;state.queueFilter??={style:'',q:''};updateQueueBadge(data);
      const header=pageHeader('Hàng đợi',data.paused?'Đang tạm dừng. Video đang chạy vẫn làm cho xong.':'Chạy lần lượt. Bước đã hoàn tất được giữ lại.',button(data.paused?'Tiếp tục hàng đợi':'Tạm dừng sau video này',async()=>{try{await request('/api/factory/queue/pause',{method:'POST',body:JSON.stringify({paused:!data.paused})});await loadQueue();}catch(error){toast(error.message);}}));
      // Keep the controls (and a half-typed search) across the 5-second refresh; rebuild only the data parts.
      const controls=root.querySelector(':scope>[data-queue-controls]'),oldHeader=root.querySelector(':scope>.studio-page-header');
      const fresh=!(controls&&oldHeader);if(!fresh){if(oldHeader.dataset.paused!==String(data.paused))oldHeader.replaceWith(header);}else root.replaceChildren(header,controls||queueControls(root));header.dataset.paused=String(data.paused);
      let layout=root.querySelector('.studio-queue-layout');if(!layout){layout=append(el('div','studio-queue-layout'),el('section','studio-queue-main'),el('aside','studio-queue-context'));const oldList=root.querySelector('.studio-queue-list');if(oldList)layout.firstElementChild.append(oldList);root.append(layout);}
      const groups=queueGroups(data.items||[]);let summary=root.querySelector('.studio-queue-summary');if(!summary){summary=el('div','studio-queue-summary');root.insertBefore(summary,root.querySelector(':scope>[data-queue-controls]')||layout);}summary.replaceChildren(...[['Đang chạy',groups.active.length],['Chờ chạy',groups.waiting.length],['Cần xử lý',groups.attention.length],['Hoàn tất',groups.done.length]].map(([label,count])=>append(el('div'),el('strong','',count),el('span','',label))));
      renderQueueList(layout.firstElementChild,fresh);renderQueueContext(layout.lastElementChild,groups,data.paused);
    }catch(error){errorNode(root,error);}}
  function renderQueueContext(root,groups,paused) {const item=groups.active[0]||groups.attention[0],job=item?.job||{},cp=job.checkpoints||{};root.replaceChildren(el('h3','',item?'Tiến độ video đang chạy':'Hàng đợi'));if(item){root.firstElementChild.textContent=groups.active.length?'Tiến độ video đang chạy':'Video cần xử lý';root.append(el('p','notice',item.title||'Video'));const stages=el('ol','studio-job-steps');for(const [key,label] of Object.entries(STAGE_LABELS)){const node=el('li',key in cp?'done':job.stage===key?'current':'',label);if(key in cp)node.prepend(el('span','','✓ '));stages.append(node);}root.append(stages);}else root.append(el('p','notice','Chưa có video đang chạy. Thêm kịch bản ở Tạo video để bắt đầu.'));root.append(el('p','studio-queue-help',paused?'Hàng đợi đã tạm dừng; video hiện tại vẫn chạy đến hết.':'Video chạy lần lượt để giữ ổn định tài nguyên.'),el('h3','','Kết nối'),button('Mở bảng hệ thống',()=>navigate('settings')),button('Mở Kho video →',()=>navigate('library')));}
  function updateQueueBadge(data) {const node=document.querySelector('[data-studio-nav="queue"]');if(!node)return;const count=queueGroups(data.items||[]).attention.length;let badge=node.querySelector('.studio-nav-badge');if(!count){badge?.remove();node.removeAttribute('aria-label');return;}if(!badge){badge=el('span','studio-nav-badge');node.append(badge);}badge.textContent=String(count);badge.title=count+' video cần xử lý';node.setAttribute('aria-label','Hàng đợi, '+count+' video cần xử lý');}
  async function refreshQueueBadge() {if(state.page==='queue')return;try{updateQueueBadge(await request('/api/factory/queue'));}catch{}}
  function stageLabel(stage) {return STAGE_LABELS[stage]||'Đang xử lý';}
  async function queueAction(item,action) {try{const scope=action==='retry'?await factoryScope():resolveScope(location.pathname);const result=await request('/api/factory/items/'+encodeURIComponent(item.id)+'/'+action,{method:'POST',headers:scope?{'X-Connector-Scope':scope}:{},body:'{}'});if(action==='retry'&&result.retry_requested)toast('Sẽ thử lại ngay sau video đang chạy.');await loadQueue();}catch(error){toast(error.message);}}
  async function rerunItem(item,overrides) {try{const scope=await factoryScope();await request('/api/factory/batches',{method:'POST',headers:{'Idempotency-Key':'rerun-'+item.id+'-'+Object.entries(overrides).map(([k,v])=>k+'='+v).join('&'),...(scope?{'X-Connector-Scope':scope}:{})},body:JSON.stringify(rerunPayload(item,overrides))});toast('Đã xếp lại vào hàng đợi.');await loadQueue();}catch(error){toast(error.message);}}
  async function deleteQueueJob(item) {await request('/api/jobs/'+encodeURIComponent(item.job_id)+'/delete',{method:'POST',body:JSON.stringify({delete_files:true,confirm:true})});toast('Đã xóa video lỗi.');await loadQueue();}
  async function reorderQueue(id,delta) {const ids=queueGroups(state.queue?.items||[]).waiting.filter(i=>!i.job_id&&i.state!=='dispatching').map(i=>i.id);const index=ids.indexOf(id);if(index<0||index+delta<0||index+delta>=ids.length)return;[ids[index],ids[index+delta]]=[ids[index+delta],ids[index]];try{await request('/api/factory/queue/reorder',{method:'POST',body:JSON.stringify({item_ids:ids})});await loadQueue();}catch(error){toast(error.message);}}

  function filterControl(label,name,options) {const wrapper=el('label');wrapper.append(el('span','',label));const node=name==='q'||name==='project'?el('input'):el('select');node.name=name;if(node.tagName==='INPUT'){node.type=name==='q'?'search':'text';node.placeholder=name==='q'?'Tìm video…':'Tên dự án';node.value=state.library[name];}else for(const [value,title] of options){const option=el('option','',title);option.value=value;option.selected=state.library[name]===value;node.append(option);}node.onchange=()=>{state.library[name]=node.value;state.library.page=1;loadLibrary();};if(node.tagName==='INPUT')node.oninput=()=>{clearTimeout(node.searchTimer);node.searchTimer=setTimeout(()=>node.onchange(),350);};wrapper.append(node);return wrapper;}
  function libraryHeader(root) {
    root.replaceChildren(pageHeader('Kho video','Xem video và lưu dấu bài đã đăng.'));
    const tabs=el('div','studio-calendar-toolbar');tabs.setAttribute('aria-label','Nội dung Kho video');
    for(const [value,label] of [['videos','Video'],['history','Sổ đăng'],['facebook','Facebook Reels']]){const tab=button(label,()=>{state.libraryView=value;return loadLibrary();});tab.setAttribute('aria-pressed',String(state.libraryView===value));tabs.append(tab);}root.append(tabs);
  }
  async function loadFacebookReels(refresh=false) {
    // How the Page's Reels are doing: views, comments, likes, copyright check, the caption check and (with read_insights) reach.
    const root=$('#studio-library'),ticket=++state.request;
    if(!root.querySelector('.st-reels'))libraryHeader(root);
    let box=root.querySelector('.st-reels');if(!box){box=el('section','st-reels');root.append(box);}
    if(!box.childElementCount)box.append(el('div','studio-loading','Đang đọc Trang Facebook…'));
    let data;try{data=await request('/api/publishing/facebook/reels'+(state.reelsChannel?'?channel_id='+encodeURIComponent(state.reelsChannel)+(refresh?'&refresh=true':''):(refresh?'?refresh=true':'')));}
    catch(error){if(ticket!==state.request)return;box.replaceChildren(el('p','studio-error',error.message),button('Mở cài đặt',()=>navigate('settings'),'secondary'));return;}
    if(ticket!==state.request)return;state.reelsChannel=data.channel_id;
    const num=v=>typeof v==='number'?v.toLocaleString('vi-VN'):'—';
    const when=new Date(data.checked_at*1000).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'});
    const reload=button('Làm mới',()=>loadFacebookReels(true),'secondary');
    const dashboard=el('a','button secondary','Xem kiếm tiền (Professional Dashboard)');dashboard.href='https://www.facebook.com/professional_dashboard';dashboard.target='_blank';dashboard.rel='noopener';
    const head=append(el('div','st-reels-head'),append(el('div'),el('strong','',data.page.name),el('span','st-muted',` · ${num(data.page.followers)} người theo dõi · ${data.items.length} Reels gần nhất · đọc lúc ${when}`)),append(el('div','st-actions'),reload,dashboard));
    const notes=[el('p','st-muted','Facebook không cho tool đọc trạng thái kiếm tiền: Reels nào bị gắn "nên xem" thì mở Professional Dashboard để kiểm tra.')];
    if(!data.insights)notes.push(el('p','st-muted','Chưa có quyền read_insights nên chưa thấy lượt tiếp cận và thời gian xem.'));
    const list=el('div','st-reels-list');
    const verdictText={fix:'Lời đăng nên sửa',review:'Lời đăng nên xem lại',safe:'Lời đăng ổn'};
    for(const item of data.items){
      const card=el('article','st-reel'+(item.low?' is-low':''));
      const thumb=el('a','st-reel-thumb');thumb.href=item.url||'#';thumb.target='_blank';thumb.rel='noopener';
      if(item.picture){const img=el('img');img.src=item.picture;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';thumb.append(img);}
      if(item.length)thumb.append(el('span','studio-video-length',clock(item.length)));
      const first=String(item.caption||'').split('\n').find(Boolean)||'(không có lời đăng)';
      const stats=el('div','st-reel-stats');
      const stat=(label,value)=>stats.append(append(el('span'),el('strong','',value),el('small','',label)));
      stat('lượt xem',num(item.views));stat('người xem',num(item.post_views));stat('bình luận',num(item.comments));stat('thích',num(item.likes));
      if(item.insights.reach!=null)stat('tiếp cận',num(item.insights.reach));
      if(item.insights.avg_watch_ms!=null)stat('xem TB',clock(item.insights.avg_watch_ms/1000));
      if(item.insights.new_followers!=null)stat('theo dõi mới',num(item.insights.new_followers));
      const tags=el('div','st-reel-tags');
      if(item.low)tags.append(el('span','st-pill is-warn','Lượt xem thấp hẳn so với Trang: nên xem trạng thái'));
      tags.append(el('span','st-pill '+(item.check.verdict==='fix'?'is-bad':item.check.verdict==='review'?'is-warn':'is-ok'),verdictText[item.check.verdict]));
      tags.append(el('span','st-pill '+(item.copyright==='match'?'is-bad':item.copyright==='clear'?'is-ok':''),item.copyright==='match'?'Trùng bản quyền':item.copyright==='clear'?'Bản quyền ổn':'Đang kiểm tra bản quyền'));
      if(!item.published)tags.append(el('span','st-pill is-warn','Chưa công khai'));
      if(item.tool)tags.append(el('span','st-pill','Đăng bằng tool'));
      const body=append(el('div','st-reel-body'),el('strong','st-reel-title',first),el('small','st-muted',item.created?new Date(item.created).toLocaleString('vi-VN',{dateStyle:'short',timeStyle:'short'}):''),stats,tags);
      const words=item.check.issues.filter(i=>i.level!=='note');
      if(words.length){const more=el('details','st-help');more.append(el('summary','',`${words.length} chỗ trong lời đăng`));
        for(const issue of words)more.append(el('p','',`“${issue.text}” · ${issue.label}`+(issue.replace?.length?` · thử: ${issue.replace.slice(0,2).join(', ')}`:'')));body.append(more);}
      append(card,thumb,body);list.append(card);
    }
    if(!data.items.length)list.append(el('p','st-muted','Trang chưa có Reels nào.'));
    box.replaceChildren(head,...notes,list);
  }
  async function loadPublicationHistory() {
    const root=$('#studio-library'),ticket=++state.request;
    try{const data=await request('/api/publication-history?'+filterQuery(state.publication));if(ticket!==state.request)return;
      const focused=document.activeElement,focusName=root.contains(focused)?focused.name:null,selection=typeof focused?.selectionStart==='number'?focused.selectionStart:null;
      libraryHeader(root);root.append(el('p','notice','Các bài bạn xác nhận đã đăng vẫn được lưu ở đây sau khi xóa job và tệp. Giờ Việt Nam (UTC+7).'));
      const filters=el('div','studio-filters');
      for(const [name,label,options] of [['q','Tìm bài đã đăng',null],['platform','Nền tảng',[['','Mọi nền tảng'],...Object.entries(PUBLICATION_PLATFORMS)]],['page_size','Số bài mỗi trang',[['10','10'],['20','20'],['30','30']]]]){
        const wrapper=el('label'),control=el(name==='q'?'input':'select');control.name='history_'+name;
        if(name==='q'){control.type='search';control.placeholder='Tìm tên video hoặc kênh…';control.value=state.publication.q;}
        else for(const [value,title] of options){const option=el('option','',title);option.value=value;option.selected=String(state.publication[name])===value;control.append(option);}
        control.onchange=()=>{state.publication[name]=name==='page_size'?Number(control.value):control.value;state.publication.page=1;loadPublicationHistory();};
        if(name==='q')control.oninput=()=>{clearTimeout(control.searchTimer);control.searchTimer=setTimeout(()=>control.onchange(),350);};
        append(wrapper,el('span','',label),control);filters.append(wrapper);
      }
      root.append(filters);const list=el('div','studio-schedule-list');
      if(!data.items?.length)list.append(empty('Chưa có bài đã đăng','Sau khi đăng video, chọn Đã đăng & dọn để lưu thông tin và xóa job/tệp.'));
      for(const entry of data.items||[])list.append(publicationRow(entry));root.append(list);
      const pages=Math.max(1,data.total_pages||1);state.publication.page=data.page||state.publication.page;
      const previous=button('← Trước',()=>{state.publication.page--;loadPublicationHistory();});previous.disabled=state.publication.page<=1;
      const next=button('Sau →',()=>{state.publication.page++;loadPublicationHistory();});next.disabled=state.publication.page>=pages;
      root.append(append(el('div','studio-pagination'),previous,el('span','','Trang '+state.publication.page+' / '+pages+' · '+(data.total||0)+' bài'),next));
      if(focusName){const replacement=root.querySelector('[name="'+focusName+'"]');replacement?.focus();if(selection!=null)replacement?.setSelectionRange?.(selection,selection);}
    }catch(error){if(ticket===state.request){libraryHeader(root);const message=el('p','studio-error',error.message);message.setAttribute('role','alert');root.append(message,button('Thử lại',()=>loadPublicationHistory()));}}
  }
  function publicationDate(value) {const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'Chưa có ngày đăng';}
  function publicationDestinations(entry) {
    const seen=new Set(),result=[];
    for(const post of [entry,...(Array.isArray(entry.posts)?entry.posts:[])]){
      if(!post||typeof post!=='object')continue;
      const platform=String(post.platform||'other'),channel=String(post.channel_name||'').trim(),url=httpsPostURL(post.post_url),timestamp=Date.parse(post.published_at);
      const key=JSON.stringify([platform,channel,url,Number.isFinite(timestamp)?timestamp:String(post.published_at||'')]);if(seen.has(key))continue;seen.add(key);
      result.push({platform:PUBLICATION_PLATFORMS[platform]||'Khác',channel,url,published_at:post.published_at});
    }return result;
  }
  function publicationRow(entry) {
    const when=publicationDate(entry.published_at);
    const summary=publicationSummary(entry),body=append(el('div'),el('h3','',summary.title),el('p','',when+' · '+summary.platform+(summary.channel?' · '+summary.channel:'')),el('p',summary.pending?'notice':'',summary.cleanup));
    if(summary.url){const link=el('a','button secondary','Mở bài đã đăng');link.href=summary.url;link.target='_blank';link.rel='noopener noreferrer';body.append(link);}
    for(const post of publicationDestinations(entry).slice(1)){
      const destination=append(el('div','studio-video-meta'),el('p','',publicationDate(post.published_at)+' · '+post.platform+(post.channel?' · '+post.channel:'')));
      if(post.url){const link=el('a','button secondary','Mở bài trên '+post.platform);link.href=post.url;link.target='_blank';link.rel='noopener noreferrer';destination.append(link);}body.append(destination);
    }
    const row=append(el('article','studio-schedule-row'),body);
    if(summary.pending){const error=el('p','studio-error');error.setAttribute('role','alert');body.append(el('p','notice','Thông tin đăng đã lưu. Tệp đang chờ dọn; thử lại sẽ tiếp tục xóa job/tệp.'),error);
      const retry=button('Thử dọn job/tệp',async()=>{if(retry.disabled)return;retry.disabled=true;error.textContent='';try{await request('/api/publication-history/'+encodeURIComponent(entry.id)+'/cleanup',{method:'POST',body:JSON.stringify({confirm:true})});await loadLibrary();}catch(e){error.textContent=e.message;}finally{retry.disabled=false;}});row.append(retry);
    }return row;
  }
  async function loadLibrary() {if(state.libraryView==='history')return loadPublicationHistory();if(state.libraryView==='facebook')return loadFacebookReels();const root=$('#studio-library');const ticket=++state.request;try{const data=await request('/api/factory/videos?'+filterQuery(state.library));if(ticket!==state.request)return;state.libraryData=data;
      const focused=document.activeElement;const focusName=root.contains(focused)?focused.name:null;const selection=focusName&&typeof focused.selectionStart==='number'?focused.selectionStart:null;
      libraryHeader(root);
      const filters=el('div','studio-filters');append(filters,filterControl('Tìm kiếm','q'),filterControl('Phong cách','style',[['','Mọi phong cách'],...Object.entries(filterStyleLabels)]),filterControl('Duyệt video','review_state',[['','Tất cả'],['pending','Chưa duyệt'],['approved','Đã duyệt']]));root.append(filters);
      const grid=el('div','studio-video-grid');if(!data.items?.length)grid.append(empty('Chưa có video phù hợp','Thành phẩm đã kiểm tra sẽ xuất hiện ở đây. Bạn có thể đổi bộ lọc hoặc tạo video mới.',button('Tạo video',()=>navigate('batch'))));for(const video of data.items||[])grid.append(videoCard(video));root.append(grid);
      const pages=Math.max(1,data.total_pages||1);const previous=button('← Trước',()=>{state.library.page--;loadLibrary();});previous.disabled=state.library.page<=1;const next=button('Sau →',()=>{state.library.page++;loadLibrary();});next.disabled=state.library.page>=pages;root.append(append(el('div','studio-pagination'),previous,el('span','','Trang '+state.library.page+' / '+pages+' · '+(data.total||0)+' video'),next));
      if(focusName){const replacement=root.querySelector('[name="'+focusName+'"]');replacement?.focus();if(selection!=null)replacement?.setSelectionRange?.(selection,selection);}
    }catch(error){if(ticket===state.request){libraryHeader(root);const message=el('p','studio-error',error.message);message.setAttribute('role','alert');root.append(message,button('Thử lại',()=>loadLibrary()));}}}
  document.addEventListener('click',event=>{for(const menu of document.querySelectorAll('details.studio-more[open]'))if(!menu.contains(event.target))menu.open=false;});
  function versionFileURL(video,version) {if(version?.drive)return version.url;return '/api/factory/videos/'+encodeURIComponent(video.job_id||video.id)+'/versions/'+encodeURIComponent(version.version_id||version.id)+'/file';}
  function openVideo(video,version) {
    const modal=dialog(video.title||'Video');modal.box.classList.add('studio-dialog-wide','studio-video-dialog');
    const portrait=version?versionFileURL(video,version):localURL(video.output_url),wide=video.wide_url&&localURL(video.wide_url);
    const formats=[portrait&&{label:'Dọc 9:16',src:portrait,cls:'portrait'},wide&&{label:'Ngang 16:9',src:wide,cls:'landscape'}].filter(Boolean);
    const preview=el('div','studio-video-preview'),figure=el('figure','video-cell');
    const player=el('video');player.controls=true;player.preload='metadata';player.setAttribute('aria-label','Xem video');
    const caption=el('span'),download=el('a','button secondary','Tải video');download.download='';
    append(figure,player,append(el('figcaption'),caption,download));
    const tabs=el('div','studio-video-formats');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Định dạng video');
    const choose=format=>{player.pause();player.src=format.src;modal.box.dataset.format=format.cls;figure.className='video-cell '+format.cls;caption.textContent=format.label;download.href=format.src;download.textContent='Tải '+format.label;for(const tab of tabs.children)tab.setAttribute('aria-pressed',String(tab.dataset.format===format.cls));};
    for(const format of formats){const tab=button(format.label,()=>choose(format),'secondary');tab.dataset.format=format.cls;tabs.append(tab);}
    if(formats.length>1)preview.append(tabs);if(formats.length){preview.append(figure);choose(formats[0]);}
    modal.onClose=()=>player.pause();modal.box.append(preview);
    if(video.drive_files?.length){const drive=el('div','studio-drive-files');drive.append(el('p','notice','Video đã lưu trên Google Drive (đã xoá khỏi máy). Tải về hoặc mở trên Drive:'));for(const file of video.drive_files){const row=el('div','studio-drive-row');const get=el('a','button secondary','Tải '+file.name);get.href=file.download;get.download=file.name;row.append(get);if(file.link){const open=el('a','button secondary','Mở trên Drive');open.href=file.link;open.target='_blank';open.rel='noopener';row.append(open);}drive.append(row);}modal.box.append(drive);}
    if(typeof global.socialPanel==='function')modal.box.append(global.socialPanel({id:video.job_id||video.id}));
    modal.box.append(button('Đã đăng & dọn',()=>{modal.close();openPostedCleanup(video);}));
  }
  function videoCard(video) {
    const id=video.job_id||video.id;const card=el('article','studio-video-card');
    const versions=Array.isArray(video.versions)?video.versions:[];let version=versions.find(v=>v.approved)||versions[0];
    const thumb=el('button','studio-video-thumb');thumb.type='button';thumb.setAttribute('aria-label','Xem '+(video.title||'video'));thumb.onclick=()=>openVideo(video,version);
    const src=video.thumbnail&&localURL(video.thumbnail);if(src){const img=el('img');img.src=src;img.alt='';img.loading='lazy';thumb.append(img);}else thumb.append(el('span','','▷'));
    const badge=el('span');const length=el('span','studio-video-length',video.duration_seconds?clock(video.duration_seconds):'');append(thumb,badge,length);
    const meta=[video.project&&video.project!==video.title?video.project:'',filterStyleLabels[video.style]].filter(Boolean).join(' · ');
    const body=append(el('div','studio-video-body'),el('h3','',video.title||'Video'),meta?el('div','studio-video-meta',meta):null);
    if(versions.length>1){const select=el('select');select.setAttribute('aria-label','Bản xuất của '+(video.title||'video'));for(const [i,v] of versions.entries()){const option=el('option','','Bản '+(versions.length-i)+(v.latest?' (mới nhất)':'')+(v.approved?' · đã duyệt':''));option.value=v.version_id||v.id;option.selected=v===version;select.append(option);}select.onchange=()=>{version=versions.find(v=>(v.version_id||v.id)===select.value);render();};body.append(select);}
    const actions=el('div','studio-video-actions');
    const render=()=>{
      const approved=version?.approved===true;badge.className='studio-state '+(approved?'completed':'pending');badge.textContent=approved?'Đã duyệt':'Chưa duyệt';
      actions.replaceChildren(button('Xem',()=>openVideo(video,version)));
      // "Đăng / hẹn giờ": opens the post form; a version not yet approved is approved first (posting it is the approval).
      const post=version?button('Đăng / hẹn giờ',async()=>{
        if(!version.approved){
          if(!global.confirm('Đăng bản video này? Tool sẽ ghi bản này là bản đã duyệt để đăng.'))return;
          try{await request('/api/factory/videos/'+encodeURIComponent(id)+'/approve',{method:'POST',body:JSON.stringify({version_id:version.version_id||version.id,sha256:version.sha256})});version.approved=true;render();}catch(error){toast(error.message);return;}
        }
        openSchedule({job_id:id,version_id:version.version_id||version.id,approved:true,title:video.title,style:video.style});
      },''):null;
      if(version?.drive){badge.className='studio-state completed';badge.textContent='☁ Trên Drive';actions.append(post);if(version.drive_link){const open=el('a','button secondary','Mở trên Drive');open.href=version.drive_link;open.target='_blank';open.rel='noopener';actions.append(open);}actions.append(button('Đã đăng & dọn',()=>openPostedCleanup(video)));return;}
      if(post)actions.append(post);
      actions.append(button('Đã đăng & dọn',()=>openPostedCleanup(video)));
      const more=el('details','studio-more');const list=el('div','studio-more-list');more.append(el('summary','','⋯'),list);more.querySelector('summary').setAttribute('aria-label','Thao tác khác');
      list.append(button('Chi tiết',()=>global.openProject(video.project||'Dự án mặc định',id)));
      if(isStory(video))list.append(button('Dựng lại khung hình',async()=>{
        if(!global.confirm('Dựng lại video này với khung hình, ảnh nền, ảnh bìa và kiểu nén hiện tại của truyện?\nGiữ nguyên lời kể, giọng đọc đã có và đúng đoạn gameplay cũ; bản cũ vẫn giữ.'))return;
        try{await request('/api/story/jobs/'+encodeURIComponent(id)+'/rerender',{method:'POST',body:'{}'});toast('Đã xếp hàng dựng lại. Xem ở Hàng đợi.');}catch(error){toast(error.message);}
      }));
      if(version){const pack=el('a','button secondary','Tải trọn bộ (video + phụ đề)');pack.href='/api/factory/videos/'+encodeURIComponent(id)+'/pack?'+filterQuery({version_id:version.version_id||version.id,include:'video,captions,sidecar'});pack.download='';list.append(pack);}
      if(video.style==='meme'){const edit=el('a','button secondary','Chỉnh sửa');edit.href='/meme-editor?job='+encodeURIComponent(id);list.append(edit);}else list.append(button('Chỉnh sửa',()=>global.openOptionalWorkspace?.(id)));
      list.append(button('Xóa',()=>openDeleteVideo(video),'secondary studio-danger'));actions.append(more);
    };
    render();append(body,actions);append(card,thumb,body);return card;
  }

  async function loadChannels(root) {
    if(!root)return;
    try {
      const data=await request('/api/publishing/channels');
      state.channels=Array.isArray(data)?data:data.items||[];state.channelDefaults=data.defaults||{};state.channelsAt=Date.now();state.calendarSignature=null;
      root.replaceChildren(el('h3','','Tài khoản đăng video'));
      const grid=el('div','studio-channel-grid');
      for(const channel of state.channels) {
        const card=el('div','studio-channel');
        append(card,el('h3','',channel.name||channel.platform||'Kênh đăng'),stateBadge(channel.connected===true?'connected':'blocked'),el('p','',channel.error||channel.message||(channel.connected?'Tài khoản đã kết nối.':'Cần kết nối tài khoản và cấp quyền đăng video.')));
        const real=String(channel.id||'').includes(':');
        card.querySelector('h3').before(el('small','st-label',channel.platform==='facebook'?'Facebook Page':channel.platform==='youtube'?'YouTube':channel.platform||''));
        if(real&&channel.platform==='youtube')card.append(el('small','st-muted','Mã kênh: '+channel.id.split(':')[1]));
        if(real&&root.id==='studioSettingsChannels')card.append(button('Gỡ kênh',async()=>{
          if(!global.confirm('Gỡ kênh "'+(channel.name||channel.id)+'" khỏi tool?\nKhông xoá gì trên YouTube/Facebook; muốn dùng lại thì bấm Kết nối.'))return;
          try{await request('/api/publishing/channels/'+encodeURIComponent(channel.id)+'/remove',{method:'POST',body:'{}'});toast('Đã gỡ kênh.');loadChannels(root);}catch(error){toast(error.message);}
        },'st-link'));
        grid.append(card);
      }
      if(!state.channels.some(channel=>channel.connected))root.append(el('p','notice','Chưa có kênh sẵn sàng đăng. Kết nối YouTube hoặc Facebook Page để bắt đầu.'));
      root.append(grid);
      const connected=state.channels.filter(channel=>channel.connected===true&&String(channel.id).includes(':'));
      if(root.id==='studioSettingsChannels'&&connected.length){
        // Each kind of video can go to its own channel: the post form picks it by itself (still changeable there).
        const box=el('div','st-defaults');box.append(el('small','st-label','Kênh mặc định khi đăng'));
        const platforms=[['youtube','YouTube · bản ngang'],['facebook','Facebook Reels · bản dọc']].filter(([p])=>connected.some(c=>c.platform===p));
        const table=el('div','st-default-table');table.style.setProperty('--cols',platforms.length);
        table.append(el('span',''),...platforms.map(([,label])=>el('small','st-muted',label)));
        for(const [style,label] of Object.entries(filterStyleLabels)){
          table.append(el('span','st-default-kind',label));
          for(const [platform,platformLabel] of platforms){
            const select=el('select');select.setAttribute('aria-label',platformLabel+' cho '+label);select.append(new Option('Không đăng',''));
            for(const channel of connected.filter(c=>c.platform===platform))select.append(new Option(channel.name||channel.id,channel.id));
            select.value=state.channelDefaults[style]?.[platform]||'';
            select.onchange=async()=>{const next=JSON.parse(JSON.stringify(state.channelDefaults||{}));next[style]={...(next[style]||{}),[platform]:select.value};
              try{const result=await request('/api/publishing/default-channels',{method:'PUT',body:JSON.stringify(next)});state.channelDefaults=result.defaults||{};toast('Đã lưu kênh cho '+label+'.');}
              catch(error){select.value=state.channelDefaults[style]?.[platform]||'';toast(error.message);}};
            table.append(select);
          }
        }
        box.append(table,el('p','st-muted','Khi bấm "Đăng / hẹn giờ", tool tick sẵn các kênh này: YouTube nhận bản ngang 16:9, Facebook nhận bản dọc làm Reels. Bỏ tick trong form nếu lần đó không muốn đăng.'));
        box.append(el('p','st-muted','Kết nối thêm kênh YouTube: bấm Kết nối YouTube, khi Google hỏi thì chọn đúng kênh (tài khoản thương hiệu).'));
        root.append(box);
      }
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
  function shortDate(date,year) {return String(date.getDate()).padStart(2,'0')+'/'+String(date.getMonth()+1).padStart(2,'0')+(year?'/'+date.getFullYear():'');}
  function channelStrip() {
    const strip=el('div','studio-channel-strip');
    for(const channel of state.channels)strip.append(el('span','studio-channel-pill '+(channel.connected===true?'ok':'off'),(channel.name||channel.platform||'Kênh')+(channel.connected===true?' · đã kết nối':' · chưa kết nối')));
    if(!state.channels.length||state.channels.some(channel=>channel.connected!==true))strip.append(button('Kết nối kênh',()=>navigate('settings')));
    return strip;
  }
  async function loadCalendar() {const root=$('#studio-calendar');try{
      const data=await request('/api/publishing/schedules');const schedules=Array.isArray(data)?data:data.items||[];
      // Channel state changes rarely; refresh it every minute instead of on every 5-second poll.
      if(!state.channelsAt||Date.now()-state.channelsAt>60000){try{const channels=await request('/api/publishing/channels');state.channels=Array.isArray(channels)?channels:channels.items||[];state.channelsAt=Date.now();}catch{}}
      const signature=JSON.stringify([schedules,state.channels.map(c=>[c.id,c.connected,c.name]),state.scheduleView,dayKey(state.week)]);
      if(signature===state.calendarSignature&&root.querySelector('.studio-calendar-toolbar'))return;state.calendarSignature=signature;state.schedules=schedules;
      root.replaceChildren(pageHeader('Lịch đăng','Giờ Việt Nam (UTC+7)',button('+ Lên lịch video',()=>navigate('library'))),channelStrip());
      const week=weekDays(state.week);const toolbar=el('div','studio-calendar-toolbar');const controls=el('div','row');
      append(controls,button('←',()=>shiftWeek(-7)),button('Hôm nay',()=>{state.week=new Date();loadCalendar();}),button('→',()=>shiftWeek(7)),el('span','muted',shortDate(week[0])+' – '+shortDate(week[6],true)));
      controls.querySelector('button').setAttribute('aria-label','Tuần trước');controls.querySelectorAll('button')[2].setAttribute('aria-label','Tuần sau');
      const modes=el('div','row');for(const [value,label] of [['week','Tuần'],['list','Danh sách']]){const node=button(label,()=>{state.scheduleView=value;loadCalendar();});node.setAttribute('aria-pressed',String(state.scheduleView===value));modes.append(node);}
      append(toolbar,controls,modes);root.append(toolbar);
      if(schedules.some(item=>['scheduled','publishing','blocked'].includes(item.state)&&Date.parse(item.publish_at||item.scheduled_at)>Date.now()))root.append(el('p','notice','Giữ máy bật và ứng dụng chạy để video được gửi đúng giờ.'));
      const filtered=schedules.filter(item=>{const key=localDay(item.scheduled_at||item.publish_at);return week.some(date=>dayKey(date)===key);});
      const calendar=el('div','studio-calendar-week');calendar.hidden=state.scheduleView!=='week';for(const date of week){const day=el('section','studio-calendar-day'+(dayKey(date)===localDay(new Date().toISOString())?' today':''));append(day,append(el('h3'),el('span','',date.toLocaleDateString('vi-VN',{weekday:'short'})),el('strong','',date.getDate())));for(const item of filtered.filter(i=>localDay(i.scheduled_at||i.publish_at)===dayKey(date))){const event=button('',()=>scheduleDetail(item),'studio-calendar-event');append(event,el('time','',prettyDate(item.scheduled_at||item.publish_at).split(' ')[0]),el('span','',item.title||item.video_title||'Video'),stateBadge(item.state||item.status));event.classList.add('is-'+(item.state||item.status||'scheduled'));day.append(event);}calendar.append(day);}root.append(calendar);
      const list=el('div','studio-schedule-list'+(state.scheduleView==='week'?' studio-calendar-list-mobile':''));if(state.scheduleView==='week')list.style.display='none';if(!filtered.length)list.append(empty('Tuần này chưa có lịch đăng','Duyệt một video trong Kho video rồi bấm Lên lịch.'));for(const item of filtered.sort((a,b)=>Date.parse(a.publish_at)-Date.parse(b.publish_at)))list.append(scheduleRow(item));root.append(list);
    }catch(error){errorNode(root,error);}}
  function dayKey(date) {return date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');}
  function localDay(value) {try{return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Ho_Chi_Minh',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}catch{return '';}}
  function weekDays(value) {const local=localDay(value.toISOString());const start=new Date(local+'T12:00:00');start.setDate(start.getDate()-((start.getDay()+6)%7));return Array.from({length:7},(_,index)=>{const date=new Date(start);date.setDate(start.getDate()+index);return date;});}
  function shiftWeek(delta) {state.week.setDate(state.week.getDate()+delta);loadCalendar();}
  function scheduleRow(item) {const channel=state.channels.find(c=>c.id===item.channel_id);const body=append(el('div'),el('h3','',item.title||item.video_title||'Video đã lên lịch'),el('p','',prettyDate(item.scheduled_at||item.publish_at)+' · '+(channel?.name||channel?.platform||item.platform||'Kênh đăng')),stateBadge(item.state||item.status));if(item.message||item.error)body.append(el('p','studio-error',item.message||item.error));const row=append(el('article','studio-schedule-row'),body,button('Chi tiết',()=>scheduleDetail(item)));return row;}
  const postedSending = new Set();
  function openPostedCleanup(video) {
    const id=video.job_id||video.id,modal=dialog('Đã đăng & dọn'),form=el('form'),error=el('p','studio-error');error.setAttribute('role','alert');
    modal.box.append(el('p','notice','Xác nhận “'+(video.title||'Video')+'” đã đăng. Lưu vào Sổ đăng và xóa vĩnh viễn job cùng video, ảnh, lời đọc trên ổ đĩa.'),form);
    const note=el('p','notice');note.hidden=true;
    const submit=el('button','studio-danger','Đã đăng & dọn');submit.type='submit';
    append(form,note,error,append(el('div','studio-dialog-actions'),button('Hủy',()=>modal.close()),submit));
    let pending=null;
    const lock=()=>{note.hidden=false;note.textContent='Thử lại sẽ dùng đúng yêu cầu đã lưu để tránh ghi hoặc xóa trùng.';};
    try{const saved=JSON.parse(global.localStorage.getItem(postedReceiptKey(id))||'null');if(saved?.key&&typeof saved.identity==='string'&&JSON.parse(saved.identity)?.confirm===true){pending=saved;lock();}}
    catch{/* An invalid unsent receipt is replaced on explicit confirmation. */}
    form.onsubmit=async event=>{
      event.preventDefault();if(postedSending.has(id)||submit.disabled)return;error.textContent='';submit.disabled=true;submit.textContent='Đang dọn…';postedSending.add(id);
      try{
        const payload=pending?JSON.parse(pending.identity):postedCleanupPayload(video);
        pending=postedCleanupRequest(global.localStorage,id,payload);lock();note.textContent='Đang lưu Sổ đăng và dọn job/tệp, vui lòng chờ…';
        const result=await postedCleanupWithRecovery(id,pending,message=>{note.textContent=message;});
        if(result.ok!==true||!result.entry?.id)throw Error('Chưa xác nhận được kết quả. Hãy thử lại để kiểm tra cùng yêu cầu.');
        try{global.localStorage.removeItem(postedReceiptKey(id));}catch{}
        modal.close();toast(result.cleanup_pending?'Đã lưu Sổ đăng; một số tệp đang chờ dọn.':'Đã lưu Sổ đăng và xóa job/tệp.');
        await Promise.allSettled([()=>loadLibrary(),()=>global.loadProjects?.(),()=>global.loadJobs?.(),()=>refreshQueueBadge()].map(refresh=>Promise.resolve().then(refresh)));
      }catch(e){error.textContent=e.message;if(e.status===422){try{global.localStorage.removeItem(postedReceiptKey(id));pending=null;note.hidden=true;}catch{}}}
      finally{postedSending.delete(id);submit.disabled=false;submit.textContent='Đã đăng & dọn';}
    };
  }
  function openDeleteVideo(video) {const modal=dialog('Xóa video');const id=video.job_id||video.id;modal.box.append(el('p','notice',video.title||'Video'));
    const filesLabel=el('label','studio-check');const files=el('input');files.type='checkbox';files.id='studioDeleteFiles';append(filesLabel,files,el('span','','Xóa luôn tệp video, ảnh, giọng đọc trên ổ đĩa (không khôi phục được)'));
    const note=el('p','notice','Không tích: video chỉ bị ẩn khỏi Kho video, Hàng đợi và dự án; tệp vẫn còn trong thư mục xuất.');const error=el('p','studio-error');error.setAttribute('role','alert');
    const confirm=button('Xóa video',async()=>{confirm.disabled=true;error.textContent='';try{const result=await request('/api/jobs/'+encodeURIComponent(id)+'/delete',{method:'POST',body:JSON.stringify({delete_files:files.checked,confirm:true})});modal.close();toast(result.files_deleted?(result.cleanup_pending?'Đã xóa video; một số tệp đang bận sẽ được dọn sau.':'Đã xóa video và tệp.'):'Đã ẩn video khỏi kho; tệp vẫn được giữ.');await loadLibrary();}catch(err){error.textContent=err.message;confirm.disabled=false;}},'studio-danger');
    files.onchange=()=>{confirm.textContent=files.checked?'Xóa video và tệp':'Xóa video';};
    append(modal.box,filesLabel,note,error,append(el('div','studio-dialog-actions'),button('Hủy',()=>modal.close()),confirm));}
  function dialog(title) {const backdrop=el('div','studio-dialog');const box=el('section','studio-dialog-box');box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');const heading=el('h2','',title);heading.id='studioDialogTitle';box.setAttribute('aria-labelledby',heading.id);const focus=document.activeElement;const modal={box};const close=()=>{modal.onClose?.();backdrop.remove();document.removeEventListener('keydown',key);focus?.focus();};const key=event=>{if(event.key==='Escape')close();if(event.key==='Tab'){const nodes=[...box.querySelectorAll('button,input,select,textarea,a[href]')].filter(n=>!n.disabled);if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}};document.addEventListener('keydown',key);backdrop.onclick=event=>{if(event.target===backdrop)close();};const closeButton=button('×',close);closeButton.setAttribute('aria-label','Đóng');box.append(append(el('header'),heading,closeButton));backdrop.append(box);document.body.append(backdrop);closeButton.focus();modal.close=close;return modal;}
  async function openSchedule(video) {
    // One form, several channels: each ticked channel gets its own schedule.
    // YouTube receives the landscape 16:9 copy, a Facebook Page receives the vertical copy as a Reel.
    if(!video.approved){toast('Duyệt đúng bản video trước khi lên lịch.');return;}
    const modal=dialog('Đăng video');modal.box.append(el('p','notice',video.title||'Bản video đã duyệt'));
    const form=el('form','st-post');const error=el('p','studio-error');error.setAttribute('role','alert');modal.box.append(form);
    const field=(text,input)=>append(el('label','st-post-field'),el('span','',text),input);
    const channelBox=el('div','st-post-channels');
    const time=el('input');time.type='datetime-local';time.required=true;time.setAttribute('aria-label','Thời gian đăng');
    const pad=n=>String(n).padStart(2,'0');
    const soonest=button('Sớm nhất',()=>{const d=new Date(Date.now()+10*60000);d.setSeconds(0,0);time.value=`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;},'secondary');
    soonest.title='Khoảng 10 phút nữa: tool gửi video ngay; YouTube công khai đúng giờ này, Facebook đăng khi tới giờ.';
    const titleInput=el('input');titleInput.maxLength=100;titleInput.required=true;titleInput.value=video.title||'';
    const ytDesc=el('textarea');ytDesc.maxLength=5000;ytDesc.rows=6;const tagsInput=el('input');tagsInput.placeholder='truyện audio, ngôn tình, trọng sinh';
    const fbCaption=el('textarea');fbCaption.maxLength=5000;fbCaption.rows=6;
    const ytBox=append(el('fieldset','st-post-platform'),el('legend','','YouTube · bản ngang 16:9'),field('Mô tả',ytDesc),field('Tag · cách nhau bằng dấu phẩy',tagsInput));
    // Facebook check: words that can cost reach, monetisation or a strike, with softer phrases one click away.
    const fbCheck=el('div','st-fbcheck');let fbVerdict='safe',fbTimer=null,fbSeq=0;
    const levelText={fix:'Nên sửa',review:'Nên xem lại',note:'Lưu ý'};
    const runCheck=async()=>{const seq=++fbSeq;let result;try{result=await request('/api/publishing/facebook-check',{method:'POST',body:JSON.stringify({text:fbCaption.value})});}catch{return;}
      if(seq!==fbSeq)return;fbVerdict=result.verdict;
      const head=el('div','st-fbcheck-head');head.append(el('span','st-pill '+(result.verdict==='fix'?'is-bad':result.verdict==='review'?'is-warn':'is-ok'),result.verdict==='fix'?'Nên sửa trước khi đăng':result.verdict==='review'?'Nên xem lại':'Ổn với Facebook'));
      head.append(el('small','st-muted','Bảng từ tham khảo từ 2 bản nghiên cứu; Facebook xét cả ngữ cảnh.'));
      const list=el('div','st-fbcheck-list');
      for(const issue of result.issues){
        const row=el('div','st-fbcheck-item is-'+issue.level);
        row.append(append(el('div'),el('strong','',issue.text),el('span','st-muted',' · '+levelText[issue.level]+' · '+issue.label)));
        if(issue.replace?.length){const fixes=el('div','st-fbcheck-fixes');for(const option of issue.replace){fixes.append(button(option,()=>{
          const chars=[...fbCaption.value];const start=chars.slice(0,issue.start).join('').length,end=chars.slice(0,issue.end).join('').length;
          if(fbCaption.value.slice(start,end)!==issue.text){runCheck();return;}
          fbCaption.value=fbCaption.value.slice(0,start)+option+fbCaption.value.slice(end);fbCaption.dataset.edited='true';runCheck();},'secondary'));}row.append(fixes);}
        list.append(row);
      }
      fbCheck.replaceChildren(head,list);};
    fbCaption.addEventListener('input',()=>{clearTimeout(fbTimer);fbTimer=setTimeout(runCheck,500);});
    const fbBox=append(el('fieldset','st-post-platform'),el('legend','','Facebook Reels · bản dọc'),field('Lời đăng',fbCaption),fbCheck);
    for(const node of [titleInput,ytDesc,tagsInput,fbCaption])node.addEventListener('input',event=>{if(event.isTrusted)node.dataset.edited='true';});
    // Honest labelling: YouTube gets the "altered or synthetic content" flag (AI voice and pictures).
    const aiLabel=el('input');aiLabel.type='checkbox';aiLabel.checked=true;
    const aiBox=append(el('label','st-post-channel st-ai-label'),aiLabel,append(el('span'),el('strong','','Gắn nhãn nội dung AI'),
      el('small','','YouTube: bật mục "Nội dung bị thay đổi hoặc tổng hợp".')));
    // Facebook, case videos: a plain note that the post retells a case and does not glorify violence (placed before the hashtags).
    const caseNote=video.style==='case'?'Bài đăng thuật lại vụ án, không cổ suý bạo lực. Khán thính giả vui lòng cân nhắc trước khi xem.':'';
    const withAiNote=text=>{const clean=String(text||'').split('\n').filter(line=>!caseNote||line.trim()!==caseNote).join('\n').replace(/\n{3,}/g,'\n\n').trim();
      if(!caseNote)return clean;const parts=clean.split('\n\n');const tagsAtEnd=parts.length>1&&/^#/.test(parts[parts.length-1].trim());
      if(tagsAtEnd)parts.splice(parts.length-1,0,caseNote);else parts.push(caseNote);return parts.join('\n\n');};
    const submit=el('button','','Lưu lịch đăng');submit.type='submit';
    append(form,el('span','st-post-label','Đăng lên'),channelBox,field('Thời gian đăng · Giờ Việt Nam (UTC+7)',append(el('div','studio-schedule-time'),time,soonest)),
      field('Tiêu đề',titleInput),aiBox,ytBox,fbBox,el('p','notice','Máy cần bật và tool cần chạy để gửi video đúng giờ.'),error,submit);
    let social=null;const boxes=[];
    const chosen=()=>boxes.filter(item=>item.input.checked).map(item=>item.channel);
    const sync=()=>{const platforms=new Set(chosen().map(c=>c.platform));ytBox.hidden=!platforms.has('youtube');const fbWasHidden=fbBox.hidden;fbBox.hidden=!platforms.has('facebook');if(fbWasHidden&&!fbBox.hidden)runCheck();
      const count=chosen().length;submit.textContent=count>1?`Lưu ${count} lịch đăng`:'Lưu lịch đăng';};
    const fill=()=>{if(!social||social.state!=='ready')return;const yt=social.youtube||{},fb=social.facebook||{};
      if(!titleInput.dataset.edited&&yt.title)titleInput.value=yt.title;
      if(!tagsInput.dataset.edited)tagsInput.value=(yt.tags||[]).join(', ');
      if(!ytDesc.dataset.edited){const tags=(yt.tags||[]).map(t=>'#'+String(t).replace(/[\s#]+/g,'')).filter(h=>h.length>1&&!String(yt.description||'').includes(h)).slice(0,5).join(' ');ytDesc.value=[yt.description,tags].filter(Boolean).join('\n\n');}
      if(!fbCaption.dataset.edited)fbCaption.value=withAiNote([fb.caption,(fb.hashtags||[]).filter(h=>!String(fb.caption||'').includes(h)).join(' ')].filter(Boolean).join('\n\n'));
      if(!fbBox.hidden)runCheck();};
    request('/api/jobs/'+encodeURIComponent(video.job_id)+'/social').then(data=>{social=data;fill();}).catch(()=>{});
    try{
      const data=await request('/api/publishing/channels');state.channels=Array.isArray(data)?data:data.items||data.channels||[];state.channelDefaults=data.defaults||{};
      const preferred=Object.values(state.channelDefaults[video.style]||{});
      for(const channel of state.channels.filter(c=>String(c.id).includes(':'))){
        const input=el('input');input.type='checkbox';input.disabled=channel.connected!==true;input.checked=!input.disabled&&preferred.includes(channel.id);input.onchange=sync;
        const kind=channel.connected!==true?'Cần kết nối lại':channel.platform==='youtube'?'YouTube · bản ngang 16:9':'Facebook Reels · bản dọc';
        channelBox.append(append(el('label','st-post-channel'),input,append(el('span'),el('strong','',channel.name||channel.id),el('small','',kind))));boxes.push({input,channel});
      }
      if(!boxes.some(item=>item.input.checked)){const first=boxes.find(item=>!item.input.disabled);if(first)first.input.checked=true;}
      if(!boxes.length){submit.disabled=true;error.textContent='Chưa có kênh đăng. Mở Cài đặt để kết nối tài khoản.';form.append(button('Mở cài đặt',()=>{modal.close();navigate('settings');}));}
      sync();
    }catch(e){error.textContent=e.message;submit.disabled=true;}
    const keys={};
    form.onsubmit=async event=>{
      event.preventDefault();if(form.dataset.sending==='true')return;error.textContent='';
      const targets=chosen();if(!targets.length){error.textContent='Tick ít nhất một kênh.';return;}
      if(targets.some(c=>c.platform==='facebook')){await runCheck();if(fbVerdict==='fix'&&!global.confirm('Lời đăng Facebook còn chỗ "Nên sửa" (từ có thể bị gỡ bài hoặc chữ viết che). Vẫn lưu lịch đăng?'))return;}
      submit.disabled=true;form.dataset.sending='true';const done=[],failed=[];
      for(const channel of targets){
        const youtube=channel.platform==='youtube';
        try{
          const tags=youtube?tagsInput.value.split(',').map(t=>t.replace(/#/g,'').trim()).filter(Boolean):[];
          const payload=schedulePayload({...video,title:titleInput.value.trim()},{channel_id:channel.id,publish_at:time.value+':00+07:00',caption:youtube?ytDesc.value:fbCaption.value,tags,ai_label:aiLabel.checked});
          const storage={getItem:()=>keys[channel.id]||null,setItem:(_key,value)=>{keys[channel.id]=value;}};const pending=pendingRequest(storage,payload);
          await request('/api/publishing/schedules',{method:'POST',headers:{'Idempotency-Key':pending.key},body:pending.identity});
          done.push(channel);const item=boxes.find(b=>b.channel===channel);item.input.checked=false;item.input.disabled=true;item.input.closest('label').classList.add('is-done');
        }catch(e){failed.push((channel.name||channel.id)+': '+e.message);}
      }
      delete form.dataset.sending;submit.disabled=false;sync();
      if(!failed.length){modal.close();navigate('calendar');toast(done.length>1?`Đã lưu ${done.length} lịch đăng.`:'Đã lưu lịch đăng.');}
      else error.textContent=(done.length?`Đã lưu ${done.length} kênh. `:'')+'Chưa lưu được: '+failed.join(' · ');
    };
  }
  function scheduleDetail(item) {const modal=dialog(item.title||item.video_title||'Chi tiết lịch đăng');append(modal.box,el('p','notice',prettyDate(item.publish_at)+' · Giờ Việt Nam'),stateBadge(item.state||item.status),el('p','',item.caption||'Chưa có lời đăng.'));if(item.message||item.error)modal.box.append(el('p','studio-error',item.message||item.error));if(item.remote_url){try{const url=new URL(item.remote_url);if(url.protocol==='https:'&&/^(www\.)?(youtube\.com|youtu\.be|facebook\.com)$/.test(url.hostname)){const link=el('a','button secondary','Mở bài đã đăng');link.href=url.href;link.target='_blank';link.rel='noopener';modal.box.append(link);}}catch{}}if(['blocked','needs_attention'].includes(item.state))modal.box.append(button('Thử lại',async()=>{try{await request('/api/publishing/schedules/'+encodeURIComponent(item.id)+'/retry',{method:'POST',body:'{}'});modal.close();loadCalendar();}catch(error){toast(error.message);}}));if(['scheduled','blocked'].includes(item.state))modal.box.append(button('Hủy lịch đăng',async()=>{try{await request('/api/publishing/schedules/'+encodeURIComponent(item.id),{method:'DELETE'});modal.close();loadCalendar();toast('Đã hủy lịch đăng.');}catch(error){toast(error.message);}}));}
  labels.connected='Đã kết nối';
  Object.assign(labels,{uploading:'Đang tải lên',processing:'Đang xử lý trên kênh',scheduled_remote:'Kênh đã nhận lịch',needs_attention:'Cần bạn kiểm tra'});
  global.ContentStudio.navigate=navigate;
  installShell();
})(globalThis);

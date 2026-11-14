/* Kể truyện: books and chapters on the server, voice settings, gameplay playlist, layout and queueing. */
(function (global) {
  'use strict';
  const VOICE_OWNER_KEY = 'voice-workspace:owner';
  const DRAFT_PREFIX = 'videostudio.story.draft.';
  const PAGE_SIZE = 50;
  const SPEEDS = [['0.75','0,75×'],['0.9','0,9×'],['1','1,0×'],['1.1','1,1×'],['1.25','1,25×'],['1.5','1,5×']];
  const RHYTHMS = [['story','Kể chuyện · nhịp B'],['natural','Tự nhiên · nhịp A']];
  const ICONS = {
    up:'<path d="M6 15l6-6 6 6"/>', down:'<path d="M6 9l6 6 6-6"/>', trash:'<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    edit:'<path d="M4 20h4L19 9l-4-4L4 16zM14 6l4 4"/>', play:'<path d="M7 5v14l11-7z"/>', upload:'<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    folder:'<path d="M3 6h7l2 2h9v11H3z"/>', book:'<path d="M3 5c3-1 6-1 9 1v14c-3-2-6-2-9-1zm18 0c-3-1-6-1-9 1v14c3-2 6-2 9-1z"/>',
    plus:'<path d="M12 5v14M5 12h14"/>', save:'<path d="M5 4h11l3 3v13H5zM8 4v5h7V4M8 14h8"/>', download:'<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
    grip:'<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01"/>', sound:'<path d="M4 9h4l5-4v14l-5-4H4zM17 9a4 4 0 0 1 0 6"/>',
    mute:'<path d="M4 9h4l5-4v14l-5-4H4zM17 9l4 6M21 9l-4 6"/>', close:'<path d="M6 6l12 12M18 6L6 18"/>', spark:'<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>'};

  function mount(root, opts = {}) {
    const doc = root.ownerDocument;
    const toast = opts.toast || (m => console.log(m));
    const state = {books:[], book:null, chapters:[], total:0, totalWords:0, allIds:[], page:1, q:'', selected:new Set(), chapter:null,
      dirty:false, saving:false, saveError:'', voices:[], gameplay:{items:[],total_seconds:0}, backgrounds:[], tab:'voice',
      mode:'each', enqueueKey:null, preview:null, destroyed:false, sources:[]};
    let saveTimer = null, pollTimer = null, dragId = null;

    // --- helpers -----------------------------------------------------------------------------------------
    const el = (tag, cls, text) => {const n=doc.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
    const add = (parent, ...kids) => {parent.append(...kids.filter(k => k != null && k !== false));return parent;};
    const icon = name => {const span=el('span','sw-icon');span.innerHTML=`<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;return span;};
    const btn = (label, action, cls = '', iconName = null) => {const b=el('button','sw-btn '+cls);b.type='button';if(iconName)b.append(icon(iconName));if(label)b.append(el('span','',label));b.onclick=async e=>{try{await action(e);}catch(error){toast(error.message);}};return b;};
    const iconBtn = (name, label, action, cls = '') => {const b=btn('',action,'sw-icon-btn '+cls,name);b.title=label;b.setAttribute('aria-label',label);return b;};
    const field = (label, control, cls = '') => add(el('label','sw-field '+cls), el('span','',label), control);
    const select = (options, value, onchange) => {const s=el('select');for(const [v,l] of options){const o=el('option','',l);o.value=v;s.append(o);}s.value=String(value??'');s.onchange=()=>onchange(s.value);return s;};
    const fmtMinutes = seconds => seconds < 60 ? `${Math.max(1,Math.round(seconds))} giây` : `${Math.round(seconds/60)} phút`;
    const fmtClock = seconds => {seconds=Math.max(0,Math.round(seconds));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(s).padStart(2,'0');};
    const words = text => (String(text||'').match(/\S+/g)||[]).length;
    const uuid = () => global.crypto.randomUUID();
    async function api(path, options = {}, timeout = 60000) {
      const response = await fetch(path, {...options, headers:{...(options.body instanceof Blob || options.raw ? {} : {'Content-Type':'application/json'}), ...options.headers}, signal:AbortSignal.timeout(timeout)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {const detail=data.detail??data.message;const error=Error(typeof detail==='string'?detail:(detail?.message||`Không thực hiện được (${response.status})`));error.status=response.status;throw error;}
      return data;
    }
    const json = (method, body, headers = {}) => ({method, body:JSON.stringify(body ?? {}), headers});
    function voiceRate() {const v=state.voices.find(x=>x.id===settings().voice_id);return Number(v?.reading_profile?.syllables_per_second)||4.2;}
    const settings = () => state.book?.settings || {};
    const layout = () => state.book?.layout || {};
    const estimate = text => words(text) / voiceRate() / Math.max(.5, Number(settings().speech_speed||1));
    const estimateWords = count => count / voiceRate() / Math.max(.5, Number(settings().speech_speed||1));

    // --- skeleton ----------------------------------------------------------------------------------------
    const page = el('div','story-workspace');
    const header = add(el('header','sw-header'), add(el('div'), el('h1','','Kể truyện'), el('p','sw-muted','Truyện đã biên tập, giọng kể rõ ràng và gameplay bạn tự quay')));
    const bar = el('div','sw-bar');
    const bookSelect = el('select','sw-book-select');bookSelect.setAttribute('aria-label','Chọn truyện');bookSelect.onchange=()=>openBook(bookSelect.value);
    const fileInput = el('input');fileInput.type='file';fileInput.multiple=true;fileInput.accept='.txt,text/plain';fileInput.hidden=true;
    const folderInput = el('input');folderInput.type='file';folderInput.multiple=true;folderInput.hidden=true;folderInput.setAttribute('webkitdirectory','');
    const drop = btn('Thả TXT / Bấm chọn',()=>fileInput.click(),'sw-drop','upload');
    const saveState = el('span','sw-save-state');saveState.setAttribute('role','status');
    add(bar, add(el('div','sw-book-pick'),icon('book'),bookSelect), btn('Thêm truyện',newBook,'','plus'), drop,
      btn('Chọn thư mục',()=>{if('webkitdirectory' in folderInput)folderInput.click();else{toast('Trình duyệt chưa hỗ trợ chọn thư mục; hãy chọn nhiều tệp.');fileInput.click();}},'','folder'),
      btn('Truyện nguồn · biên tập ChatGPT',openSources,'','spark'), saveState, fileInput, folderInput);
    for (const input of [fileInput, folderInput]) input.onchange = async () => {try{await importFiles([...input.files]);}catch(e){toast(e.message);}finally{input.value='';}};

    // left: chapters
    const left = el('section','sw-panel sw-chapters');
    const search = el('input');search.type='search';search.placeholder='Tìm chương…';search.setAttribute('aria-label','Tìm chương');
    search.oninput = () => {clearTimeout(search.timer);search.timer=setTimeout(()=>{state.q=search.value;state.page=1;loadChapters();},250);};
    const selectAll = el('input');selectAll.type='checkbox';selectAll.onchange=()=>{state.selected=selectAll.checked?new Set(state.allIds):new Set();renderChapters();renderFooter();};
    const selectedCount = el('span');
    const chapterList = el('div','sw-chapter-list');
    const pager = el('div','sw-pager');
    add(left, el('h2','','Truyện & chương'), add(el('div','sw-search'),search),
      add(el('div','sw-select-row'), selectedCount, add(el('label','sw-check'), selectAll, el('span','','Chọn tất cả'))), chapterList, pager,
      el('p','sw-muted sw-hint','Kéo ⠿ hoặc dùng ↑ ↓ để đổi thứ tự đọc.'));

    // middle: chapter editor
    const middle = el('section','sw-panel sw-editor');
    const editorTitle = el('h2');const editorSub = el('p','sw-muted','Đọc nguyên văn nội dung bạn đã sửa');
    const chapterName = el('input');chapterName.type='text';chapterName.maxLength=300;chapterName.oninput=()=>markDirty();
    const text = el('textarea','sw-text');text.spellcheck=false;text.oninput=()=>{markDirty();renderMeta();};
    const meta = el('span','sw-muted');
    const readTitle = el('input');readTitle.type='checkbox';readTitle.onchange=()=>markDirty();
    const previewBox = el('div','sw-preview');
    add(middle, add(el('div','sw-editor-head'), editorTitle, editorSub), field('Tên chương', chapterName), field('Nội dung lời kể', text, 'sw-text-field'),
      add(el('div','sw-meta-row'), meta, add(el('label','sw-check'), readTitle, el('span','','Đọc tên chương'))),
      add(el('div','sw-editor-actions'), btn('Lưu chương',()=>saveChapter(true),'','save'), btn('Đọc thử khoảng 1 phút',previewVoice,'sw-accent','play')),
      previewBox, el('p','sw-muted sw-note','ⓘ Nghe thử là tuỳ chọn; hàng đợi không dừng để chờ duyệt từng chương.'));

    // right: settings tabs
    const right = el('section','sw-panel sw-settings');
    const tabs = el('div','sw-tabs');tabs.setAttribute('role','tablist');
    const tabBody = el('div','sw-tab-body');
    for (const [key,label] of [['voice','Giọng kể'],['gameplay','Gameplay'],['frame','Khung hình']]) {
      const t = btn(label,()=>{state.tab=key;renderSettings();},'sw-tab');t.dataset.tab=key;t.setAttribute('role','tab');tabs.append(t);
    }
    add(right, el('h2','','Thiết lập kể chuyện'), tabs, tabBody);

    const columns = add(el('div','sw-columns'), left, middle, right);
    const footer = el('footer','sw-footer');
    const total = el('span','sw-total');
    const modeSelect = select([['each','Mỗi chương một video'],['merge','Gộp chương đã chọn thành một video']], state.mode, v=>{state.mode=v;state.enqueueKey=null;renderFooter();});
    modeSelect.setAttribute('aria-label','Cách tạo video');
    const enqueueButton = btn('',enqueue,'sw-primary');
    add(footer, total, modeSelect, btn('Lưu nháp',()=>saveChapter(true),'','save'), enqueueButton);
    const empty = el('div','sw-empty');
    add(page, header, bar, columns, footer, empty);
    root.replaceChildren(page);

    // --- drag & drop files anywhere on the page ------------------------------------------------------------
    page.ondragover = e => {if(!dragId && [...(e.dataTransfer?.types||[])].includes('Files')){e.preventDefault();drop.classList.add('is-dragging');}};
    page.ondragleave = e => {if(!page.contains(e.relatedTarget))drop.classList.remove('is-dragging');};
    page.ondrop = async e => {
      if (dragId || ![...(e.dataTransfer?.types||[])].includes('Files')) return;
      e.preventDefault();drop.classList.remove('is-dragging');
      try {await importFiles(await collectDropped(e.dataTransfer));} catch(error) {toast(error.message);}
    };
    async function collectDropped(transfer) {
      const items=[...(transfer.items||[])].map(i=>i.webkitGetAsEntry?.()).filter(Boolean);
      if(!items.length)return [...transfer.files];
      const files=[];
      async function walk(entry){
        if(entry.isFile){files.push(await new Promise((ok,fail)=>entry.file(ok,fail)));return;}
        const reader=entry.createReader();let batch;do{batch=await new Promise((ok,fail)=>reader.readEntries(ok,fail));for(const child of batch)await walk(child);}while(batch.length);
      }
      for(const entry of items)await walk(entry);
      return files;
    }

    // --- books -------------------------------------------------------------------------------------------
    async function loadBooks(selectId) {
      const [books, voices, backgrounds] = await Promise.all([api('/api/story/books'), state.voices.length?{voices:state.voices}:api('/api/voices').catch(()=>({voices:[]})), api('/api/story/backgrounds').catch(()=>({items:[]}))]);
      state.books = books.items; state.voices = (voices.voices||voices.items||[]).filter(v=>v.selectable!==false); state.backgrounds = backgrounds.items;
      bookSelect.replaceChildren(...state.books.map(b=>{const o=el('option','',`${b.title} · ${b.chapters} chương`);o.value=b.id;return o;}));
      const remembered = selectId || readLocal('book');
      const target = state.books.find(b=>b.id===remembered) || state.books[0];
      if (target) await openBook(target.id); else renderAll();
    }
    async function openBook(id) {
      if (state.book && state.book.id !== id) await saveChapter(false);
      state.book = await api('/api/story/books/'+id);
      bookSelect.value = id; writeLocal('book', id);
      state.selected = new Set(); state.page = 1; state.q = ''; search.value = ''; state.chapter = null; state.enqueueKey = null;
      await Promise.all([loadChapters(true), loadGameplay()]);
      renderAll();
    }
    async function newBook() {
      const title = (global.prompt('Tên truyện mới:') || '').trim();
      if (!title) return;
      const book = await api('/api/story/books', json('POST', {title}));
      await loadBooks(book.id); toast('Đã tạo truyện “'+title+'”. Thả các tệp TXT để thêm chương.');
    }
    async function patchBook(patch, message) {
      state.book = await api('/api/story/books/'+state.book.id, json('PATCH', {...patch, expected_revision:state.book.revision}));
      state.enqueueKey = null; renderAll(); if (message) toast(message);
    }

    // --- chapters ----------------------------------------------------------------------------------------
    async function loadChapters(openFirst = false) {
      if (!state.book) return;
      const data = await api(`/api/story/books/${state.book.id}/chapters?page=${state.page}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(state.q)}`);
      state.chapters = data.items; state.total = data.total; state.totalWords = data.total_words; state.allIds = data.all_ids;
      state.wordsById = state.wordsById || new Map(); for (const c of data.items) state.wordsById.set(c.id, c.words);
      state.selected = new Set([...state.selected].filter(id => state.allIds.includes(id)));
      if ((openFirst || !state.chapter) && data.items[0]) await openChapter(data.items[0].id);
      renderChapters(); renderFooter();
    }
    async function openChapter(id) {
      if (state.chapter && state.chapter.id !== id) await saveChapter(false);
      const chapter = await api('/api/story/chapters/'+id);
      const draft = readLocal('chapter.'+id);
      state.chapter = chapter; state.dirty = false; state.saveError = '';
      chapterName.value = chapter.title; text.value = chapter.text; readTitle.checked = chapter.read_title;
      if (draft && draft.base === chapter.revision && (draft.text !== chapter.text || draft.title !== chapter.title)) {
        chapterName.value = draft.title; text.value = draft.text; state.dirty = true; toast('Đã khôi phục phần bạn gõ dở chưa kịp lưu.'); scheduleSave();
      }
      state.preview = null; renderEditor(); renderChapters();
    }
    function markDirty() {
      if (!state.chapter) return;
      state.dirty = true; state.saveError = '';
      writeLocal('chapter.'+state.chapter.id, {base:state.chapter.revision, title:chapterName.value, text:text.value});
      renderSaveState(); scheduleSave();
    }
    function scheduleSave() {clearTimeout(saveTimer); saveTimer = setTimeout(() => saveChapter(false).catch(e=>toast(e.message)), 1500);}
    async function saveChapter(announce) {
      clearTimeout(saveTimer);
      if (!state.chapter || !state.dirty || state.saving) {if(announce&&!state.dirty)toast('Chương đã được lưu.');return;}
      state.saving = true; renderSaveState();
      const id = state.chapter.id;
      try {
        const saved = await api('/api/story/chapters/'+id, json('PUT', {title:chapterName.value, text:text.value, read_title:readTitle.checked, expected_revision:state.chapter.revision}));
        if (state.chapter?.id === id) {state.chapter = saved; state.dirty = chapterName.value !== saved.title || text.value !== saved.text;}
        removeLocal('chapter.'+id); state.enqueueKey = null;
        const row = state.chapters.find(c=>c.id===id); if (row) Object.assign(row, {title:saved.title, words:saved.words, revision:saved.revision});
        state.wordsById?.set(id, saved.words);
        if (announce) toast('Đã lưu chương.');
      } catch (error) {state.saveError = error.message; if (announce || error.status === 409) toast(error.message);}
      finally {state.saving = false; renderSaveState(); renderChapters(); renderFooter();}
    }
    async function importFiles(files) {
      const texts = files.filter(f => /\.txt$/i.test(f.name) || f.type === 'text/plain');
      if (!texts.length) throw Error('Chọn tệp .txt (mỗi tệp một chương, hoặc một tệp gộp có tiêu đề “Chương N”).');
      if (!state.book) {
        const guess = (texts[0].webkitRelativePath||'').split('/')[0] || texts[0].name.replace(/\.txt$/i,'');
        const book = await api('/api/story/books', json('POST', {title:guess}));
        await loadBooks(book.id);
      }
      let added=0, updated=0, skipped=0;
      texts.sort((a,b)=>(a.webkitRelativePath||a.name).localeCompare(b.webkitRelativePath||b.name,'vi',{numeric:true}));
      for (let i = 0; i < texts.length; i += 20) {
        const chunk = await Promise.all(texts.slice(i,i+20).map(async f => ({name:f.webkitRelativePath||f.name, text:await f.text()})));
        saveState.textContent = `Đang nhập ${Math.min(i+20,texts.length)}/${texts.length} tệp…`;
        const result = await api(`/api/story/books/${state.book.id}/chapters/import`, json('POST', {files:chunk}), 120000);
        added += result.added; updated += result.updated; skipped += result.skipped;
      }
      await loadBooks(state.book.id);
      toast(`Đã thêm ${added} chương` + (updated ? `, cập nhật ${updated}` : '') + (skipped ? `, bỏ qua ${skipped} chương trùng` : '') + '.');
    }
    async function moveChapter(id, delta) {
      const ids = [...state.allIds]; const from = ids.indexOf(id); const to = from + delta;
      if (from < 0 || to < 0 || to >= ids.length) return;
      ids.splice(to, 0, ids.splice(from, 1)[0]); await reorder(ids);
    }
    async function reorder(ids) {await api(`/api/story/books/${state.book.id}/chapters/order`, json('POST', {chapter_ids:ids})); state.enqueueKey = null; await loadChapters();}
    async function renameChapter(chapter) {
      const title = (global.prompt('Tên chương:', chapter.title) || '').trim(); if (!title || title === chapter.title) return;
      if (state.chapter?.id === chapter.id) {chapterName.value = title; markDirty(); await saveChapter(false);}
      else await api('/api/story/chapters/'+chapter.id, json('PUT', {title, expected_revision:chapter.revision}));
      await loadChapters();
    }
    async function deleteChapters(ids) {
      if (!global.confirm(`Xoá ${ids.length} chương khỏi thư viện truyện? Tệp gốc trên máy và video đã xuất không bị xoá.`)) return;
      await api(`/api/story/books/${state.book.id}/chapters/delete`, json('POST', {chapter_ids:ids, confirm:true}));
      for (const id of ids) state.selected.delete(id);
      if (ids.includes(state.chapter?.id)) state.chapter = null;
      await loadChapters(true);
    }

    // --- voice preview (uses Phòng thử giọng tasks) ---------------------------------------------------------
    function voiceOwner() {
      try {const saved = JSON.parse(global.localStorage.getItem(VOICE_OWNER_KEY)||'null'); if (saved) return saved;} catch {}
      const owner = uuid(); try {global.localStorage.setItem(VOICE_OWNER_KEY, JSON.stringify(owner));} catch {} return owner;
    }
    function sampleText(full) {
      const target = Math.round(voiceRate() * 75 * Math.max(.5, Number(settings().speech_speed||1)));
      const sentences = String(full||'').replace(/\n{2,}/g,'\n').split(/(?<=[.!?…])\s+/);
      let out = '';
      for (const s of sentences) {if (words(out) >= target) break; out += (out?' ':'') + s;}
      return out.trim().slice(0, 19000);
    }
    async function previewVoice() {
      if (!state.chapter) throw Error('Chọn một chương trước.');
      const s = settings();
      const heading = readTitle.checked ? `Chương ${state.chapter.number || orderOf(state.chapter.id)}. ${chapterName.value}.\n` : '';
      const body = {text:(heading + sampleText(text.value)).trim(), voice_id:s.voice_id, speech_engine:s.speech_engine||'vieneu', speech_rhythm:s.speech_rhythm||'story',
        speech_speed:Number(s.speech_speed||1), speech_volume:100, title:`Kể truyện – ${state.book.title} – ${chapterName.value}`.slice(0,150)};
      if (body.speech_engine === 'khanhtts') {body.khanh_steps = Number(s.khanh_steps||32); if (s.speech_reference_text) body.speech_reference_text = s.speech_reference_text;}
      if (!body.text) throw Error('Chương chưa có nội dung.');
      const owner = voiceOwner();
      const task = await api('/api/voice-studio/tasks', json('POST', body, {'X-Voice-Owner':owner, 'Idempotency-Key':uuid()}));
      state.preview = {id:task.id, owner, state:task.state, message:task.message, estimate:estimate(body.text)}; renderPreview(); pollPreview();
    }
    function pollPreview() {
      clearTimeout(pollTimer);
      if (!state.preview || ['completed','failed','cancelled'].includes(state.preview.state)) return;
      pollTimer = setTimeout(async () => {
        try {const task = await api('/api/voice-studio/tasks/'+state.preview.id, {headers:{'X-Voice-Owner':state.preview.owner}}); Object.assign(state.preview, {state:task.state, message:task.message, duration:task.result?.duration_seconds});}
        catch (error) {state.preview.message = error.message;}
        renderPreview(); pollPreview();
      }, 3000);
    }
    const orderOf = id => state.allIds.indexOf(id) + 1;

    // --- gameplay ----------------------------------------------------------------------------------------
    async function loadGameplay() {if (state.book) state.gameplay = await api('/api/story/gameplay?book_id='+state.book.id);}
    async function uploadClips(files) {
      for (const file of files) {
        if (!/\.(mp4|mkv|mov|webm)$/i.test(file.name)) {toast(file.name+': chỉ nhận MP4, MKV, MOV hoặc WebM.'); continue;}
        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('PUT', '/api/story/gameplay?name='+encodeURIComponent(file.name));
          xhr.upload.onprogress = e => {if (e.lengthComputable) {state.upload = `${file.name}: ${Math.round(e.loaded/e.total*100)}%`; renderSettings();}};
          xhr.onload = () => {state.upload = ''; if (xhr.status < 300) resolve(); else {let m='Không tải lên được '+file.name;try{m=JSON.parse(xhr.responseText).detail||m;}catch{} reject(Error(m));}};
          xhr.onerror = () => {state.upload = ''; reject(Error('Mất kết nối khi tải '+file.name));};
          xhr.send(file);
        });
      }
      await loadGameplay(); renderSettings(); renderFooter(); toast('Đã thêm clip gameplay.');
    }
    async function savePlaylist(items) {
      state.gameplay = await api(`/api/story/books/${state.book.id}/gameplay`, json('PUT', {clips:items.map(c=>({id:c.id,start:Number(c.start)||0,end:Number(c.end)||c.duration}))}));
      state.enqueueKey = null; renderSettings(); renderFooter();
    }

    // --- layout preview ------------------------------------------------------------------------------------
    async function openLayout() {
      if (!state.book) return;
      const dialog = el('dialog','sw-dialog sw-layout-dialog');
      const close = () => {dialog.close(); dialog.remove();};
      const body = el('div','sw-layout-body');
      const status = el('p','sw-muted','Đang dựng ảnh xem trước từ khung gameplay đầu tiên…');
      const frames = el('div','sw-layout-frames');
      const guides = el('input');guides.type='checkbox';
      const chapterId = state.chapter?.id;
      const CANVAS = {ngang:[1920,1080], doc:[1080,1920]};
      const DEFAULT_BOX = {ngang:[384,178,1152], doc:[36,650,1008]};
      async function shot(orientation, figure) {
        figure ||= add(el('figure','sw-frame sw-frame-'+orientation), el('figcaption','',orientation==='ngang'?'Ngang 16:9':'Dọc 9:16'));
        if (!figure.parentNode) frames.append(figure);
        const box = el('div','sw-frame-box'); figure.querySelector('.sw-frame-box')?.remove(); figure.querySelector('.sw-frame-actions')?.remove(); figure.append(box);
        box.append(el('p','sw-muted','Đang dựng ảnh xem trước…'));
        try {
          const result = await api(`/api/story/books/${state.book.id}/preview`, json('POST', {kind:'still', orientation, chapter_id:chapterId}), 120000);
          const img = el('img'); img.src = result.url; img.alt = 'Bố cục '+orientation; img.draggable = false;
          box.replaceChildren(img, guideLayer(orientation), gameEditor(orientation, box, figure));
          const reset = btn('Về cỡ mặc định', async () => {const gb = {...(layout().game_box||{})}; delete gb[orientation]; await patchBook({layout:{game_box:gb}}); await shot(orientation, figure);}, '');
          reset.disabled = !(layout().game_box||{})[orientation];
          figure.append(add(el('div','sw-frame-actions'), el('span','sw-muted','Kéo khung game để di chuyển, kéo góc để đổi cỡ (giữ 16:9). Phụ đề tự nằm dưới khung.'), reset));
        } catch (error) {box.replaceChildren(el('p','sw-error',error.message));}
      }
      function gameEditor(orientation, box, figure) {
        const [W,H] = CANVAS[orientation];
        let [x,y,w] = (layout().game_box||{})[orientation] || DEFAULT_BOX[orientation];
        const frame = el('div','sw-game-edit'); const handle = el('span','sw-game-handle'); frame.append(handle);
        frame.title = 'Kéo để di chuyển khung game; kéo góc dưới phải để đổi cỡ';
        const place = () => {const h=w*9/16;Object.assign(frame.style,{left:x/W*100+'%',top:y/H*100+'%',width:w/W*100+'%',height:h/H*100+'%'});};
        place();
        frame.onpointerdown = event => {
          event.preventDefault(); frame.setPointerCapture(event.pointerId);
          const rect = box.getBoundingClientRect(), scale = W / rect.width, start = {px:event.clientX, py:event.clientY, x, y, w};
          const resizing = event.target === handle;
          frame.onpointermove = move => {
            const dx = (move.clientX-start.px)*scale, dy = (move.clientY-start.py)*scale;
            const centred = Math.abs(start.x + start.w/2 - W/2) < 3;
            if (resizing && centred) {w = Math.max(W*.35, Math.min(W, start.w + 2*Math.max(dx, dy*16/9))); x = (W - w)/2; y = start.y;}
            else if (resizing) {w = Math.max(W*.35, Math.min(W - start.x, start.w + Math.max(dx, dy*16/9)));}
            else {x = start.x + dx; y = start.y + dy; if (Math.abs(x + w/2 - W/2) < W*.015) x = (W - w)/2;}
            w = Math.min(w, W); x = Math.max(0, Math.min(W - w, x)); y = Math.max(0, Math.min(H - w*9/16, y)); place();
          };
          frame.onpointerup = async () => {
            frame.onpointermove = null; frame.onpointerup = null;
            if (Math.abs(x-start.x) < 2 && Math.abs(y-start.y) < 2 && Math.abs(w-start.w) < 2) return;
            const gb = {...(layout().game_box||{}), [orientation]:[Math.round(x),Math.round(y),Math.round(w)]};
            try {await patchBook({layout:{game_box:gb}}); await shot(orientation, figure);} catch (error) {toast(error.message);}
          };
        };
        return frame;
      }
      function guideLayer(orientation) {
        const layer = el('div','sw-guides'); layer.hidden = !guides.checked;
        const [W,H] = CANVAS[orientation];
        const boxes = orientation==='ngang' ? [[120,22,1680,150,'Tiêu đề']] : [[80,210,920,280,'Tiêu đề'],[0,1440,1080,480,'Vùng nút của YouTube/Facebook']];
        for (const [gx,gy,gw,gh,label] of boxes) {const g=el('span','sw-guide',label);Object.assign(g.style,{left:gx/W*100+'%',top:gy/H*100+'%',width:gw/W*100+'%',height:gh/H*100+'%'});layer.append(g);}
        return layer;
      }
      guides.onchange = () => dialog.querySelectorAll('.sw-guides').forEach(n => n.hidden = !guides.checked);
      const testOut = el('div','sw-test-out');
      const testButton = btn('Render thử 10 giây', async () => {
        testButton.disabled = true; testOut.replaceChildren(el('p','sw-muted','Đang dựng 10 giây bản ngang (không đọc giọng, không đổi vị trí gameplay)…'));
        try {const r = await api(`/api/story/books/${state.book.id}/preview`, json('POST', {kind:'clip', orientation:'ngang', chapter_id:chapterId}), 240000);
          const video = el('video'); video.controls = true; video.src = r.url; video.muted = true; testOut.replaceChildren(video);}
        catch (error) {testOut.replaceChildren(el('p','sw-error',error.message));}
        finally {testButton.disabled = false;}
      }, '', 'play');
      add(body, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Khung hình kể chuyện'), el('p','sw-muted',`${state.book.title} · ${chapterName.value||''}`)), iconBtn('close','Đóng',close)),
        frames, status,
        add(el('div','sw-layout-tools'), add(el('label','sw-check'), guides, el('span','','Hiện vùng an toàn')), el('span','sw-muted','Giữ trọn khung gameplay ngang ở cả hai định dạng. Đường vùng an toàn chỉ hiện ở đây, không đốt vào video.'), testButton),
        testOut);
      dialog.append(body); doc.body.append(dialog); dialog.showModal();
      dialog.addEventListener('cancel', () => dialog.remove());
      await Promise.all([shot('ngang'), shot('doc')]); status.remove();
    }

    // --- crawled sources + ChatGPT editing ------------------------------------------------------------------
    async function openSources() {
      const dialog = el('dialog','sw-dialog sw-sources-dialog');
      const list = el('div','sw-source-list');
      const close = () => {clearInterval(dialog.timer); dialog.close(); dialog.remove();};
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Truyện nguồn'),
        el('p','sw-muted','Truyện tải về bằng công cụ wikicv. Tool gửi từng chương cho ChatGPT biên tập theo quy tắc viết để nghe, tự kiểm tra rồi gộp lại; chương đã xong không gửi lại.')), iconBtn('close','Đóng',close)), list);
      async function refresh() {
        let data; try {data = await api('/api/story/sources');} catch (error) {list.replaceChildren(el('p','sw-error',error.message)); return;}
        const signature = JSON.stringify(data); if (signature === list.dataset.signature) return; list.dataset.signature = signature;
        if (data.root_missing || !data.items.length) {list.replaceChildren(el('p','sw-muted','Chưa thấy truyện nào trong thư mục wikicv_auto_v3_2_mixed_titles/du_lieu_truyen.')); return;}
        list.replaceChildren(...data.items.map(source => {
          const row = el('article','sw-source');
          const progress = el('progress'); progress.max = source.chapters || 1; progress.value = source.edited;
          const status = source.running ? 'Đang biên tập…' : source.edited >= source.chapters && source.chapters ? 'Đã biên tập xong' : source.edited ? `Đã biên tập ${source.edited}/${source.chapters} chương` : 'Chưa biên tập';
          add(row, add(el('div','sw-source-info'), el('strong','',source.title), el('span','sw-muted',`${source.chapters} chương · ${status}` + (source.needs_review.length ? ` · cần xem lại: ${source.needs_review.join(', ')}` : '')), progress,
            source.log.length ? el('pre','sw-source-log',source.log.join('\n')) : null, source.error ? el('p','sw-error',source.error) : null),
            add(el('div','sw-source-actions'),
              (()=>{const b=btn(source.edited&&source.edited<source.chapters?'Biên tập tiếp':'Biên tập bằng ChatGPT',async()=>{await api(`/api/story/sources/${encodeURIComponent(source.name)}/edit`, json('POST',{}));toast('Đã bắt đầu biên tập. Có thể đóng cửa sổ này; tool vẫn chạy.');refresh();},'');b.disabled=source.running||(source.edited>=source.chapters&&source.chapters>0);return b;})(),
              (()=>{const b=btn(source.book_id?'Cập nhật vào Kể truyện':'Nhập vào Kể truyện',async()=>{const r=await api(`/api/story/sources/${encodeURIComponent(source.name)}/import`, json('POST',{}),120000);toast(`Đã nhập: thêm ${r.added}, cập nhật ${r.updated} chương.`);close();await loadBooks(r.book.id);},'sw-accent');b.disabled=!source.merged;b.title=source.merged?'':'Biên tập trước để có bản đọc được';return b;})()));
          return row;
        }));
      }
      doc.body.append(dialog); dialog.showModal(); dialog.addEventListener('cancel', () => {clearInterval(dialog.timer); dialog.remove();});
      await refresh(); dialog.timer = setInterval(refresh, 5000);
    }

    // --- queue -------------------------------------------------------------------------------------------
    async function enqueue() {
      await saveChapter(false);
      if (state.dirty) throw Error('Chưa lưu được chương đang sửa. Kiểm tra lỗi lưu rồi thử lại.');
      const ids = state.allIds.filter(id => state.selected.has(id));
      if (!ids.length) throw Error('Tick chọn ít nhất một chương trong danh sách.');
      if (!state.gameplay.items.some(c=>c.available)) {state.tab='gameplay';renderSettings();throw Error('Chưa có clip gameplay. Thêm clip trong tab Gameplay (nghe thử giọng vẫn dùng được).');}
      const l = layout(); if (!l.horizontal && !l.vertical) {state.tab='frame';renderSettings();throw Error('Chọn ít nhất một định dạng xuất: ngang hoặc dọc.');}
      state.enqueueKey ||= 'story-' + uuid();
      enqueueButton.disabled = true; enqueueButton.textContent = 'Đang thêm vào hàng đợi…';
      try {
        const result = await api(`/api/story/books/${state.book.id}/enqueue`, json('POST', {chapter_ids:ids, mode:state.mode}, {'Idempotency-Key':state.enqueueKey}), 120000);
        toast(`Đã thêm ${result.videos} video vào hàng đợi.`); state.enqueueKey = null; state.selected = new Set(); renderChapters();
        if (opts.openQueue && global.confirm(`Đã thêm ${result.videos} video vào hàng đợi. Mở Hàng đợi để theo dõi?`)) opts.openQueue();
      } finally {renderFooter();}
    }

    // --- rendering -----------------------------------------------------------------------------------------
    function renderAll() {renderEmpty(); renderChapters(); renderEditor(); renderSettings(); renderFooter(); renderSaveState();}
    function renderEmpty() {
      const none = !state.book;
      columns.hidden = none; footer.hidden = none;
      empty.hidden = !none;
      if (none) empty.replaceChildren(el('h2','','Chưa có truyện nào'), el('p','sw-muted','Bấm Thêm truyện, thả tệp TXT vào đây, hoặc mở Truyện nguồn để biên tập truyện tải từ wikicv bằng ChatGPT.'),
        add(el('div','sw-empty-actions'), btn('Thêm truyện',newBook,'sw-primary','plus'), btn('Truyện nguồn · biên tập ChatGPT',openSources,'','spark')));
    }
    function renderSaveState() {
      saveState.classList.toggle('is-error', Boolean(state.saveError));
      saveState.textContent = state.saveError ? '⚠ ' + state.saveError : state.saving ? 'Đang lưu…' : state.dirty ? 'Chưa lưu' : state.chapter ? '✓ Đã lưu chương' : '';
    }
    function renderChapters() {
      if (!state.book) return;
      selectedCount.textContent = `${state.selected.size} chương đã chọn`;
      selectAll.checked = state.allIds.length > 0 && state.selected.size === state.allIds.length;
      selectAll.indeterminate = state.selected.size > 0 && state.selected.size < state.allIds.length;
      chapterList.replaceChildren(...state.chapters.map(chapter => {
        const row = el('article','sw-chapter'); row.classList.toggle('is-active', chapter.id === state.chapter?.id); row.draggable = !state.q;
        row.ondragstart = e => {if(e.target.closest('button,input')){e.preventDefault();return;}dragId=chapter.id;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',chapter.id);};
        row.ondragend = () => {dragId = null;}; row.ondragover = e => {if(dragId)e.preventDefault();};
        row.ondrop = async e => {if(!dragId||dragId===chapter.id)return;e.preventDefault();const ids=[...state.allIds];const from=ids.indexOf(dragId);ids.splice(from,1);ids.splice(ids.indexOf(chapter.id)+(from<ids.indexOf(chapter.id)+1?1:0),0,dragId);dragId=null;try{await reorder(ids);}catch(err){toast(err.message);}};
        const check = el('input'); check.type='checkbox'; check.checked = state.selected.has(chapter.id); check.setAttribute('aria-label','Chọn '+chapter.title);
        check.onchange = () => {if(check.checked)state.selected.add(chapter.id);else state.selected.delete(chapter.id);state.enqueueKey=null;renderChapters();renderFooter();};
        const open = el('button','sw-chapter-open'); open.type='button'; open.onclick = () => openChapter(chapter.id).catch(e=>toast(e.message));
        add(open, add(el('strong'), el('span','sw-order',String(chapter.order).padStart(2,'0')), el('span','',chapter.title)), el('span','sw-muted',`${chapter.words.toLocaleString('vi-VN')} từ · khoảng ${fmtMinutes(estimateWords(chapter.words))}`));
        const position = state.allIds.indexOf(chapter.id);
        const up = iconBtn('up','Đưa lên',()=>moveChapter(chapter.id,-1)); up.disabled = position <= 0 || Boolean(state.q);
        const down = iconBtn('down','Đưa xuống',()=>moveChapter(chapter.id,1)); down.disabled = position >= state.allIds.length-1 || Boolean(state.q);
        const grip = el('span','sw-grip'); grip.append(icon('grip')); grip.title = 'Kéo để đổi thứ tự';
        add(row, grip, check, open, add(el('div','sw-row-actions'), up, down, iconBtn('edit','Đổi tên',()=>renameChapter(chapter)), iconBtn('trash','Xoá khỏi thư viện',()=>deleteChapters([chapter.id]),'sw-danger')));
        return row;
      }));
      if (!state.chapters.length) chapterList.append(el('p','sw-muted sw-list-empty', state.q ? 'Không có chương khớp.' : 'Chưa có chương. Thả tệp TXT (mỗi tệp một chương) hoặc một tệp gộp có tiêu đề “Chương N”.'));
      const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
      const prev = iconBtn('up','Trang trước',async()=>{state.page--;await loadChapters();}); prev.disabled = state.page <= 1;
      const next = iconBtn('down','Trang sau',async()=>{state.page++;await loadChapters();}); next.disabled = state.page >= pages;
      pager.replaceChildren(el('span','sw-muted',`${state.total} chương · ${state.totalWords.toLocaleString('vi-VN')} từ`), ...(pages > 1 ? [prev, el('span','',`${state.page}/${pages}`), next] : []));
    }
    function renderEditor() {
      const has = Boolean(state.chapter);
      for (const n of [chapterName, text, readTitle]) n.disabled = !has;
      editorTitle.textContent = has ? `Chương ${String(orderOf(state.chapter.id)).padStart(2,'0')} · ${chapterName.value || state.chapter.title}` : 'Chọn một chương';
      renderMeta(); renderPreview();
    }
    function renderMeta() {
      const count = words(text.value);
      meta.textContent = state.chapter ? `${count.toLocaleString('vi-VN')} từ · ${text.value.length.toLocaleString('vi-VN')} ký tự · ước tính ${fmtMinutes(estimate(text.value))} theo giọng đã chọn` : '';
    }
    function renderPreview() {
      const p = state.preview;
      if (!p) {previewBox.replaceChildren(); previewBox.hidden = true; return;}
      previewBox.hidden = false;
      const s = settings();
      const voice = state.voices.find(v=>v.id===s.voice_id)?.name || s.voice_id;
      const head = add(el('div','sw-preview-head'), el('strong','','Mẫu nghe của chương này'), el('span','sw-muted',`${voice} · ${s.speech_engine==='khanhtts'?'KhanhTTS':'VieNeu'} · ${s.speech_rhythm==='natural'?'Nhịp tự nhiên':'Nhịp kể chuyện'}`));
      if (p.state !== 'completed') {
        previewBox.replaceChildren(head, el('p', p.state==='failed'?'sw-error':'sw-muted', p.state==='failed' ? (p.message||'Không tạo được bản nghe thử.') : `Đang tạo khoảng ${fmtMinutes(p.estimate)} nghe thử… ${p.message||''}`));
        return;
      }
      const audio = el('audio'); audio.controls = true; audio.preload = 'metadata';
      audio.src = `/api/voice-studio/tasks/${encodeURIComponent(p.id)}/audio/mp3?owner=${encodeURIComponent(p.owner)}`;
      const download = el('a','sw-btn'); download.href = audio.src + '&download=true'; download.append(icon('download'), el('span','','Tải MP3'));
      previewBox.replaceChildren(head, add(el('div','sw-player'), audio, download), el('span','sw-muted', p.duration ? `Dài thật: ${fmtClock(p.duration)}` : ''));
    }
    function renderSettings() {
      for (const t of tabs.children) {const on = t.dataset.tab === state.tab; t.classList.toggle('is-on', on); t.setAttribute('aria-selected', String(on));}
      if (!state.book) {tabBody.replaceChildren(); return;}
      tabBody.replaceChildren(state.tab === 'voice' ? voiceTab() : state.tab === 'gameplay' ? gameplayTab() : frameTab());
    }
    function voiceTab() {
      const s = {...settings()};
      const box = el('div','sw-tab-pane');
      const clean = value => {const out={...value};if(out.speech_engine!=='khanhtts')delete out.speech_reference_text;for(const k of Object.keys(out))if(out[k]===''||out[k]==null)delete out[k];return out;};
      function draw() {
        const engine = el('div','sw-segment');
        for (const [v,l] of [['vieneu','VieNeu'],['khanhtts','KhanhTTS']]) {const b=btn(l,()=>{s.speech_engine=v;draw();},'');b.setAttribute('aria-pressed',String((s.speech_engine||'vieneu')===v));engine.append(b);}
        const voiceOptions = state.voices.map(v=>[v.id, v.name + (v.kind==='clone'?' · giọng riêng':'')]);
        if (s.voice_id && !voiceOptions.some(([id])=>id===s.voice_id)) voiceOptions.push([s.voice_id, s.voice_id]);
        const voice = select(voiceOptions, s.voice_id, v=>{s.voice_id=v;draw();});
        const sample = iconBtn('play','Nghe mẫu giọng',()=>{const v=state.voices.find(x=>x.id===s.voice_id);if(!v?.sample_url)throw Error('Giọng này chưa có mẫu nghe. Mở Phòng thử giọng để nghe.');new Audio(v.sample_url).play().catch(e=>toast('Không phát được: '+e.message));});
        const rhythm = select(RHYTHMS, s.speech_rhythm||'story', v=>{s.speech_rhythm=v;});
        const speed = select(SPEEDS, String(Number(s.speech_speed||1)), v=>{s.speech_speed=Number(v);});
        const steps = select([['16','Nhanh · 16 bước'],['32','Chuẩn · 32 bước']], String(s.khanh_steps||32), v=>{s.khanh_steps=Number(v);});
        const reference = el('textarea'); reference.rows = 3; reference.value = s.speech_reference_text || ''; reference.placeholder = 'Dán đúng lời của bản thu mẫu (cần khi dùng giọng riêng với KhanhTTS)'; reference.oninput = () => {s.speech_reference_text = reference.value;};
        const batch = el('input'); batch.type='number'; batch.min=1; batch.max=512; batch.value = s.speech_batch_size || 256; batch.oninput = () => {s.speech_batch_size = Number(batch.value);};
        const link = el('a','','Mở Phòng thử giọng ↗'); link.href = '/resources?tab=voices';
        const khanh = (s.speech_engine||'vieneu') === 'khanhtts';
        box.replaceChildren(...[field('Công cụ giọng kể', engine), field('Giọng đọc', add(el('div','sw-inline'), voice, sample)), field('Nhịp đọc', rhythm), field('Tốc độ', speed),
          khanh ? field('Chất lượng KhanhTTS', steps) : null,
          add(el('p','sw-muted sw-link-row'), el('span','','Sắc thái theo bản thu tham chiếu. '), link),
          add(el('details','sw-advanced'), el('summary','','Mẫu giọng & nâng cao'), field('Batch giọng đọc (cụm/lượt)', batch), khanh ? field('Lời trong mẫu giọng riêng', reference) : null,
            el('p','sw-muted','Nhịp B thêm khoảng nghỉ theo dấu câu, đoạn và chỗ chuyển cảnh (đo khoảng lặng có sẵn rồi chỉ bù phần thiếu). 16/32 là số bước tinh chỉnh của KhanhTTS, không phải số câu. Không có nút chọn cảm xúc vì engine chưa hỗ trợ thật.')),
          btn('Lưu thiết lập cho truyện',()=>patchBook({settings:clean(s)},'Đã lưu thiết lập giọng cho truyện.'),'sw-wide','save')].filter(Boolean));
      }
      draw();
      return box;
    }
    function gameplayTab() {
      const box = el('div','sw-tab-pane');
      const clipInput = el('input'); clipInput.type='file'; clipInput.multiple=true; clipInput.accept='.mp4,.mkv,.mov,.webm,video/*'; clipInput.hidden=true;
      clipInput.onchange = async () => {try{await uploadClips([...clipInput.files]);}catch(e){toast(e.message);}finally{clipInput.value='';}};
      const items = state.gameplay.items.map(c=>({...c}));
      const l = layout();
      const summary = el('p','sw-muted',`${items.length} clip · ${fmtClock(state.gameplay.total_seconds)} dùng được` + (state.gameplay.cursor ? ` · chương sau tiếp tục từ clip ${state.gameplay.cursor.clip+1}, giây ${Math.round(state.gameplay.cursor.offset)}` : ''));
      const list = el('div','sw-clips');
      items.forEach((clip, index) => {
        const row = el('article','sw-clip'); if (!clip.available) row.classList.add('is-missing');
        const img = el('img'); img.src = clip.thumbnail; img.alt = ''; img.loading = 'lazy';
        const start = el('input'); start.type='number'; start.min=0; start.step=1; start.value=Math.round(clip.start); start.setAttribute('aria-label','Bắt đầu (giây)');
        const end = el('input'); end.type='number'; end.min=1; end.step=1; end.value=Math.round(clip.end); end.setAttribute('aria-label','Kết thúc (giây)');
        start.onchange = () => {clip.start = Number(start.value); savePlaylist(items).catch(e=>toast(e.message));};
        end.onchange = () => {clip.end = Number(end.value); savePlaylist(items).catch(e=>toast(e.message));};
        const up = iconBtn('up','Lên',()=>{items.splice(index-1,0,items.splice(index,1)[0]);return savePlaylist(items);}); up.disabled = index === 0;
        const down = iconBtn('down','Xuống',()=>{items.splice(index+1,0,items.splice(index,1)[0]);return savePlaylist(items);}); down.disabled = index === items.length-1;
        const remove = iconBtn('trash','Bỏ khỏi truyện này',()=>{items.splice(index,1);return savePlaylist(items);},'sw-danger');
        add(row, img, add(el('div','sw-clip-info'), el('strong','',clip.name), el('span','sw-muted',`${fmtClock(clip.duration)} · ${clip.width}×${clip.height} · ${Math.round(clip.fps)}fps${clip.has_audio?'':' · không tiếng'}${clip.available?'':' · KHÔNG THẤY TỆP'}`),
          add(el('div','sw-clip-range'), el('span','sw-muted','Dùng từ'), start, el('span','sw-muted','đến'), end, el('span','sw-muted','giây'))),
          add(el('div','sw-row-actions'), up, down, remove));
        list.append(row);
      });
      if (!items.length) list.append(el('p','sw-muted','Chưa có clip. Thêm video gameplay bạn đã quay (MP4/MKV/MOV/WebM). Clip được lưu một lần trong thư viện chung, dùng cho mọi truyện.'));
      const audio = el('input'); audio.type='checkbox'; audio.checked = Boolean(l.game_audio); audio.onchange = () => patchBook({layout:{game_audio:audio.checked}});
      const resume = el('input'); resume.type='checkbox'; resume.checked = l.continue_gameplay !== false; resume.onchange = () => patchBook({layout:{continue_gameplay:resume.checked}});
      add(box, summary, list, state.upload ? el('p','sw-muted',`Đang tải lên ${state.upload}`) : null,
        btn('Thêm clip gameplay',()=>clipInput.click(),'sw-wide','upload'), clipInput,
        add(el('label','sw-check'), audio, icon(l.game_audio?'sound':'mute'), el('span','',l.game_audio?'Tiếng game: Bật (nhỏ, dưới lời kể)':'Tiếng game: Tắt')),
        add(el('label','sw-check'), resume, el('span','','Chương sau tiếp tục từ chỗ gameplay chương trước dừng')),
        el('p','sw-muted','Clip ngắn hơn lời kể sẽ nối clip tiếp theo, hết danh sách thì lặp lại. Không tăng tốc game, không kéo khung hình đứng.'));
      return box;
    }
    function frameTab() {
      const l = {...layout()};
      const box = el('div','sw-tab-pane');
      const channel = el('input'); channel.type='text'; channel.maxLength=80; channel.value = l.channel || ''; channel.placeholder = 'Ví dụ: TRUYỆN ĐÊM';
      const background = select(state.backgrounds.map(b=>[b.id,b.name]), l.background || 'preset:dem-xanh', v=>{l.background=v;});
      const bgInput = el('input'); bgInput.type='file'; bgInput.accept='.png,.jpg,.jpeg,.webp'; bgInput.hidden=true;
      bgInput.onchange = async () => {const f=bgInput.files[0];if(!f)return;try{const r=await api('/api/story/backgrounds?name='+encodeURIComponent(f.name),{method:'PUT',body:f,raw:true});state.backgrounds=(await api('/api/story/backgrounds')).items;await patchBook({layout:{background:r.id}},'Đã thêm ảnh nền.');}catch(e){toast(e.message);}finally{bgInput.value='';}};
      const check = (key, label) => {const c=el('input');c.type='checkbox';c.checked=l[key]!==false;c.onchange=()=>{l[key]=c.checked;};return add(el('label','sw-check'),c,el('span','',label));};
      add(box, field('Tên kênh', channel), field('Ảnh nền', add(el('div','sw-inline'), background, iconBtn('upload','Tải ảnh nền lên',()=>bgInput.click()))), bgInput,
        el('h3','','Đầu ra'), add(el('div','sw-checks'), check('horizontal','Ngang 16:9'), check('vertical','Dọc 9:16'), check('burn_subtitles','Hiện phụ đề trên video'), check('export_srt','Xuất phụ đề SRT'), check('export_mp3','MP3 lời kể')),
        btn('Lưu khung hình cho truyện',()=>patchBook({layout:{...l, channel:channel.value}},'Đã lưu khung hình cho truyện.'),'sw-wide','save'),
        btn('Xem bố cục ngang / dọc',openLayout,'sw-wide sw-accent'));
      return box;
    }
    function renderFooter() {
      if (!state.book) return;
      const ids = state.allIds.filter(id => state.selected.has(id));
      const wordsSelected = ids.reduce((sum, id) => sum + (state.wordsById?.get(id) || 0), 0);
      const count = state.mode === 'merge' ? (ids.length ? 1 : 0) : ids.length;
      total.textContent = ids.length ? `${ids.length} chương đã chọn · khoảng ${fmtMinutes(estimateWords(wordsSelected))} lời kể` : 'Tick chọn chương để tạo video';
      enqueueButton.disabled = !ids.length;
      enqueueButton.textContent = state.mode === 'merge' && ids.length > 1 ? `Gộp ${ids.length} chương thành 1 video →` : `Thêm ${count} chương vào hàng đợi →`;
      modeSelect.value = state.mode;
    }

    // --- local draft backup (only the chapter being edited) --------------------------------------------------
    function readLocal(key) {try {return JSON.parse(global.localStorage.getItem(DRAFT_PREFIX+key)||'null');} catch {return null;}}
    function writeLocal(key, value) {try {global.localStorage.setItem(DRAFT_PREFIX+key, JSON.stringify(value));} catch {}}
    function removeLocal(key) {try {global.localStorage.removeItem(DRAFT_PREFIX+key);} catch {}}
    const beforeUnload = e => {if (state.dirty) {writeLocal('chapter.'+state.chapter.id, {base:state.chapter.revision, title:chapterName.value, text:text.value}); e.preventDefault();}};
    global.addEventListener('beforeunload', beforeUnload);

    renderAll();
    loadBooks().catch(error => toast(error.message));
    return {
      refresh: () => {if (state.book) loadChapters().then(loadGameplay).then(renderSettings).catch(e=>toast(e.message)); else loadBooks().catch(e=>toast(e.message));},
      save: () => saveChapter(false).catch(e=>toast(e.message)),
      destroy: () => {global.removeEventListener('beforeunload', beforeUnload); clearTimeout(saveTimer); clearTimeout(pollTimer); state.destroyed = true;},
    };
  }
  global.StoryWorkspace = {mount};
})(typeof window === 'undefined' ? globalThis : window);

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
    left:'<path d="M15 6l-6 6 6 6"/>', right:'<path d="M9 6l6 6-6 6"/>',
    mute:'<path d="M4 9h4l5-4v14l-5-4H4zM17 9l4 6M21 9l-4 6"/>', close:'<path d="M6 6l12 12M18 6L6 18"/>', spark:'<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>'};

  function mount(root, opts = {}) {
    const doc = root.ownerDocument;
    const toast = opts.toast || (m => console.log(m));
    const state = {books:[], book:null, chapters:[], total:0, totalWords:0, allIds:[], orderIds:[], view:'todo', counts:{todo:0,done:0}, page:1, q:'', selected:new Set(), chapter:null,
      dirty:false, saving:false, saveError:'', voices:[], gameplay:{items:[],total_seconds:0}, backgrounds:[], tab:'voice',
      mode:'each', target:30, audioOnly:false, enqueueKey:null, preview:null, destroyed:false, sources:[]};
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
    // Tải truyện từ WikiCV has its own window; this button opens it and always shows how the download is going.
    const crawlButton = btn('Tải từ WikiCV',()=>openCrawl(),'sw-crawl-button','download'); crawlButton.setAttribute('aria-live','polite');
    add(bar, add(el('div','sw-book-pick'),icon('book'),bookSelect), btn('Thêm truyện',newBook,'','plus'), drop,
      btn('Chọn thư mục',()=>{if('webkitdirectory' in folderInput)folderInput.click();else{toast('Trình duyệt chưa hỗ trợ chọn thư mục; hãy chọn nhiều tệp.');fileInput.click();}},'','folder'),
      btn('Truyện nguồn · biên tập ChatGPT',openSources,'','spark'), crawlButton, saveState, fileInput, folderInput);
    for (const input of [fileInput, folderInput]) input.onchange = async () => {try{await importFiles([...input.files]);}catch(e){toast(e.message);}finally{input.value='';}};

    // left: chapters
    const left = el('section','sw-panel sw-chapters');
    const search = el('input');search.type='search';search.placeholder='Tìm chương…';search.setAttribute('aria-label','Tìm chương');
    search.oninput = () => {clearTimeout(search.timer);search.timer=setTimeout(()=>{state.q=search.value;state.page=1;loadChapters();},250);};
    const selectAll = el('input');selectAll.type='checkbox';selectAll.onchange=()=>{state.selected=selectAll.checked?new Set(state.allIds):new Set();renderChapters();renderFooter();};
    const selectedCount = el('span');
    const statusFilter = select([['','Mọi chương'],['pending','Chưa duyệt'],['reviewed','Đã duyệt'],['issues','Cần sửa chữ']], '', v=>{state.status=v;state.page=1;loadChapters().catch(e=>toast(e.message));});
    statusFilter.setAttribute('aria-label','Lọc theo trạng thái duyệt');
    // Chưa làm / Đã xong: a chapter with a finished video lives only in Đã xong; search, filter and Chọn tất cả act on the open tab.
    const listTabs = el('div','sw-tabs sw-list-tabs');listTabs.setAttribute('role','tablist');listTabs.setAttribute('aria-label','Chương chưa làm hoặc đã xong');
    for (const key of ['todo','done']) {
      const t = btn('',async()=>{if(state.view===key)return;state.view=key;state.page=1;state.selected=new Set();state.enqueueKey=null;await loadChapters();},'sw-tab');
      t.dataset.view=key;t.setAttribute('role','tab');listTabs.append(t);
    }
    const chapterList = el('div','sw-chapter-list');
    const pager = el('div','sw-pager');
    // Cần kiểm tra cả truyện: every spot across the book in one list; tapping one opens that chapter at that spot.
    const issuesBox = el('details','sw-lint sw-book-issues'); issuesBox.hidden = true;
    add(left, el('h2','','Truyện & chương'), listTabs, add(el('div','sw-search'),search,statusFilter),
      add(el('div','sw-select-row'), selectedCount, add(el('label','sw-check'), selectAll, el('span','','Chọn tất cả'))), chapterList, pager, issuesBox,
      el('p','sw-muted sw-hint','Kéo ⠿ hoặc dùng ↑ ↓ để đổi thứ tự đọc.'));

    // middle: chapter editor
    const middle = el('section','sw-panel sw-editor');
    const editorTitle = el('h2');const editorSub = el('p','sw-muted','Đọc nguyên văn nội dung bạn đã sửa');
    const chapterName = el('input');chapterName.type='text';chapterName.maxLength=300;chapterName.oninput=()=>markDirty();
    const text = el('textarea','sw-text');text.spellcheck=false;text.oninput=()=>{markDirty();renderMeta();};
    const meta = el('span','sw-muted');
    const readTitle = el('input');readTitle.type='checkbox';readTitle.onchange=()=>markDirty();
    const reviewed = el('input');reviewed.type='checkbox';
    reviewed.onchange = async () => {
      try {const saved = await api('/api/story/chapters/'+state.chapter.id, json('PUT', {reviewed:reviewed.checked}));
        state.chapter.reviewed = saved.reviewed; const row = state.chapters.find(c=>c.id===saved.id); if (row) row.reviewed = saved.reviewed; renderChapters();
        if (saved.reviewed && state.status !== 'reviewed') toast('Đã đánh dấu duyệt.');}
      catch (error) {reviewed.checked = !reviewed.checked; toast(error.message);}
    };
    const sourceBox = el('textarea','sw-text sw-source-text'); sourceBox.readOnly = true; sourceBox.setAttribute('aria-label','Bản convert gốc');
    const sourceField = field('Bản convert gốc (chỉ đọc)', sourceBox, 'sw-text-field sw-source-field'); sourceField.hidden = true;
    const compare = btn('Xem bản convert', async () => {
      if (!sourceField.hidden) {sourceField.hidden = true; compareWrap.classList.remove('is-compare'); compare.lastChild.textContent = 'Xem bản convert'; return;}
      const source = await api('/api/story/chapters/'+state.chapter.id+'/source');
      sourceBox.value = source.text; sourceField.hidden = false; compareWrap.classList.add('is-compare'); compare.lastChild.textContent = 'Ẩn bản convert';
    }, '');
    const compareWrap = el('div','sw-compare');
    const previewBox = el('div','sw-preview');
    add(compareWrap, sourceField, field('Nội dung lời kể', text, 'sw-text-field'));
    // Soát chữ: what the TTS reads badly (rules "viết để nghe"); click an item to select that spot in the text.
    const lintBox = el('details','sw-lint'); lintBox.hidden = true;
    function renderLint(chapter) {
      const issues = chapter?.lint || [];
      lintBox.hidden = !chapter;
      const summary = el('summary','', issues.length ? `Soát chữ: ${issues.length} chỗ nên sửa${issues.length >= 300 ? ' (hiện 300 chỗ đầu)' : ''}` : 'Soát chữ: không thấy lỗi viết để nghe');
      const list = el('div','sw-lint-list');
      for (const issue of issues) {
        const item = el('button','sw-lint-item'); item.type = 'button';
        add(item, el('strong','',issue.label), el('span','sw-muted',issue.excerpt));
        item.onclick = () => jumpTo(issue);
        list.append(item);
      }
      lintBox.classList.toggle('is-clean', !issues.length);
      lintBox.replaceChildren(summary, list, el('p','sw-muted','Máy chỉ soát được ký hiệu, câu dài, số, chữ in hoa; tên riêng, xưng hô và người nói vẫn cần bạn đọc lại.'));
    }
    function jumpTo(issue, reveal = false) {
      if (state.dirty) {toast('Lưu chương trước để vị trí lỗi khớp với chữ.'); return;}
      const chars = [...text.value];  // server offsets count characters, the textarea counts UTF-16 units
      const start = chars.slice(0, issue.start).join('').length, end = chars.slice(0, issue.end).join('').length;
      if (reveal) text.scrollIntoView({block:'center'});  // on a phone the editor sits below the chapter list
      text.focus({preventScroll:true}); text.setSelectionRange(start, end);
      // Lines wrap (a phone wraps a lot), so counting "\n" lands far off: measure the spot in a copy of the box instead.
      const style = getComputedStyle(text), copy = el('div');
      for (const p of ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','paddingTop','paddingRight','paddingBottom','paddingLeft','borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth','boxSizing','tabSize','wordSpacing']) copy.style[p] = style[p];
      Object.assign(copy.style, {position:'absolute', visibility:'hidden', top:'0', left:'-9999px', whiteSpace:'pre-wrap', overflowWrap:'break-word', width:text.clientWidth + 'px', borderStyle:'solid'});
      const mark = el('span'); mark.textContent = text.value.slice(start, end) || '.';
      copy.append(doc.createTextNode(text.value.slice(0, start)), mark); doc.body.append(copy);
      const top = mark.offsetTop, height = mark.offsetHeight; copy.remove();
      text.scrollTop = Math.max(0, top - Math.max(0, (text.clientHeight - Math.min(height, text.clientHeight)) / 2));
    }
    async function loadIssues(code = issuesBox.code || '') {
      if (!state.book) {issuesBox.hidden = true; return;}
      const book = state.book.id;
      const data = await api(`/api/story/books/${book}/issues?code=${encodeURIComponent(code)}`);
      if (state.book?.id !== book) return;
      issuesBox.code = data.counts[code] ? code : ''; issuesBox.hidden = false;
      const summary = el('summary','', data.total ? `Cần kiểm tra cả truyện: ${data.total.toLocaleString('vi-VN')} chỗ ở ${data.chapters} chương` : 'Cần kiểm tra cả truyện: không còn chỗ nào');
      const kinds = select([['', `Mọi loại (${data.total})`], ...Object.entries(data.counts).sort((a, b) => b[1].count - a[1].count).map(([k, v]) => [k, `${v.label} (${v.count})`])],
        issuesBox.code, v => loadIssues(v).catch(e => toast(e.message)));
      kinds.setAttribute('aria-label','Loại cần kiểm tra');
      const list = el('div','sw-lint-list');
      for (const issue of data.items) {
        const item = el('button','sw-lint-item'); item.type = 'button';
        add(item, el('strong','',`Chương ${String(issue.order).padStart(2,'0')} · ${issue.label}`), el('span','sw-muted',issue.excerpt));
        item.onclick = async () => {
          try {if (state.chapter?.id !== issue.chapter_id) await openChapter(issue.chapter_id); jumpTo(issue, true);}
          catch (error) {toast(error.message);}
        };
        list.append(item);
      }
      issuesBox.classList.toggle('is-clean', !data.total);
      const noteCount = data.counts.note?.count || 0;
      // Xoá lời bình: every author/translator note of the book at once; each chapter keeps its old text in Bản cũ.
      const strip = noteCount ? btn(`Xoá lời bình cả truyện (${noteCount} chỗ)`, async () => {
        if (!confirm(`Xoá ${noteCount} đoạn lời tác giả, lời người dịch, xin bình luận… trong cả truyện?\nBản trước khi xoá vẫn giữ trong "Bản cũ" của từng chương.`)) return;
        if (state.chapter) await saveChapter(false);
        const result = await api(`/api/story/books/${state.book.id}/strip-notes`, json('POST', {}));
        toast(`Đã xoá ${result.parts} đoạn lời bình ở ${result.chapters} chương.` + (result.skipped.length ? ` Bỏ qua chương ${result.skipped.join(', ')} vì cả chương chỉ có lời bình, bạn xem và xoá chương đó.` : ''));
        if (state.chapter) await openChapter(state.chapter.id);
        await loadChapters();
      }, 'sw-danger', 'trash') : null;
      issuesBox.replaceChildren(summary, ...(data.total ? [kinds] : []), ...(strip ? [strip] : []), list,
        ...(data.more ? [el('p','sw-muted',`Còn ${data.more.toLocaleString('vi-VN')} chỗ nữa: chọn từng loại để xem tiếp.`)] : []),
        el('p','sw-muted','Bấm một mục để mở đúng chương và bôi đen chỗ đó. Sửa xong bấm Lưu chương, danh sách tự cập nhật.'));
    }
    function refreshIssues() {clearTimeout(issuesBox.timer); issuesBox.timer = setTimeout(() => loadIssues().catch(() => {}), 400);}
    add(middle, add(el('div','sw-editor-head'), editorTitle, editorSub), field('Tên chương', chapterName), compareWrap, lintBox,
      add(el('div','sw-meta-row'), meta, add(el('label','sw-check'), readTitle, el('span','','Đọc tên chương')), add(el('label','sw-check sw-reviewed'), reviewed, el('span','','Đã duyệt'))),
      add(el('div','sw-editor-actions'), btn('Lưu chương',()=>saveChapter(true),'','save'), btn('Đọc thử khoảng 1 phút',previewVoice,'sw-accent','play'), compare, btn('Bản cũ',openHistory,''),
        btn('Đọc lại câu đang chọn',retakeSelection,'','sound')),
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
    const modeSelect = select([['each','Mỗi chương một video'],['group','Gộp thành tập theo độ dài'],['merge','Gộp chương đã chọn thành một video']], state.mode, v=>{state.mode=v;state.enqueueKey=null;renderFooter();});
    const targetSelect = select([['15','khoảng 15 phút'],['20','khoảng 20 phút'],['30','khoảng 30 phút'],['45','khoảng 45 phút'],['60','khoảng 60 phút'],['90','khoảng 90 phút']], '30',
      v=>{state.target=Number(v);state.enqueueKey=null;renderFooter();});
    targetSelect.setAttribute('aria-label','Độ dài mỗi tập');
    // Mirrors the server: consecutive chapters fill an episode until it would pass the target by more than half a chapter.
    function groupsFor(ids) {
      if (state.mode === 'each') return ids.map(id=>[id]);
      if (state.mode === 'merge') return ids.length ? [ids] : [];
      const out = []; let current = [], length = 0;
      for (const id of ids) {const sec = estimateWords(state.wordsById?.get(id)||0);
        if (current.length && length + sec/2 > state.target*60) {out.push(current); current = []; length = 0;}
        current.push(id); length += sec;}
      if (current.length) out.push(current);
      return out;
    }
    modeSelect.setAttribute('aria-label','Cách tạo video');
    const enqueueButton = btn('',enqueue,'sw-primary');
    const audioOnly = el('input'); audioOnly.type = 'checkbox';
    audioOnly.onchange = () => {state.audioOnly = audioOnly.checked; state.enqueueKey = null; renderFooter();};
    const audioOnlyLabel = add(el('label','sw-check sw-audio-only'), audioOnly, el('span','','Chỉ làm lời đọc (MP3)'));
    audioOnlyLabel.title = 'Đọc trước thành MP3 để nghe duyệt. Khi dựng video sau, giọng đã đọc được dùng lại, không đọc lại.';
    // Làm dần cả truyện: the chapters not yet made go into the queue one episode at a time (the chosen way of making
    // episodes); the book stops by itself when the new gameplay is too short for the next episode, and goes on when clips arrive.
    const autorunBar = el('div','sw-autorun'); autorunBar.hidden = true; autorunBar.setAttribute('role','status'); autorunBar.setAttribute('aria-live','polite');
    const autorunButton = btn('Làm dần cả truyện',startAutorun,'sw-autorun-start','play');
    autorunButton.title = 'Đưa lần lượt các chương chưa làm vào hàng đợi, mỗi lần một tập (theo cách tạo video đang chọn). Hết gameplay mới thì tạm dừng và báo; có clip mới đủ thì tự chạy tiếp.';
    add(footer, autorunBar, total, modeSelect, targetSelect, audioOnlyLabel, btn('Lưu nháp',()=>saveChapter(true),'','save'), autorunButton, enqueueButton);
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
      // The voice list can be slow (it reads every voice's profile): books open first, the voice tab fills in when it arrives.
      if (!state.voices.length) api('/api/voices').then(voices => {
        state.voices = (voices.voices||voices.items||[]).filter(v=>v.selectable!==false);
        if (state.book) {renderSettings(); renderMeta(); renderFooter();}
      }).catch(() => {});
      const [books, backgrounds] = await Promise.all([api('/api/story/books'), api('/api/story/backgrounds').catch(()=>({items:[]}))]);
      state.books = books.items; state.backgrounds = backgrounds.items; state.loaded = true;
      api('/api/settings/output-root').then(info => {state.disk = info; renderFooter();}).catch(() => {});
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
      state.autorun = null; renderAutorun();
      await Promise.all([loadChapters(true), loadGameplay(), loadAutorun()]);
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
      const data = await api(`/api/story/books/${state.book.id}/chapters?page=${state.page}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(state.q)}&status=${state.status||''}&view=${state.view}`);
      state.chapters = data.items; state.total = data.total; state.totalWords = data.total_words; state.allIds = data.all_ids;
      state.orderIds = data.order_ids || data.all_ids; state.counts = data.counts || {todo:data.total, done:0};
      state.wordsById = new Map(Object.entries(data.words_by_id || {}));
      state.selected = new Set([...state.selected].filter(id => state.allIds.includes(id)));
      if ((openFirst || !state.chapter) && data.items[0]) await openChapter(data.items[0].id);
      renderChapters(); renderFooter(); refreshIssues();
    }
    async function openChapter(id) {
      if (state.chapter && state.chapter.id !== id) await saveChapter(false);
      const chapter = await api('/api/story/chapters/'+id);
      const draft = readLocal('chapter.'+id);
      state.chapter = chapter; state.dirty = false; state.saveError = '';
      chapterName.value = chapter.title; text.value = chapter.text; readTitle.checked = chapter.read_title; reviewed.checked = Boolean(chapter.reviewed);
      sourceField.hidden = true; compareWrap.classList.remove('is-compare'); compare.lastChild.textContent = 'Xem bản convert';
      renderLint(chapter);
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
        if (state.chapter?.id === id) {state.chapter = saved; state.dirty = chapterName.value !== saved.title || text.value !== saved.text; renderLint(saved);}
        refreshIssues();
        removeLocal('chapter.'+id); state.enqueueKey = null;
        const row = state.chapters.find(c=>c.id===id); if (row) Object.assign(row, {title:saved.title, words:saved.words, revision:saved.revision, issues:saved.issues});
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
      const shown = state.allIds, at = shown.indexOf(id), neighbour = shown[at + delta];
      if (at < 0 || !neighbour) return;
      const ids = state.orderIds.filter(x => x !== id);
      ids.splice(ids.indexOf(neighbour) + (delta > 0 ? 1 : 0), 0, id); await reorder(ids);
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

    async function openHistory() {
      if (!state.chapter) return;
      await saveChapter(false);
      const data = await api(`/api/story/chapters/${state.chapter.id}/history`);
      const dialog = el('dialog','sw-dialog sw-history-dialog');
      const close = () => {dialog.close(); dialog.remove();};
      const list = el('div','sw-source-list');
      for (const item of data.items) {
        const when = new Date(item.saved*1000).toLocaleString('vi-VN');
        list.append(add(el('article','sw-source'), add(el('div','sw-source-info'), el('strong','',`Bản ${item.revision} · ${item.title}`), el('span','sw-muted',`${when} · ${item.reason} · ${item.characters.toLocaleString('vi-VN')} ký tự`)),
          btn('Khôi phục bản này', async () => {const saved = await api(`/api/story/chapters/${state.chapter.id}/restore`, json('POST', {revision:item.revision})); close(); state.dirty = false; await openChapter(saved.id); toast('Đã khôi phục. Bản đang có trước đó cũng được cất lại trong Bản cũ.');}, 'sw-accent')));
      }
      if (!data.items.length) list.append(el('p','sw-muted','Chương này chưa có bản cũ nào.'));
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Bản cũ của chương'), el('p','sw-muted','Mỗi lần lưu hoặc nhập bản mới, tool cất lại bản trước đó.')), iconBtn('close','Đóng',close)), list);
      doc.body.append(dialog); dialog.showModal(); dialog.addEventListener('cancel', () => dialog.remove());
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
    // Same rule as the server: whole words only, longest first, case-insensitive; subtitles keep the written text.
    function speak(textValue, rules) {
      const list = [...(rules||[])].sort((a,b)=>b.from.length-a.from.length);
      let out = textValue;
      for (const r of list) {
        const escaped = r.from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        out = out.replace(new RegExp('(?<![\\p{L}\\p{N}_])' + escaped + '(?![\\p{L}\\p{N}_])', 'giu'), r.to);
      }
      return out;
    }
    const parseRules = value => value.split('\n').map(line => line.split(/\s*(?:=>|→|=)\s*/)).filter(p => p.length >= 2 && p[0].trim() && p.slice(1).join('=').trim())
      .map(p => ({from:p[0].trim(), to:p.slice(1).join('=').trim()}));
    // "Đọc lại câu đang chọn": the selected sentence gets a fresh reading the next time its chapter is queued.
    async function retakeSelection() {
      if (!state.book || !state.chapter) throw Error('Chọn một chương trước.');
      const picked = text.value.slice(text.selectionStart, text.selectionEnd).trim();
      if (!picked) throw Error('Bôi đen câu bị đọc sai trong ô nội dung chương, rồi bấm lại.');
      const result = await api(`/api/story/books/${state.book.id}/retake`, json('POST', {text:picked}));
      if (result.book) {state.book = result.book;}
      toast(`Đã đánh dấu đọc lại (lần ${result.take}). Thêm chương này vào hàng đợi lại: chỉ câu đó được đọc mới, phần còn lại dùng giọng đã có.`);
    }
    async function previewVoice() {
      if (!state.chapter) throw Error('Chọn một chương trước.');
      const s = settings();
      const heading = readTitle.checked ? `Chương ${state.chapter.number || orderOf(state.chapter.id)}. ${chapterName.value}.\n` : '';
      const body = {text:speak((heading + sampleText(text.value)).trim(), s.pronunciations), voice_id:s.voice_id, speech_engine:s.speech_engine||'vieneu', speech_rhythm:s.speech_rhythm||'story',
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
    const orderOf = id => state.orderIds.indexOf(id) + 1;

    // --- gameplay ----------------------------------------------------------------------------------------
    async function loadGameplay() {
      if (!state.book) return;
      const [gameplay, folder] = await Promise.all([api('/api/story/gameplay?book_id='+state.book.id), api('/api/story/gameplay/drive-folder').catch(() => null)]);
      state.gameplay = gameplay; state.driveFolder = folder;
      watchFolder();
    }
    // While the Drive folder is fetching clips, refresh the Gameplay tab every 2 s; reload the playlist when it ends.
    function watchFolder() {
      clearTimeout(state.folderTimer);
      if (state.driveFolder?.task?.state !== 'running') return;
      state.folderTimer = setTimeout(async () => {
        if (state.destroyed) return;
        try {
          state.driveFolder = await api('/api/story/gameplay/drive-folder');
          if (state.driveFolder.task.state !== 'running') {await loadGameplay(); renderFooter();}
          if (state.tab === 'gameplay') renderSettings();
        } catch {}
        watchFolder();
      }, 2000);
    }
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
      const close = () => {clearInterval(dialog.timer); crawlViews.delete(onCrawl); dialog.close(); dialog.remove();};
      const crawlBox = add(el('div','sw-crawl-link'), el('span','sw-muted','Truyện mới, tiến độ tải và lỗi khi tải nằm trong cửa sổ riêng.'),
        btn('Tải truyện từ WikiCV',()=>openCrawl(),'sw-accent','download'));
      const crawlRunning = () => Boolean(state.crawl?.running);
      const onCrawl = (data, finished) => {if (finished) {list.dataset.signature=''; refresh();}};
      crawlViews.add(onCrawl);
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Truyện nguồn'),
        el('p','sw-muted','Tải truyện từ WikiCV, rồi tool gửi từng chương cho ChatGPT biên tập theo quy tắc viết để nghe, tự kiểm tra rồi gộp lại; chương đã xong không gửi lại.')), iconBtn('close','Đóng',close)), crawlBox, list);
      async function refresh() {
        let data; try {data = await api('/api/story/sources');} catch (error) {list.replaceChildren(el('p','sw-error',error.message)); return;}
        const signature = JSON.stringify(data); if (signature === list.dataset.signature) return; list.dataset.signature = signature;
        if (data.root_missing || !data.items.length) {list.replaceChildren(el('p','sw-muted','Chưa thấy truyện nào trong thư mục wikicv_auto_v3_2_mixed_titles/du_lieu_truyen.')); return;}
        list.replaceChildren(...data.items.map(source => {
          const row = el('article','sw-source');
          const progress = el('progress'); progress.max = source.chapters || 1; progress.value = source.edited;
          const status = source.pausing ? 'Đang tạm dừng…' : source.running ? `Đang biên tập ${source.edited}/${source.chapters} chương…` : source.paused ? `Đã tạm dừng ở ${source.edited}/${source.chapters} chương` : source.edited >= source.chapters && source.chapters ? 'Đã biên tập xong' : source.edited ? `Đã biên tập ${source.edited}/${source.chapters} chương` : 'Chưa biên tập';
          const path = `/api/story/sources/${encodeURIComponent(source.name)}`;
          add(row, add(el('div','sw-source-info'), el('strong','',source.title), el('span','sw-muted',`${source.chapters} chương${source.downloaded?` (${source.downloaded} mục đã tải)`:''} · ${status}` + (source.needs_review.length ? ` · cần xem lại: ${source.needs_review.join(', ')}` : '')), progress,
            source.log.length ? el('pre','sw-source-log',source.log.join('\n') + (source.status ? `\n… ${source.status}` : '')) : null, source.error ? el('p','sw-error',source.error) : null),
            add(el('div','sw-source-actions'),
              source.url ? (()=>{const b=btn('Tải chương mới',async()=>{await startCrawl(source.url, 0); openCrawl();},'','upload');b.disabled=crawlRunning();b.title='Chạy lại công cụ tải: chỉ lấy các chương mới đăng trên WikiCV';return b;})() : null,
              // Tạm dừng: the chapter not yet typed is withdrawn; one already sent is still read, so Tiếp tục does not send it again.
              source.running ? (()=>{const b=btn(source.pausing?'Đang tạm dừng…':'Tạm dừng',async()=>{await api(`${path}/pause`, json('POST',{}));toast('Đang tạm dừng. Chương đã xong được giữ; bấm Tiếp tục để làm tiếp.');refresh();},'');b.disabled=source.pausing;return b;})() :
              (()=>{const b=btn(source.paused?'Tiếp tục':source.edited&&source.edited<source.chapters?'Biên tập tiếp':'Biên tập bằng ChatGPT',async()=>{await api(`${path}/edit`, json('POST',{}));toast(source.paused?'Đã tiếp tục biên tập.':'Đã bắt đầu biên tập. Có thể đóng cửa sổ này; tool vẫn chạy.');refresh();},source.paused?'sw-accent':'');b.disabled=source.edited>=source.chapters&&source.chapters>0;return b;})(),
              (()=>{const b=btn(source.book_id?'Cập nhật vào Kể truyện':'Nhập vào Kể truyện',async()=>{const r=await api(`/api/story/sources/${encodeURIComponent(source.name)}/import`, json('POST',{}),120000);toast(`Đã nhập: thêm ${r.added}, cập nhật ${r.updated} chương`+(r.kept?`, giữ nguyên ${r.kept} chương bạn đã sửa.`:'.'));close();await loadBooks(r.book.id);},'sw-accent');b.disabled=!source.merged;b.title=source.merged?'':'Biên tập trước để có bản đọc được';return b;})()));
          return row;
        }));
      }
      doc.body.append(dialog); dialog.showModal(); dialog.addEventListener('cancel', () => {clearInterval(dialog.timer); crawlViews.delete(onCrawl); dialog.remove();});
      await refresh(); dialog.timer = setInterval(refresh, 5000);
    }

    // --- Tải truyện từ WikiCV: its own window + the bar button's live state -----------------------------------
    // The user's own crawl_wikicv.py runs on the server (robots.txt, 2–4 s between chapters, stops when blocked).
    const crawlViews = new Set();
    const crawlTitle = d => d.title || d.url || '';
    const crawlHead = d => d.running ? `Đang tải: ${crawlTitle(d)}` : d.error ? `Dừng vì lỗi: ${crawlTitle(d)}` : d.stopped ? `Đã dừng: ${crawlTitle(d)}` : `Đã tải xong: ${crawlTitle(d)}`;
    function renderCrawlButton() {
      const d = state.crawl || {};
      const label = crawlButton.lastChild;
      crawlButton.classList.toggle('is-running', Boolean(d.running));
      crawlButton.classList.toggle('is-error', Boolean(!d.running && d.error));
      label.textContent = d.running ? `Đang tải · ${d.saved || 0} chương` : d.error ? 'Tải truyện bị lỗi' : 'Tải từ WikiCV';
      crawlButton.title = d.url ? crawlHead(d) : 'Tải truyện mới từ WikiCV';
    }
    async function pollCrawl() {
      clearTimeout(state.crawlTimer);
      if (state.destroyed) return;
      try {
        const data = await api('/api/story/crawl');
        const finished = Boolean(state.crawl?.running && !data.running);
        state.crawl = data; renderCrawlButton();
        for (const view of crawlViews) view(data, finished);
        if (finished) toast(data.error ? `Tải truyện dừng vì lỗi: ${data.error}` : `${crawlHead(data)} · ${data.saved} chương mới.`);
      } catch {}
      state.crawlTimer = setTimeout(pollCrawl, state.crawl?.running ? 2500 : 30000);
    }
    async function startCrawl(url, max) {
      await api('/api/story/crawl', json('POST', {url, max_chapters: max || 0}));
      toast('Đã bắt đầu tải. Có thể đóng cửa sổ; tiến độ hiện ở nút Tải từ WikiCV.');
      await pollCrawl();
    }
    function openCrawl() {
      const dialog = el('dialog','sw-dialog sw-crawl-dialog');
      const urlInput = el('input'); urlInput.type='url'; urlInput.placeholder='https://wikicv.org/truyen/ten-truyen-…'; urlInput.setAttribute('aria-label','Link trang giới thiệu truyện trên WikiCV');
      const limitInput = el('input'); limitInput.type='number'; limitInput.min='0'; limitInput.max='5000'; limitInput.value='0'; limitInput.title='0 = tải đến chương mới nhất'; limitInput.setAttribute('aria-label','Số chương tối đa');
      const startButton = btn('Tải truyện',()=>startCrawl(urlInput.value.trim(), Number(limitInput.value)),'sw-accent','download');
      const statusBox = el('section','sw-crawl-status');
      const close = () => {crawlViews.delete(draw); dialog.close(); dialog.remove();};
      const when = t => t ? new Date(t * 1000).toLocaleString('vi-VN', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit'}) : '';
      function draw(d) {
        startButton.disabled = Boolean(d.running);
        if (!d.url) {statusBox.replaceChildren(el('p','sw-muted','Chưa tải truyện nào. Dán link ở trên rồi bấm Tải truyện.')); return;}
        const facts = [`${d.saved || 0} chương mới`, d.known ? `${d.known} chương đã có` : '', d.total ? `tổng ${d.total} chương đã lưu` : '', d.position ? `đang ở mục ${d.position}` : '',
          d.complete === true ? 'đã đến chương mới nhất' : d.complete === false ? 'chưa đến chương mới nhất' : ''].filter(Boolean).join(' · ');
        const times = [d.started ? 'bắt đầu ' + when(d.started) : '', d.finished ? 'kết thúc ' + when(d.finished) : ''].filter(Boolean).join(' · ');
        const log = el('pre','sw-source-log sw-crawl-log', (d.log || []).join('\n') || 'Chưa có nhật ký.');
        statusBox.replaceChildren(
          add(el('div','sw-crawl-head'), el('strong','',crawlHead(d)),
            d.running ? btn('Dừng',async()=>{await api('/api/story/crawl/stop', json('POST',{})); await pollCrawl();},'','close') : null),
          el('span','sw-muted', facts + (d.last ? ` · vừa lưu: ${d.last}` : '')), times ? el('span','sw-muted', times) : null,
          d.error ? el('p','sw-warning', d.error) : null, el('strong','sw-crawl-log-title','Nhật ký'), log);
        log.scrollTop = log.scrollHeight;
      }
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Tải truyện từ WikiCV'),
          el('p','sw-muted','Dán link trang giới thiệu truyện. Chương đã tải không tải lại; chạy lại để lấy chương mới. Tool tải chậm (2–4 giây mỗi chương) và tự dừng nếu trang chặn. Tải xong, mở Truyện nguồn để biên tập bằng ChatGPT.')),
          iconBtn('close','Đóng',close)),
        add(el('div','sw-crawl-form'), urlInput, add(el('label','sw-crawl-limit'), el('span','sw-muted','Tối đa'), limitInput, el('span','sw-muted','chương')), startButton),
        statusBox);
      crawlViews.add(draw);
      draw(state.crawl || {});
      doc.body.append(dialog); dialog.showModal(); dialog.addEventListener('cancel', () => {crawlViews.delete(draw); dialog.remove();});
      pollCrawl();
    }
    pollCrawl();  // the bar button shows a download that is running (or failed) as soon as the page opens

    // --- queue -------------------------------------------------------------------------------------------
    async function enqueue() {
      await saveChapter(false);
      if (state.dirty) throw Error('Chưa lưu được chương đang sửa. Kiểm tra lỗi lưu rồi thử lại.');
      const ids = state.allIds.filter(id => state.selected.has(id));
      if (!ids.length) throw Error('Tick chọn ít nhất một chương trong danh sách.');
      if (!state.audioOnly && !state.gameplay.items.some(c=>c.available)) {state.tab='gameplay';renderSettings();throw Error('Chưa có clip gameplay. Thêm clip trong tab Gameplay, hoặc tick "Chỉ làm lời đọc (MP3)" để nghe trước.');}
      const l = layout(); if (!state.audioOnly && !l.horizontal && !l.vertical) {state.tab='frame';renderSettings();throw Error('Chọn ít nhất một định dạng xuất: ngang hoặc dọc.');}
      state.enqueueKey ||= 'story-' + uuid();
      enqueueButton.disabled = true; enqueueButton.textContent = 'Đang thêm vào hàng đợi…';
      try {
        const result = await api(`/api/story/books/${state.book.id}/enqueue`, json('POST', {chapter_ids:ids, mode:state.mode, target_minutes:state.target, audio_only:state.audioOnly}, {'Idempotency-Key':state.enqueueKey}), 120000);
        toast(state.audioOnly ? `Đã thêm ${result.videos} bản lời đọc vào hàng đợi. Nghe ở Kho video khi xong.` : `Đã thêm ${result.videos} video vào hàng đợi.`); state.enqueueKey = null; state.selected = new Set(); renderChapters();
        if (opts.openQueue && global.confirm(`Đã thêm ${result.videos} video vào hàng đợi. Mở Hàng đợi để theo dõi?`)) opts.openQueue();
      } finally {renderFooter();}
    }

    // --- rendering -----------------------------------------------------------------------------------------
    // --- Làm dần cả truyện ------------------------------------------------------------------------------------
    async function loadAutorun() {
      if (!state.book) return;
      const bookId = state.book.id;
      const data = await api(`/api/story/books/${bookId}/autorun`).catch(() => null);
      if (!data || state.book?.id !== bookId) return;
      const before = state.autorun;
      state.autorun = data; renderAutorun();
      // an episode finished meanwhile: the chapter tabs move it to Đã xong
      if (before && before.todo != null && data.todo != null && before.todo !== data.todo) loadChapters().catch(() => {});
      clearTimeout(state.autorunTimer);
      if (data.state !== 'off' && !state.destroyed) state.autorunTimer = setTimeout(() => loadAutorun().catch(() => {}), 15000);
    }
    async function autorunAction(body) {
      state.autorun = await api(`/api/story/books/${state.book.id}/autorun`, json('POST', body), 120000);
      renderAutorun(); loadChapters().catch(() => {});
      clearTimeout(state.autorunTimer);
      if (state.autorun.state !== 'off') state.autorunTimer = setTimeout(() => loadAutorun().catch(() => {}), 15000);
    }
    async function startAutorun() {
      const mode = state.mode === 'group' ? 'group' : 'each';
      await autorunAction({action:'start', mode, target_minutes:state.target});
      toast(mode === 'group' ? `Làm dần cả truyện: mỗi lần một tập khoảng ${state.target} phút.` : 'Làm dần cả truyện: mỗi lần một chương.');
    }
    function renderAutorun() {
      const run = state.autorun;
      const on = Boolean(run && run.state !== 'off');
      autorunBar.hidden = !on; autorunButton.hidden = on || !state.book;
      if (!on) {autorunBar.replaceChildren(); return;}
      const warn = run.state === 'waiting_gameplay' || run.state === 'error';
      autorunBar.className = 'sw-autorun' + (warn ? ' is-warning' : run.state === 'paused' ? ' is-paused' : '');
      const how = run.mode === 'group' ? `tập khoảng ${run.target_minutes} phút` : 'mỗi chương một video';
      const head = {running:'Đang làm dần cả truyện', waiting_gameplay:'Tạm dừng: thiếu gameplay mới', error:'Tạm dừng vì lỗi', paused:'Đã tạm dừng'}[run.state] || 'Làm dần cả truyện';
      const detail = [how, run.todo != null ? `còn ${run.todo} chương chưa làm` : '', run.reuse ? 'đang dùng lại clip đã dùng' : ''].filter(Boolean).join(' · ');
      const actions = add(el('div','sw-autorun-actions'),
        run.state === 'running' ? btn('Tạm dừng', () => autorunAction({action:'pause'})) : btn('Tiếp tục', () => autorunAction({action:'resume'}), 'sw-accent', 'play'),
        btn('Dừng hẳn', async () => {
          if (!global.confirm('Dừng hẳn làm dần cả truyện này? Tập đang trong hàng đợi vẫn làm xong; các chương còn lại không được xếp tiếp.')) return;
          await autorunAction({action:'stop'}); toast('Đã dừng hẳn làm dần cả truyện.');
        }));
      autorunBar.replaceChildren(add(el('div','sw-autorun-text'), el('strong','',head), el('span','',run.message || ''), el('span','sw-muted',detail)), actions);
    }

    function renderAll() {renderEmpty(); renderChapters(); renderEditor(); renderSettings(); renderFooter(); renderSaveState(); renderAutorun();}
    function renderEmpty() {
      const none = !state.book;
      columns.hidden = none; footer.hidden = none;
      empty.hidden = !none;
      if (none && !state.loaded) {empty.replaceChildren(el('p','sw-muted','Đang mở truyện…')); return;}
      if (none) empty.replaceChildren(el('h2','','Chưa có truyện nào'), el('p','sw-muted','Bấm Thêm truyện, thả tệp TXT vào đây, hoặc mở Truyện nguồn để biên tập truyện tải từ wikicv bằng ChatGPT.'),
        add(el('div','sw-empty-actions'), btn('Thêm truyện',newBook,'sw-primary','plus'), btn('Truyện nguồn · biên tập ChatGPT',openSources,'','spark')));
    }
    function renderSaveState() {
      saveState.classList.toggle('is-error', Boolean(state.saveError));
      saveState.textContent = state.saveError ? '⚠ ' + state.saveError : state.saving ? 'Đang lưu…' : state.dirty ? 'Chưa lưu' : state.chapter ? '✓ Đã lưu chương' : '';
    }
    function renderChapters() {
      if (!state.book) return;
      for (const t of listTabs.children) {
        const on = t.dataset.view === state.view; t.classList.toggle('is-on', on); t.setAttribute('aria-selected', String(on));
        t.replaceChildren(el('span','',t.dataset.view === 'done' ? 'Đã xong' : 'Chưa làm'), el('span','sw-tab-count',String(state.counts[t.dataset.view] ?? 0)));
      }
      selectedCount.textContent = `${state.selected.size} chương đã chọn`;
      selectAll.checked = state.allIds.length > 0 && state.selected.size === state.allIds.length;
      selectAll.indeterminate = state.selected.size > 0 && state.selected.size < state.allIds.length;
      chapterList.replaceChildren(...state.chapters.map(chapter => {
        const row = el('article','sw-chapter'); row.classList.toggle('is-active', chapter.id === state.chapter?.id); row.draggable = !state.q;
        row.ondragstart = e => {if(e.target.closest('button,input')){e.preventDefault();return;}dragId=chapter.id;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',chapter.id);};
        row.ondragend = () => {dragId = null;}; row.ondragover = e => {if(dragId)e.preventDefault();};
        row.ondrop = async e => {if(!dragId||dragId===chapter.id)return;e.preventDefault();const ids=[...state.orderIds];const from=ids.indexOf(dragId);ids.splice(from,1);ids.splice(ids.indexOf(chapter.id)+(from<ids.indexOf(chapter.id)+1?1:0),0,dragId);dragId=null;try{await reorder(ids);}catch(err){toast(err.message);}};
        const check = el('input'); check.type='checkbox'; check.checked = state.selected.has(chapter.id); check.setAttribute('aria-label','Chọn '+chapter.title);
        check.onchange = () => {if(check.checked)state.selected.add(chapter.id);else state.selected.delete(chapter.id);state.enqueueKey=null;renderChapters();renderFooter();};
        const open = el('button','sw-chapter-open'); open.type='button'; open.onclick = () => openChapter(chapter.id).catch(e=>toast(e.message));
        add(open, add(el('strong'), el('span','sw-order',String(chapter.order).padStart(2,'0')), el('span','',chapter.title), chapter.issues ? el('span','sw-badge sw-badge-warn',`⚠ ${chapter.issues}`) : null, chapter.reviewed ? el('span','sw-badge','✓ duyệt') : null), el('span','sw-muted',`${chapter.words.toLocaleString('vi-VN')} từ · khoảng ${fmtMinutes(estimateWords(chapter.words))}`));
        const position = state.allIds.indexOf(chapter.id);
        const up = iconBtn('up','Đưa lên',()=>moveChapter(chapter.id,-1)); up.disabled = position <= 0 || Boolean(state.q);
        const down = iconBtn('down','Đưa xuống',()=>moveChapter(chapter.id,1)); down.disabled = position >= state.allIds.length-1 || Boolean(state.q);
        const grip = el('span','sw-grip'); grip.append(icon('grip')); grip.title = 'Kéo để đổi thứ tự';
        const rename = iconBtn('edit','Đổi tên',()=>renameChapter(chapter)), remove = iconBtn('trash','Xoá khỏi thư viện',()=>deleteChapters([chapter.id]),'sw-danger');
        add(row, grip, check, open, add(el('div','sw-row-actions'), up, down, rename, remove));
        return row;
      }));
      if (!state.chapters.length) chapterList.append(el('p','sw-muted sw-list-empty', state.q || state.status ? 'Không có chương khớp.' : state.view === 'done' ? 'Chưa có chương nào làm xong video. Video trong hàng đợi làm xong thì chương chuyển sang đây.' : state.counts.done ? 'Mọi chương đều đã có video. Xem ở tab Đã xong.' : 'Chưa có chương. Thả tệp TXT (mỗi tệp một chương) hoặc một tệp gộp có tiêu đề “Chương N”.'));
      const pages = Math.max(1, Math.ceil(state.total / PAGE_SIZE));
      const prev = iconBtn('left','Trang trước',async()=>{state.page--;await loadChapters();}); prev.disabled = state.page <= 1;
      const next = iconBtn('right','Trang sau',async()=>{state.page++;await loadChapters();}); next.disabled = state.page >= pages;
      pager.replaceChildren(el('span','sw-muted',`${state.total} chương · ${state.totalWords.toLocaleString('vi-VN')} từ`), ...(pages > 1 ? [prev, el('span','',`${state.page}/${pages}`), next] : []));
    }
    function renderEditor() {
      const has = Boolean(state.chapter);
      for (const n of [chapterName, text, readTitle, reviewed, compare]) n.disabled = !has;
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
        const dict = el('textarea','sw-dict'); dict.rows = 5; dict.spellcheck = false;
        dict.value = (s.pronunciations||[]).map(r=>r.from+' = '+r.to).join('\n');
        dict.placeholder = 'Mỗi dòng: cách viết = cách đọc\nVí dụ:\nCEO = xi i ô\nMr. = mít tơ\n5km = năm ki lô mét';
        dict.oninput = () => {s.pronunciations = parseRules(dict.value);};
        // Suggestions from the book: abbreviations, numbers glued to units, clock times, symbols.
        const suggestBox = el('div','sw-suggest');
        const suggestButton = btn('Gợi ý từ truyện', async () => {
          suggestButton.disabled = true; suggestBox.replaceChildren(el('p','sw-muted','Đang quét các chương…'));
          try {
            const data = await api(`/api/story/books/${state.book.id}/pronunciation-suggestions`);
            if (!data.items.length) {suggestBox.replaceChildren(el('p','sw-muted',`Đã quét ${data.chapters} chương: không thấy chữ viết tắt, số kèm đơn vị hay ký hiệu cần thêm.`)); return;}
            const rows = data.items.map(item => {
              const tick = el('input'); tick.type='checkbox'; tick.checked=true;
              const reading = el('input'); reading.value = item.to; reading.setAttribute('aria-label','Cách đọc '+item.from);
              const row = add(el('label','sw-suggest-row'), tick, el('strong','',item.from), el('span','sw-muted','='), reading,
                el('small','sw-muted',`${item.kind} · ${item.count} lần · …${item.example}…`));
              return {row, tick, reading, item};
            });
            const addButton = btn('Thêm các mục đã chọn', () => {
              const lines = rows.filter(r => r.tick.checked && r.reading.value.trim()).map(r => r.item.from + ' = ' + r.reading.value.trim());
              if (!lines.length) {toast('Chưa chọn mục nào.'); return;}
              dict.value = [dict.value.trim(), ...lines].filter(Boolean).join('\n'); s.pronunciations = parseRules(dict.value);
              suggestBox.replaceChildren(el('p','sw-muted',`Đã thêm ${lines.length} mục. Bấm Lưu thiết lập cho truyện để áp dụng.`));
            }, 'sw-accent', 'plus');
            suggestBox.replaceChildren(el('p','sw-muted',`Đã quét ${data.chapters} chương. Sửa cách đọc nếu cần, bỏ tick mục không muốn thêm.`), ...rows.map(r => r.row), addButton);
          } catch (error) {suggestBox.replaceChildren(el('p','sw-error',error.message));}
          finally {suggestButton.disabled = false;}
        }, '', 'spark');
        const khanh = (s.speech_engine||'vieneu') === 'khanhtts';
        // Greeting at the start and the end of every episode of this book, read with the narration voice.
        const intro = el('textarea'); intro.rows = 2; intro.maxLength = 600; intro.value = s.intro_text || '';
        intro.placeholder = 'Ví dụ: Chào mừng các bạn đến với kênh Tôi Đọc Truyện. Hôm nay là {chuong} của truyện {truyen}.'; intro.oninput = () => {s.intro_text = intro.value;};
        const outro = el('textarea'); outro.rows = 2; outro.maxLength = 600; outro.value = s.outro_text || '';
        outro.placeholder = 'Ví dụ: Cảm ơn các bạn đã lắng nghe. Nhớ bấm đăng ký kênh để nghe tập tiếp theo nhé.'; outro.oninput = () => {s.outro_text = outro.value;};
        box.replaceChildren(...[field('Công cụ giọng kể', engine), field('Giọng đọc', add(el('div','sw-inline'), voice, sample)), field('Nhịp đọc', rhythm), field('Tốc độ', speed),
          khanh ? field('Chất lượng KhanhTTS', steps) : null,
          add(el('p','sw-muted sw-link-row'), el('span','','Sắc thái theo bản thu tham chiếu. '), link),
          add(el('details','sw-advanced'), el('summary','',`Từ điển phát âm (${(s.pronunciations||[]).length} mục)`), dict, suggestButton, suggestBox,
            el('p','sw-muted','Chỉ đổi cách đọc; phụ đề và chữ trên video vẫn giữ nguyên. Khớp nguyên từ, không phân biệt hoa thường. Bấm Lưu thiết lập để áp dụng; chương đã có lời đọc sẽ đọc lại những câu bị đổi.')),
          add(el('details','sw-advanced'), el('summary','',`Lời chào đầu và cuối tập${s.intro_text||s.outro_text?' · đang bật':''}`), field('Đầu tập', intro), field('Cuối tập', outro),
            el('p','sw-muted','{truyen} = tên truyện, {chuong} = chương của tập (ví dụ Chương 3 hoặc Chương 3–5). Để trống thì không đọc. Bấm Lưu thiết lập để áp dụng cho các tập làm sau.')),
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
      const list = clipGrid(items);
      const audio = el('input'); audio.type='checkbox'; audio.checked = Boolean(l.game_audio); audio.onchange = () => patchBook({layout:{game_audio:audio.checked}});
      const resume = el('input'); resume.type='checkbox'; resume.checked = l.continue_gameplay !== false; resume.onchange = () => patchBook({layout:{continue_gameplay:resume.checked}});
      const link = el('input'); link.type = 'text'; link.placeholder = 'Dán link Google Drive của video gameplay';
      const addLink = btn('Thêm từ Drive', async () => {
        const task = await api('/api/story/gameplay/link', json('POST', {url: link.value}));
        link.value = '';
        const poll = async () => {
          const t = await api('/api/story/gameplay/link/' + task.id);
          state.upload = t.state === 'running' ? `${t.name}: tải từ Drive ${t.size ? Math.round(t.received / t.size * 100) : Math.round(t.received / 2**20)}${t.size ? '%' : ' MB'}` : '';
          if (t.state === 'running') {renderSettings(); setTimeout(poll, 2000); return;}
          if (t.state === 'failed') toast(t.error); else toast('Đã thêm clip từ Drive.');
          await loadGameplay(); renderSettings(); renderFooter();
        };
        poll();
      }, '', 'upload');
      const avgWords = state.total ? state.totalWords / state.total : 0;
      const chapterSeconds = avgWords ? estimateWords(avgWords) : 0;
      const covered = chapterSeconds ? Math.floor(state.gameplay.total_seconds / chapterSeconds) : 0;
      const warning = items.length && chapterSeconds && covered < state.total
        ? el('p','sw-warning', covered < 1 ? `Gameplay (${fmtClock(state.gameplay.total_seconds)}) ngắn hơn một chương (khoảng ${fmtMinutes(chapterSeconds)}): mỗi chương sẽ lặp lại cảnh cũ. Thêm clip để tránh lặp.`
          : `Gameplay đủ cho khoảng ${covered} chương; từ chương ${covered + 1} sẽ lặp lại cảnh cũ. Thêm clip để tránh lặp.`) : null;
      add(box, summary, warning, driveFolderBox(), list, state.upload ? el('p','sw-muted',`Đang tải: ${state.upload}`) : null,
        btn('Thêm clip gameplay từ máy',()=>clipInput.click(),'sw-wide','upload'), add(el('div','sw-inline'), link, addLink), clipInput,
        add(el('label','sw-check'), audio, icon(l.game_audio?'sound':'mute'), el('span','',l.game_audio?'Tiếng game: Bật (nhỏ, dưới lời kể)':'Tiếng game: Tắt')),
        add(el('label','sw-check'), resume, el('span','','Chương sau tiếp tục từ chỗ gameplay chương trước dừng')),
        el('p','sw-muted','Clip ngắn hơn lời kể sẽ nối clip tiếp theo, hết danh sách thì lặp lại. Không tăng tốc game, không kéo khung hình đứng.'));
      return box;
    }
    // Clips as a grid of small thumbnails in a box of its own height (a thousand clips do not stretch the page): tiles
    // are added a screenful at a time while scrolling, pictures load when they come into view. The bin on a tile asks
    // on the tile itself, then deletes the clip everywhere; a tap on the tile opens the viewer.
    const CLIP_PAGE = 48;
    function clipGrid(items) {
      const wrap = el('div','sw-clip-grid-wrap');
      if (!items.length) return add(wrap, el('p','sw-muted','Chưa có clip. Thêm video gameplay bạn đã quay (MP4/MKV/MOV/WebM). Clip được lưu một lần trong thư viện chung, dùng cho mọi truyện.'));
      const grid = el('div','sw-clip-grid');
      let shown = 0;
      const more = () => {
        const until = Math.min(items.length, Math.max(shown + CLIP_PAGE, state.clipShown || 0));
        for (; shown < until; shown++) grid.append(clipTile(items, shown));
        state.clipShown = shown;
      };
      more();
      grid.onscroll = () => {
        state.clipScroll = grid.scrollTop;
        if (shown < items.length && grid.scrollTop + grid.clientHeight > grid.scrollHeight - 200) more();
      };
      requestAnimationFrame(() => {grid.scrollTop = state.clipScroll || 0;});
      return add(wrap, grid);
    }
    function clipTile(items, index) {
      const clip = items[index];
      const tile = el('article','sw-tile'); if (!clip.available) tile.classList.add('is-missing'); if (clip.used) tile.classList.add('is-used');
      tile.tabIndex = 0; tile.setAttribute('role','button');
      tile.setAttribute('aria-label', `Clip ${index+1}: ${clip.name}, ${fmtClock(clip.end - clip.start)} dùng. Bấm để xem`);
      tile.title = clip.name;
      const img = el('img'); img.src = clip.thumbnail; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      img.onerror = () => {img.replaceWith(el('span','sw-tile-blank', 'Chưa có ảnh'));};
      const badge = el('span','sw-tile-num', String(index + 1));
      const time = el('span','sw-tile-time', fmtClock(clip.end - clip.start));
      const flags = el('span','sw-tile-flags', [clip.source === 'drive' ? '☁' : '', clip.used ? 'Đã dùng' : '', clip.available ? '' : 'Mất tệp'].filter(Boolean).join(' · '));
      const bin = iconBtn('trash','Xoá clip',() => {state.confirmClip = clip.id; tile.replaceChildren(...tileBody(), confirmBox());}, 'sw-tile-bin');
      const tileBody = () => [img, badge, time, flags, bin];
      const confirmBox = () => {
        const box = el('div','sw-tile-confirm'); box.setAttribute('role','alertdialog'); box.setAttribute('aria-label','Xác nhận xoá clip');
        const keep = btn('Huỷ', () => {state.confirmClip = null; tile.replaceChildren(...tileBody());});
        const go = btn('Xoá', async () => {
          go.disabled = keep.disabled = true; go.lastChild.textContent = 'Đang xoá…';
          try {
            const r = await api('/api/story/gameplay/' + clip.id, {method: 'DELETE'});
            state.confirmClip = null;
            toast(r.drive === 'failed' ? `Đã xoá clip khỏi máy. Drive chưa xoá được: ${r.error}` : r.drive === 'trashed' ? 'Đã xoá clip trên máy và chuyển vào thùng rác Drive.' : 'Đã xoá clip.');
            await loadGameplay(); renderSettings(); renderFooter();
          } catch (error) {go.disabled = keep.disabled = false; go.lastChild.textContent = 'Xoá'; throw error;}
        }, 'sw-danger-solid');
        box.onclick = e => e.stopPropagation(); box.onkeydown = e => {e.stopPropagation(); if (e.key === 'Escape') keep.click();};
        return add(box, el('strong','','Xoá clip này?'), el('span','', clip.source === 'drive' ? 'Xoá trên máy và đưa vào thùng rác Drive.' : 'Xoá hẳn khỏi máy.'), add(el('div','sw-tile-confirm-actions'), keep, go));
      };
      bin.addEventListener('click', e => e.stopPropagation());
      tile.replaceChildren(...tileBody(), ...(state.confirmClip === clip.id ? [confirmBox()] : []));
      tile.onclick = () => openClip(items, index);
      tile.onkeydown = e => {if (e.target === tile && (e.key === 'Enter' || e.key === ' ')) {e.preventDefault(); openClip(items, index);}};
      return tile;
    }
    // The clip viewer: play the clip, set the part a video uses (from the player's current second or typed), move it
    // in this book's order or take it out of this book only.
    function openClip(items, index) {
      const clip = items[index];
      const dialog = el('dialog','sw-dialog sw-clip-dialog');
      const close = () => {video.pause(); video.removeAttribute('src'); video.load(); dialog.close(); dialog.remove();};
      const video = el('video'); video.controls = true; video.preload = 'metadata'; video.playsInline = true;
      video.src = `/api/story/gameplay/${clip.id}/video#t=${Math.max(0, Number(clip.start) || 0)}`;
      const note = el('p','sw-muted', clip.cached || clip.source !== 'drive' ? '' : 'Clip đang phát thẳng từ Drive (chưa có trên máy), có thể chậm một chút.');
      video.onerror = () => {note.className = 'sw-warning'; note.textContent = 'Không phát được clip này' + (clip.available ? '.' : ': không thấy tệp trên máy và Drive.');};
      const start = el('input'); start.type='number'; start.min=0; start.step=1; start.value=Math.round(clip.start); start.setAttribute('aria-label','Bắt đầu (giây)');
      const end = el('input'); end.type='number'; end.min=1; end.step=1; end.max=Math.floor(clip.duration); end.value=Math.round(clip.end); end.setAttribute('aria-label','Kết thúc (giây)');
      const length = el('span','sw-muted');
      const showLength = () => {length.textContent = `Dùng ${fmtClock(Math.max(0, Number(end.value) - Number(start.value)))} trên ${fmtClock(clip.duration)}`;};
      start.oninput = end.oninput = showLength; showLength();
      const here = (input) => btn(input === start ? 'Bắt đầu từ đây' : 'Kết thúc ở đây', () => {input.value = Math.round(video.currentTime); showLength();}, '', 'play');
      const jump = btn('Xem từ đầu đoạn', () => {video.currentTime = Number(start.value) || 0; video.play().catch(() => {});});
      video.ontimeupdate = () => {if (!video.paused && Number(end.value) > Number(start.value) && video.currentTime >= Number(end.value)) video.pause();};
      const save = btn('Lưu đoạn dùng', async () => {
        clip.start = Number(start.value); clip.end = Number(end.value);
        await savePlaylist(items); toast('Đã lưu đoạn dùng của clip.'); close();
      }, 'sw-primary', 'save');
      const move = (to) => async () => {items.splice(to, 0, items.splice(index, 1)[0]); await savePlaylist(items); close(); openClip(state.gameplay.items.map(c => ({...c})), to);};
      const up = btn('Lên trước', move(index - 1), '', 'up'); up.disabled = index === 0;
      const down = btn('Xuống sau', move(index + 1), '', 'down'); down.disabled = index === items.length - 1;
      const drop = btn('Bỏ khỏi truyện này', async () => {items.splice(index, 1); await savePlaylist(items); toast('Đã bỏ clip khỏi truyện này. Clip vẫn còn cho truyện khác.'); close();});
      const info = `${fmtClock(clip.duration)} · ${clip.width}×${clip.height} · ${Math.round(clip.fps)}fps${clip.has_audio?'':' · không tiếng'}${clip.source==='drive'?(clip.cached?' · Drive, đã tải về máy':' · Drive, chưa tải về máy'):''}${clip.used?' · đã dùng':''}`;
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','',`Clip ${index + 1}: ${clip.name}`), el('p','',info)), iconBtn('close','Đóng',close)),
        video, note,
        add(el('div','sw-clip-range'), el('span','sw-muted','Dùng từ giây'), start, here(start), el('span','sw-muted','đến giây'), end, here(end), length),
        add(el('div','sw-clip-dialog-actions'), jump, up, down, drop, save));
      doc.body.append(dialog); dialog.showModal();
      dialog.addEventListener('cancel', e => {e.preventDefault(); close();});
    }
    // Thư mục gameplay trên Drive: the tool fetches new videos from it by itself and moves used ones into "Used".
    function driveFolderBox() {
      const f = state.driveFolder;
      if (!f) return null;
      const box = el('section','sw-drive-folder');
      const head = add(el('div','sw-drive-head'), icon('folder'), el('strong','','Thư mục gameplay trên Drive'));
      const save = saveDriveFolder;
      if (!f.folder) {
        const link = el('input'); link.type = 'text'; link.placeholder = 'Dán link thư mục Drive chứa video gameplay';
        link.setAttribute('aria-label','Link thư mục gameplay trên Drive');
        add(box, head, el('p','sw-muted','Bỏ video gameplay vào một thư mục Drive. Tool tự lấy video mới về dùng (15 phút kiểm tra một lần), clip nào đã phát hết thì chuyển vào thư mục Used bên trong.'),
          btn('Chọn thư mục trên Drive', () => openFolderPicker(), 'sw-accent sw-wide', 'folder'),
          add(el('details','sw-drive-paste'), el('summary','','Hoặc dán link thư mục'),
            add(el('div','sw-inline'), link, btn('Dùng link này', () => save({link: link.value}, 'Đã chọn thư mục. Đang lấy clip về…'), ''))));
        return box;
      }
      const t = f.task || {};
      const running = t.state === 'running';
      const reuse = el('input'); reuse.type = 'checkbox'; reuse.checked = Boolean(f.reuse);
      reuse.onchange = () => save({reuse: reuse.checked}, reuse.checked ? 'Clip đã dùng được đưa lại vào danh sách.' : 'Clip đã dùng được bỏ khỏi danh sách.').catch(e => {reuse.checked = !reuse.checked; toast(e.message);});
      const sync = btn(running ? 'Đang lấy clip…' : 'Lấy clip mới', async () => {state.driveFolder = await api('/api/story/gameplay/drive-folder/sync', json('POST', {})); renderSettings(); watchFolder();}, '', 'download');
      sync.disabled = running;
      const change = btn('Đổi thư mục', () => openFolderPicker(), '', 'folder');
      const last = f.folder.last_sync ? new Date(f.folder.last_sync * 1000).toLocaleString('vi-VN', {hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit'}) : 'chưa';
      const progress = running ? el('p','sw-muted', t.total ? `Đang tải ${t.done + 1}/${t.total}: ${t.current} ${t.size ? Math.round(t.received / t.size * 100) + '%' : ''}` : 'Đang xem thư mục có video mới không…') : null;
      const problem = (f.folder.error || t.error) ? el('p','sw-warning', f.folder.error || t.error) : null;
      add(box, head,
        add(el('p','sw-drive-name'), el('span','', f.folder.name), el('span','sw-muted', ` · ${f.new} clip mới · ${f.used} đã dùng${f.to_move ? ` (${f.to_move} chưa chuyển vào Used)` : ''} · lấy lần cuối ${last}`)),
        progress, problem,
        add(el('label','sw-check'), reuse, el('span','','Dùng lại clip đã dùng (clip trong Used vẫn được phát lại)')),
        el('p','sw-muted', f.reuse ? 'Clip phát hết vẫn chuyển vào Used, nhưng vẫn nằm trong danh sách để dùng lại.'
          : 'Clip phát hết sẽ chuyển vào Used và bỏ khỏi danh sách. Khi hết clip mới, video vẫn được làm bằng clip đã dùng.'),
        add(el('div','sw-drive-actions'), sync, change));
      return box;
    }
    async function saveDriveFolder(data, done) {
      state.driveFolder = await api('/api/story/gameplay/drive-folder', json('PUT', data));
      if (done) toast(done);
      await loadGameplay(); renderSettings(); watchFolder();
    }
    // Browse Drive like a file picker: tap a folder to open it, then "Chọn thư mục này".
    async function openFolderPicker() {
      const dialog = el('dialog','sw-dialog sw-folder-dialog');
      const close = () => {dialog.close(); dialog.remove();};
      const trail = [{id: 'root', name: 'Drive của tôi'}];
      let account = state.driveFolder?.folder?.account || '';
      const accountBox = el('div','sw-folder-account'), crumbs = el('nav','sw-crumbs'), list = el('div','sw-folder-list'), info = el('span','sw-muted');
      crumbs.setAttribute('aria-label','Đường dẫn thư mục');
      const choose = btn('Chọn thư mục này', async () => {
        const here = trail[trail.length - 1];
        await saveDriveFolder({link: here.id, account}, `Đã chọn thư mục ${here.name}. Đang lấy clip về…`); close();
      }, 'sw-primary', 'folder');
      const open = item => {trail.push(item); load();};
      async function load() {
        const here = trail[trail.length - 1];
        choose.disabled = true; info.textContent = '';
        list.replaceChildren(el('p','sw-muted','Đang mở thư mục…'));
        let d;
        try {d = await api(`/api/story/gameplay/drive-folders?account=${encodeURIComponent(account)}&parent=${encodeURIComponent(here.id)}`);}
        catch (error) {list.replaceChildren(el('p','sw-warning', error.message)); return;}
        account = d.account;
        accountBox.replaceChildren(d.accounts.length > 1
          ? field('Tài khoản Drive', select(d.accounts.map(a => [a, a]), account, v => {account = v; trail.splice(1); load();}))
          : el('span','sw-muted', 'Tài khoản: ' + account));
        crumbs.replaceChildren(...trail.flatMap((t, i) => {
          const b = btn(t.name, () => {trail.splice(i + 1); load();}, 'sw-crumb'); b.disabled = i === trail.length - 1;
          return i ? [el('span','sw-muted','›'), b] : [b];
        }));
        const rows = d.folders.map(f => btn(f.name, () => open({id: f.id, name: f.name}), 'sw-folder-row', 'folder'));
        if (here.id === 'root') rows.push(btn('Được chia sẻ với tôi', () => open({id: 'shared', name: 'Được chia sẻ với tôi'}), 'sw-folder-row sw-folder-shared', 'folder'));
        list.replaceChildren(...(rows.length ? rows : [el('p','sw-muted','Không có thư mục con.')]));
        const pickable = here.id !== 'root' && here.id !== 'shared';
        choose.disabled = !pickable;
        info.textContent = pickable ? `${d.videos} video trong thư mục này` : 'Mở thư mục chứa video gameplay rồi bấm Chọn thư mục này.';
      }
      add(dialog, add(el('div','sw-layout-head'), add(el('div'), el('h2','','Chọn thư mục gameplay'),
          el('p','sw-muted','Bấm vào thư mục để mở. Tool lấy video trong thư mục bạn chọn và tạo thư mục Used bên trong.')), iconBtn('close','Đóng',close)),
        accountBox, crumbs, list, add(el('div','sw-folder-foot'), info, choose));
      doc.body.append(dialog); dialog.showModal(); dialog.addEventListener('cancel', () => dialog.remove());
      await load();
    }
    function frameTab() {
      const l = {...layout()};
      const box = el('div','sw-tab-pane');
      const channel = el('input'); channel.type='text'; channel.maxLength=80; channel.value = l.channel || ''; channel.placeholder = 'Ví dụ: TRUYỆN ĐÊM';
      const background = select(state.backgrounds.map(b=>[b.id,b.name]), l.background || 'preset:dem-xanh', v=>{l.background=v;});
      const bgInput = el('input'); bgInput.type='file'; bgInput.accept='.png,.jpg,.jpeg,.webp'; bgInput.hidden=true;
      bgInput.onchange = async () => {const f=bgInput.files[0];if(!f)return;try{const r=await api('/api/story/backgrounds?name='+encodeURIComponent(f.name),{method:'PUT',body:f,raw:true});state.backgrounds=(await api('/api/story/backgrounds')).items;await patchBook({layout:{background:r.id}},'Đã thêm ảnh nền.');}catch(e){toast(e.message);}finally{bgInput.value='';}};
      const check = (key, label) => {const c=el('input');c.type='checkbox';c.checked=l[key]!==false;c.onchange=()=>{l[key]=c.checked;};return add(el('label','sw-check'),c,el('span','',label));};
      const codec = select([['hevc','HEVC · nhẹ khoảng một nửa (mặc định)'],['h264','H.264 · mở được trên mọi máy']], l.video_codec || 'hevc', v=>{l.video_codec=v;});
      const coverBox = el('div','sw-cover');
      const drawCover = () => {
        const source = select([['game','Một khung hình gameplay'],['image','Ảnh của tôi']], l.cover_source || 'game', v=>{l.cover_source=v;drawCover();});
        const coverText = el('input'); coverText.type='checkbox'; coverText.checked = l.cover_text !== false; coverText.onchange = () => {l.cover_text = coverText.checked;};
        const parts = [field('Ảnh bìa lấy từ', source)];
        if ((l.cover_source||'game') === 'game') {
          const at = el('input'); at.type='range'; at.min=2; at.max=98; at.step=1; at.value = Math.round((l.cover_at ?? 0.3)*100);
          const label = el('span','sw-muted', at.value+'% thời lượng');
          at.oninput = () => {l.cover_at = Number(at.value)/100; label.textContent = at.value+'% thời lượng';};
          parts.push(field('Lấy khung hình ở', add(el('div','sw-inline'), at, label)));
        } else {
          const images = state.backgrounds.filter(b=>String(b.id).startsWith('image:'));
          if (!l.cover_image && images.length) l.cover_image = images[0].id;
          const pick = select(images.length ? images.map(b=>[b.id,b.name]) : [['','Chưa có ảnh, tải lên']], l.cover_image || '', v=>{l.cover_image=v;});
          const coverInput = el('input'); coverInput.type='file'; coverInput.accept='.png,.jpg,.jpeg,.webp'; coverInput.hidden=true;
          coverInput.onchange = async () => {const f=coverInput.files[0];if(!f)return;try{const r=await api('/api/story/backgrounds?name='+encodeURIComponent(f.name),{method:'PUT',body:f,raw:true});state.backgrounds=(await api('/api/story/backgrounds')).items;l.cover_image=r.id;drawCover();toast('Đã tải ảnh bìa lên, bấm Lưu khung hình.');}catch(e){toast(e.message);}finally{coverInput.value='';}};
          parts.push(field('Ảnh bìa', add(el('div','sw-inline'), pick, iconBtn('upload','Tải ảnh bìa lên',()=>coverInput.click()))), coverInput,
            el('p','sw-muted','Ảnh được cắt vừa 1280×720.'));
        }
        parts.push(add(el('label','sw-check'), coverText, el('span','','Ghi tên truyện và chương lên ảnh bìa')));
        coverBox.replaceChildren(...parts);
      };
      drawCover();
      add(box, field('Tên kênh', channel), field('Ảnh nền', add(el('div','sw-inline'), background, iconBtn('upload','Tải ảnh nền lên',()=>bgInput.click()))), bgInput,
        field('Nén video', codec),
        el('h3','','Ảnh bìa'), coverBox,
        el('h3','','Đầu ra'), add(el('div','sw-checks'), check('horizontal','Ngang 16:9'), check('vertical','Dọc 9:16'), check('burn_subtitles','Hiện phụ đề trên video'), check('export_srt','Xuất phụ đề SRT'), check('export_mp3','MP3 lời kể')),
        btn('Lưu khung hình cho truyện',()=>patchBook({layout:{...l, channel:channel.value}},'Đã lưu khung hình cho truyện.'),'sw-wide','save'),
        btn('Xem bố cục ngang / dọc',openLayout,'sw-wide sw-accent'));
      return box;
    }
    function renderFooter() {
      if (!state.book) return;
      const ids = state.allIds.filter(id => state.selected.has(id));
      const wordsSelected = ids.reduce((sum, id) => sum + (state.wordsById?.get(id) || 0), 0);
      const groups = groupsFor(ids), count = groups.length;
      targetSelect.hidden = state.mode !== 'group'; targetSelect.value = String(state.target);
      total.textContent = ids.length ? `${ids.length} chương đã chọn · khoảng ${fmtMinutes(estimateWords(wordsSelected))} lời kể` : 'Tick chọn chương để tạo video';
      // Rough space need: finished videos (HEVC, both formats) plus the temporary gameplay master of one chapter.
      const minutes = estimateWords(wordsSelected) / 60, needGb = state.audioOnly ? (minutes * 3 + 100) / 1024 : (minutes * 35 + 600) / 1024;
      if (state.disk?.free_gb != null && ids.length && state.disk.free_gb < needGb) {
        const warn = el('span','sw-disk-warning',` · Ổ lưu ${state.disk.root} chỉ còn ${state.disk.free_gb} GB, cần khoảng ${needGb.toFixed(1)} GB. Đổi nơi lưu trong Cài đặt hoặc kết nối Google Drive.`);
        total.append(warn);
      }
      enqueueButton.disabled = !ids.length;
      enqueueButton.textContent = state.mode === 'merge' && ids.length > 1 ? `Gộp ${ids.length} chương thành 1 video →`
        : state.mode === 'group' ? `Tạo ${count} tập từ ${ids.length} chương →` : `Thêm ${count} chương vào hàng đợi →`;
      if (state.audioOnly && ids.length) enqueueButton.textContent = `Đọc thành ${count} MP3 →`;
      audioOnly.checked = state.audioOnly;
      if (state.mode === 'group' && groups.length) {
        const longest = Math.max(...groups.map(g=>g.reduce((t,id)=>t+estimateWords(state.wordsById?.get(id)||0),0)));
        total.append(el('span','',` · ${count} tập, dài nhất khoảng ${fmtMinutes(longest)}`));
      }
      modeSelect.value = state.mode;
    }

    // --- local draft backup (only the chapter being edited) --------------------------------------------------
    function readLocal(key) {try {return JSON.parse(global.localStorage.getItem(DRAFT_PREFIX+key)||'null');} catch {return null;}}
    function writeLocal(key, value) {try {global.localStorage.setItem(DRAFT_PREFIX+key, JSON.stringify(value));} catch {}}
    function removeLocal(key) {try {global.localStorage.removeItem(DRAFT_PREFIX+key);} catch {}}
    const beforeUnload = e => {if (state.dirty) {writeLocal('chapter.'+state.chapter.id, {base:state.chapter.revision, title:chapterName.value, text:text.value}); e.preventDefault();}};
    global.addEventListener('beforeunload', beforeUnload);

    renderAll();
    loadBooks().catch(error => {state.loaded = true; renderEmpty(); toast(error.message);});
    return {
      refresh: () => {if (state.book) loadChapters().then(loadGameplay).then(renderSettings).catch(e=>toast(e.message)); else loadBooks().catch(e=>toast(e.message));},
      save: () => saveChapter(false).catch(e=>toast(e.message)),
      destroy: () => {global.removeEventListener('beforeunload', beforeUnload); clearTimeout(saveTimer); clearTimeout(pollTimer); clearTimeout(state.crawlTimer); clearTimeout(state.folderTimer); clearTimeout(state.autorunTimer); state.destroyed = true;},
    };
  }
  global.StoryWorkspace = {mount};
})(typeof window === 'undefined' ? globalThis : window);

/* Create Video: the host retains import, validation and queue transport ownership. */
(function (global) {
  'use strict';
  const DRAFT_KEY = 'videostudio.create.draft.v1';
  const LAST_KEY = 'videostudio.batch.last';
  const DEFAULTS = Object.freeze({style:'case',input:'script',voice:'',image_provider:'comfy',speech_engine:'vieneu',speech_batch_size:256,khanh_steps:32,speech_rhythm:'natural',speech_speed:1,duration_mode:'auto',seconds:1,unit:'60'});
  const TRANSIENT = new Set(['key','title','text','error','uncertain','submitted_duration_seconds','selected']);
  const uuid = () => global.crypto.randomUUID();
  const fallbackEstimate = text => Math.max(0, Math.ceil((String(text || '').match(/\S+/g) || []).length / 4.2));
  const clone = value => JSON.parse(JSON.stringify(value));
  function settingsOf(row) {
    return Object.fromEntries(Object.entries(row || {}).filter(([key]) => !TRANSIENT.has(key)));
  }
  function estimatedSeconds(row, estimate = fallbackEstimate) {
    const seconds = Number(estimate(row.text || '', row.voice || '', row.style, row));
    // Empty scripts start at a visible one-minute target until there is text to measure.
    return Number.isFinite(seconds) && seconds > 0 ? seconds : 60;
  }
  function syncDuration(row, estimate = fallbackEstimate) {
    if (row.uncertain || Number.isFinite(row.submitted_duration_seconds)) return row;
    row.unit = ['1','60'].includes(String(row.unit)) ? String(row.unit) : '60';
    if (row.duration_mode === 'auto') row.seconds = Number((estimatedSeconds(row, estimate) / Number(row.unit)).toFixed(6));
    return row;
  }
  function convertDurationUnit(row, unit, estimate = fallbackEstimate) {
    unit=String(unit);
    if (!['1','60'].includes(unit)) throw Error('Chọn Giây hoặc Phút.');
    if (row.uncertain || Number.isFinite(row.submitted_duration_seconds)) return row;
    const total=row.duration_mode==='auto' ? estimatedSeconds(row,estimate) : Number(row.seconds)*Number(row.unit||60);
    if (String(row.seconds).trim()!=='' && Number.isFinite(total)) row.seconds=Number((total/Number(unit)).toPrecision(12));
    row.unit=unit;
    return row;
  }
  function setMinutes(row, value) {
    row.duration_mode = 'manual'; row.seconds = value; row.unit = '60';
    return row;
  }
  function setSeconds(row, value) {
    row.duration_mode = 'manual'; row.seconds = value; row.unit = '1';
    return row;
  }
  function resetDuration(row, estimate) {
    row.duration_mode = 'auto'; delete row.submitted_duration_seconds;
    return syncDuration(row, estimate);
  }
  function createRow(settings = {}, base = {}, estimate) {
    const row = {...DEFAULTS, ...settingsOf(settings), key:uuid(),title:'',text:'',error:'',uncertain:false,...base};
    if (!row.duration_mode) row.duration_mode = 'auto';
    if (!row.unit || !['1', '60'].includes(String(row.unit))) row.unit = '60';
    return syncDuration(row, estimate);
  }
  function editRow(row, patch, estimate) {
    if (row.uncertain) return false;
    if(patch.voice!=null&&patch.voice!==row.voice&&!Object.hasOwn(patch,'speech_reference_text'))delete row.speech_reference_text;
    Object.assign(row, patch); row.key = uuid(); row.error = ''; delete row.submitted_duration_seconds;
    syncDuration(row, estimate); return true;
  }
  function validateRow(row) {
    if (!String(row.text || '').trim()) return 'Chưa có nội dung.';
    if (!row.voice) return 'Chọn giọng đọc.';
    const totalSeconds = Number(row.seconds) * Number(row.unit || 1);
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return 'Nhập số phút hoặc số giây lớn hơn 0.';
    if (!Number.isInteger(Number(row.speech_batch_size)) || Number(row.speech_batch_size) < 1 || Number(row.speech_batch_size) > 512) return 'Batch giọng đọc phải là số nguyên từ 1 đến 512.';
    if (!['vieneu','khanhtts'].includes(row.speech_engine)) return 'Chọn bộ đọc hợp lệ.';
    if (row.speech_engine === 'khanhtts' && ![16,32].includes(Number(row.khanh_steps))) return 'KhanhTTS hỗ trợ 16 hoặc 32 bước.';
    if (!['natural','story'].includes(row.speech_rhythm)) return 'Chọn nhịp đọc hợp lệ.';
    if (!Number.isFinite(Number(row.speech_speed)) || Number(row.speech_speed) < .5 || Number(row.speech_speed) > 2) return 'Tốc độ đọc phải từ 0,5 đến 2.';
    return '';
  }
  function serializeDraft({rows,common,selectedKeys,activeKey}) {
    return JSON.stringify({version:1,rows,common,selectedKeys:[...(selectedKeys || [])],activeKey,savedAt:new Date().toISOString()});
  }
  function restoreDraft(raw) {
    try {
      const draft = JSON.parse(raw);
      if (draft?.version !== 1 || !Array.isArray(draft.rows) || draft.rows.some(row => !row || typeof row !== 'object' || typeof row.key !== 'string' || typeof row.text !== 'string')) return null;
      const keys = new Set(draft.rows.map(row => row.key));
      if (keys.size !== draft.rows.length) return null;
      return {rows:draft.rows,common:draft.common && typeof draft.common === 'object' ? draft.common : {},selectedKeys:(draft.selectedKeys || []).filter(key => keys.has(key)),activeKey:keys.has(draft.activeKey) ? draft.activeKey : draft.rows[0]?.key};
    } catch { return null; }
  }
  function applySettings(rows, selectedKeys, settings, estimate) {
    let changed = 0, skipped = 0;
    for (const row of rows) if (selectedKeys.has(row.key)) {
      if (row.uncertain) {skipped++; continue;}
      editRow(row, settingsOf(settings), estimate); changed++;
    }
    return {changed, skipped};
  }
  function moveRow(rows, from, to) {
    if (from < 0 || from >= rows.length || to < 0 || to >= rows.length || from === to) return false;
    rows.splice(to, 0, rows.splice(from, 1)[0]); return true;
  }

  function mount(root, options = {}) {
    const doc = root.ownerDocument;
    const state = options.state || {batchRows:[]};
    const estimate = options.estimateNarrationSeconds || fallbackEstimate;
    const durationText = options.durationText || (seconds => `${Math.round(seconds / 60 * 10) / 10} phút`);
    const metrics = options.textMetrics || (text => ({words:(String(text).match(/\S+/g)||[]).length,characters:Array.from(String(text)).length}));
    const styles = Object.entries(options.styleLabels || {news:'Tin tức',case:'Vụ án',meme:'Meme hài'});
    const engineOptions = [['vieneu','VieNeu'],['khanhtts','KhanhTTS']];
    const imageOptions = [['comfy','ComfyUI'],['flow','Google Flow'],['chatgpt','ChatGPT'],['meta','Meta AI']];
    const rhythmOptions = [['natural','Tự nhiên'],['story','Kể chuyện']];
    let storage, common = {...DEFAULTS}, selected = new Set(), activeKey, editorKey, importing = false, destroyed = false, draggedKey;
    try { storage = options.storage || global.localStorage; common = {...common,...JSON.parse(storage?.getItem(LAST_KEY) || '{}')}; } catch { /* Storage may be disabled by the browser. */ }
    let restored;
    try {restored = restoreDraft(storage?.getItem(options.draftKey || DRAFT_KEY));} catch { /* Keep the host rows if the draft is unavailable. */ }
    if (restored && options.restore !== false) {
      state.batchRows = restored.rows; common = {...common,...restored.common}; selected = new Set(restored.selectedKeys); activeKey = restored.activeKey;
    }
    if (!state.batchRows?.length) state.batchRows = [createRow(common, {}, estimate)];
    for (const row of state.batchRows) {
      for (const [key,value] of Object.entries(DEFAULTS)) if (row[key] == null) row[key] = value;
      row.unit = ['1','60'].includes(String(row.unit)) ? String(row.unit) : '60';
      syncDuration(row, estimate);
    }
    activeKey ||= state.batchRows[0]?.key;
    if (!restored) common = {...common,...settingsOf(state.batchRows.at(-1))};
    const node = (tag, cls, text) => {const value=doc.createElement(tag);if(cls)value.className=cls;if(text != null)value.textContent=text;return value;};
    const append = (parent,...children) => {parent.append(...children);return parent;};
    const button = (label, action, cls = '') => {const value=node('button',`sc-button ${cls}`,label);value.type='button';value.onclick=action;return value;};
    const notify = message => {status.textContent = message;options.toast?.(message);};
    const rowForActive = () => state.batchRows.find(row => row.key === activeKey);
    const busy = () => Boolean(state.batchSubmitting || importing);
    const locked = row => busy() || Boolean(row?.uncertain);
    const titleFor = (row,index) => row.title?.trim() || String(row.text || '').split('\n').find(line => line.trim())?.slice(0,75) || `Kịch bản ${String(index+1).padStart(2,'0')}`;
    const voiceList = () => (options.voiceOptions?.() || []).map(voice => Array.isArray(voice) ? voice : [voice.id,voice.name || voice.id]);
    const voiceName = id => voiceList().find(([value]) => value === id)?.[1] || id || 'Chưa chọn giọng';
    const labelFor = (list,value) => list.find(([key]) => key === value)?.[1] || value;
    const page = node('div','studio-create'); page.dataset.batchPage='true';
    const heading = append(node('header','sc-heading'),append(node('div'),node('h1','','Tạo video'),node('p','sc-muted','Một kịch bản hay cả thư mục — tạo lần lượt, giữ riêng cài đặt từng bài.')));
    const saved = node('span','sc-draft-state','Chưa lưu nháp');saved.setAttribute('role','status');heading.append(saved);
    const commonPanel = node('section','sc-panel sc-common');
    append(commonPanel,append(node('div','sc-panel-heading'),node('h2','','Thiết lập chung'),node('span','sc-muted','Áp dụng cho video mới thêm')));
    const commonFields = node('div','sc-common-fields');
    const commonControls = new Map();
    const editorControls = new Map();
    function save(message = false) {
      if (destroyed) return false;
      try {
        if (!storage) throw Error('Trình duyệt không cho phép lưu nháp.');
        storage.setItem(options.draftKey || DRAFT_KEY,serializeDraft({rows:state.batchRows,common,selectedKeys:selected,activeKey}));
        storage.setItem(LAST_KEY,JSON.stringify(settingsOf(common)));
        saved.textContent = '✓ Đã lưu nháp'; saved.classList.remove('is-error');
        if (message) notify('Đã lưu nháp trên máy này.');
        return true;
      } catch {saved.textContent='Chưa lưu được nháp';saved.classList.add('is-error');if(message)notify('Không lưu được nháp. Kiểm tra dung lượng hoặc quyền lưu của trình duyệt.');return false;}
    }
    function remember(row) {common = {...common,...settingsOf(row)};}
    function edit(row, patch) {
      if (locked(row)) return;
      const oldKey = row.key;
      if (!editRow(row,patch,estimate)) return;
      if (selected.delete(oldKey)) selected.add(row.key);
      if (activeKey === oldKey) {activeKey=row.key;editorKey=row.key;}
      if(Object.keys(patch).some(key=>!['text','title'].includes(key)))remember(row);refresh(false);
    }
    function changeUnit(target, unit) {
      if (target==='common') {
        const changed=convertDurationUnit({...common,text:rowForActive()?.text||''},unit,estimate);
        Object.assign(common,{unit:changed.unit,seconds:changed.seconds});
        if (state.batchRows.length===1 && !locked(rowForActive())) edit(rowForActive(),{unit:common.unit,seconds:common.seconds,duration_mode:common.duration_mode});
        else refresh(false);
      } else {
        const row=rowForActive();if(!row||locked(row))return;
        const changed=convertDurationUnit({...row},unit,estimate);
        edit(row,{unit:changed.unit,seconds:changed.seconds});
      }
    }
    function changeSetting(target,key,value) {
      if (target === 'common') {
        if(key==='voice'&&common.voice!==value)delete common.speech_reference_text;
        common[key] = value;
        if (key === 'seconds') common.duration_mode = 'manual';
        if(state.batchRows.length===1&&!locked(rowForActive())){const patch=key==='seconds'?{seconds:value,duration_mode:'manual'}:{[key]:value};edit(rowForActive(),patch);return;}
        refresh(false);
      } else {
        const row = rowForActive();
        edit(row,key === 'seconds' ? {seconds:value,duration_mode:'manual'} : {[key]:value});
      }
    }
    function field(target, key, caption, choices, attrs = {}) {
      const wrapper = node('label','sc-field');wrapper.append(node('span','',caption));
      const input = node(choices ? 'select' : 'input'); input.setAttribute('aria-label',`${caption}${target==='common'?' — thiết lập chung':' — mục đang sửa'}`);
      for (const [name,value] of Object.entries(attrs)) input.setAttribute(name,String(value));
      if (choices) input._scChoices = choices;
      input[choices ? 'onchange' : 'oninput'] = () => changeSetting(target,key,input.value);
      wrapper.append(input);(target==='common'?commonControls:editorControls).set(key,{input,wrapper});return wrapper;
    }
    function durationField(target) {
      const wrapper = field(target,'seconds','Thời lượng',null,{type:'number',min:'0.000001',step:'any',inputmode:'decimal'});
      const line = node('div','sc-duration-line');const input=wrapper.lastChild;line.append(input);
      const unitSelect = node('select','sc-unit-select');
      unitSelect.setAttribute('aria-label',`Đơn vị thời lượng${target==='common'?' — thiết lập chung':' — mục đang sửa'}`);
      const optMin=node('option','','Phút');optMin.value='60';
      const optSec=node('option','','Giây');optSec.value='1';
      unitSelect.append(optMin,optSec);
      unitSelect.onchange = () => changeUnit(target, unitSelect.value);
      line.append(unitSelect);
      const reset = button('Tự tính',() => {
        if (target==='common') {
          common.duration_mode='auto';const active=rowForActive();
          const updated=syncDuration({...common,text:active?.text||''},estimate);common.seconds=updated.seconds;common.unit=updated.unit;
          if(state.batchRows.length===1&&!locked(active))edit(active,{duration_mode:'auto',unit:common.unit});else refresh(false);
        }
        else {const row=rowForActive();edit(row,{duration_mode:'auto'});}
      },'sc-reset');reset.title='Bỏ thời lượng tự nhập, tính lại theo nội dung và giọng';line.append(reset);wrapper.append(line);
      const note=node('small','sc-muted');wrapper.append(note);Object.assign((target==='common'?commonControls:editorControls).get('seconds'),{reset,note,unitSelect});return wrapper;
    }
    function voiceField(target) {
      const wrapper=field(target,'voice','Giọng đọc',() => voiceList());const line=node('div','sc-voice-line');line.append(wrapper.lastChild);
      const play=button('▷',async()=>{
        const value=target==='common'?common:rowForActive();if(!value?.voice)return notify('Chọn giọng đọc trước khi nghe mẫu.');
        try {if(options.previewVoice)await options.previewVoice(value.voice,value);else notify('Mở Phòng thử giọng trong Kho tài nguyên để nghe giọng này.');}
        catch(error){notify(error.message || 'Không nghe được mẫu giọng.');}
      },'sc-preview');play.setAttribute('aria-label',`Nghe mẫu giọng${target==='common'?' chung':' của mục đang sửa'}`);line.append(play);wrapper.append(line);return wrapper;
    }
    function advancedFields(target) {
      const details=node('details','sc-advanced');details.append(node('summary','','Nâng cao'));
      const grid=node('div','sc-advanced-grid');append(grid,
        field(target,'input','Nguồn nội dung',[['script','Đã có kịch bản'],['idea','Phát triển ý tưởng']]),
        field(target,'speech_batch_size','Batch giọng đọc (câu/lượt)',null,{type:'number',min:1,max:512,step:1}),
        field(target,'khanh_steps','Chất lượng KhanhTTS',[['16','16 bước · nhanh'],['32','32 bước · kỹ hơn']]),
        field(target,'speech_speed','Tốc độ đọc',null,{type:'number',min:.5,max:2,step:.05}),
        field(target,'speech_reference_text','Lời trong mẫu giọng clone',null,{type:'text',maxlength:10000,placeholder:'Dán đúng lời của bản thu tham chiếu'}));
      details.append(grid);return details;
    }
    append(commonFields,field('common','style','Phong cách',styles),field('common','speech_engine','Bộ đọc',engineOptions),voiceField('common'),field('common','image_provider','Hình ảnh',imageOptions));
    const commonBottom=node('div','sc-common-bottom');
    const apply=button('Áp dụng cho các mục đã chọn',()=>{
      const chosenRows=state.batchRows.filter(row=>selected.has(row.key));const active=rowForActive();
      const result=applySettings(state.batchRows,selected,common,estimate);
      selected=new Set(chosenRows.map(row=>row.key));if(active)activeKey=active.key;
      refresh();notify(`Đã áp dụng cho ${result.changed} mục.${result.skipped?' Giữ nguyên mục đang chờ xác định kết quả gửi.':''}`);
    },'sc-button-outline');
    append(commonBottom,durationField('common'),field('common','speech_rhythm','Nhịp đọc',rhythmOptions),apply,advancedFields('common'));
    append(commonPanel,commonFields,commonBottom);
    const toolbar=node('div','sc-toolbar');
    const file=node('input');file.type='file';file.multiple=true;file.accept='.txt,.json,text/plain,application/json';file.hidden=true;file.id='studioBatchFile';
    const folder=node('input');folder.type='file';folder.multiple=true;folder.hidden=true;const folderSupported='webkitdirectory' in folder;folder.setAttribute('webkitdirectory','');
    async function importFiles(files) {
      if (busy()) throw Error('Đang xử lý, vui lòng chờ rồi nhập thêm file.');
      if (!options.importFiles) throw Error('Chức năng nhập file chưa được kết nối.');
      importing=true;refresh(false);
      try {await options.importFiles([...files]);activeKey=state.batchRows.at(-1)?.key;remember(state.batchRows.at(-1));}
      finally {importing=false;refresh();}
    }
    for(const input of [file,folder])input.onchange=async()=>{try{await importFiles(input.files || []);}catch(error){notify(error.message);}finally{input.value='';}};
    const drop=button('⇧  Thả file / Bấm chọn',()=>file.click(),'sc-file-drop');drop.title='Nhập TXT/JSON hoặc kéo thả cả thư mục';
    const folderButton=button('▱  Chọn thư mục',()=>{if(folderSupported)folder.click();else{notify('Trình duyệt chưa hỗ trợ chọn thư mục; hãy chọn nhiều file.');file.click();}});
    function addRow(base={}) {
      if (busy()) return null;
      const row=createRow(common,base,estimate);state.batchRows.push(row);activeKey=row.key;refresh();editorTitle.focus();return row;
    }
    const add=button('+  Thêm kịch bản',()=>addRow());
    const allLabel=node('label','sc-select-all');const all=node('input');all.type='checkbox';all.onchange=()=>{selected=all.checked?new Set(state.batchRows.map(row=>row.key)):new Set();refresh(false);};
    const itemCount=node('span');append(allLabel,itemCount,node('span','','Chọn tất cả'),all);
    append(toolbar,drop,folderButton,add,file,folder,allLabel);
    const importHint=node('p','sc-import-hint sc-muted','Mỗi file TXT là một video. Bạn có thể sửa nội dung trước khi xếp hàng.');
    const columns=node('div','sc-columns');
    const listPanel=node('section','sc-panel sc-list-panel');const listHeading=node('h2');const list=node('div','sc-script-list');list.id='studioBatchList';
    append(listPanel,append(node('div','sc-panel-heading'),listHeading),list,node('p','sc-list-hint sc-muted','↕ Kéo để đổi thứ tự chạy · hoặc dùng nút ↑ ↓'));
    const editorPanel=node('section','sc-panel sc-editor-panel');const editorHeading=node('h2');
    const rowSettings=node('details','sc-row-settings');const settingsSummary=node('summary','','Cài đặt riêng');rowSettings.append(settingsSummary);const rowSettingsGrid=node('div','sc-row-settings-grid');rowSettings.append(rowSettingsGrid);
    append(rowSettingsGrid,field('row','style','Phong cách',styles),field('row','speech_engine','Bộ đọc',engineOptions),voiceField('row'),field('row','image_provider','Hình ảnh',imageOptions),field('row','speech_rhythm','Nhịp đọc',rhythmOptions),advancedFields('row'));
    const editorBody=node('div','sc-editor-body');
    const titleLabel=node('label','sc-field');titleLabel.append(node('span','','Tiêu đề'));const editorTitle=node('input');editorTitle.type='text';editorTitle.maxLength=200;editorTitle.placeholder='Tên video (để trống: AI tự đặt)';titleLabel.append(editorTitle);editorTitle.oninput=()=>edit(rowForActive(),{title:editorTitle.value});
    const textLabel=node('label','sc-field sc-text-field');textLabel.append(node('span','','Kịch bản / ý tưởng'));const editorText=node('textarea');editorText.maxLength=100000;editorText.placeholder='Dán lời đọc hoặc ý tưởng của bạn…';textLabel.append(editorText);editorText.oninput=()=>edit(rowForActive(),{text:editorText.value});
    const counts=node('span','sc-muted sc-counts');
    function duplicate(row) {
      if(!row || locked(row))return;
      const copy=createRow(settingsOf(row),{text:row.text,title:row.title?`${row.title} (2)`:''},estimate);
      state.batchRows.splice(state.batchRows.indexOf(row)+1,0,copy);activeKey=copy.key;remember(copy);refresh();
    }
    function removeRow(row) {
      if(!row || locked(row))return;
      const index=state.batchRows.indexOf(row);selected.delete(row.key);state.batchRows.splice(index,1);
      if(activeKey===row.key)activeKey=state.batchRows[Math.min(index,state.batchRows.length-1)]?.key;
      refresh();
    }
    const duplicateButton=button('▢  Nhân bản mục',()=>duplicate(rowForActive()),'sc-link');
    const removeButton=button('♜  Xóa mục',()=>removeRow(rowForActive()),'sc-link');
    const editorActions=append(node('div','sc-editor-actions'),duplicateButton,removeButton,counts);
    const rowError=node('p','sc-row-error');rowError.setAttribute('role','alert');
    const uncertainNote=node('p','sc-notice','Chưa rõ kết quả gửi. Cài đặt được giữ nguyên để thử lại cùng yêu cầu, tránh tạo trùng.');
    const imageNote=node('p','sc-notice','Meme dùng kho asset có sẵn; lựa chọn dịch vụ tạo ảnh không áp dụng.');
    const activeDuration=durationField('row');activeDuration.classList.add('sc-inline-duration');
    append(editorBody,titleLabel,textLabel,activeDuration,editorActions,rowError,uncertainNote,imageNote,node('p','sc-notice','ⓘ Nội dung được lưu nháp tự động trên máy này.'));
    append(editorPanel,append(node('div','sc-panel-heading sc-editor-heading'),editorHeading),rowSettings,editorBody);
    append(columns,listPanel,editorPanel);
    const footer=node('footer','sc-panel sc-footer');const total=node('span','sc-total');const saveButton=button('▣  Lưu nháp',()=>save(true));
    const submit=button('Thêm video vào hàng đợi',async()=>{
      if (busy() || !state.batchRows.length) return;
      let invalid=false;
      for(const row of state.batchRows) {
        syncDuration(row,estimate);
        try {const error=validateRow(row);if(error)throw Error(error);const result=options.validation?.(row);if(typeof result==='string'&&result)throw Error(result);row.error='';}
        catch(error){row.error=error.message;invalid=true;}
      }
      if(invalid){const row=state.batchRows.find(row=>row.error);activeKey=row.key;refresh();notify('Sửa các mục đang báo lỗi trước khi thêm.');return;}
      save();
      try {if(!options.submit)throw Error('Chức năng xếp hàng chưa được kết nối.');await options.submit();}
      catch(error){notify(error.message);}
      finally{refresh();}
    },'sc-primary');submit.id='studioBatchSubmit';append(footer,total,saveButton,submit);
    const status=node('p','sc-status');status.id='studioBatchStatus';status.setAttribute('role','status');
    append(page,heading,commonPanel,toolbar,importHint,columns,footer,status);root.replaceChildren(page);
    function syncControl(record,value,disabled) {
      const {input,wrapper}=record;
      if(input.tagName==='SELECT') {
        const choices=typeof input._scChoices==='function'?input._scChoices():input._scChoices;
        const list=choices.length?[...choices]:[['','Đang tải giọng…']];
        if(value!==''&&value!=null&&!list.some(([key])=>String(key)===String(value)))list.push([String(value),String(value)]);
        const signature=JSON.stringify(list);
        if(input._scSignature!==signature && doc.activeElement!==input) {
          input.replaceChildren(...list.map(([key,label])=>{const option=node('option','',label);option.value=key;return option;}));input._scSignature=signature;
        }
      }
      if(doc.activeElement!==input && input.value!==String(value ?? ''))input.value=String(value ?? '');
      input.disabled=disabled;wrapper.classList.toggle('is-disabled',disabled);
    }
    function syncFields(target,records,value) {
      for(const [key,record] of records) {
        const disabled=target==='row'?locked(value):busy();
        syncControl(record,value[key],disabled || key==='image_provider'&&value.style==='meme');
        if(key==='khanh_steps')record.wrapper.hidden=value.speech_engine!=='khanhtts';
        if(key==='speech_reference_text')record.wrapper.hidden=value.speech_engine!=='khanhtts'||!String(value.voice||'').startsWith('clone:');
        if(key==='seconds') {
          const isSec = String(value.unit) === '1';
          record.unitSelect.value = isSec ? '1' : '60';
          record.unitSelect.disabled = disabled;
          record.reset.disabled = disabled;
          record.input.setAttribute('aria-label', `${isSec ? 'Độ dài (giây)' : 'Độ dài (phút)'}${target==='common'?' — thiết lập chung':' — mục đang sửa'}`);
          record.input.step = 'any';
          record.input.min = '0.000001';
          record.note.textContent=value.duration_mode==='manual'
            ? `Đã tự nhập (${isSec ? 'giây' : 'phút'}) · giữ nguyên khi sửa nội dung/giọng`
            : `Tự tính theo nội dung và giọng (${isSec ? 'giây' : 'phút'}) · có thể sửa trực tiếp`;
        }
      }
    }
    function renderList() {
      list.replaceChildren();listHeading.textContent=`Danh sách kịch bản (${state.batchRows.length})`;
      for(const [index,row] of state.batchRows.entries()) {
        const card=node('article','sc-script-card');card.classList.toggle('is-active',row.key===activeKey);card.classList.toggle('has-error',Boolean(row.error));card.dataset.key=row.key;card.draggable=!busy();
        card.ondragstart=event=>{if(event.target.closest('button,input')){event.preventDefault();return;}draggedKey=row.key;event.dataTransfer?.setData('application/x-studio-row',row.key);if(event.dataTransfer)event.dataTransfer.effectAllowed='move';};
        card.ondragend=()=>{draggedKey=null;};card.ondragover=event=>{if(draggedKey)event.preventDefault();};
        card.ondrop=event=>{if(!draggedKey)return;event.preventDefault();event.stopPropagation();const from=state.batchRows.findIndex(item=>item.key===draggedKey);moveRow(state.batchRows,from,index);draggedKey=null;refresh();};
        const grip=node('span','sc-grip','⠿');grip.setAttribute('aria-hidden','true');
        const check=node('input');check.type='checkbox';check.checked=selected.has(row.key);check.setAttribute('aria-label',`Chọn video ${index+1}`);check.onchange=()=>{if(check.checked)selected.add(row.key);else selected.delete(row.key);refresh(false);};
        const open=button('',()=>{activeKey=row.key;refresh();},'sc-script-open');open.setAttribute('aria-label',`Sửa video ${index+1}: ${titleFor(row,index)}`);open.setAttribute('aria-pressed',String(row.key===activeKey));
        const rowMetrics=metrics(row.text);const seconds=row.uncertain&&row.submitted_duration_seconds?row.submitted_duration_seconds:Number(row.seconds)*Number(row.unit);
        append(open,node('strong','',`${String(index+1).padStart(2,'0')}  ${titleFor(row,index)}`),node('span','sc-muted',`${rowMetrics.words.toLocaleString('vi-VN')} từ · ≈ ${Number.isFinite(seconds)?durationText(seconds):'chưa có độ dài'} · ${labelFor(styles,row.style)}`),node('span','sc-row-chip',`${voiceName(row.voice)} · ${labelFor(imageOptions,row.image_provider)}${row.uncertain?' · Chờ xác định':''}`));
        const actions=node('div','sc-card-actions');const copy=button('▢',()=>duplicate(row));copy.title='Nhân bản';copy.setAttribute('aria-label',`Nhân bản video ${index+1}`);copy.disabled=locked(row);
        const menu=node('details','sc-card-menu');const menuSummary=node('summary','','•••');menuSummary.setAttribute('aria-label',`Thao tác video ${index+1}`);menu.append(menuSummary);
        const menuBody=node('div','sc-card-menu-body');
        const up=button('↑ Lên',()=>{moveRow(state.batchRows,index,index-1);refresh();});up.disabled=busy()||index===0;
        const down=button('↓ Xuống',()=>{moveRow(state.batchRows,index,index+1);refresh();});down.disabled=busy()||index===state.batchRows.length-1;
        const remove=button('Xóa',()=>removeRow(row));remove.disabled=locked(row);append(menuBody,up,down,remove);menu.append(menuBody);append(actions,copy,menu);
        append(card,grip,check,open,actions);if(row.error)card.append(node('span','sc-card-error',row.error));list.append(card);
      }
      if(!state.batchRows.length)list.append(node('p','sc-empty sc-muted','Chưa có kịch bản. Thêm kịch bản hoặc nhập file để bắt đầu.'));
    }
    function refresh(rebuildEditor = true) {
      if(destroyed)return;
      const firstVoice=voiceList()[0]?.[0];
      // Catalog loading must populate genuinely empty choices, while retaining saved voice IDs.
      if(firstVoice) {
        if(!common.voice)common.voice=firstVoice;
        for(const row of state.batchRows)if(!row.voice&&!row.uncertain)row.voice=firstVoice;
      }
      const validKeys=new Set(state.batchRows.map(row=>row.key));selected=new Set([...selected].filter(key=>validKeys.has(key)));
      if(!validKeys.has(activeKey))activeKey=state.batchRows[0]?.key;
      for(const row of state.batchRows)syncDuration(row,estimate);
      const active=rowForActive();
      if(common.duration_mode==='auto') {const updated=syncDuration({...common,text:active?.text||''},estimate);common.seconds=updated.seconds;common.unit=updated.unit;}
      syncFields('common',commonControls,common);
      renderList();
      editorBody.hidden=!active;rowSettings.hidden=!active;
      editorHeading.textContent=active?`Chỉnh nội dung · Mục ${String(state.batchRows.indexOf(active)+1).padStart(2,'0')}`:'Chỉnh nội dung';
      if(active) {
        // These inputs stay mounted while typing and while the host loads voice profiles.
        if(editorKey!==active.key || rebuildEditor) {
          if(doc.activeElement!==editorTitle)editorTitle.value=active.title || '';
          if(doc.activeElement!==editorText)editorText.value=active.text || '';
          editorKey=active.key;
        }
        const readOnly=locked(active);editorTitle.disabled=readOnly;editorText.disabled=readOnly;duplicateButton.disabled=readOnly;removeButton.disabled=readOnly;
        syncFields('row',editorControls,active);
        const count=metrics(active.text);counts.textContent=`${count.words.toLocaleString('vi-VN')} từ · ${count.characters.toLocaleString('vi-VN')} ký tự · ≈ ${durationText(Number(active.seconds)*Number(active.unit))}`;
        rowError.textContent=active.error || '';rowError.hidden=!active.error;uncertainNote.hidden=!active.uncertain;imageNote.hidden=active.style!=='meme';
      }
      itemCount.textContent=`${state.batchRows.length} mục · `;all.checked=Boolean(state.batchRows.length)&&selected.size===state.batchRows.length;all.indeterminate=selected.size>0&&selected.size<state.batchRows.length;
      apply.disabled=busy()||!selected.size;apply.title=selected.size?`Áp dụng cho ${selected.size} mục đã chọn`:'Chọn ít nhất một mục trong danh sách';
      for(const control of [drop,folderButton,add])control.disabled=busy();
      const seconds=state.batchRows.reduce((sum,row)=>sum+(Number(row.seconds)*Number(row.unit)||0),0);total.textContent=`▷  ${state.batchRows.length} video · Ước tính tổng ${durationText(seconds)} nội dung`;
      submit.textContent=state.batchSubmitting?'Đang thêm vào hàng đợi…':`Thêm ${state.batchRows.length} video vào hàng đợi →`;submit.disabled=busy()||!state.batchRows.length;
      save();
    }
    page.ondragover=event=>{if(!draggedKey && [...(event.dataTransfer?.types || [])].includes('Files')){event.preventDefault();drop.classList.add('is-dragging');}};
    page.ondragleave=event=>{if(!page.contains(event.relatedTarget))drop.classList.remove('is-dragging');};
    page.ondrop=async event=>{
      if(draggedKey)return;
      if(![...(event.dataTransfer?.types || [])].includes('Files'))return;
      event.preventDefault();event.stopPropagation();drop.classList.remove('is-dragging');
      try {const files=options.collectDroppedFiles?await options.collectDroppedFiles(event.dataTransfer):[...(event.dataTransfer?.files || [])];await importFiles(files);}
      catch(error){notify(error.message);}
    };
    const beforeUnload=()=>save();global.addEventListener?.('beforeunload',beforeUnload);
    refresh();
    return {refresh,update:refresh,save,addRow,importFiles,rememberSettings(row){remember(row);save();},get common(){return common;},get selectedKeys(){return new Set(selected);},get activeKey(){return activeKey;},destroy(){save();destroyed=true;global.removeEventListener?.('beforeunload',beforeUnload);}};
  }
  global.StudioCreate = {mount,DEFAULTS,DRAFT_KEY,LAST_KEY,settingsOf,estimatedSeconds,syncDuration,convertDurationUnit,setMinutes,setSeconds,resetDuration,createRow,editRow,validateRow,serializeDraft,restoreDraft,applySettings,moveRow};
})(typeof window === 'undefined' ? globalThis : window);

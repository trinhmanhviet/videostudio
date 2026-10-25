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
  document.head.append(style);

  let state = null;
  let busy = false;
  let job = null;
  let exportIdentity = null;
  let objectURLs = [];
  let workspaceScrollY = 0;
  let editorScrollY = 0;
  let candidateTimers = [];
  let previousViewId = 'viewWorkspace';
  const promptDrafts = new Map();
  const expandedPrompts = new Set();

  const $ = id => document.getElementById(id);
  const node = (tag, content, cls) => {
    const e = document.createElement(tag);
    if (content !== undefined) e.textContent = content;
    if (cls) e.className = cls;
    return e;
  };
  const clock = s => {
    const n = Math.max(0, Math.floor(Number(s) || 0));
    return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
  };
  const base = () => '/api/jobs/' + encodeURIComponent(job) + '/scene-editor';

  function message(s, error = false) {
    const el = $('sePageMessage');
    if (!el) return;
    el.textContent = s;
    el.style.color = error ? '#fca5a5' : 'var(--accent)';
  }

  function setBusy(val) {
    busy = val;
    const view = $('viewSceneEditor');
    if (!view) return;
    view.querySelectorAll('button, select, input').forEach(e => {
      if (e.id === 'btnBackFromEditor') return;
      if (e.dataset.permDisabled === 'true') {
        e.disabled = true;
        return;
      }
      e.disabled = busy;
    });
  }

  async function jsonRequest(path, options = {}) {
    const r = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      signal: AbortSignal.timeout(120000)
    });
    const data = await r.json().catch(() => ({ detail: 'Phản hồi không hợp lệ' }));
    if (!r.ok) {
      throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
    }
    return data;
  }

  async function mutation(path, payload) {
    if (busy || !state?.editable) return;
    setBusy(true);
    message('Đang lưu thay đổi...');
    try {
      state = await jsonRequest(base() + path, {
        method: 'POST',
        body: JSON.stringify({ ...payload, version: state.version })
      });
      exportIdentity = null;
      render();
      message('Đã cập nhật ảnh cảnh. Lời đọc, phụ đề và timeline vẫn giữ nguyên.');
    } catch (e) {
      message(e.message + ' (Hãy thử bấm Làm mới nếu phiên bản bị lệch).', true);
    } finally {
      setBusy(false);
    }
  }

  function render() {
    candidateTimers.forEach(t => clearTimeout(t));
    candidateTimers = [];
    objectURLs.forEach(u => URL.revokeObjectURL(u));
    objectURLs = [];

    const grid = $('sePageGrid');
    if (!grid || !state) return;

    // Header info
    const editedCount = state.scenes.filter(s => s.edit_id !== 'original').length;
    const titleEl = $('sePageTitle');
    if (titleEl) titleEl.textContent = 'Ảnh từng cảnh (Bản ' + state.version + ')';
    const countEl = $('sePageCount');
    if (countEl) countEl.textContent = `${state.scenes.length} cảnh${editedCount > 0 ? ` · ${editedCount} đã sửa` : ''}`;

    const filter = $('sePageFilter')?.value || 'all';
    const rows = state.scenes.filter(s => filter === 'all' || (filter === 'edited' && s.edit_id !== 'original'));

    const cards = rows.map(s => {
      const card = node('article', undefined, 'se-card');
      card.dataset.sceneId = s.scene_id;

      // 1. Header: Cảnh X · start - end (duration s)
      const headerText = `Cảnh ${s.index + 1} · ${clock(s.start)} - ${clock(s.start + s.duration)} (${Number(s.duration).toFixed(2)}s)`;
      card.append(node('div', headerText, 'se-card-header'));

      // 2. Top Row: Left Image (9:16) + Right Controls
      const topRow = node('div', undefined, 'se-card-top');

      // 2a. Left: Image container
      const imgWrap = node('div', undefined, 'se-card-img-wrap');
      const mainImg = node('img', undefined, 'se-main-image');
      mainImg.loading = 'lazy';
      mainImg.src = s.image_url + '&thumb=true';
      mainImg.alt = `Ảnh cảnh ${s.index + 1}`;
      mainImg.style.objectFit = s.fit === 'contain' ? 'contain' : 'cover';
      imgWrap.append(mainImg);
      topRow.append(imgWrap);

      // 2b. Right: Controls (Browse, Vẽ lại, Radios)
      const ctrls = node('div', undefined, 'se-card-ctrls');

      // Hidden file input
      const fileInput = node('input');
      fileInput.type = 'file';
      fileInput.accept = 'image/png,image/jpeg,image/webp';
      fileInput.style.display = 'none';
      ctrls.append(fileInput);

      // Browse button
      const browseBtn = node('button', 'Browse', 'se-btn-green');
      browseBtn.type = 'button';
      browseBtn.title = 'Tải ảnh từ máy tính lên để thay cho cảnh này';
      browseBtn.onclick = () => fileInput.click();
      ctrls.append(browseBtn);

      // Status indicator
      const cardStatus = node('div', undefined, 'se-card-status');

      // File change -> Upload immediately
      fileInput.onchange = async () => {
        const f = fileInput.files[0];
        if (!f) return;
        if (f.size > 20 * 1024 * 1024) {
          cardStatus.textContent = 'Ảnh tối đa 20 MB.';
          cardStatus.className = 'se-card-status is-error';
          fileInput.value = '';
          return;
        }
        setBusy(true);
        browseBtn.disabled = true;
        cardStatus.textContent = 'Đang tải lên...';
        cardStatus.className = 'se-card-status';
        try {
          state = await jsonRequest(
            base() + '/scenes/' + encodeURIComponent(s.scene_id) + '/image?fit=cover&version=' + state.version,
            {
              method: 'POST',
              headers: { 'Content-Type': f.type || 'application/octet-stream' },
              body: f
            }
          );
          exportIdentity = null;
          render();
          message('Đã áp dụng ảnh tải lên cho Cảnh ' + (s.index + 1));
        } catch (err) {
          cardStatus.textContent = err.message;
          cardStatus.className = 'se-card-status is-error';
        } finally {
          setBusy(false);
          browseBtn.disabled = false;
        }
      };

      // Vẽ lại button
      const regenBtn = node('button', 'Vẽ lại', 'se-btn-green');
      regenBtn.type = 'button';
      regenBtn.title = 'Yêu cầu vẽ lại ảnh cho cảnh này';
      ctrls.append(regenBtn);

      // Provider radio buttons (ChatGPT, Flow, Comfy)
      const radioBox = node('div', undefined, 'se-provider-radios');
      const radioName = 'provider_' + s.scene_id;

      const rChat = node('label', undefined, 'se-radio-item');
      const rChatInput = node('input');
      rChatInput.type = 'radio';
      rChatInput.name = radioName;
      rChatInput.value = 'chatgpt';
      rChatInput.checked = true;
      rChat.append(document.createTextNode('Chatgpt'), rChatInput);

      const rFlow = node('label', undefined, 'se-radio-item is-disabled');
      const rFlowInput = node('input');
      rFlowInput.type = 'radio';
      rFlowInput.name = radioName;
      rFlowInput.value = 'flow';
      rFlowInput.disabled = true;
      rFlowInput.dataset.permDisabled = 'true';
      rFlow.title = 'Google Flow chưa bật';
      rFlow.append(document.createTextNode('Flow'), rFlowInput);

      const rComfy = node('label', undefined, 'se-radio-item is-disabled');
      const rComfyInput = node('input');
      rComfyInput.type = 'radio';
      rComfyInput.name = radioName;
      rComfyInput.value = 'comfy';
      rComfyInput.disabled = true;
      rComfyInput.dataset.permDisabled = 'true';
      rComfy.title = 'Comfy tạo từng cảnh chưa bật';
      rComfy.append(document.createTextNode('Comfy'), rComfyInput);

      radioBox.append(rChat, rFlow, rComfy);
      ctrls.append(radioBox);

      // Prompt editing toggle
      const promptToggle = node('button', '✏️ Sửa mô tả vẽ', 'se-prompt-toggle');
      promptToggle.type = 'button';
      const promptBox = node('div', undefined, 'se-prompt-box');
      const draftKey = job + ':' + s.scene_id;
      promptBox.hidden = !expandedPrompts.has(draftKey);
      const promptInput = node('textarea', undefined, 'se-prompt-input');
      promptInput.value = promptDrafts.has(draftKey) ? promptDrafts.get(draftKey) : (s.visual_prompt || s.narration || '');
      promptInput.oninput = () => { promptDrafts.set(draftKey, promptInput.value); };
      promptInput.maxLength = 12000;
      promptInput.placeholder = 'Mô tả hình ảnh bằng tiếng Anh hoặc tiếng Việt...';
      promptBox.append(promptInput);

      promptToggle.onclick = () => {
        promptBox.hidden = !promptBox.hidden;
        if (!promptBox.hidden) expandedPrompts.add(draftKey);
        else expandedPrompts.delete(draftKey);
      };
      ctrls.append(promptToggle, promptBox);

      // Append status under controls
      ctrls.append(cardStatus);
      topRow.append(ctrls);
      card.append(topRow);

      // 3. Middle Section: Narration + Audio Player
      const narrP = node('p', s.narration, 'se-narration');
      card.append(narrP);

      const audio = node('audio', undefined, 'se-audio');
      audio.controls = true;
      audio.preload = 'none';
      audio.src = s.audio_url;
      card.append(audio);

      // 4. Bottom Section: History Dropdown + Thumbnail Grid
      const historySelect = node('select', undefined, 'se-history-select');
      historySelect.setAttribute('aria-label', `Lịch sử ảnh cảnh ${s.index + 1}`);

      // Original option
      historySelect.append(new Option('Ảnh gốc · cắt vừa', 'original'));

      // Populate history items
      (s.history || []).forEach(h => {
        const timeStr = new Date(h.created * 1000).toLocaleString();
        const fitStr = h.fit === 'contain' ? 'toàn ảnh' : 'cắt vừa';
        const provStr = h.provider === 'chatgpt' ? 'ChatGPT' : 'Tải lên';
        historySelect.append(new Option(`${timeStr} · ${fitStr} (${provStr})`, h.id));
      });
      historySelect.value = s.edit_id;

      // Handle dropdown change -> restore
      historySelect.onchange = () => {
        mutation('/scenes/' + encodeURIComponent(s.scene_id) + '/restore', { edit_id: historySelect.value });
      };
      card.append(historySelect);

      // Thumbnail Grid (4 columns, scrollable)
      const thumbsGrid = node('div', undefined, 'se-thumbs-grid');

      // Helper to append a thumbnail
      function addThumb(imgSrc, label, isActive, onClick) {
        const tWrap = node('div', undefined, 'se-thumb-wrap' + (isActive ? ' is-active' : ''));
        const tImg = node('img', undefined, 'se-thumb-img');
        tImg.loading = 'lazy';
        tImg.src = imgSrc;
        tImg.alt = label;
        tWrap.append(tImg);
        if (label) {
          tWrap.append(node('span', label, 'se-thumb-badge'));
        }
        tWrap.onclick = onClick;
        thumbsGrid.append(tWrap);
        return tWrap;
      }

      // Add Original thumb
      addThumb(
        `/api/jobs/${job}/scene-editor/scenes/${s.scene_id}/image?edit=original&thumb=true`,
        'Ảnh gốc',
        s.edit_id === 'original',
        () => mutation('/scenes/' + encodeURIComponent(s.scene_id) + '/restore', { edit_id: 'original' })
      );

      // Add Revisions thumbs
      (s.history || []).forEach(h => {
        addThumb(
          `/api/jobs/${job}/scene-editor/scenes/${s.scene_id}/image?edit=${h.id}&thumb=true`,
          h.provider === 'chatgpt' ? 'ChatGPT' : 'Đã sửa',
          s.edit_id === h.id,
          () => mutation('/scenes/' + encodeURIComponent(s.scene_id) + '/restore', { edit_id: h.id })
        );
      });

      card.append(thumbsGrid);

      // Function to poll and load ChatGPT candidates for this scene
      async function loadCandidates() {
        const thisJob = job;
        if (!card.isConnected || $('viewSceneEditor')?.hidden || thisJob !== job) return;
        try {
          const genData = await jsonRequest(base() + '/scenes/' + encodeURIComponent(s.scene_id) + '/generations');
          if (!card.isConnected || $('viewSceneEditor')?.hidden || thisJob !== job) return;
          const items = genData.items || [];
          const running = items.find(t => ['queued', 'running'].includes(t.state));
          if (running) {
            regenBtn.disabled = true;
            cardStatus.textContent = 'Đang vẽ ảnh trên ChatGPT...';
            candidateTimers.push(setTimeout(loadCandidates, 3000));
          } else {
            regenBtn.disabled = false;
          }

          // Add completed candidates to thumbsGrid if not already there
          items.forEach(cand => {
            if (cand.state === 'completed' && cand.image_url) {
              const existing = thumbsGrid.querySelector(`[data-cand-id="${cand.id}"]`);
              if (!existing) {
                const tWrap = addThumb(
                  cand.image_url,
                  'Ứng viên mới',
                  false,
                  async () => {
                    cardStatus.textContent = 'Đang áp dụng ảnh ứng viên...';
                    try {
                      await mutation(
                        '/scenes/' + encodeURIComponent(s.scene_id) + '/generations/' + encodeURIComponent(cand.id) + '/apply',
                        { fit: 'cover' }
                      );
                    } catch (e) {
                      cardStatus.textContent = e.message;
                      cardStatus.className = 'se-card-status is-error';
                    }
                  }
                );
                if (tWrap) tWrap.dataset.candId = cand.id;
              }
            }
          });
        } catch (_) {}
      }

      // Check candidates initially
      loadCandidates();

      // Hook "Vẽ lại" button
      regenBtn.onclick = async () => {
        const text = promptInput.value.trim() || s.visual_prompt || s.narration;
        if (!text) {
          cardStatus.textContent = 'Nhập mô tả hình ảnh cần vẽ.';
          cardStatus.className = 'se-card-status is-error';
          return;
        }
        setBusy(true);
        regenBtn.disabled = true;
        cardStatus.textContent = 'Đang gửi yêu cầu tới ChatGPT...';
        cardStatus.className = 'se-card-status';
        try {
          const key = crypto.randomUUID();
          await jsonRequest(base() + '/scenes/' + encodeURIComponent(s.scene_id) + '/generations', {
            method: 'POST',
            headers: { 'Idempotency-Key': key },
            body: JSON.stringify({ prompt: text, provider: 'chatgpt', version: state.version })
          });
          cardStatus.textContent = 'Đã gửi! Đang vẽ trên ChatGPT...';
          setTimeout(loadCandidates, 2500);
        } catch (e) {
          cardStatus.textContent = e.message;
          cardStatus.className = 'se-card-status is-error';
          regenBtn.disabled = false;
        } finally {
          setBusy(false);
        }
      };

      return card;
    });

    grid.replaceChildren(...cards);
  }

  async function refresh() {
    if (busy || !job) return;
    setBusy(true);
    message('Đang tải dữ liệu cảnh...');
    try {
      state = await jsonRequest(base());
      render();
      message('Đã nạp ' + state.scenes.length + ' cảnh.');
    } catch (e) {
      message(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  window.openSceneEditor = async (jid) => {
    if (busy) return;
    job = jid;
    state = null;
    exportIdentity = null;

    // Save previous scroll position
    workspaceScrollY = window.scrollY || document.documentElement.scrollTop;

    // Switch views
    const viewGallery = document.getElementById('viewGallery');
    const viewWorkspace = document.getElementById('viewWorkspace');
    const viewEditor = document.getElementById('viewSceneEditor');

    previousViewId = (viewWorkspace && !viewWorkspace.hidden) ? 'viewWorkspace' : 'viewGallery';

    if (viewGallery) viewGallery.hidden = true;
    if (viewWorkspace) viewWorkspace.hidden = true;
    if (viewEditor) viewEditor.hidden = false;

    // Update URL hash without jumping
    if (location.hash !== '#/editor/' + encodeURIComponent(jid)) {
      location.hash = '#/editor/' + encodeURIComponent(jid);
    }

    // Scroll to top of editor
    window.scrollTo(0, editorScrollY || 0);

    // Initial load
    await refresh();
  };

  function closeSceneEditor() {
    if (busy) return;

    candidateTimers.forEach(t => clearTimeout(t));
    candidateTimers = [];

    // Pause all audio
    const viewEditor = document.getElementById('viewSceneEditor');
    if (viewEditor) {
      viewEditor.querySelectorAll('audio').forEach(a => a.pause());
      viewEditor.hidden = true;
    }

    editorScrollY = window.scrollY || document.documentElement.scrollTop;

    // Restore workspace or gallery
    const viewWorkspace = document.getElementById('viewWorkspace');
    const viewGallery = document.getElementById('viewGallery');

    if (previousViewId === 'viewWorkspace' && viewWorkspace) {
      viewWorkspace.hidden = false;
    } else if (viewGallery) {
      viewGallery.hidden = false;
    }

    // Restore scroll position
    window.scrollTo(0, workspaceScrollY || 0);

    // Clean hash
    if (location.hash.startsWith('#/editor')) {
      history.replaceState(null, '', location.pathname + location.search);
    }
  }

  // Bind top bar events
  const btnBack = document.getElementById('btnBackFromEditor');
  if (btnBack) btnBack.onclick = closeSceneEditor;

  const btnReload = document.getElementById('sePageReload');
  if (btnReload) btnReload.onclick = refresh;

  const filterSelect = document.getElementById('sePageFilter');
  if (filterSelect) filterSelect.onchange = () => state && render();

  const btnExport = document.getElementById('sePageExport');
  if (btnExport) {
    btnExport.onclick = async () => {
      if (busy || !state?.editable) return;
      setBusy(true);
      message('Đang chốt ảnh và tạo phiên bản xuất mới...');
      try {
        const key = crypto.randomUUID();
        const child = await jsonRequest(base() + '/export', {
          method: 'POST',
          headers: { 'Idempotency-Key': key },
          body: JSON.stringify({ version: state.version, confirm_all: true })
        });
        message('Đã xuất phiên bản video mới: ' + child.id.slice(0, 8) + '. Đang dựng video với các ảnh đã chọn!');
        if (typeof window.loadJobs === 'function') await window.loadJobs();
      } catch (e) {
        message('Lỗi xuất video: ' + e.message, true);
      } finally {
        setBusy(false);
      }
    };
  }

  // Handle browser Back / Forward navigation
  window.addEventListener('hashchange', () => {
    const match = location.hash.match(/^#\/editor\/([^?&]+)/);
    const viewEditor = document.getElementById('viewSceneEditor');
    if (match) {
      const targetJob = decodeURIComponent(match[1]);
      if (targetJob !== job || (viewEditor && viewEditor.hidden)) {
        window.openSceneEditor(targetJob);
      }
    } else {
      if (viewEditor && !viewEditor.hidden) {
        closeSceneEditor();
      }
    }
  });

  // Check initial hash on load
  window.addEventListener('DOMContentLoaded', () => {
    const match = location.hash.match(/^#\/editor\/([^?&]+)/);
    if (match) {
      window.openSceneEditor(decodeURIComponent(match[1]));
    }
  });
})();

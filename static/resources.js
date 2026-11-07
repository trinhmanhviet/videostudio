(function () {
  'use strict';
  const normalize = value => String(value ?? '').toLowerCase().normalize('NFD').replace(/\p{M}/gu, '').replace(/đ/g, 'd').replace(/[_-]+/g, ' ').trim();
  function matches(item, query) {
    const terms = normalize([item.id, item.name, item.label, item.label_vi, item.label_en, item.kind, ...(item.search_terms || [])].join(' '));
    return normalize(query).split(/\s+/).filter(Boolean).every(word => terms.includes(word));
  }
  function imageURL(item, kind) {
    const id = encodeURIComponent(item.id);
    if (kind === 'backgrounds') return `/meme-assets/backgrounds/${id}.png`;
    return item.source === 'memestudio' ? `/meme-assets/props/${id}.png` : `/prop-assets/${id}.png`;
  }
  window.ResourceLibrary = {normalize, matches, imageURL};
  if (typeof document === 'undefined') return;

  const $ = selector => document.querySelector(selector);
  const labels = {props:'đạo cụ', backgrounds:'bối cảnh', voices:'giọng đọc', sfx:'âm thanh'};
  const state = {kind:'props', selected:null, props:[], backgrounds:[], voices:[], sfx:[], extra:{}, errors:[]};
  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text != null) el.textContent = text;
    if (className) el.className = className;
    return el;
  }
  async function request(path, options) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Không tải được dữ liệu (${res.status})`);
    return data;
  }
  function status(message, error = false) {
    $('#resourceStatus').textContent = message;
    $('#resourceStatus').dataset.state = error ? 'error' : 'saved';
  }
  function title(item) { return item.label_vi || item.label || item.name || item.id; }
  function preview(item, kind, large = false) {
    const box = node('div', null, 'asset-preview');
    if (kind === 'props' || kind === 'backgrounds') {
      if (kind === 'props' && item.exists === false) { box.append(node('span', 'Chưa có ảnh', 'muted')); return box; }
      const img = node('img');
      img.src = imageURL(item, kind);
      img.alt = large ? title(item) : '';
      img.loading = 'lazy';
      img.onerror = () => { img.remove(); box.append(node('span', 'Không tải được ảnh', 'muted')); };
      box.append(img);
    } else box.append(node('span', kind === 'voices' ? '♩' : '♫', 'asset-icon'));
    return box;
  }
  function visibleItems() {
    return (state[state.kind] || []).filter(item => matches(item, $('#resourceSearch').value)).filter(item => {
      if (state.kind !== 'props') return true;
      return $('#resourceFilter').value === 'uploaded' ? item.uploaded : $('#resourceFilter').value === 'ready' ? item.exists !== false : true;
    });
  }
  function render() {
    if (state.kind === 'characters') return;
    const grid = $('#resourceGrid');
    grid.replaceChildren();
    const items = visibleItems();
    if (!items.some(item => item.id === state.selected)) state.selected = items[0]?.id || null;
    for (const item of items) {
      const card = node('button', null, 'resource-card');
      card.type = 'button';
      card.dataset.kind = state.kind;
      card.setAttribute('aria-pressed', String(item.id === state.selected));
      card.append(preview(item, state.kind), node('strong', title(item)));
      const subtitle = item.label_en || (state.kind === 'props' ? item.id.replace(/_/g, ' ') : item.id);
      card.append(node('small', subtitle));
      if (state.kind === 'props') card.append(node('span', item.exists === false ? 'Thiếu ảnh' : '✓', 'asset-state'));
      if (state.kind === 'voices' && item.available === false) card.append(node('small', 'Không khả dụng'));
      card.onclick = () => { state.selected = item.id; render(); };
      grid.append(card);
    }
    if (!items.length) grid.append(node('div', $('#resourceSearch').value ? 'Không tìm thấy tài nguyên phù hợp.' : `Chưa có ${labels[state.kind]} trong thư viện.`, 'resource-empty'));
    $('#resourceCount').textContent = `${items.length} ${labels[state.kind]}`;
    inspect(items.find(item => item.id === state.selected));
  }
  function detailRow(list, name, value) {
    const row = node('div');
    row.append(node('dt', name), node('dd', value));
    list.append(row);
  }
  function inspect(item) {
    const panel = $('#resourceInspector');
    panel.replaceChildren();
    if (!item) { panel.append(node('div', 'Chọn một tài nguyên để xem chi tiết.', 'resource-empty')); return; }
    const kind = state.kind;
    panel.append(preview(item, kind, true), node('h2', title(item)), node('p', item.label_en || item.id));
    const dl = node('dl');
    if (kind === 'props') {
      detailRow(dl, 'Nguồn', item.uploaded ? 'Ảnh đã tải lên' : 'Thư viện có sẵn');
      detailRow(dl, 'Trạng thái', item.exists === false ? 'Chưa có ảnh' : 'Sẵn sàng dùng');
      const layout = item.handheld_layout || item.default_layout || item.layout || state.extra.prop_layouts?.[item.id];
      if (layout) {
        if (Number.isFinite(layout.scale)) detailRow(dl, 'Kích thước mặc định', `${Math.round(layout.scale * 100)}%`);
        if (Number.isFinite(layout.grip_x) && Number.isFinite(layout.grip_y)) detailRow(dl, 'Điểm cầm đã lưu', `${Math.round(layout.grip_x * 100)}% / ${Math.round(layout.grip_y * 100)}%`);
      }
      const usage = item.usage_count ?? state.extra.prop_usage?.[item.id];
      if (Number.isInteger(usage)) detailRow(dl, 'Đang dùng', `${usage} tập phim`);
      panel.append(dl, node('p', 'Chọn đạo cụ trong phòng chỉnh sửa tập phim để gán ảnh, căn kích thước và điểm cầm.'));
    } else if (kind === 'voices') {
      detailRow(dl, 'Trạng thái', item.available === false ? 'Không khả dụng' : 'Có trong thư viện');
      if (item.engine) detailRow(dl, 'Bộ giọng', item.engine);
      panel.append(dl);
      if (item.sample_url) {
        const audio = node('audio'); audio.controls = true; audio.preload = 'none'; audio.src = item.sample_url; panel.append(audio);
      } else panel.append(node('p', 'Giọng này chưa có bản nghe mẫu.'));
      panel.append(node('p', 'Chọn giọng trong phần tạo tập phim để sử dụng.'));
    } else if (kind === 'sfx') {
      const audio = node('audio'); audio.controls = true; audio.preload = 'none'; audio.src = item.url; panel.append(audio);
      panel.append(node('p', 'Âm thanh có sẵn trong bộ tài nguyên hoạt hình.'));
    } else panel.append(node('p', 'Chọn bối cảnh này từ tab Cảnh trong phòng chỉnh sửa tập phim.'));
    const projects = node('a', 'Mở dự án video →', 'btn secondary'); projects.href = '/?view=projects'; panel.append(projects);
  }
  function selectKind(kind, updateURL = true) {
    if (!['characters','props','backgrounds','voices','sfx'].includes(kind)) kind = 'props';
    state.kind = kind; state.selected = null;
    document.querySelectorAll('[data-resource]').forEach(button => button.setAttribute('aria-selected', String(button.dataset.resource === kind)));
    $('#characterResource').hidden = kind !== 'characters';
    $('#resourceBody').hidden = kind === 'characters';
    $('#resourceFilter').hidden = kind !== 'props';
    $('#voiceNote').hidden = kind !== 'voices';
    $('#resourceImport').hidden = kind !== 'props';
    $('#resourceSearch').value = '';
    if (kind === 'characters' && !$('#characterFrame').src) $('#characterFrame').src = '/characters.html?embedded=1';
    if (updateURL) { const url = new URL(window.location.href); url.searchParams.set('tab', kind); window.history.replaceState(null, '', url); }
    render();
  }
  async function load() {
    status('Đang tải thư viện…');
    const results = await Promise.allSettled([request('/api/meme/catalog'), request('/api/voices'), request('/api/resources')]);
    state.errors = [];
    if (results[0].status === 'fulfilled') {
      state.props = results[0].value.props || [];
      state.backgrounds = (results[0].value.backgrounds || []).map(item => typeof item === 'string' ? {id:item,label:item.replace(/_/g, ' ')} : item);
    } else state.errors.push('đạo cụ / bối cảnh');
    if (results[1].status === 'fulfilled') { const data = results[1].value; state.voices = Array.isArray(data) ? data : data.items || data.voices || []; }
    else state.errors.push('giọng đọc');
    if (results[2].status === 'fulfilled') { state.extra = results[2].value; state.sfx = state.extra.sfx || []; }
    else state.errors.push('âm thanh / thông tin sử dụng');
    status(state.errors.length ? `Không tải được: ${state.errors.join(', ')}` : '✓ Đã cập nhật thư viện', state.errors.length > 0);
    render();
  }
  document.querySelectorAll('[data-resource]').forEach(button => button.onclick = () => selectKind(button.dataset.resource));
  $('#resourceSearch').oninput = render;
  $('#resourceFilter').onchange = render;
  $('#resourceImport').onclick = () => { $('#importError').textContent = ''; $('#importDialog').showModal(); };
  $('#closeImport').onclick = () => $('#importDialog').close();
  $('#openClone').onclick = () => $('#cloneDialog').showModal();
  $('#closeClone').onclick = () => $('#cloneDialog').close();
  $('#resourceCloneDuration').oninput = () => { $('#resourceCloneDurationLabel').textContent = $('#resourceCloneDuration').value + ' giây'; };
  $('#importForm').onsubmit = async event => {
    event.preventDefault();
    const file = $('#importFile').files[0], label = $('#importLabel').value.trim();
    if (!file || !label) return;
    if (file.size > 20 * 1024 * 1024) { $('#importError').textContent = 'Ảnh vượt quá 20 MB.'; return; }
    $('#importSubmit').disabled = true; $('#importError').textContent = '';
    try {
      const id = normalize(label).replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'prop';
      await request(`/api/resources/props/upload?label=${encodeURIComponent(label)}&prop_id=${encodeURIComponent(id)}`, {method:'POST', headers:{'Content-Type':file.type}, body:file});
      $('#importDialog').close(); $('#importForm').reset(); await load();
    } catch (error) { $('#importError').textContent = error.message; }
    finally { $('#importSubmit').disabled = false; }
  };
  function readAudio(file) {
    return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('Không đọc được bản thu.')); reader.readAsDataURL(file); });
  }
  $('#resourceCloneForm').onsubmit = async event => {
    event.preventDefault();
    const file = $('#resourceCloneFile').files[0], name = $('#resourceCloneName').value.trim();
    if (!file || !name) return;
    $('#resourceCloneSubmit').disabled = true; $('#cloneError').textContent = ''; $('#cloneMessage').textContent = 'Đang đọc bản thu và tạo giọng trên GPU…';
    try {
      const data = await request('/api/voices/clone', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name, audio_base64:await readAudio(file), duration:Number($('#resourceCloneDuration').value)})});
      $('#cloneMessage').textContent = 'Đã tạo giọng. Bản nghe mẫu có trong thư viện.';
      await load(); state.selected = data.voice?.id; render();
    } catch (error) { $('#cloneError').textContent = error.message; $('#cloneMessage').textContent = ''; }
    finally { $('#resourceCloneSubmit').disabled = false; }
  };
  selectKind(new URLSearchParams(window.location.search).get('tab') || 'props', false);
  load();
})();

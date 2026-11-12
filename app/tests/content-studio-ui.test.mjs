import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.existsSync(new URL('../static/content-studio.js', import.meta.url)) ? fs.readFileSync(new URL('../static/content-studio.js', import.meta.url), 'utf8') : '';
const context = vm.createContext({URL, URLSearchParams, crypto:{randomUUID:()=> 'request-1'}});
vm.runInContext(source, context);
const ui = context.ContentStudio || {};
const plain = value => JSON.parse(JSON.stringify(value));

test('TXT import preserves multiline scripts separated by a blank line', () => {
  assert.equal(typeof ui.parseImport, 'function');
  assert.deepEqual(plain(ui.parseImport('\uFEFFLời đầu\r\nLời tiếp\r\n\r\nVideo hai', 'stories.txt')), [{text:'Lời đầu\nLời tiếp'}, {text:'Video hai'}]);
});
test('JSON import accepts string and editable item objects without trusting other fields', () => {
  assert.equal(typeof ui.parseImport, 'function');
  assert.deepEqual(plain(ui.parseImport('{"items":["Một",{"text":"Hai","title":"Tên","duration_seconds":90,"job_id":"ignored"}]}', 'stories.json')), [{text:'Một'}, {text:'Hai',title:'Tên',duration_seconds:90}]);
});
test('JSON import keeps per-video style and content source for the batch page', () => {
  assert.deepEqual(plain(ui.parseImport('[{"text":"A","style":"meme","input_mode":"script"},{"text":"B","style":"Vụ án"}]', 'mix.json')),
    [{text:'A',style:'meme',input_mode:'script'}, {text:'B',style:'case'}]);
  assert.throws(()=>ui.parseImport('[{"text":"A","style":"phim"}]','a.json'));
  assert.throws(()=>ui.parseImport('[{"text":"A","input_mode":"auto"}]','a.json'));
});
test('imports reject invalid data before any network request', () => {
  assert.equal(typeof ui.parseImport, 'function');
  for (const value of ['[]','[{}]','[{"text":"x","duration_seconds":0}]','[{"text":"x","duration_seconds":"invalid"}]']) assert.throws(()=>ui.parseImport(value,'a.json'));
});
test('batch identity is persisted and reused for a network retry but changes with payload', () => {
  assert.equal(typeof ui.pendingRequest, 'function');
  const saved=new Map();const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
  let sequence=0; const uuid=()=> 'key-'+(++sequence);
  const first=ui.pendingRequest(storage,{items:[{text:'a'}]},uuid);
  const retry=ui.pendingRequest(storage,{items:[{text:'a'}]},uuid);
  assert.equal(first.key,retry.key);
  assert.equal(ui.pendingRequest(storage,{items:[{text:'b'}]},uuid).key,'key-2');
});
test('scope comes from current production URL or an explicitly connected validated bridge', () => {
  assert.equal(typeof ui.resolveScope, 'function');
  const id='a7bd67dd-7f0d-4a91-8c3e-9d5114a1bf00';
  assert.equal(ui.resolveScope('/story-video/projects/'+id+'/production'),id);
  assert.equal(ui.resolveScope('/',{scope:id,connected:false,validated:true}),null);
  assert.equal(ui.resolveScope('/',{scope:id,connected:true,validated:false}),null);
  assert.equal(ui.resolveScope('/',{scope:id,connected:true,validated:true}),id);
  assert.equal(ui.resolveScope('/?scope='+id),null);
});
test('bridge discovery requires a live server-validated root and refuses ambiguous connections', async () => {
  assert.equal(typeof ui.discoverScope, 'function');
  const a='a7bd67dd-7f0d-4a91-8c3e-9d5114a1bf00',b='b7bd67dd-7f0d-4a91-8c3e-9d5114a1bf00';
  let requests=0;
  const read=async path=>{requests++;return path==='/api/connector/status'?{items:[{scope:a},{scope:b}]}:{bridge:path.includes(a)?a:b,ready:path.includes(a),heartbeat:{connected:true,fresh:true,supported_build:true,build:'videostudio-extension-0.3.0'}};};
  assert.equal(await ui.discoverScope('/',read),a);assert.equal(requests,3);
  await assert.rejects(()=>ui.discoverScope('/',async path=>path==='/api/connector/status'?{items:[{scope:a},{scope:b}]}:{bridge:path.includes(a)?a:b,ready:true,heartbeat:{connected:true,fresh:true,supported_build:true,build:'videostudio-extension-0.3.0'}}));
  assert.equal(await ui.discoverScope('/',async()=>({items:[]})),null);
});
test('changing connector scope creates a new idempotency receipt', () => {
  const saved=new Map();const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
  let sequence=0;const uuid=()=>String(++sequence);const payload={items:[{text:'a'}]};
  assert.notEqual(ui.pendingRequest(storage,payload,uuid,'first').key,ui.pendingRequest(storage,payload,uuid,'second').key);
});
test('dedicated browser transports submit without borrowing an old connector scope', async () => {
  assert.equal(typeof ui.scopeForTransport,'function');
  const path='/story-video/projects/a7bd67dd-7f0d-4a91-8c3e-9d5114a1bf00/production';
  const unexpected=()=>{throw Error('should not discover another session');};
  assert.equal(await ui.scopeForTransport(path,'cdp',unexpected),null);
  assert.equal(await ui.scopeForTransport(path,'chrome',unexpected),null);
  assert.equal(await ui.scopeForTransport(path,'extension',unexpected),'a7bd67dd-7f0d-4a91-8c3e-9d5114a1bf00');
});
test('library filters retain server pagination and escape query text', () => {
  assert.equal(typeof ui.filterQuery, 'function');
  const q=new URLSearchParams(ui.filterQuery({q:'mẹ & bố',style:'meme',project:'',review_state:'approved',page:2,page_size:12}));
  assert.equal(q.get('q'),'mẹ & bố');assert.equal(q.get('page'),'2');assert.equal(q.has('project'),false);assert.equal(q.get('review_state'),'approved');
});
test('scheduling requires and pins the selected approved version', () => {
  assert.equal(typeof ui.schedulePayload, 'function');
  assert.throws(()=>ui.schedulePayload({job_id:'j',version_id:'v',review_state:'pending'},{channel_id:'c',publish_at:'2026-12-01T10:00:00+07:00'}));
  const p=ui.schedulePayload({job_id:'j',version_id:'v',review_state:'approved',title:'Tên video'},{channel_id:'c',publish_at:'2026-12-01T10:00:00+07:00',caption:'Lời đăng'});
  assert.equal(p.job_id,'j');assert.equal(p.version_id,'v');assert.equal(p.channel_id,'c');assert.equal(p.caption,'Lời đăng');
  assert.equal(p.publish_at,'2026-12-01T10:00:00+07:00');assert.equal(p.title,'Tên video');assert.equal(p.scheduled_at,undefined);
});
test('approved shell is progressive and retains the canonical application scripts', () => {
  const html=fs.readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
  assert.match(html,/studio-shell\.css/);assert.match(html,/content-studio\.js/);
  for(const id of ['galleryContainer','projectInput','create','viewWorkspace','projectJobsList','voice','textProvider','imageProvider'])assert.ok(html.includes('id="'+id+'"'),id);
  assert.match(html,/scene-editor\.js/);assert.match(html,/function archiveProject\(/);assert.match(html,/function openOptionalWorkspace\(/);
});
test('preflight refresh cannot re-enable create while a factory submission is pending',()=>{
  const html=fs.readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
  const nodes={'#submit':{disabled:false},'#voice':{value:'voice'},'#create':{dataset:{submitting:'true'}}};
  const context=vm.createContext({$:id=>nodes[id],ready:true,submitting:false});
  vm.runInContext(html.match(/function enable\(\)\{[^\n]+\}/)[0],context);
  context.enable();assert.equal(nodes['#submit'].disabled,true);
  delete nodes['#create'].dataset.submitting;context.enable();assert.equal(nodes['#submit'].disabled,false);
});

test('navigation during a pending refresh eventually loads the newly selected page', async()=>{
  let release;
  const barrier=new Promise(resolve=>release=resolve), calls=[];
  const context=vm.createContext({
    state:{page:'calendar',loading:false},
    loadQueue:async()=>calls.push('queue'),loadLibrary:async()=>calls.push('library'),
    loadCalendar:async()=>{calls.push('calendar');await barrier;},
    loadChannels:async()=>calls.push('settings'),$:()=>null,
  });
  const definition=source.match(/async function refreshPage\(\)[\s\S]*?(?=\n  async function factoryScope)/)[0];
  vm.runInContext(definition,context);
  const first=context.refreshPage();
  context.state.page='library';
  await context.refreshPage();
  release();await first;
  assert.deepEqual(calls,['calendar','library']);
});

test('queue groups put the running video first, waiting in run order, errors apart and hide superseded failures', () => {
  const item = (id, state, content, created, extra={}) => ({id, state, content, created, ...extra});
  const groups = plain(ui.queueGroups([
    item('old-gemini', 'failed', 'Truyện A', 1),
    item('done', 'completed', 'Truyện B', 2),
    item('next', 'pending', 'Truyện C', 3),
    item('later', 'waiting', 'Truyện D', 4),
    item('broken', 'failed', 'Truyện E', 5),
    item('rerun', 'running', 'Truyện  A ', 6),
    item('skipped', 'skipped', 'Truyện F', 7),
  ]));
  assert.deepEqual(groups.active.map(i=>i.id), ['rerun']);
  assert.deepEqual(groups.waiting.map(i=>i.id), ['next','later']);
  assert.deepEqual(groups.attention.map(i=>i.id), ['broken']);
  assert.deepEqual(groups.done.map(i=>i.id), ['skipped','done','old-gemini']);
  assert.equal(groups.done.find(i=>i.id==='old-gemini').superseded, true);
});
test('queue errors are explained in Vietnamese with the right next step', () => {
  const explain = (message, extra={}) => plain(ui.explainQueueError({message, ...extra}));
  assert.equal(explain('browser_unavailable: Gemini New chat did not reach a stable blank composer; no prompt sent').action, 'chatgpt');
  const unsure = explain('delivery_indeterminate: Matching completed response unavailable; receipt retained');
  assert.equal(unsure.action, 'retry');
  assert.match(unsure.text, /ChatGPT/);
  assert.equal(explain('Utterance exceeds safe caption area; split narration upstream').action, 'open');
  assert.equal(explain('[WinError 10061] No connection could be made because the target machine actively refused it', {job:{stage:'images'}}).text.includes('ComfyUI'), true);
  const kept = explain('Something odd', {job:{stage:'images', checkpoints:{plan:{},speech:{},research:{},script:{}}}});
  assert.equal(kept.action, 'retry');
  assert.match(kept.kept, /Kịch bản, Lời đọc/);
  assert.match(kept.kept, /Tạo hình ảnh/);
});
test('a rerun copies only request settings and applies the override', () => {
  const payload = plain(ui.rerunPayload({id:'x', project:'P', style:'case', input_mode:'script', title:'T', content:'Nội dung',
    request:{idea:'Nội dung', project:'P', content_style:'case', workflow_mode:'provided_narration', voice_id:'v', duration_seconds:600, text_provider:'gemini', image_provider:'comfy'}}, {text_provider:'chatgpt'}));
  assert.deepEqual(payload, {project:'P', style:'case', input_mode:'script', defaults:{voice_id:'v', duration_seconds:600, text_provider:'chatgpt', image_provider:'comfy'}, items:[{text:'Nội dung', title:'T'}]});
});

test('script duration is estimated from the measured reading speed', () => {
  assert.equal(ui.estimateNarrationSeconds(Array(4026).fill('tiếng').join(' ')), 959);
  assert.equal(ui.estimateNarrationSeconds('Xin chào'), 5);
  assert.equal(ui.estimateNarrationSeconds(''), 0);
  assert.equal(ui.autoDuration('case','script'), true);
  assert.equal(ui.autoDuration('meme','script'), false);
  assert.equal(ui.autoDuration('news','idea'), false);
  assert.equal(ui.durationText(959), '16 phút');
  assert.equal(ui.durationText(40), '40 giây');
});

test('a raw story file becomes one video without its heading line', () => {
  assert.deepEqual(plain(ui.parseStoryFile('﻿PHẠM NHÂN “BỎ TRỐN”\r\n\r\nĐoạn một.\r\n\r\nĐoạn hai.', '001_pham-nhan.txt')),
    {heading:'PHẠM NHÂN “BỎ TRỐN”', text:'Đoạn một.\n\nĐoạn hai.'});
  assert.deepEqual(plain(ui.parseStoryFile('Một câu chuyện dài không có tiêu đề riêng mà vào thẳng nội dung ngay từ dòng đầu tiên, kéo dài hơn hẳn một tiêu đề bình thường rất nhiều.\n\nĐoạn sau.', 'a.txt')).heading, '');
  assert.equal(ui.parseStoryFile('Chỉ có tiêu đề', 'b.txt').text, 'Chỉ có tiêu đề');
  assert.equal(ui.parseStoryFile('nội dung', 'INDEX.txt'), null);
  assert.equal(ui.parseStoryFile('nội dung', 'all_cases_clean.txt'), null);
  assert.equal(ui.parseStoryFile('   ', 'c.txt'), null);
});


test('JSON speech batches accept every integer from 1 to 512 and reject invalid values',()=>{
  for(const size of [1,17,256,512])assert.equal(ui.parseImport(JSON.stringify([{text:'Voice',speech_batch_size:size}]),'voice.json')[0].speech_batch_size,size);
  for(const size of [0,513,1.5,'invalid'])assert.throws(()=>ui.parseImport(JSON.stringify([{text:'Voice',speech_batch_size:size}]),'voice.json'));
});

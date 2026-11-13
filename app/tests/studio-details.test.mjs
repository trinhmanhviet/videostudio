import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({console, crypto:{randomUUID:(()=>{let n=0;return()=>`detail-key-${++n}`;})()}});
const path = new URL('../static/studio-details.js', import.meta.url);
if (fs.existsSync(path)) vm.runInContext(fs.readFileSync(path, 'utf8'),context);
const api = context.StudioDetails || {};
const plain = v => JSON.parse(JSON.stringify(v));

test('partial cache counts never mark images complete or unlock scene mutation',()=>{
  const job={state:'failed',stage:'images',checkpoints:{script:{},speech:{},music:{}}};
  const model=api.presentation(job,{partial:true,image_count:7,scenes:Array.from({length:24},(_,index)=>({index}))},null);
  assert.equal(model.canEdit,false);
  assert.equal(model.steps.find(s=>s.key==='images').status,'current');
  assert.match(model.steps.find(s=>s.key==='images').label,/7\/24/);
  assert.equal(model.steps.find(s=>s.key==='music').status,'done');
  assert.equal(model.canExport,false);
  assert.match(model.resumeLabel,/tạo ảnh/);
});

test('cancelled jobs require explicit supported resume and correct payload',()=>{
  assert.deepEqual(plain(api.retryPayload({state:'cancelled',stage:'images',checkpoints:{script:{}}})),{resume_cancelled:true});
  assert.equal(api.retryPayload({state:'cancelled',stage:'research',checkpoints:{}}),null);
  assert.deepEqual(plain(api.retryPayload({state:'failed',checkpoints:{}})),{});
  assert.equal(api.retryPayload({state:'running',checkpoints:{}}),null);
});

test('scene search filters all scenes before clamping pagination',()=>{
  const scenes=Array.from({length:24},(_,index)=>({index,narration:index===20?'Cửa cuối hành lang':'Căn phòng',image_url:index<7?'/preview':null}));
  let view=api.scenePage(scenes,{query:'cua cuoi',filter:'missing',page:8});
  assert.equal(view.items.length,1);assert.equal(view.items[0].index,20);assert.equal(view.page,0);
  view=api.scenePage(scenes,{filter:'ready',page:1});
  assert.equal(view.total,7);assert.equal(view.page,0);
  view=api.scenePage(scenes,{filter:'missing',page:1});
  assert.equal(view.total,17);assert.equal(view.items.length,8);assert.equal(view.pages,3);
});

test('uncertain generation/export retries keep keys until payload identity changes',()=>{
  const keys=api.createRequestKeys();
  const request={version:1,prompt:'Room',provider:'comfy'};
  const first=keys.for('scene-0',request);
  assert.equal(keys.for('scene-0',request),first);
  assert.notEqual(keys.for('scene-0',{...request,version:2}),first);
  assert.notEqual(keys.for('scene-1',request),first);
  const exportKey=keys.for('export',{version:2});
  assert.equal(keys.for('export',{version:2}),exportKey);
});

test('meme jobs keep scene tools unavailable even with image checkpoint',()=>{
  const model=api.presentation({state:'completed',request:{workflow_mode:'meme'},checkpoints:{speech:{},images:{},verify:{verified:true}}},{}, {editable:true,can_export:true});
  assert.equal(model.canEdit,false);assert.equal(model.canExport,false);assert.equal(model.meme,true);
});

test('download and candidate URLs must stay inside the intended job scope',()=>{
  assert.equal(api.scopedURL('/api/jobs/job-1/details/images/0','job-1'),'/api/jobs/job-1/details/images/0');
  for(const value of ['javascript:alert(1)','https://elsewhere.test/video','//elsewhere.test/file','/api/jobs/other/details/images/0','/api/jobs/job-1/../other/files/a']) assert.equal(api.scopedURL(value,'job-1'),null,value);
});

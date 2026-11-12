import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context=vm.createContext({URL,URLSearchParams});
vm.runInContext(fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8'),context);
function fixture(importFiles,onError=()=>{}){
  const handlers={},classes=new Set();
  const target={addEventListener:(name,fn)=>handlers[name]=fn,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}};
  context.ContentStudio.bindStoryDrop(target,importFiles,onError);
  const event=(files=[],types=['Files'])=>({dataTransfer:{files,types},preventDefault(){this.prevented=true;},stopPropagation(){}});
  return {handlers,classes,event};
}
test('dropping one or multiple files uses the existing importer without submitting jobs',async()=>{
  const calls=[];const f=fixture(async files=>calls.push(Array.from(files)));
  const one={name:'one.txt'},two={name:'two.txt'};
  await f.handlers.drop(f.event([one]));
  await f.handlers.drop(f.event([one,two]));
  assert.deepEqual(calls,[[one],[one,two]]);
});
test('file drag shows a target, permits dropping, and clears nested drag state',()=>{
  const f=fixture(()=>{});const e=f.event();
  f.handlers.dragenter(e);f.handlers.dragenter(e);f.handlers.dragover(e);
  assert.equal(e.prevented,true);assert.equal(e.dataTransfer.dropEffect,'copy');
  f.handlers.dragleave(e);assert.equal(f.classes.has('studio-file-dragging'),true);
  f.handlers.dragleave(e);assert.equal(f.classes.size,0);
});
test('text dragging is not intercepted',async()=>{
  let imported=false;const f=fixture(()=>{imported=true;});const e=f.event([],['text/plain']);
  f.handlers.dragover(e);await f.handlers.drop(e);
  assert.equal(e.prevented,undefined);assert.equal(imported,false);
});
test('import failures display through the existing error handler and reset highlight',async()=>{
  const errors=[];const f=fixture(async()=>{throw Error('File trống');},error=>errors.push(error.message));
  f.handlers.dragenter(f.event());await f.handlers.drop(f.event([{name:'empty.txt'}]));
  assert.deepEqual(errors,['File trống']);assert.equal(f.classes.size,0);
});

test('folder drop drains every directory readEntries batch and preserves relative ordering',async()=>{
  const file=name=>({isFile:true,isDirectory:false,name,file:ok=>ok({name})});
  const dir=(name,batches)=>({isFile:false,isDirectory:true,name,createReader:()=>({readEntries:ok=>ok(batches.shift()||[])})});
  const root=dir('stories',[[file('1.txt')],[dir('nested',[[file('2.txt')],[file('ignore.png')]])],[]]);
  const files=await context.ContentStudio.collectDroppedFiles({items:[{kind:'file',webkitGetAsEntry:()=>root}],files:[]});
  assert.deepEqual(Array.from(files,f=>[f.name,f.webkitRelativePath]),[['1.txt','stories/1.txt'],['2.txt','stories/nested/2.txt']]);
});

test('folder collection falls back to FileList when entry API is absent',async()=>{
  const file={name:'phone.txt'};
  assert.deepEqual(Array.from(await context.ContentStudio.collectDroppedFiles({files:[file]})),[file]);
});

test('auto duration uses measured selected voice while explicit manual seconds stay fixed',()=>{
  const ui=context.ContentStudio;
  ui.setVoiceProfiles([{id:'fast',reading_profile:{syllables_per_second:5,source:'verified_jobs'}},{id:'slow',reading_profile:{syllables_per_second:2.5,source:'preview'}}]);
  const text=Array(100).fill('tiếng').join(' ');
  assert.equal(ui.estimateNarrationSeconds(text,'fast'),20);
  assert.equal(ui.estimateNarrationSeconds(text,'slow'),40);
  const row={text,voice:'fast',style:'case',input:'script',duration_mode:'manual',seconds:2,unit:60};
  assert.equal(ui.durationForRow(row),120);
  row.voice='slow';assert.equal(ui.durationForRow(row),120);
  row.duration_mode='auto';assert.equal(ui.durationForRow(row),40);
});

test('the actual batch payload honors a manual override and uses the chosen voice for auto',()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const definition=source.match(/function batchPayload\(row\)[\s\S]*?(?=\n  async function submitBatch)/)[0];
  const payloadContext=vm.createContext({$:()=>null,durationForRow:context.ContentStudio.durationForRow});
  vm.runInContext(definition,payloadContext);
  const row={title:'Test',text:Array(100).fill('tiếng').join(' '),voice:'slow',style:'case',input:'script',duration_mode:'manual',seconds:2,unit:60};
  assert.equal(payloadContext.batchPayload(row).defaults.duration_seconds,120);
  row.duration_mode='auto';assert.equal(payloadContext.batchPayload(row).defaults.duration_seconds,40);
});

test('failed response retry keeps its submitted duration even when voice profiles refresh',()=>{
  const ui=context.ContentStudio;
  const row={text:Array(100).fill('tiếng').join(' '),voice:'slow',style:'case',input:'script',duration_mode:'auto',submitted_duration_seconds:40};
  ui.setVoiceProfiles([{id:'slow',reading_profile:{syllables_per_second:5,source:'verified_jobs'}}]);
  assert.equal(ui.durationForRow(row),40);
});

test('single-video auto retry keeps its original body and key when calibration changes',()=>{
  const saved=new Map();const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
  let sequence=0;const uuid=()=>String(++sequence);
  const payload={defaults:{voice_id:'slow',duration_seconds:40},items:[{text:'same'}]};
  const first=context.ContentStudio.pendingRequest(storage,payload,uuid,'scope',true);
  const retry=context.ContentStudio.pendingRequest(storage,{...payload,defaults:{...payload.defaults,duration_seconds:20}},uuid,'scope',true);
  assert.equal(retry.key,first.key);assert.equal(retry.identity,first.identity);
  const manual=context.ContentStudio.pendingRequest(storage,{...payload,defaults:{...payload.defaults,duration_seconds:20}},uuid,'scope',false);
  assert.notEqual(manual.key,first.key);
});

test('single-video auto pin does not hide text or voice edits',()=>{
  for(const change of [p=>({...p,items:[{text:'edited'}]}),p=>({...p,defaults:{...p.defaults,voice_id:'other'}})]){
    const saved=new Map();const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
    let sequence=0;const uuid=()=>String(++sequence);
    const payload={defaults:{voice_id:'slow',duration_seconds:40},items:[{text:'same'}]};
    const first=context.ContentStudio.pendingRequest(storage,payload,uuid,'scope',true);
    const next=context.ContentStudio.pendingRequest(storage,change(payload),uuid,'scope',true);
    assert.notEqual(next.key,first.key);
  }
});

test('article counts include words and Unicode characters',()=>{
  assert.deepEqual(JSON.parse(JSON.stringify(context.ContentStudio.textMetrics('Xin chào 👋'))),{words:3,characters:10});
  assert.deepEqual(JSON.parse(JSON.stringify(context.ContentStudio.textMetrics(''))),{words:0,characters:0});
});

test('batch payload uses each row image provider and clears irrelevant batch settings',()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const definition=source.match(/function batchPayload\(row\)[\s\S]*?(?=\n  async function submitBatch)/)[0];
  const payloadContext=vm.createContext({$:id=>id==='#imageProvider'?{value:'flow'}:id==='#flowBatchSize'?{value:'10'}:null,durationForRow:()=>60});
  vm.runInContext(definition,payloadContext);
  const row={title:'Test',text:'Kịch bản',voice:'voice',style:'case',input:'script',image_provider:'comfy'};
  let payload=payloadContext.batchPayload(row).defaults;
  assert.equal(payload.image_provider,'comfy');assert.equal(payload.flow_batch_size,1);
  row.image_provider='meta';payload=payloadContext.batchPayload(row).defaults;
  assert.equal(payload.image_provider,'meta');assert.equal(payload.meta_batch_size,8);assert.equal(payload.flow_batch_size,1);
  row.image_provider='chatgpt';assert.equal(payloadContext.batchPayload(row).defaults.image_provider,'chatgpt');
  row.style='meme';assert.equal(payloadContext.batchPayload(row).defaults.image_provider,'comfy');
});

test('dropping anywhere on the web opens the batch page and imports through the same file pipeline once',async()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const definition=source.match(/function installGlobalStoryDrop\(\)[\s\S]*?(?=\n  function installShell)/)[0];
  const handlers={},classes=new Set(),calls=[];
  const body={addEventListener:(name,fn)=>handlers[name]=fn,classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)}};
  const dropContext=vm.createContext({document:{body},bindStoryDrop:context.ContentStudio.bindStoryDrop,
    navigate:(...args)=>calls.push(['navigate',...args]),loadBatchPage:()=>calls.push(['prepare']),
    global:{ContentStudio:{importStoryFiles:async files=>calls.push(['import',...files.map(f=>f.name)])}},$:()=>null,toast:()=>{}});
  vm.runInContext(definition,dropContext);dropContext.installGlobalStoryDrop();
  const event={dataTransfer:{types:['Files'],files:[{name:'one.txt'},{name:'two.txt'}]},preventDefault(){},stopPropagation(){}};
  handlers.dragenter(event);await handlers.drop(event);
  assert.deepEqual(calls,[['navigate','batch',false],['prepare'],['import','one.txt','two.txt']]);
  assert.equal(classes.size,0);
});


test('batch speech size defaults to 256, supports non-multiples of 16 and remains available to meme narration',()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const definition=source.match(/function batchPayload\(row\)[\s\S]*?(?=\n  async function submitBatch)/)[0];
  const sandbox=vm.createContext({$:()=>null,durationForRow:()=>60});vm.runInContext(definition,sandbox);
  const row={title:'Test',text:'Story',voice:'voice',style:'meme',input:'script'};
  assert.equal(sandbox.batchPayload(row).defaults.speech_batch_size,256);
  row.speech_batch_size=17;assert.equal(sandbox.batchPayload(row).defaults.speech_batch_size,17);
  for(const value of [0,513,1.5]){row.speech_batch_size=value;assert.throws(()=>sandbox.batchPayload(row));}
});


test('new and remembered rows preserve speech batches through cloning and JSON file import',async()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const saved=new Map();let seq=0;
  const sandbox=vm.createContext({state:{batchRows:[]},global:{crypto:{randomUUID:()=>String(++seq)}},
    localStorage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)},$:()=>null,voiceOptions:()=>[['v','Voice']],
    parseImport:context.ContentStudio.parseImport,renderBatchRows:()=>{},toast:()=>{}});
  vm.runInContext(source.match(/function rememberedRow\(\)[\s\S]*?(?=\n  function touchRow)/)[0],sandbox);
  let row=sandbox.newBatchRow();assert.equal(row.speech_batch_size,256);
  row.speech_batch_size=33;sandbox.rememberRow(row);row=sandbox.newBatchRow();assert.equal(row.speech_batch_size,33);
  const clone=sandbox.newBatchRow({...row,key:'clone'});assert.equal(clone.speech_batch_size,33);
  vm.runInContext(source.match(/async function addStoryFiles\(files\)[\s\S]*?(?=\n  function loadBatchPage)/)[0],sandbox);
  await sandbox.addStoryFiles([{name:'voice.json',text:async()=>JSON.stringify([{text:'Story',speech_batch_size:17}])}]);
  assert.equal(sandbox.state.batchRows[0].speech_batch_size,17);
});

test('single video submission sends the chosen speech batch in request defaults',async()=>{
  const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
  const values={'#idea':'Narration','#voice':'v','#duration':'60','#unit':'1','#studioSpeechBatchSize':'33','#projectInput':'Project','#studioStyle':'meme','#textProvider':'chatgpt','#imageProvider':'comfy','#flowBatchSize':'1','#musicVolume':'0','#createPitch':'0'};
  const nodes=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,{value}]));nodes['#submitError']={};nodes['#submit']={};
  const calls=[],form={dataset:{inputMode:'script'}};
  const sandbox=vm.createContext({form,state:{batch:false},$:id=>nodes[id],normalizeItem:value=>value,
    factoryScope:async()=>null,pendingRequest:(storage,payload)=>({key:'key',identity:JSON.stringify(payload)}),sessionStorage:{removeItem:()=>{}},PENDING_KEY:'key',
    request:async(path,opts)=>calls.push({path,opts}),renderBatchItems:()=>{},closeDrawer:()=>{},navigate:()=>{},toast:()=>{},global:{}});
  vm.runInContext(source.match(/form.onsubmit=async event=>\{[\s\S]*?(?=\n    document.addEventListener)/)[0],sandbox);
  await form.onsubmit({preventDefault(){}});
  assert.equal(calls.length,1);assert.equal(JSON.parse(calls[0].opts.body).defaults.speech_batch_size,33);
  nodes['#studioSpeechBatchSize'].value='513';await form.onsubmit({preventDefault(){}});assert.equal(calls.length,1);assert.match(nodes['#submitError'].textContent,/512/);
});

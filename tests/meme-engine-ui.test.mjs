import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
test('cancelled animated script can explicitly resume while other cancelled text stays stopped',()=>{
  const ctx=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function canResumeCancelledJob('),source.indexOf('function renderJobCard(')),ctx);
  const j={status:'cancelled',stage:'script',request:{workflow_mode:'meme',meme_engine:'hyperframes'},checkpoints:{plan:{},research:{}}};
  assert.equal(ctx.canResumeCancelledJob(j),true);
  assert.equal(ctx.canResumeCancelledJob({...j,status:'running'}),false);
  assert.equal(ctx.canResumeCancelledJob({...j,request:{workflow_mode:'research'}}),false);
  assert.equal(ctx.canResumeCancelledJob({...j,checkpoints:{}}),false);
});
function setup(mode='meme',engine='hyperframes'){
  const nodes=new Map();
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,disabled:false,textContent:'',options:[]});return nodes.get(id);};
  $('#workflowMode').value=mode;$('#memeEngine').value=engine;$('#duration').value='60';$('#unit').value='1';$('#imageProvider').value='flow';$('#flowBatchSize').value='5';
  let refreshes=0;
  const ctx=vm.createContext({$,voices:[],extensionScope:'root',URLSearchParams,ready:true,enable(){},preflight(){refreshes++;},updateFlowBatchChoices(){},onVoice(){}});
  const start=source.indexOf('function isAnimatedMeme(');
  const end=source.indexOf("$('#workflowMode').onchange",start);
  assert.ok(start>=0,'animated meme controls exist');
  vm.runInContext(source.slice(start,end),ctx);
  return {$,ctx,refreshes:()=>refreshes};
}
test('animated meme hides image and music controls and explains voice plus SFX',()=>{
  const {$,ctx}=setup();ctx.updateWorkflowMode();
  assert.equal($('#memeEngine').hidden,false);
  for(const id of ['imageProvider','flowBatchSize','musicVolume']){assert.equal($('#'+id).hidden,true,id);assert.equal($('#'+id).disabled,true,id);}
  assert.match($('#workflowModeNote').textContent,/SFX/);
  assert.equal($('#musicVolumeLabel').hidden,true);
});
test('legacy engine and regular modes restore relevant controls',()=>{
  const {$,ctx}=setup();ctx.updateWorkflowMode();$('#memeEngine').value='pillow';ctx.updateWorkflowMode();assert.equal($('#musicVolume').hidden,false);
  $('#workflowMode').value='research';ctx.updateWorkflowMode();assert.equal($('#memeEngine').hidden,true);assert.equal($('#imageProvider').disabled,false);
});
test('request opts into hyperframes only for meme and avoids Flow admission',()=>{
  const {ctx}=setup();const payload={workflow_mode:'meme',image_provider:'flow',flow_batch_size:5,music_volume:.35};ctx.applyMemeEngine(payload);
  assert.equal(payload.meme_engine,'hyperframes');assert.equal(payload.image_provider,'comfy');assert.equal(payload.flow_batch_size,1);assert.equal(payload.music_volume,0);
  const regular={workflow_mode:'research',image_provider:'flow'};ctx.applyMemeEngine(regular);assert.equal(regular.meme_engine,undefined);assert.equal(regular.image_provider,'flow');
});
test('preferred clone fills only an empty animated meme selection',()=>{
  const {$,ctx}=setup();vm.runInContext("voices=[{id:'clone:18cad821-0d87-461f-a443-d45db92e36e9',available:true}]",ctx);
  ctx.selectPreferredMemeVoice();assert.equal($('#voice').value,'clone:18cad821-0d87-461f-a443-d45db92e36e9');
  $('#voice').value='chosen';ctx.selectPreferredMemeVoice();assert.equal($('#voice').value,'chosen');
});
test('animated preflight carries the selected engine and ordinary modes keep the original query',()=>{
  const {$,ctx}=setup();
  assert.equal(ctx.preflightRequestPath(),'/api/preflight?scope=root&workflow_mode=meme&meme_engine=hyperframes');
  $('#memeEngine').value='pillow';assert.equal(ctx.preflightRequestPath(),'/api/preflight?scope=root');
  $('#workflowMode').value='research';assert.equal(ctx.preflightRequestPath(),'/api/preflight?scope=root');
  vm.runInContext("extensionScope=null",ctx);assert.equal(ctx.preflightRequestPath(),'/api/preflight');
  $('#workflowMode').value='meme';$('#memeEngine').value='hyperframes';
  assert.equal(ctx.preflightRequestPath(),'/api/preflight?workflow_mode=meme&meme_engine=hyperframes');
});
test('workflow and engine changes refresh preflight once and disable submission meanwhile',()=>{
  const ui=setup();ui.ctx.updateWorkflowMode();assert.equal(ui.refreshes(),0);
  ui.ctx.onWorkflowModeChange();assert.equal(ui.refreshes(),1);assert.equal(ui.ctx.ready,false);
  ui.$('#memeEngine').value='pillow';ui.ctx.onWorkflowModeChange();assert.equal(ui.refreshes(),2);
  assert.match(source,/\$\('#workflowMode'\)\.onchange=onWorkflowModeChange/);
  assert.match(source,/\$\('#memeEngine'\)\.onchange=onWorkflowModeChange/);
});
test('a stale preflight response cannot restore readiness after an engine change',async()=>{
  const {$,ctx}=setup();let resolveResponse,requested;
  ctx.api=path=>{requested=path;return new Promise(resolve=>{resolveResponse=resolve;});};
  ctx.configureTextTransport=()=>assert.fail('stale response must not configure transport');
  vm.runInContext(source.match(/^async function preflight\(\).*$/m)[0],ctx);
  const pending=ctx.preflight();
  assert.equal(requested,'/api/preflight?scope=root&workflow_mode=meme&meme_engine=hyperframes');
  $('#memeEngine').value='pillow';ctx.ready=false;resolveResponse({ready:true,checks:[]});
  await pending;assert.equal(ctx.ready,false);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
function setup(mode='meme'){
 const nodes=new Map();
 const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,disabled:false,textContent:'',options:[]});return nodes.get(id);};
 $('#workflowMode').value=mode;$('#duration').value='60';$('#unit').value='1';
 let refreshes=0;
 const ctx=vm.createContext({$,voices:[],extensionScope:'root',URLSearchParams,ready:true,enable(){},preflight(){refreshes++;},updateFlowBatchChoices(){},onVoice(){}});
 vm.runInContext(source.slice(source.indexOf('function isAnimatedMeme('),source.indexOf("$('#workflowMode').onchange")),ctx);
 return {$,ctx,refreshes:()=>refreshes};
}
test('one meme UI has no engine selector',()=>{
 assert.doesNotMatch(source,/id="memeEngine"|Meme ảnh — cũ|Hoạt hình nhân vật — mới/);
 const {$,ctx}=setup();ctx.updateWorkflowMode();
 for(const id of ['imageProvider','flowBatchSize','musicVolume'])assert.equal($('#'+id).hidden,true,id);
 assert.match($('#workflowModeNote').textContent,/SFX/);
});
test('meme submission and preflight require no engine flag',()=>{
 const {ctx}=setup();const payload={workflow_mode:'meme',image_provider:'flow',flow_batch_size:5,music_volume:.35};
 ctx.applyMemeEngine(payload);assert.equal(payload.meme_engine,undefined);assert.equal(payload.image_provider,'comfy');assert.equal(payload.flow_batch_size,1);
 assert.equal(ctx.preflightRequestPath(),'/api/preflight?scope=root&workflow_mode=meme');
});
test('research controls and requests retain their existing behavior',()=>{
 const {$,ctx}=setup('research');ctx.updateWorkflowMode();
 assert.equal($('#imageProvider').disabled,false);assert.equal($('#musicVolume').hidden,false);
 const payload={workflow_mode:'research',image_provider:'flow'};ctx.applyMemeEngine(payload);assert.deepEqual(payload,{workflow_mode:'research',image_provider:'flow'});
 assert.equal(ctx.preflightRequestPath(),'/api/preflight?scope=root');
});
test('workflow changes disable admission while refreshing preflight',()=>{
 const ui=setup();ui.ctx.onWorkflowModeChange();assert.equal(ui.refreshes(),1);assert.equal(ui.ctx.ready,false);
});
test('saved meme script may resume independent of historical engine flag',()=>{
 const ctx=vm.createContext({});vm.runInContext(source.slice(source.indexOf('function canResumeCancelledJob('),source.indexOf('function renderJobCard(')),ctx);
 const j={status:'cancelled',stage:'script',request:{workflow_mode:'meme'},checkpoints:{plan:{},research:{}}};
 assert.equal(ctx.canResumeCancelledJob(j),true);
 assert.equal(ctx.canResumeCancelledJob({...j,request:{workflow_mode:'research'}}),false);
});

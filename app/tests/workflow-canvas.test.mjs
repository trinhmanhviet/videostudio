import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/workflow-canvas.js',import.meta.url),'utf8');
const {WorkflowModel,mountWorkflowCanvas}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const fixture=()=>({schema_version:1,id:'flow',name:'Test',revision:3,viewport:{x:0,y:0,zoom:1},nodes:[{id:'input',type:'input',x:0,y:0,config:{}},{id:'script',type:'script',x:200,y:0,config:{}},{id:'speech',type:'speech',x:400,y:0,config:{}}],edges:[{id:'first',source:'input',source_port:'brief',target:'script',target_port:'brief'}]});
test('dragging and configuration mutate only the local editable graph',()=>{const original=fixture();const model=new WorkflowModel(original);model.move('script',300,70);model.configure('speech','voice_id','preset:new');assert.equal(model.graph.nodes[1].x,300);assert.equal(model.graph.nodes[2].config.voice_id,'preset:new');assert.equal(original.nodes[1].x,200);assert.ok(model.dirty);});
test('connect/reconnect/disconnect have concrete edge semantics and reject mismatched sockets',()=>{const model=new WorkflowModel(fixture());model.connect('script','script','speech','script');assert.equal(model.graph.edges.length,2);assert.throws(()=>model.connect('input','brief','speech','script'),/compatible/);assert.equal(model.graph.edges.length,2);model.disconnect(model.graph.edges[0].id);assert.equal(model.graph.edges.length,1);model.connect('input','brief','script','brief');assert.equal(model.graph.edges.length,2);});
test('optional stage add/remove preserves valid defaults and clears attached edges',()=>{const model=new WorkflowModel(fixture());const node=model.add('music');assert.equal(node.type,'music');assert.ok(model.graph.edges.some(e=>e.target===node.id));model.configure(node.id,'enabled',false);assert.equal(model.graph.nodes.find(n=>n.id===node.id).config.enabled,false);model.remove(node.id);assert.ok(!model.graph.edges.some(e=>e.source===node.id||e.target===node.id));assert.throws(()=>model.remove('speech'),/required/);});
test('cloning resets identity and optimistic revision',()=>{const model=new WorkflowModel(fixture());model.clone();assert.equal(model.graph.id,'');assert.equal(model.graph.revision,0);assert.match(model.graph.name,/copy/);});


test('speech nodes seed a concrete batch size without changing existing explicit values',()=>{
 const model=new WorkflowModel(fixture());assert.equal(model.graph.nodes.find(n=>n.type==='speech').config.speech_batch_size,256);
 const graph=fixture();graph.nodes.find(n=>n.type==='speech').config.speech_batch_size=17;
 assert.equal(new WorkflowModel(graph).graph.nodes.find(n=>n.type==='speech').config.speech_batch_size,17);
});


test('an existing job seeds its speech batch into the editable template',async()=>{
 const nodes=new Map(),listeners={};const node=()=>({classList:{add(){},toggle(){}},style:{},addEventListener(){},removeEventListener(){},querySelector:selector=>{if(!nodes.has(selector))nodes.set(selector,node());return nodes.get(selector);}});
 const container=node();container.addEventListener=(name,handler)=>listeners[name]=handler;
 const graph=fixture();graph.edges=[];
 const canvas=mountWorkflowCanvas(container,{job:{id:'job',request:{speech_batch_size:33}},api:async path=>path==='/api/workflows'?{templates:[graph],items:[]}:path==='/api/voices'?{voices:[]}:{}});
 await canvas.ready;assert.equal(canvas.getGraph().nodes.find(n=>n.type==='speech').config.speech_batch_size,33);
 const speech={dataset:{node:'speech'},closest:selector=>selector==='[data-node]'?speech:null};
 await listeners.click({target:speech});
 assert.match(nodes.get('.wf-inspector').innerHTML,/data-config="speech_batch_size" type="number" value="33"[^>]*min="1" max="512" step="1"/);
 canvas.destroy();
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as protocol from '../protocol.mjs';

const scope='123e4567-e89b-42d3-a456-426614174000';
const prompt='YÊU CẦU STUDIO req\nhello';
const source=(await readFile(new URL('../background.js',import.meta.url),'utf8')).replace(/^import .*?;\r?\n/,'');
function worker({probeFailures=0,receiptOffline=false}={}){
  let listener,next=20;
  let now=Date.now();
  class Clock extends Date {static now(){return now;}}
  const values={};const opened=[],closed=[],sent=[],created=[];
  const chrome={storage:{local:{get:async key=>({[key]:structuredClone(values[key])}),set:async data=>{Object.assign(values,structuredClone(data));}}},
    runtime:{onMessage:{addListener:fn=>{listener=fn;}}},
    tabs:{create:async options=>{created.push(options);await new Promise(r=>setImmediate(r));const tab={id:++next,status:'complete'};opened.push(tab.id);return tab;},
      get:async id=>({id,status:'complete'}),remove:async id=>{closed.push(id);},
      sendMessage:async(_tab,message)=>{sent.push(message);if(message.kind==='probe'&&probeFailures-->0)throw Error('Receiving end does not exist');return {ok:true,ready:true,visibleUser:null,visibleReply:null};},onUpdated:{addListener(){},removeListener(){}}}};
  vm.runInNewContext(source,{chrome,...protocol,URL,fetch:async()=>{if(receiptOffline)throw Error('server offline');return {ok:true,json:async()=>({id:'req',version:1,accepted:false})};},setTimeout,clearTimeout,Date:Clock,Error,Number,String,Promise,AbortSignal});
  const sender={url:`http://localhost:8877/story-video/projects/${scope}/production`,frameId:0,tab:{id:7}};
  return {values,opened,closed,sent,created,advance:ms=>{now+=ms;},send:(message,from=sender)=>new Promise(r=>listener(message,from,r))};
}
test('concurrent claims persist one attempt and open only one ChatGPT tab',async()=>{
  const w=worker();await w.send({kind:'start',scope});
  const claim={kind:'claim',id:'req',version:1,prompt};
  const replies=await Promise.all([w.send(claim),w.send(claim)]);
  assert.ok(replies.every(r=>r.ok));assert.equal(w.opened.length,1);
  assert.equal(w.values.videostudio_bridge_v2.job.attempt,1);
});
test('Stop during a claim cannot be overwritten by its late storage write',async()=>{
  const w=worker();await w.send({kind:'start',scope});
  await Promise.all([w.send({kind:'claim',id:'req',version:1,prompt}),w.send({kind:'stop'})]);
  assert.equal(w.values.videostudio_bridge_v2.active,false);
  assert.ok(w.opened.every(id=>w.closed.includes(id)));
});
test('a late uncertain event cannot overwrite a completed reply',async()=>{
  const w=worker();await w.send({kind:'start',scope});await w.send({kind:'claim',id:'req',version:1,prompt});
  const sender={url:'https://chatgpt.com/',frameId:0,tab:{id:w.opened[0]}};
  await w.send({kind:'sent',id:'req',attempt:1},sender);
  await w.send({kind:'reply',id:'req',attempt:1,text:'{"ok":true}'},sender);
  await w.send({kind:'uncertain',id:'req',attempt:1,reason:'stale timeout'},sender);
  assert.equal(w.values.videostudio_bridge_v2.job.phase,'reply');
});
test('Stop/Start preserves pending attempt instead of resetting the retry budget',async()=>{
  const w=worker();await w.send({kind:'start',scope});await w.send({kind:'claim',id:'req',version:1,prompt});
  await w.send({kind:'stop'});await w.send({kind:'start',scope});
  const state=await w.send({kind:'snapshot'});
  assert.equal(state.job?.id,'req');assert.equal(state.job?.attempt,1);
  assert.equal(w.opened.length,1);
});
test('double Stop is idempotent and retains the suspended receipt',async()=>{
  const w=worker();await w.send({kind:'start',scope});await w.send({kind:'claim',id:'req',version:1,prompt});
  await w.send({kind:'stop'});await w.send({kind:'stop'});await w.send({kind:'start',scope});
  assert.equal((await w.send({kind:'snapshot'})).job?.attempt,1);
});
test('tab load waits for the content script handshake before one delivery',async()=>{
  const w=worker({probeFailures:2});await w.send({kind:'start',scope});
  await w.send({kind:'claim',id:'req',version:1,prompt});
  assert.equal(w.values.videostudio_bridge_v2.job.phase,'dispatching');
  assert.equal(w.opened.length,1);
  assert.equal(w.sent.filter(m=>m.kind==='probe').length,3);
  assert.equal(w.sent.filter(m=>m.kind==='deliver').length,1);
});
test('in-flight receipt network failure is transient and preserves the attempt',async()=>{
  const w=worker({receiptOffline:true});await w.send({kind:'start',scope});await w.send({kind:'claim',id:'req',version:1,prompt});
  const result=await w.send({kind:'reconcile'});
  assert.equal(result.ok,false);assert.equal(result.transient,true);
  assert.equal(w.values.videostudio_bridge_v2.job.attempt,1);
  assert.equal(w.values.videostudio_bridge_v2.active,true);
});
test('initial delivery creates ChatGPT in the background without activating any tab',async()=>{
  const w=worker();await w.send({kind:'start',scope});
  assert.equal((await w.send({kind:'claim',id:'req',version:1,prompt})).ok,true);
  assert.equal(w.created.length,1);assert.equal(w.created[0].active,false);
});
test('the bounded retry also creates a background tab and never steals focus',async()=>{
  const w=worker();await w.send({kind:'start',scope});await w.send({kind:'claim',id:'req',version:1,prompt});
  w.advance(31000);
  const result=await w.send({kind:'reconcile'});
  assert.equal(result.status,'retried');assert.equal(w.created.length,2);
  assert.ok(w.created.every(options=>options.active===false));
});

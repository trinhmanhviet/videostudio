import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as protocol from '../protocol.mjs';
const scope='123e4567-e89b-42d3-a456-426614174000',id='request-closed-tab';
const url='https://chatgpt.com/c/123e4567-e89b-42d3-a456-426614174111';
const prompt=`YÊU CẦU STUDIO ${id}\nScript request`;
const source=(await readFile(new URL('../background.js',import.meta.url),'utf8')).replace(/^import .*?;\r?\n/,'');
function worker({matches=1,known=true,foreign=false,original='closed',foreignMarker=false}={}){
 let state=protocol.start({studioTab:7,scope}),listener;
 state.job={id,prompt,version:1,attempt:1,phase:'sent',send_attempted:true,chatTab:20,startedAt:Date.now()-600000};state.chatTab=20;state.ownedTabs=[20];
 state=protocol.migrateBridge(state);const slot=protocol.sessionSlot(state,scope);
 if(known)slot.job.conversation_url=url;
 slot.chatTab=20;slot.ownedTabs=[20];slot.job_id='video';
 const actions=[],tabs=Array.from({length:matches},(_,i)=>({id:30+i,url:foreign?'https://chatgpt.com/c/123e4567-e89b-42d3-a456-426614174999':url}));
 const chrome={storage:{local:{get:async()=>({videostudio_bridge_v2:structuredClone(state)}),set:async value=>{state=structuredClone(value.videostudio_bridge_v2);}}},
  runtime:{onMessage:{addListener:fn=>listener=fn}},tabs:{
   query:async()=>tabs,get:async tab=>({id:tab,url,status:'complete'}),
   create:async options=>{const tab={id:90,url:options.url,status:'complete'};tabs.push(tab);actions.push({kind:'create',...options});return tab;},remove:async tab=>actions.push({kind:'remove',tab}),
   sendMessage:async(tab,message)=>{
    actions.push({tab,...message});
    if(tab===20){if(original==='hung')return new Promise(()=>{});throw Error('No tab with id');}
    if(message.kind==='probe')return {ok:true};
    if(message.kind!=='inspect')throw Error('Recovery must never deliver another prompt');
    return {visibleUser:foreignMarker?'YÊU CẦU STUDIO different-request\nOther text':prompt,visibleReply:'{"recovered":true}',conversationUrl:tabs.find(t=>t.id===tab)?.url};
   },onUpdated:{addListener(){},removeListener(){}}}};
 vm.runInNewContext(source,{chrome,...protocol,URL,fetch:async()=>({ok:true,json:async()=>({id,version:1,accepted:false})}),AbortSignal,setTimeout,clearTimeout,Date,Error,Promise,Number,String});
 const send=message=>new Promise(resolve=>listener(message,{url:`http://localhost:8877/story-video/projects/${scope}/production`,frameId:0,tab:{id:7}},resolve));
 return {send,actions,get:()=>protocol.sessionSlot(state,scope)};
}
test('closed tab is rebound to its exact conversation and matching request without resending',async()=>{
 const w=worker();const result=await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(result.status,'reply');assert.equal(w.get().job.chatTab,30);assert.equal(w.get().job.attempt,1);
 assert.equal(w.get().job.text,'{"recovered":true}');assert.ok(w.actions.some(a=>a.tab===30&&a.match_only===true));
 assert.ok(w.actions.every(a=>a.kind==='inspect'));
});
test('old saved state without a URL can recover only by the exact immutable request',async()=>{
 const w=worker({known:false});await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(w.get().job.chatTab,30);assert.equal(w.get().job.phase,'reply');
});
test('a different conversation URL cannot take over a request with known URL',async()=>{
 const w=worker({foreign:true});await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(w.get().job.chatTab,20);assert.equal(w.get().job.phase,'sent');
});
test('multiple matching replacement tabs stay unresolved and never resend',async()=>{
 const w=worker({matches:2});await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(w.get().job.chatTab,20);assert.equal(w.get().job.phase,'sent');
});
test('a frozen renderer cannot hold reconciliation forever',async()=>{
 const w=worker({original:'hung'});const result=await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(result.status,'reply');assert.equal(w.get().job.chatTab,30);
});
test('same URL with a foreign request marker cannot take over the job',async()=>{
 const w=worker({foreignMarker:true});await w.send({kind:'reconcile',scope,inspect_only:true});
 assert.equal(w.get().job.chatTab,20);assert.equal(w.get().job.phase,'sent');
});
test('a sent request with a missing tab is never sent again while waiting for replacement',async()=>{
 const w=worker({matches:0});const result=await w.send({kind:'reconcile',scope});
 assert.equal(result.status,'awaiting-replacement');assert.equal(w.get().job.attempt,1);
 assert.ok(w.actions.every(a=>a.kind==='inspect'));
});
test('user repair reopens the saved conversation in background and recovers without Send',async()=>{
 const w=worker({matches:0});const result=await w.send({kind:'recover_chat',scope,id,job_id:'video'});
 assert.equal(result.status,'reply');assert.equal(w.get().job.chatTab,90);assert.equal(w.get().job.attempt,1);
 const created=w.actions.filter(a=>a.kind==='create');assert.equal(created.length,1);assert.equal(created[0].url,url);assert.equal(created[0].active,false);
 assert.ok(!w.actions.some(a=>a.kind==='deliver'));
});
test('user repair requests a URL when old saved state has no conversation URL',async()=>{
 const w=worker({matches:0,known:false});const result=await w.send({kind:'recover_chat',scope,id,job_id:'video'});
 assert.equal(result.status,'needs-chat-url');assert.ok(!w.actions.some(a=>a.kind==='create'));
});
test('user-pasted exact conversation URL repairs old state without resetting the request',async()=>{
 const w=worker({matches:0,known:false});const result=await w.send({kind:'recover_chat',scope,id,job_id:'video',url});
 assert.equal(result.status,'reply');assert.equal(w.get().job.id,id);assert.equal(w.get().job.version,1);
});
test('repair refuses non-ChatGPT URLs before opening a tab',async()=>{
 const w=worker({matches:0,known:false});const result=await w.send({kind:'recover_chat',scope,id,job_id:'video',url:'https://example.test/c/123e4567-e89b-42d3-a456-426614174111'});
 assert.equal(result.ok,false);assert.ok(!w.actions.some(a=>a.kind==='create'));
});

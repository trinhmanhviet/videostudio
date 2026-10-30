import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as protocol from '../protocol.mjs';

const root='123e4567-e89b-42d3-a456-426614174000';
const production=`http://localhost:8877/story-video/projects/${root}/production`;
const source=(await readFile(new URL('../background.js',import.meta.url),'utf8')).replace(/^import .*?;\r?\n/,'');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function worker(initial=protocol.start({studioTab:7,scope:root}),existingAlarm=null){
  let listener,onAlarm,alarm=existingAlarm,ownerUrl=production,closed=false,failure=false,hold=null,now=Date.now(),lookup=null,observation=null;
  class Clock extends Date{static now(){return now;}}
  const values={videostudio_bridge_v2:initial},created=[],requests=[],timeouts=[],messages=[];
  const chrome={
    storage:{local:{get:async key=>({[key]:structuredClone(values[key])}),set:async data=>Object.assign(values,structuredClone(data))}},
    runtime:{getManifest:()=>({version:'0.3.3'}),onMessage:{addListener:fn=>listener=fn}},
    alarms:{get:async()=>alarm,create:async(name,options)=>{alarm={name,...options};created.push(alarm);},onAlarm:{addListener:fn=>onAlarm=fn}},
    tabs:{get:async id=>{if(closed)throw Error('Tab closed');return {id,url:ownerUrl};},remove:async()=>{},create:async()=>{throw Error('Read-only pulse must not open tabs');},sendMessage:async(id,message)=>{messages.push({tab:id,...message});return observation?.(id,message)??{visibleUser:null,visibleReply:null};}}
  };
  const fetch=async(url,options={})=>{requests.push({url,...options,body:options.body?JSON.parse(options.body):null});if(hold)await hold;if(failure)throw Error('offline');return lookup?.(url,options)??{ok:true,json:async()=>({id:url.split('/').at(-1),version:1,accepted:false})};};
  const load=()=>vm.runInNewContext(source,{chrome,...protocol,URL,fetch,AbortSignal:{timeout:ms=>{timeouts.push(ms);return AbortSignal.timeout(ms);}},setTimeout,clearTimeout,Date:Clock,Error,Number,String,Promise});
  load();
  const send=message=>new Promise(resolve=>listener(message,{url:production,frameId:0,tab:{id:7}},resolve));
  return {values,created,requests,timeouts,messages,send,load,flush,fire:async name=>{onAlarm?.({name:name??alarm?.name});await flush();},advance:ms=>now+=ms,lookup:value=>lookup=value,seen:value=>observation=value,
    url:value=>ownerUrl=value,close:()=>closed=true,offline:value=>failure=value,hold:promise=>hold=promise,alarm:()=>alarm,dropAlarm:()=>alarm=null};
}

test('worker installs its periodic alarm and renews the active root while the page is idle',async()=>{
  const w=worker();await w.flush();
  assert.equal(w.created.length,1);assert.equal(w.alarm().periodInMinutes,0.5);
  await w.fire();
  assert.equal(w.requests.length,1);assert.equal(w.requests[0].url,`http://localhost:8877/api/connector/status/${root}`);
  assert.equal(w.requests[0].method,'POST');assert.deepEqual(w.requests[0].body,{build:'videostudio-extension-0.3.0',runtime_version:'0.3.3',stage:'active',connected:true,enabled:true});
  assert.equal(w.requests[0].headers['X-VS-Client'],'videostudio-extension');
  assert.deepEqual(w.timeouts,[15000]);
  await w.fire('another-extension-alarm');assert.equal(w.requests.length,1);
});

test('worker startup recreates a missing alarm without replacing its existing period',async()=>{
  const w=worker();await w.flush();w.load();await w.flush();assert.equal(w.created.length,1);
  w.dropAlarm();w.load();await w.flush();assert.equal(w.created.length,2);
});

test('paused, closed, and unrelated owner pages cannot renew bridge heartbeat',async()=>{
  const w=worker();await w.flush();await w.send({kind:'stop'});await w.fire();assert.equal(w.requests.length,0);
  for(const url of ['http://localhost:8877/',production+'?other=1',production.replace(root,'123e4567-e89b-42d3-a456-426614174001'),'https://untrusted.invalid/']){
    const other=worker();await other.flush();other.url(url);await other.fire();assert.equal(other.requests.length,0,url);
  }
  const gone=worker();await gone.flush();gone.close();await gone.fire();assert.equal(gone.requests.length,0);
});

test('heartbeat reports only current root smoke mode errors and never changes stored requests on failure',async()=>{
  const initial=protocol.start({studioTab:7,scope:root});
  protocol.claim(initial,{studioTab:7,scope:root,id:'smoke',version:1,prompt:'YÊU CẦU STUDIO smoke\ntest'});protocol.beginAttempt(initial,20);
  initial.job.phase='uncertain';initial.job.reason='Chat mode not confirmed';
  const bridge=protocol.migrateBridge(initial);bridge.sessions[0].is_smoke=true;bridge.sessions[0].job.is_smoke=true;
  const w=worker(bridge);await w.flush();const before=structuredClone(w.values);
  w.offline(true);await w.fire();assert.deepEqual(w.values,before);
  assert.equal(w.requests.length,2);
  assert.deepEqual(w.requests[0].body.error,{code:'chat_mode',message:'Chat mode not confirmed'});
  w.offline(false);await w.fire();assert.equal(w.requests.length,3);
  w.values.videostudio_bridge_v2.sessions[0].is_smoke=false;delete w.values.videostudio_bridge_v2.sessions[0].job.is_smoke;
  await w.fire();assert.equal(w.requests.at(-1).body.error,undefined);
});

test('Stop serializes after an in-flight pulse and prevents queued pulse renewal',async()=>{
  const w=worker();await w.flush();let release;w.hold(new Promise(resolve=>release=resolve));
  await w.fire();const stopped=w.send({kind:'stop'});await w.fire();
  assert.equal(w.requests.length,1);release();assert.equal((await stopped).ok,true);await w.flush();
  assert.equal(w.values.videostudio_bridge_v2.active,false);assert.equal(w.requests.length,1);
});

const child='123e4567-e89b-42d3-a456-426614174001';
function pendingBridge(){
  const bridge=protocol.migrateBridge(protocol.start({studioTab:7,scope:root}));
  for(const [scope,tab] of [[root,20],[child,21]]){
    const slot=protocol.start({studioTab:7,scope});
    protocol.claim(slot,{studioTab:7,scope,id:'same',version:1,prompt:'YÊU CẦU STUDIO same\nhello'});protocol.beginAttempt(slot,tab);slot.job.phase='uncertain';slot.job.reason='HTTP 403';slot.job.startedAt=Date.now()-400000;
    bridge.sessions.push(slot);
  }
  return protocol.syncBridge(bridge);
}

test('idle alarm reconciles each exact pending slot read-only and throttles unresolved requests',async()=>{
  const w=worker(pendingBridge());await w.flush();
  w.seen(tab=>({visibleUser:'YÊU CẦU STUDIO same\n[collapsed]',visibleReply:tab===21?'child answer':null}));
  await w.fire();
  assert.equal(w.requests.filter(r=>r.method==='POST').length,1);assert.deepEqual(w.messages.map(m=>[m.tab,m.kind,m.id]),[[20,'inspect','same'],[21,'inspect','same']]);
  assert.equal(w.values.videostudio_bridge_v2.sessions[0].job.phase,'uncertain');assert.equal(w.values.videostudio_bridge_v2.sessions[1].job.text,'child answer');
  assert.ok(w.values.videostudio_bridge_v2.sessions.every(s=>s.job.attempt===1));
  await w.fire();assert.equal(w.messages.length,2);
  w.advance(26000);await w.fire();assert.equal(w.messages.length,3);assert.equal(w.messages.at(-1).tab,20);
});

test('a forbidden or offline receipt cannot block another slot or bridge heartbeat',async()=>{
  for(const forbidden of [true,false]){
    const w=worker(pendingBridge());await w.flush();
    w.lookup(url=>{
      if(url.includes(`/projects/${root}/runs/`)){if(forbidden)return {ok:false,status:403};throw Error('network offline');}
      return {ok:true,json:async()=>({id:'same',version:1,accepted:false})};
    });
    w.seen(()=>({visibleUser:'YÊU CẦU STUDIO same\nhello',visibleReply:'child survives'}));
    await w.fire();assert.equal(w.requests.filter(r=>r.method==='POST').length,1);assert.equal(w.values.videostudio_bridge_v2.sessions[1].job.text,'child survives');
    assert.equal(w.values.videostudio_bridge_v2.sessions[0].job.reason,'HTTP 403');assert.equal(w.messages.length,1);assert.equal(w.messages[0].tab,21);
  }
});

test('automatic inspection skips cancelled and inactive slots and never runs after Stop',async()=>{
  const initial=pendingBridge();initial.sessions[0].cancelled=true;initial.sessions[1].active=false;
  const w=worker(initial);await w.flush();await w.fire();assert.equal(w.requests.length,1);assert.equal(w.messages.length,0);
  const stopped=worker(pendingBridge());await stopped.flush();await stopped.send({kind:'stop'});await stopped.fire();assert.equal(stopped.requests.length,0);assert.equal(stopped.messages.length,0);
});

test('automatic inspection accepts no foreign or blocked reply and never creates a new attempt',async()=>{
  const w=worker(pendingBridge());await w.flush();
  w.seen(tab=>({visibleUser:tab===20?'YÊU CẦU STUDIO other\nforeign':'YÊU CẦU STUDIO same\nhello',visibleReply:'wrong',blocked:tab===21}));
  await w.fire();assert.ok(w.values.videostudio_bridge_v2.sessions.every(s=>s.job.phase==='uncertain'&&s.job.attempt===1));assert.equal(w.messages.length,2);
});

test('sent and dispatching requests recover from exact accepted receipts even if heartbeat is unavailable',async()=>{
  const initial=pendingBridge();initial.sessions[0].job.phase='sent';initial.sessions[1].job.phase='dispatching';
  const w=worker(initial);await w.flush();
  w.lookup((url,options)=>{if(options.method==='POST')throw Error('heartbeat offline');return {ok:true,json:async()=>({id:'same',version:1,accepted:true,response_text:url.includes(`/projects/${root}/`)?'root receipt':'child receipt'})};});
  await w.fire();
  const slots=w.values.videostudio_bridge_v2.sessions;assert.equal(slots[0].job.text,'root receipt');assert.equal(slots[1].job.text,'child receipt');assert.ok(slots.every(s=>s.job.phase==='reply'&&s.job.attempt===1));
  assert.equal(w.requests.filter(r=>r.method==='POST').length,1);assert.ok(w.messages.every(m=>m.kind==='inspect'));
});

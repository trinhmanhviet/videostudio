import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as protocol from '../protocol.mjs';

const root='123e4567-e89b-42d3-a456-426614174000';
const a='123e4567-e89b-42d3-a456-426614174001';
const b='123e4567-e89b-42d3-a456-426614174002';
const foreign='123e4567-e89b-42d3-a456-426614174003';
const source=(await readFile(new URL('../background.js',import.meta.url),'utf8')).replace(/^import .*?;\r?\n/,'');
function worker(initial=null){
  let listener,next=20,now=Date.now(),observed={ok:true,visibleUser:null,visibleReply:null};
  class Clock extends Date{static now(){return now;}}
  const values={videostudio_bridge_v2:initial},created=[],closed=[],activated=[],requests=[],messages=[];
  let memberships=[{scope:a,job_id:'video-a',state:'running'},{scope:b,job_id:'video-b',state:'queued'}],membershipOffline=false,pending=[],dismissed=null;
  const chrome={storage:{local:{get:async key=>({[key]:structuredClone(values[key])}),set:async data=>Object.assign(values,structuredClone(data))}},
    runtime:{onMessage:{addListener:fn=>{listener=fn;}}},
    tabs:{create:async options=>{const tab={id:++next,status:'complete'};created.push({...options,id:tab.id});return tab;},get:async id=>{if(closed.includes(id))throw Error('closed');return {id,status:'complete'};},
      update:async(id,options)=>{activated.push({id,...options});return {id};},remove:async id=>closed.push(id),sendMessage:async(id,message)=>{messages.push({id,...message});return observed;}}};
  const fetch=async url=>{requests.push(url);if(membershipOffline&&url.endsWith('/sessions'))throw Error('server offline');return {ok:true,json:async()=>url.includes('/jobs/')?dismissed:url.endsWith('/sessions')?{items:memberships}:url.endsWith('/pending')?{items:pending}:{id:url.endsWith('/smoke')?'smoke':'same',version:1,accepted:false}};};
  const load=()=>vm.runInNewContext(source,{chrome,...protocol,URL,fetch,AbortSignal,setTimeout,clearTimeout,Date:Clock,Error,Number,String,Promise});load();
  const owner={url:`http://localhost:8877/story-video/projects/${root}/production`,frameId:0,tab:{id:7}};
  const send=(message,sender=owner)=>new Promise(resolve=>listener(message,sender,resolve));
  const claim=scope=>send({kind:'claim',scope,id:'same',version:1,prompt:'YÊU CẦU STUDIO same\nhello'});
  return {values,created,closed,activated,requests,messages,send,claim,load,seen:value=>observed=value,advance:ms=>now+=ms,memberships:items=>memberships=items,pending:items=>pending=items,dismissed:item=>dismissed=item,offline:()=>membershipOffline=true,
    chat:tab=>({url:'https://chatgpt.com/',frameId:0,tab:{id:tab}})};
}

test('legacy v2 pending and suspended jobs migrate into a recoverable root slot',async()=>{
  for(const paused of [false,true]){
    const legacy=protocol.start({studioTab:7,scope:root});
    protocol.claim(legacy,{studioTab:7,scope:root,id:'same',version:1,prompt:'YÊU CẦU STUDIO same\nhello'});protocol.beginAttempt(legacy,19);
    if(paused)protocol.stop(legacy);
    const w=worker(legacy);await w.send({kind:'start',scope:root});
    const snapshot=await w.send({kind:'snapshot'});
    assert.equal(snapshot.sessions?.[0]?.scope,root);assert.equal(snapshot.sessions[0].job.attempt,1);assert.equal(snapshot.job.id,'same');assert.equal(w.created.length,0);
  }
});

test('read-only recovery can read an exact completed turn after earlier auth or after-send mode errors',async()=>{
  for(const reason of ['Login required','captcha','Chat mode unknown','Chat mode not confirmed after send']){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
    await w.send({kind:'uncertain',id:'same',attempt:1,reason,send_attempted:true},w.chat(w.created[0].id));
    w.seen({visibleUser:'YÊU CẦU STUDIO same\n[collapsed]',visibleReply:'completed answer'});
    assert.equal((await w.send({kind:'reconcile',scope:a,inspect_only:true})).status,'reply',reason);
    const slot=(await w.send({kind:'snapshot'})).sessions[0];assert.equal(slot.job.text,'completed answer');assert.equal(slot.job.reason,reason);
    assert.equal(slot.job.attempt,1);assert.equal(w.created.length,1);
  }
});

test('dismiss closes only the selected child and its retained tabs after exact server attestation',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);await w.claim(b);
  const value=w.values.videostudio_bridge_v2;value.sessions[0].retained=[{...structuredClone(value.sessions[0]),chatTab:70,ownedTabs:[70],retained:[]}];
  w.dismissed({scope:a,job_id:'video-a',state:'failed',dismissed:true});
  assert.equal((await w.send({kind:'dismiss_session',scope:a,job_id:'video-a'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.active,true);assert.deepEqual(snapshot.sessions.map(s=>s.scope),[b]);assert.deepEqual(w.closed,[w.created[0].id,70]);
  assert.equal((await w.send({kind:'sent',id:'same',attempt:1},w.chat(w.created[1].id))).ok,true);
});

test('dismiss fails closed for missing, mismatched, active, or undismissed server identity',async()=>{
  for(const change of [null,{scope:b},{job_id:'video-b'},{state:'running'},{dismissed:false}]){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
    w.dismissed(change===null?null:{scope:a,job_id:'video-a',state:'failed',dismissed:true,...change});
    assert.equal((await w.send({kind:'dismiss_session',scope:a,job_id:'video-a'})).ok,false);
    assert.equal((await w.send({kind:'snapshot'})).sessions.length,1);assert.deepEqual(w.closed,[]);
  }
});
test('composer mismatch retains bounded diagnostics on the exact scoped request',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  const diagnostic={expected_length:6134,actual_length:6141,first_diff:1591,actual_context:'URL decoration'};
  await w.send({kind:'uncertain',id:'same',attempt:1,reason:'Composer mismatch',send_attempted:false,composer_diagnostic:diagnostic},w.chat(w.created[0].id));
  const job=(await w.send({kind:'snapshot'})).sessions.find(slot=>slot.scope===a).job;
  assert.equal(job.composer_diagnostic?.first_diff,1591);
  assert.equal(w.values.videostudio_last_composer_diagnostic?.scope,a);
  assert.equal(w.values.videostudio_last_composer_diagnostic?.request_id,'same');
});

test('Start can discover and reconnect the saved bridge without replacing video sessions',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  const home={url:'http://localhost:8877/',frameId:0,tab:{id:8}};
  const connection=await w.send({kind:'connection'},home);
  assert.equal(connection.ok,true);assert.equal(connection.scope,root);
  assert.equal(connection.url,`/story-video/projects/${root}/production`);
  assert.equal(connection.sessions,undefined);
  const otherPage={...home,url:`http://localhost:8877/story-video/projects/${foreign}/production`};
  assert.equal((await w.send({kind:'start',scope:root,reconnect:true},otherPage)).ok,true);
  const restored=await w.send({kind:'snapshot'},{...home,url:`http://localhost:8877/story-video/projects/${root}/production`});
  assert.equal(restored.sessions.find(slot=>slot.scope===a).job.attempt,1);
  assert.equal(w.created.length,1);assert.deepEqual(w.closed,[]);
  assert.equal((await w.send({kind:'snapshot'})).ok,false);
});

test('saved connection lookup and reconnect reject foreign or unsupported pages',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  for(const url of ['https://untrusted.invalid/','http://localhost:8877/other']){
    const sender={url,frameId:0,tab:{id:8}};
    assert.equal((await w.send({kind:'connection'},sender)).ok,false);
    assert.equal((await w.send({kind:'start',scope:root,reconnect:true},sender)).ok,false);
  }
  assert.equal((await w.send({kind:'start',scope:foreign,reconnect:true},{url:'http://localhost:8877/',frameId:0,tab:{id:8}})).ok,false);
  assert.equal((await w.send({kind:'snapshot'})).ok,true);
  assert.equal(w.created.length,1);assert.deepEqual(w.closed,[]);
});

test('recovery imports a completed reply bound to the exact marker in a collapsed user bubble',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  await w.send({kind:'sent',id:'same',attempt:1},w.chat(w.created[0].id));
  w.seen({visibleUser:'YÊU CẦU STUDIO same\n[collapsed bubble]',visibleReply:'{"ok":true}'});
  const reply=await w.send({kind:'reconcile',scope:a});
  assert.equal(reply.status,'reply');
  const snapshot=await w.send({kind:'snapshot'});
  assert.equal(snapshot.sessions.find(slot=>slot.scope===a).job.text,'{"ok":true}');
  assert.equal(w.created.length,1);
});

test('matching marker without a completed reply remains pending without another send',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  w.seen({visibleUser:'YÊU CẦU STUDIO same\n[collapsed bubble]',visibleReply:null});
  assert.equal((await w.send({kind:'reconcile',scope:a})).status,'pending');
  assert.equal(w.created.length,1);
});

test('a different request sharing a marker prefix is never accepted during recovery',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  w.seen({visibleUser:'YÊU CẦU STUDIO same-other\nUnrelated',visibleReply:'{"wrong":true}'});
  assert.equal((await w.send({kind:'reconcile',scope:a})).status,'foreign-turn');
  assert.equal((await w.send({kind:'snapshot'})).sessions.find(slot=>slot.scope===a).job.text,undefined);
  assert.equal(w.created.length,1);
});

test('child slots coexist with exact callback binding even for identical exchange ids',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});
  assert.equal((await w.claim(a)).ok,true);assert.equal((await w.claim(b)).ok,true);
  const [tabA,tabB]=w.created.map(tab=>tab.id);
  assert.equal((await w.send({kind:'sent',id:'same',attempt:1},w.chat(tabA))).ok,true);
  assert.equal((await w.send({kind:'reply',scope:b,id:'same',attempt:1,text:'wrong'},w.chat(tabA))).ok,false);
  assert.equal((await w.send({kind:'reply',id:'same',attempt:2,text:'wrong'},w.chat(tabA))).ok,false);
  assert.equal((await w.send({kind:'reply',id:'same',attempt:1,text:'answer a'},w.chat(tabA))).ok,true);
  await w.send({kind:'uncertain',id:'same',attempt:1,reason:'late'},w.chat(tabA));
  await w.send({kind:'uncertain',id:'same',attempt:1,reason:'failed b'},w.chat(tabB));
  const snapshot=await w.send({kind:'snapshot'});
  assert.equal(snapshot.sessions.find(s=>s.scope===a).job.text,'answer a');
  assert.equal(snapshot.sessions.find(s=>s.scope===b).job.phase,'uncertain');
  assert.equal(snapshot.job,null);assert.ok(w.created.every(tab=>tab.active===false));assert.deepEqual(w.activated,[]);
});

test('child claims require current bridge membership and exact job ownership',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});
  assert.equal((await w.claim(foreign)).ok,false);
  assert.equal((await w.send({kind:'claim',scope:a,job_id:'video-b',id:'same',version:1,prompt:'YÊU CẦU STUDIO same\nhello'})).ok,false);
  assert.equal(w.created.length,0);assert.equal((await w.claim(a)).ok,true);
  w.memberships([{scope:b,job_id:'video-b'}]);assert.equal((await w.claim(a)).ok,false);
});

test('scoped import closes only its owned tab and keeps the accepted receipt',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);await w.claim(b);
  const tabA=w.created[0].id;await w.send({kind:'sent',id:'same',attempt:1},w.chat(tabA));await w.send({kind:'reply',id:'same',attempt:1,text:'answer'},w.chat(tabA));
  assert.equal((await w.send({kind:'imported',scope:b,id:'same',version:1,accepted:true})).ok,false);
  assert.equal((await w.send({kind:'imported',scope:a,id:'same',version:1,accepted:true})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions.find(s=>s.scope===a).job,null);assert.equal(snapshot.sessions.find(s=>s.scope===a).lastReceipt.id,'same');
  assert.equal(snapshot.sessions.find(s=>s.scope===b).job.phase,'dispatching');assert.deepEqual(w.closed,[tabA]);
});

test('explicit Open Chat and cancel affect only the selected session and retain its request',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);await w.claim(b);
  const tabA=w.created[0].id,tabB=w.created[1].id;
  assert.equal((await w.send({kind:'open_chat',scope:foreign})).ok,false);
  assert.equal((await w.send({kind:'open_chat',scope:a})).ok,true);assert.deepEqual(w.activated,[{id:tabA,active:true}]);
  assert.equal((await w.send({kind:'cancel_session',scope:a})).ok,true);assert.deepEqual(w.closed,[tabA]);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions.find(s=>s.scope===a).job.id,'same');assert.equal(snapshot.sessions.find(s=>s.scope===a).active,false);assert.equal(snapshot.sessions.find(s=>s.scope===b).active,true);
  assert.equal((await w.send({kind:'sent',id:'same',attempt:1},w.chat(tabB))).ok,true);assert.equal((await w.claim(a)).ok,false);
});

test('Stop, reload, and same bridge Start preserve every slot retry budget',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);await w.claim(b);await w.send({kind:'stop'});w.load();await w.send({kind:'start',scope:root});
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions.length,2);assert.ok(snapshot.sessions.every(s=>s.job.attempt===1));assert.equal(w.created.length,2);assert.equal(w.closed.length,2);
});

test('another bridge Start cannot silently replace child sessions',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);
  const response=await w.send({kind:'start',scope:foreign},{url:'http://localhost:8877/',frameId:0,tab:{id:7}});
  assert.equal(response.ok,false);assert.equal((await w.send({kind:'snapshot'})).sessions[0].job.attempt,1);assert.deepEqual(w.closed,[]);
});

test('Check old request reads the selected receipt without retrying',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);w.advance(40000);
  const response=await w.send({kind:'reconcile',scope:a,inspect_only:true});assert.equal(response.ok,true);assert.equal(response.status,'unresolved');assert.equal(w.created.length,1);
  assert.ok(w.requests.some(url=>url.includes(`/projects/${a}/runs/${a}/chatgpt-exchanges/same`)));
});

test('server-known video can be cancelled before its first local exchange',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});
  assert.equal((await w.send({kind:'cancel_session',scope:foreign})).ok,false);
  assert.equal((await w.send({kind:'cancel_session',scope:a})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions[0].job,null);assert.equal(snapshot.sessions[0].cancelled,true);assert.deepEqual(w.created,[]);
  assert.equal((await w.claim(a)).ok,false);
});

test('membership outage fails closed without claiming or launching an unrelated session',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);w.offline();
  const failed=await w.claim(b);assert.equal(failed.ok,false);assert.equal(failed.transient,true);assert.equal(w.created.length,1);
  assert.equal((await w.send({kind:'snapshot'})).sessions.length,1);
});

test('two child claims and cancellation serialize without losing the other video',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});
  const responses=await Promise.all([w.claim(a),w.claim(b),w.send({kind:'cancel_session',scope:a})]);assert.ok(responses.every(r=>r.ok));
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions.find(s=>s.scope===a).cancelled,true);assert.equal(snapshot.sessions.find(s=>s.scope===b).job.attempt,1);assert.deepEqual(w.closed,[w.created[0].id]);
});

test('paused old request inspection preserves attempts and never opens a tab',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);w.advance(40000);await w.send({kind:'stop'});
  const result=await w.send({kind:'reconcile',scope:a,inspect_only:true});assert.equal(result.ok,true);assert.equal(result.status,'unresolved');assert.equal(w.created.length,1);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.active,false);assert.equal(snapshot.sessions[0].job.attempt,1);
});

test('stale pending claim cannot launch after server cancellation or terminal job state',async()=>{
  for(const update of [{state:'cancelled'},{state:'failed'},{state:'completed'},{state:'running',cancel_requested:true}]){
    const w=worker();await w.send({kind:'start',scope:root});w.memberships([{scope:a,job_id:'video-a',...update}]);
    const response=await w.claim(a);assert.equal(response.ok,false,JSON.stringify(update));assert.equal(w.created.length,0);assert.equal((await w.send({kind:'snapshot'})).sessions.length,0);
    assert.equal((await w.send({kind:'cancel_session',scope:a})).ok,true);
  }
});

test('legacy root archive can be reconnected without losing its original attempt',async()=>{
  const w=worker();const owner={url:'http://localhost:8877/',frameId:0,tab:{id:7}};
  await w.send({kind:'start',scope:root},owner);await w.claim(root);
  assert.equal((await w.send({kind:'start',scope:foreign},owner)).ok,true);
  assert.equal(w.values[`videostudio_bridge_archive_${root}`].sessions[0].job.attempt,1);
  assert.equal((await w.send({kind:'start',scope:root},owner)).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.job?.attempt,1);assert.equal(snapshot.sessions[0].job.id,'same');assert.equal(w.created.length,1);
});

test('paused sessions accept only explicit boolean read-only recovery',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(a);w.advance(40000);await w.send({kind:'stop'});
  assert.equal((await w.send({kind:'reconcile',scope:a,inspect_only:'true'})).ok,false);assert.equal(w.created.length,1);
});

const smoke={kind:'claim',scope:root,job_id:null,id:'smoke',version:1,prompt:'YÊU CẦU STUDIO smoke\nconnection test',is_smoke:true};
const smokePending={scope:root,job_id:null,id:smoke.id,version:1,prompt:smoke.prompt,is_smoke:true,attachments:[]};
test('server-attested smoke retains failed root video request with exact historical actions and callbacks',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const oldTab=w.created[0].id;
  await w.send({kind:'sent',id:'same',attempt:1},w.chat(oldTab));
  w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);
  assert.equal((await w.send(smoke)).ok,true);const smokeTab=w.created[1].id;
  await w.send({kind:'reply',id:'same',attempt:1,text:'old failed reply'},w.chat(oldTab));
  let snapshot=await w.send({kind:'snapshot'});const slot=snapshot.sessions[0];
  assert.equal(slot.job.id,'smoke');assert.equal(slot.job.is_smoke,true);assert.equal(slot.retained[0].job_id,'legacy-video');assert.equal(slot.retained[0].job.text,'old failed reply');assert.equal(slot.retained[0].job.attempt,1);
  assert.equal((await w.send({kind:'imported',scope:root,id:'same',version:1,accepted:true})).ok,false);
  assert.equal((await w.send({kind:'open_chat',scope:root,id:'same'})).ok,true);assert.equal(w.activated[0].id,oldTab);
  assert.equal((await w.send({kind:'reconcile',scope:root,id:'same'})).ok,false);
  assert.equal((await w.send({kind:'reconcile',scope:root,id:'same',inspect_only:true})).ok,true);assert.equal(w.created.length,2);
  assert.equal((await w.send({kind:'sent',id:'smoke',attempt:1},w.chat(smokeTab))).ok,true);
  assert.equal((await w.send({kind:'reply',id:'smoke',attempt:1,text:'smoke answer'},w.chat(smokeTab))).ok,true);
  assert.equal((await w.send({kind:'imported',scope:root,id:'smoke',version:1,accepted:true})).ok,true);
  snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions[0].job,null);assert.equal(snapshot.sessions[0].retained[0].job.text,'old failed reply');
  await w.send({kind:'stop'});assert.ok(w.closed.includes(oldTab));assert.ok(w.closed.includes(smokeTab));
});

test('smoke replacement requires exact server pending request and terminal legacy job',async()=>{
  for(const variant of ['missing','wrong-version','wrong-prompt','not-smoke','active-root']){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);
    w.memberships([{scope:root,job_id:'legacy-video',state:variant==='active-root'?'running':'failed'}]);
    const pending={...smokePending};if(variant==='wrong-version')pending.version=2;if(variant==='wrong-prompt')pending.prompt+='changed';if(variant==='not-smoke')pending.is_smoke=false;
    w.pending(variant==='missing'?[]:[pending]);assert.equal((await w.send(smoke)).ok,false,variant);
    const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.job.id,'same');assert.equal(snapshot.job.attempt,1);assert.equal(w.created.length,1);
  }
});

test('Stop and worker reload preserve current smoke and retained video attempts',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);w.memberships([{scope:root,job_id:'legacy-video',state:'cancelled'}]);w.pending([smokePending]);
  assert.equal((await w.send(smoke)).ok,true);await w.send({kind:'stop'});assert.equal(w.closed.length,2);w.load();await w.send({kind:'start',scope:root});
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.job.is_smoke,true);assert.equal(snapshot.job.attempt,1);assert.equal(snapshot.sessions[0].retained[0].job.attempt,1);assert.equal(w.created.length,2);
});

test('server-attested legacy root cancellation acknowledges no local waiting',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});w.memberships([{scope:root,job_id:'legacy-video',state:'cancelled'}]);
  assert.equal((await w.send({kind:'cancel_session',scope:root,job_id:'foreign-video'})).ok,false);
  assert.equal((await w.send({kind:'cancel_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions[0].job,null);assert.equal(snapshot.sessions[0].cancelled,true);assert.equal(snapshot.sessions[0].job_id,'legacy-video');assert.equal(w.created.length,0);
});

test('cancelling legacy root video closes its retained tabs without cancelling control smoke',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const oldTab=w.created[0].id;w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);
  assert.equal((await w.send(smoke)).ok,true);const smokeTab=w.created[1].id;
  assert.equal((await w.send({kind:'cancel_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions[0].job.id,'smoke');assert.equal(snapshot.sessions[0].active,true);assert.equal(snapshot.sessions[0].retained[0].cancelled,true);assert.deepEqual(w.closed,[oldTab]);
  assert.equal((await w.send({kind:'sent',id:'smoke',attempt:1},w.chat(smokeTab))).ok,true);
});

test('legacy cancellation during first control smoke records an empty historical video only',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);
  assert.equal((await w.send(smoke)).ok,true);
  assert.equal((await w.send({kind:'cancel_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.sessions[0].job.id,'smoke');assert.equal(snapshot.sessions[0].cancelled,false);assert.equal(snapshot.sessions[0].retained[0].job,null);assert.equal(snapshot.sessions[0].retained[0].cancelled,true);assert.deepEqual(w.closed,[]);
});

test('a fresh root can run another explicit smoke after the previous test was accepted',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});w.memberships([]);w.pending([smokePending]);assert.equal((await w.send(smoke)).ok,true);
  const tab=w.created[0].id;await w.send({kind:'sent',id:'smoke',attempt:1},w.chat(tab));await w.send({kind:'reply',id:'smoke',attempt:1,text:'accepted smoke'},w.chat(tab));await w.send({kind:'imported',scope:root,id:'smoke',version:1,accepted:true});
  const next={...smoke,id:'smoke2',prompt:'YÊU CẦU STUDIO smoke2\nnew connection test'};w.pending([{...smokePending,id:next.id,prompt:next.prompt}]);
  assert.equal((await w.send(next)).ok,true);assert.equal(w.created.length,2);assert.equal((await w.send({kind:'snapshot'})).job.id,'smoke2');
});

async function acceptCurrentSmoke(w){
  const tab=w.created.at(-1).id;
  await w.send({kind:'sent',id:'smoke',attempt:1},w.chat(tab));await w.send({kind:'reply',id:'smoke',attempt:1,text:'accepted smoke'},w.chat(tab));
  assert.equal((await w.send({kind:'imported',scope:root,id:'smoke',version:1,accepted:true})).ok,true);
}
const resumedRoot={kind:'claim',scope:root,job_id:'legacy-video',is_smoke:false,id:'same',version:1,prompt:'YÊU CẦU STUDIO same\nhello'};

test('legacy exact pre-send Chat mode failures recover once in a fresh background tab with the same request',async()=>{
  for(const reason of ['Chat mode not confirmed','Chat mode unknown']){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const first=w.created[0].id;
    await w.send({kind:'uncertain',id:'same',attempt:1,reason},w.chat(first));
    assert.equal((await w.send({kind:'reconcile',scope:root,inspect_only:true})).status,'unresolved');assert.equal(w.created.length,1);
    assert.equal((await w.send({kind:'reconcile',scope:root})).status,'retried');
    const job=(await w.send({kind:'snapshot'})).job;
    assert.equal(job.id,'same');assert.equal(job.version,1);assert.equal(job.attempt,2);assert.equal(job.prompt,'YÊU CẦU STUDIO same\nhello');
    assert.ok(w.created.every(tab=>tab.active===false));assert.deepEqual(w.closed,[first]);
    await w.send({kind:'uncertain',id:'same',attempt:2,reason,send_attempted:false},w.chat(w.created[1].id));
    assert.equal((await w.send({kind:'reconcile',scope:root})).status,'exhausted');assert.equal(w.created.length,2);
  }
});

test('explicit after-send mode failures and human challenges never enter the pre-send retry exception',async()=>{
  for(const [reason,send_attempted] of [['Chat mode not confirmed',true],['Chat mode unknown',true],['Chat mode not confirmed after send',false],['Login required',false],['captcha',false]]){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);
    await w.send({kind:'uncertain',id:'same',attempt:1,reason,send_attempted},w.chat(w.created[0].id));
    assert.equal((await w.send({kind:'reconcile',scope:root})).status,'human-or-invalid',reason);assert.equal(w.created.length,1);
  }
});

test('explicit pre-send mode failure stays recoverable across worker reload without resetting its attempt',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);
  await w.send({kind:'uncertain',id:'same',attempt:1,reason:'Chat mode not confirmed',send_attempted:false},w.chat(w.created[0].id));
  w.load();assert.equal((await w.send({kind:'snapshot'})).job.send_attempted,false);
  assert.equal((await w.send({kind:'reconcile',scope:root})).status,'retried');
  assert.equal((await w.send({kind:'snapshot'})).job.attempt,2);assert.equal(w.created.length,2);
});

test('confirmed sent receipt cannot be downgraded to a safe pre-send mode failure',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const sender=w.chat(w.created[0].id);
  await w.send({kind:'sent',id:'same',attempt:1},sender);
  await w.send({kind:'uncertain',id:'same',attempt:1,reason:'Chat mode unknown',send_attempted:false},sender);
  assert.equal((await w.send({kind:'reconcile',scope:root})).status,'human-or-invalid');assert.equal(w.created.length,1);
});
test('resumed legacy root promotes its exact retained request without resending or resetting retry budget',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);w.advance(31000);assert.equal((await w.send({kind:'reconcile',scope:root})).status,'retried');
  const videoTab=w.created.at(-1).id;w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);assert.equal((await w.send(smoke)).ok,true);await acceptCurrentSmoke(w);
  w.memberships([{scope:root,job_id:'legacy-video',state:'running'}]);const deliveries=w.messages.filter(item=>item.kind==='deliver').length;
  const promoted=await w.send(resumedRoot);assert.equal(promoted.ok,true);assert.equal(promoted.phase,'dispatching');
  const slot=(await w.send({kind:'snapshot'})).sessions[0];assert.equal(slot.job.attempt,2);assert.equal(slot.job.chatTab,videoTab);assert.equal(slot.job_id,'legacy-video');assert.equal(slot.is_smoke,false);assert.notEqual(slot.job.is_smoke,true);
  assert.equal(w.messages.filter(item=>item.kind==='deliver').length,deliveries);assert.equal(w.created.length,3);assert.ok(slot.retained.some(item=>item.is_smoke&&item.lastReceipt?.id==='smoke'));
  assert.equal((await w.send({kind:'sent',id:'same',attempt:2},w.chat(videoTab))).ok,true);assert.equal((await w.send({kind:'reply',id:'same',attempt:2,text:'resumed video answer'},w.chat(videoTab))).ok,true);
  assert.equal((await w.send({kind:'imported',scope:root,id:'same',version:1,accepted:true})).ok,true);
});

test('root video new request after smoke is classified as video while old request remains retained',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);assert.equal((await w.send(smoke)).ok,true);await acceptCurrentSmoke(w);
  w.memberships([{scope:root,job_id:'legacy-video',state:'retrying'}]);const next={...resumedRoot,id:'next-video',prompt:'YÊU CẦU STUDIO next-video\nnew video request'};
  assert.equal((await w.send(next)).ok,true);const slot=(await w.send({kind:'snapshot'})).sessions[0];assert.equal(slot.job.id,next.id);assert.equal(slot.job.attempt,1);assert.equal(slot.is_smoke,false);assert.notEqual(slot.job.is_smoke,true);assert.equal(slot.job_id,'legacy-video');assert.equal(slot.retained.find(item=>item.job?.id==='same').job.attempt,1);assert.equal(w.created.length,3);
});

test('retained promotion rejects terminal membership and immutable request changes',async()=>{
  for(const variant of ['failed','foreign-job','version','prompt']){
    const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);await w.send(smoke);await acceptCurrentSmoke(w);
    w.memberships([{scope:root,job_id:'legacy-video',state:variant==='failed'?'failed':'running'}]);const request={...resumedRoot};if(variant==='foreign-job')request.job_id='foreign-video';if(variant==='version')request.version=2;if(variant==='prompt')request.prompt+='changed';
    assert.equal((await w.send(request)).ok,false,variant);const slot=(await w.send({kind:'snapshot'})).sessions[0];assert.equal(slot.job,null);assert.equal(slot.is_smoke,true);assert.equal(slot.retained.find(item=>item.job?.id==='same').job.attempt,1);assert.equal(w.created.length,2);
  }
});

test('dismissing a retained legacy video preserves the current pending connection test',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const oldTab=w.created[0].id;
  w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);await w.send(smoke);
  w.dismissed({scope:root,job_id:'legacy-video',state:'failed',dismissed:true});w.memberships([]);
  assert.equal((await w.send({kind:'dismiss_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.active,true);assert.equal(snapshot.job.id,'smoke');assert.equal(snapshot.sessions[0].retained.length,0);assert.deepEqual(w.closed,[oldTab]);
  assert.equal((await w.send({kind:'sent',id:'smoke',attempt:1},w.chat(w.created[1].id))).ok,true);
});

test('dismissing a legacy root video keeps the master connection and retained smoke receipt',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);const oldTab=w.created[0].id;
  w.memberships([{scope:root,job_id:'legacy-video',state:'failed'}]);w.pending([smokePending]);await w.send(smoke);await acceptCurrentSmoke(w);
  w.memberships([{scope:root,job_id:'legacy-video',state:'running'}]);await w.send(resumedRoot);
  w.dismissed({scope:root,job_id:'legacy-video',state:'failed',dismissed:true});
  assert.equal((await w.send({kind:'dismiss_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.active,true);assert.equal(snapshot.job,null);assert.equal(snapshot.sessions[0].is_smoke,true);assert.equal(snapshot.sessions[0].lastReceipt.id,'smoke');assert.ok(w.closed.includes(oldTab));
});

test('dismissing a root video without a control slot removes only its local session',async()=>{
  const w=worker();await w.send({kind:'start',scope:root});await w.claim(root);
  w.dismissed({scope:root,job_id:'legacy-video',state:'cancelled',dismissed:true});
  assert.equal((await w.send({kind:'dismiss_session',scope:root,job_id:'legacy-video'})).ok,true);
  const snapshot=await w.send({kind:'snapshot'});assert.equal(snapshot.active,true);assert.equal(snapshot.sessions.length,0);assert.equal(snapshot.job,null);
  assert.equal((await w.send({kind:'connection'})).active,true);
});

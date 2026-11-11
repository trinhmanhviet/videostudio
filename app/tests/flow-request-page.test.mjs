import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {runFlowRpc,readFlowReceipt,flowSessionInfo,forgetFlowVerification} from '../extensions/videostudio-chatgpt/flow/page.mjs';

const project='11111111-1111-4111-8111-111111111111';
const generationContext=[null,22,null,null,null,project,null,null,null,null,[]];
const generation=Array(14).fill(null);generation[7]=generationContext;
const command={id:'22222222-2222-4222-8222-222222222222',operation:'generate_image',rpcid:'ogiZ0b',source_path:'/project/'+project,payload:[null,[generation],1,generationContext,['batch-fixture']]};
function fixture(fetcher=async()=>new Response('fixture response',{status:200})){
  const storage=new Map();const calls=[],timeouts=[],verifications=[];
  const context=vm.createContext({location:{origin:'https://flow.google.com',pathname:'/project/'+project},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    URLSearchParams,AbortSignal:{timeout:milliseconds=>{timeouts.push(milliseconds);return AbortSignal.timeout(milliseconds);}},TextDecoder,command,setTimeout,clearTimeout,navigator:{userAgent:'fixture-browser'},
    grecaptcha:{enterprise:{ready:callback=>callback(),execute:async(...args)=>{verifications.push(args);return 'fixture-proof-'.repeat(10);}}}});
  context[Symbol.for('videostudio.flow.session.v1')]={at:'fixture-csrf',sid:'fixture-session',build:'fixture-build',language:'vi',verificationSiteKey:'fixture-public-site-key',
    nativeFetch:async(...args)=>{calls.push(args);return fetcher(...args);}};
  const invoke=fn=>vm.runInContext(`(${fn.toString()})(command)`,context);
  return {context,storage,calls,timeouts,verifications,invoke};
}
test('generation is sent once even when the caller repeats before its response',async()=>{
  let finish;const wait=new Promise(resolve=>{finish=resolve;});
  const f=fixture(async()=>{await wait;return new Response('fixture response');});
  const first=f.invoke(runFlowRpc),second=f.invoke(runFlowRpc);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.calls.length,1);assert.equal(f.storage.size,1);
  finish();assert.equal((await first).http_status,200);assert.equal((await second).http_status,200);
  assert.equal(f.calls[0][1].credentials,'include');
  assert.equal(f.calls[0][1].headers['x-browser-validation'],undefined);
  assert.equal(new URLSearchParams(f.calls[0][1].body).get('at'),'fixture-csrf');
  assert.equal(f.timeouts[0],90000); // real HAR generation responses take 20-26 seconds
  assert.equal(f.verifications.length,1);
  assert.equal(f.verifications[0][1].action,'IMAGE_GENERATION');
  const rpc=JSON.parse(JSON.parse(new URLSearchParams(f.calls[0][1].body).get('f.req'))[0][0][1]);
  assert.equal(rpc[1][0][7][10][0],'fixture-proof-'.repeat(10));
  assert.deepEqual(rpc[1][0][7][10],rpc[3][10]);
  assert.ok(![...f.storage.values()].join('').includes('fixture-proof-'));
  assert.equal(command.payload[3][10].length,0);
});
test('missing page verification SDK never sends an incomplete generation request',async()=>{
  const f=fixture();delete f.context.grecaptcha;
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'verification_unavailable');assert.equal(f.calls.length,0);
});
test('page verification rejection is respected without a generation request or a second verification call',async()=>{
  const f=fixture();let attempts=0;f.context.grecaptcha.enterprise.execute=async()=>{attempts++;throw Error('rejected');};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'verification_failed');
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'verification_failed');
  assert.equal(f.calls.length,0);assert.equal(attempts,1);
});
test('guarded SDK is reported before acquiring proof or sending generation',async()=>{
  const f=fixture();
  f.context.grecaptcha.enterprise.execute=function(){throw Error('extension_hijack_detected');};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'verification_guarded');
  assert.equal(f.calls.length,0);assert.equal(f.verifications.length,0);
});
test('project requests do not acquire generation verification tokens',async()=>{
  const f=fixture();f.context.command={...command,operation:'create_project',rpcid:'jHPbke',source_path:'/',payload:['projects/*',[null,['Fixture']],[null,22]]};
  assert.equal((await f.invoke(runFlowRpc)).http_status,200);assert.equal(f.verifications.length,0);
});
test('desktop handoff returns one proof in memory without fetching generation or persisting proof',async()=>{
  const f=fixture();f.context.command={...command,operation:'prepare_generation',rpcid:'__flow_verify__',payload:[],arguments:{handoff_hash:'a'.repeat(64)}};
  const result=await f.invoke(runFlowRpc);
  assert.equal(result.verification_token,'fixture-proof-'.repeat(10));
  assert.equal(result.request_id,command.id);assert.equal(f.calls.length,0);
  assert.ok(![...f.storage.values()].join('').includes(result.verification_token));
  f.context.command=command.id;f.invoke(forgetFlowVerification);
  f.context.command={...command,operation:'prepare_generation',rpcid:'__flow_verify__',payload:[],arguments:{handoff_hash:'a'.repeat(64)}};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'verification_handoff_uncertain');assert.equal(f.verifications.length,1);
});
test('reload journal prevents a second POST after an uncertain attempt',async()=>{
  const f=fixture();
  f.storage.set('videostudio.flow.request:'+command.id,JSON.stringify({attempted:true}));
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'previous_attempt');assert.equal(f.calls.length,0);
});
test('network failure stays uncertain and is not automatically resubmitted',async()=>{
  const f=fixture(async()=>{throw Error('lost connection');});
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'network_uncertain');
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'network_uncertain');assert.equal(f.calls.length,1);
});
test('changed identity with the same ID does not issue a request',async()=>{
  const f=fixture();await f.invoke(runFlowRpc);f.context.command={...command,payload:['different']};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'previous_attempt');assert.equal(f.calls.length,1);
});
test('wrong project or missing session blocks before sending',async()=>{
  const f=fixture();f.context.location.pathname='/project/33333333-3333-4333-8333-333333333333';
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'wrong_project');
  f.context[Symbol.for('videostudio.flow.session.v1')].at=null;
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'session_unavailable');assert.equal(f.calls.length,0);
});
test('cannot send outside Flow or call an arbitrary RPC',async()=>{
  const f=fixture();f.context.command={...command,rpcid:'unknown'};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'session_unavailable');
  f.context.command=command;f.context.location.origin='https://evil.invalid';
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'session_unavailable');assert.equal(f.calls.length,0);
});
test('cannot submit if the pre-send journal cannot be persisted',async()=>{
  const f=fixture();f.context.sessionStorage.setItem=()=>{throw Error('quota');};
  assert.equal((await f.invoke(runFlowRpc)).transport_error,'session_unavailable');assert.equal(f.calls.length,0);
});
test('HTTP rejection is returned intact for the correlated backend parser',async()=>{
  const f=fixture(async()=>new Response('access denied',{status:403}));
  const result=await f.invoke(runFlowRpc);assert.equal(result.http_status,403);assert.equal(result.body,'access denied');
});
test('receipt inspection never sends or creates a replacement',async()=>{
  const f=fixture();await f.invoke(runFlowRpc);
  f.context.command=command.id;
  assert.equal((await f.invoke(readFlowReceipt)).http_status,200);assert.equal(f.calls.length,1);
});
test('readiness exports booleans/build, never CSRF or session secrets',()=>{
  const f=fixture();const status=f.invoke(flowSessionInfo);
  assert.equal(status.session_ready,true);assert.equal(status.at,undefined);assert.equal(status.sid,undefined);
});
test('readiness reports a verification guard without replacing or executing the SDK',()=>{
  const f=fixture();
  const guarded=()=>{throw Error('extension_hijack_detected');};
  f.context.grecaptcha.enterprise.execute=guarded;
  assert.equal(f.invoke(flowSessionInfo).verification_guard_detected,true);
  assert.equal(f.context.grecaptcha.enterprise.execute,guarded);
  assert.equal(f.verifications.length,0);assert.equal(f.calls.length,0);
});
test('observer refreshes metadata and leaves outgoing requests unchanged',async()=>{
  const sent=[];
  class XHR {open(...args){sent.push(['open',...args]);}send(...args){sent.push(['send',...args]);}}
  const context=vm.createContext({location:{origin:'https://flow.google.com',href:'https://flow.google.com/'},XMLHttpRequest:XHR,
    URL,URLSearchParams,Request,setTimeout,fetch:async(...args)=>{sent.push(args);return 'ok';}});
  vm.runInContext(fs.readFileSync(new URL('../extensions/videostudio-chatgpt/flow/session.js',import.meta.url),'utf8'),context);
  const url='https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=UpteDb&f.sid=one&bl=build-one';
  await context.fetch(url,{body:'at=csrf-one&f.req=unchanged',method:'POST'});
  await context.fetch(url.replace('one','two'),{body:'at=csrf-two&f.req=unchanged',method:'POST'});
  const session=context[Symbol.for('videostudio.flow.session.v1')];
  assert.equal(session.at,'csrf-two');assert.equal(session.sid,'two');assert.equal(sent[0][1].body,'at=csrf-one&f.req=unchanged');
  assert.equal(session.cookie,undefined);
});

async function workerFixture({storage={},loseCallback=false,proofOnly=false}={}){
  let listener;let flowCalls=0,polls=0,callbacks=0,alarms=0;const scripts=[];
  const origin='chrome-extension://'+'a'.repeat(32);
  const stored=storage;
  const chrome={
    storage:{local:{get:async key=>({[key]:structuredClone(stored[key])}),set:async data=>Object.assign(stored,structuredClone(data)),remove:async key=>{delete stored[key];}}},
    runtime:{id:'a'.repeat(32),getURL:path=>origin+'/'+path,getManifest:()=>({version:'0.3.12'}),onMessage:{addListener:fn=>listener=fn},onInstalled:{addListener(){}},onStartup:{addListener(){}}},
    tabs:{get:async id=>({id,url:'https://flow.google.com/project/'+project})},
    permissions:{contains:async()=>true},
    scripting:{getRegisteredContentScripts:async()=>[],registerContentScripts:async values=>scripts.push(...values),executeScript:async options=>{
      if(options.files)return [];
      if(options.func.name==='flowSessionInfo')return [{result:{tab_open:true,session_ready:true,project_id:project}}];
      if(options.func.name==='runFlowRpc'){flowCalls++;return [{result:proofOnly?{request_id:command.id,verification_token:'fixture-transient-proof-'.repeat(10),user_agent:'fixture-UA'}:{http_status:200,body:'correlated fixture response'}}];}
      if(options.func.name==='forgetFlowVerification')return [{result:true}];
      throw Error('Unexpected script');
    }},
    alarms:{create:async()=>{alarms++;},clear:async()=>{},onAlarm:{addListener(){}}}
  };
  const fetcher=async(url,options)=>{
    const path=new URL(url).pathname;
    if(path.endsWith('/pair'))return Response.json({client_id:'client-fixture',key:'fixture-key'});
    if(path.endsWith('/poll')){polls++;return Response.json({command:polls===1?{...command,...(proofOnly?{operation:'prepare_generation',rpcid:'__flow_verify__',payload:[]}:{}),dispatch:'fixture-dispatch'}:null});}
    if(path.endsWith('/result')){callbacks++;return loseCallback?Response.json({detail:'temporary callback failure'},{status:503}):Response.json({state:'completed'});}
    throw Error('Unexpected URL');
  };
  const context=vm.createContext({chrome,fetch:fetcher,AbortSignal,Error,Set,console,flowSessionInfo,runFlowRpc,readFlowReceipt,forgetFlowVerification,setInterval:()=>1,clearInterval(){}});
  const source=fs.readFileSync(new URL('../extensions/videostudio-chatgpt/flow/background.mjs',import.meta.url),'utf8').replace(/^import .*?;\r?\n/,'');
  vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));
  const sender={id:chrome.runtime.id,url:origin+'/flow/popup.html'};
  const send=message=>new Promise(resolve=>listener(message,sender,resolve));
  return {stored,send,listener,counts:()=>({flowCalls,polls,callbacks,alarms}),scripts};
}
test('Flow module stays idle before opt-in and never handles ChatGPT messages',async()=>{
  const worker=await workerFixture();
  assert.deepEqual(worker.counts(),{flowCalls:0,polls:0,callbacks:0,alarms:0});
  assert.equal(worker.listener({kind:'start'},{},()=>assert.fail('must not reply')),false);
});
test('integrated worker dispatches once and keeps a lost callback for restart recovery',async()=>{
  const first=await workerFixture({loseCallback:true});
  await first.send({kind:'flow:connect',server:'http://localhost:8878',tab:10,code:'fixture-code'});
  assert.equal(first.counts().flowCalls,1);assert.equal(first.counts().callbacks,1);
  assert.ok(first.stored.videostudio_flow_pending_v1.result);
  assert.equal(first.scripts[0].js[0],'flow/session.js');
  // Restart after the app reply was lost. Recovery uploads the journal result,
  // never executes another generation. No queued server command on this run.
  const resumedStorage=structuredClone(first.stored);
  // Disabled polling on this reload also verifies that receipt delivery survives Stop.
  resumedStorage.videostudio_flow_bridge_v1.enabled=false;
  const restarted=await workerFixture({storage:resumedStorage});
  assert.equal(restarted.counts().callbacks,1);assert.equal(restarted.counts().flowCalls,0);
  assert.equal(restarted.stored.videostudio_flow_pending_v1,undefined);
});
test('worker never writes verification proof to chrome.storage even if callback fails',async()=>{
  const worker=await workerFixture({loseCallback:true,proofOnly:true});
  await worker.send({kind:'flow:connect',server:'http://localhost:8878',tab:10,code:'fixture-code'});
  assert.equal(worker.counts().flowCalls,1);assert.equal(worker.counts().callbacks,1);
  assert.equal(worker.stored.videostudio_flow_pending_v1.result,null);
  assert.ok(!JSON.stringify(worker.stored).includes('fixture-transient-proof-'));
});

import test from 'node:test';import assert from 'node:assert/strict';
import {BUILD,digest} from 'file:///D:/Projects/storyforge/extensions/chatgpt-web/protocol.js';
const project='11111111-1111-4111-8111-111111111111',run='22222222-2222-4222-8222-222222222222',id='33333333-3333-4333-8333-333333333333';
const owner={frameId:0,tab:{id:5},url:`http://localhost:3000/story-video/projects/${project}/production`};
const scope={project_id:project,run_id:run,studio_tab_id:5,studio_origin:'http://localhost:3000'};
const exchange={id,version:1,prompt:`YÊU CẦU STUDIO ${id}\nOnly JSON`,attachments:[]};
async function fixture(recover=false){
 const token=crypto.randomUUID(),known='https://chatgpt.com/c/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
 let state={storyforge_chatgpt_web_v1:{scope,enabled:true,epoch:crypto.randomUUID(),owned_tab_id:8,logs:[],job:recover?{exchange_id:id,version:1,signature:await digest(JSON.stringify([exchange.prompt,[]])),token,attempts:1,phase:'waiting',tab_id:8,recover_page:true,recovery_url:known,page_url:known,last_prompt:exchange.prompt,receipt:{marker:`STUDIO-DELIVERY ${token}`,user_count:1,user_hash:'a'.repeat(64),path:known.slice('https://chatgpt.com'.length)}}:null}};
 let listener;const created=[],commands=[],updated=[];
 globalThis.chrome={storage:{local:{get:async()=>structuredClone(state),set:async v=>{state=structuredClone(v)},setAccessLevel:async()=>{}}},runtime:{onMessage:{addListener:f=>{listener=f}},onInstalled:{addListener:()=>{}},onStartup:{addListener:()=>{}}},alarms:{create:async()=>{},onAlarm:{addListener:()=>{}}},tabs:{create:async options=>{created.push(options);return {id:9}},get:async tabId=>({id:tabId,url:tabId===5?owner.url:known}),update:async(...args)=>{updated.push(args);return {id:8,url:known}},query:async()=>[],remove:async()=>{},onUpdated:{addListener:()=>{}},onRemoved:{addListener:()=>{}},sendMessage:async(tabId,message)=>{
  if(message.kind==='storyforge_hello'){if(tabId===8)throw Error('Could not establish connection. Receiving end does not exist.');return {ready:true,build:BUILD,page_instance:crypto.randomUUID(),empty_chat:!recover}}
  if(message.kind==='storyforge_chat_command'){commands.push(message.command);return {accepted:true}}
  if(message.kind==='storyforge_authorize_current_run')return {allowed:true};return {ok:true};
 }}};
 await import('file:///D:/Projects/storyforge/extensions/chatgpt-web/background.js?reload-test='+crypto.randomUUID());
 const call=message=>new Promise(resolve=>listener({project_id:project,run_id:run,...message},owner,resolve));
 await call({kind:'storyforge_start'});await call({kind:'storyforge_generate',exchange,files:[]});
 for(let i=0;i<100&&!commands.length&&state.storyforge_chatgpt_web_v1.enabled;i++)await new Promise(r=>setTimeout(r,5));
 return {created,commands,updated,state:state.storyforge_chatgpt_web_v1,token,known};
}
test('stale listener before a new request preserves old tab and prepares exactly one owned replacement',async()=>{const f=await fixture();assert.equal(f.commands.length,1,JSON.stringify(f.state.error));assert.equal(f.created.length,1);assert.equal(f.created[0].url,'https://chatgpt.com/');assert.equal(f.updated.length,0);assert.equal(f.commands[0].kind,'generate');assert.equal(f.state.job.attempts,1);});
test('stale listener while recovering a sent request opens only known URL and never generates again',async()=>{const f=await fixture(true);assert.equal(f.commands.length,1,JSON.stringify(f.state.error));assert.equal(f.created[0].url,f.known);assert.equal(f.commands[0].kind,'recover');assert.equal(f.commands[0].token,f.token);assert.equal(f.state.job.attempts,1);assert.equal(f.updated.length,0);});

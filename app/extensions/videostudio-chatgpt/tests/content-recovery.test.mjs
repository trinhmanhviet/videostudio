import test from 'node:test';
import assert from 'node:assert/strict';
import {ensureStudioScripts,ensureChatScript} from '../content-recovery.mjs';
const scope='123e4567-e89b-42d3-a456-426614174000';
function fixture(ping=null){
 const injected=[];const tabs=[{id:1,url:'http://localhost:8877/'},{id:2,url:`http://localhost:8877/story-video/projects/${scope}/production`},{id:3,url:'https://untrusted.invalid/'},{id:4,url:'http://localhost:8877/editor.html'}];
 return {injected,chrome:{runtime:{getManifest:()=>({version:'0.3.17'})},tabs:{query:async()=>tabs,get:async id=>({id,url:id===5?'https://chatgpt.com/c/owned':'https://untrusted.invalid/'}),sendMessage:async()=>{if(!ping)throw Error('Receiving end does not exist');return ping;}},scripting:{executeScript:async request=>injected.push(request)}}};
}
test('reload recovery reinjects only canonical Studio pages and does not reload/navigate tabs',async()=>{const f=fixture();await ensureStudioScripts(f.chrome);assert.deepEqual(f.injected.map(r=>r.target.tabId),[1,2]);assert.ok(f.injected.every(r=>r.files.join(',')==='studio.js'));});
test('a live matching content build is left untouched',async()=>{const f=fixture({ok:true,version:'0.3.17'});await ensureStudioScripts(f.chrome);assert.equal(f.injected.length,0);});
test('a dead or stale content build is replaced',async()=>{const f=fixture({ok:false,version:'0.3.16'});await ensureStudioScripts(f.chrome);assert.equal(f.injected.length,2);});
test('ChatGPT recovery only reattaches scripts on an exact ChatGPT origin',async()=>{const f=fixture();assert.equal(await ensureChatScript(f.chrome,5),true);assert.equal(await ensureChatScript(f.chrome,8),false);assert.deepEqual(f.injected[0].files,['send-button.js','logical-text.js','chatgpt.js']);assert.equal(f.injected.length,1);});

test('unsupported browser APIs are a no-op and do not alter persisted sessions',async()=>{const chrome={storage:{local:{set:()=>{throw Error('No state changes permitted');}}}};await ensureStudioScripts(chrome);assert.equal(await ensureChatScript(chrome,5),false);});

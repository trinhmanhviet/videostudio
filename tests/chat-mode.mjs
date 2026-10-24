import test from 'node:test';import assert from 'node:assert/strict';
import {classifyComposerMode,ensureChatMode,assertChatMode} from 'file:///D:/Projects/storyforge/extensions/chatgpt-web/chatgpt-dom.js';
const view=()=>[{}];globalThis.getComputedStyle=()=>({visibility:'visible'});
function fixture({mode='work',text='',toggle=true,label}={}){
 let selected=mode,clicks=0;
 const input={tagName:'DIV',children:[],innerText:text,getClientRects:view,getAttribute:k=>k==='aria-label'?(label??(selected==='chat'?'Ask ChatGPT':'Work with ChatGPT')):null,querySelector:()=>null};
 const button=name=>({textContent:name,disabled:false,getClientRects:view,getAttribute:k=>k==='aria-pressed'?String(selected===name.toLowerCase()):null,click(){clicks++;selected=name.toLowerCase();}});
 const chat=button('Chat'),work=button('Work');const group={getClientRects:view,querySelectorAll:()=>[chat,work]};
 const doc={querySelectorAll:s=>s.includes('Composer mode')?(toggle?[group]:[]):[input]};
 return {doc,clicks:()=>clicks,setMode:m=>{selected=m;}};
}
test('classify only explicit Chat, never infer from model/workspace',()=>{
 assert.equal(classifyComposerMode({hasToggle:true,chatPressed:true}),'chat');assert.equal(classifyComposerMode({hasToggle:true,workPressed:true}),'work');assert.equal(classifyComposerMode({label:'GPT-6.1 Sol'}),'unknown');
});
test('new empty Work composer selects Chat after authorization',async()=>{const f=fixture();let permit=0;assert.equal((await ensureChatMode({doc:f.doc,allowSwitch:true,authorize:async()=>{permit++;}})).mode,'chat');assert.equal(f.clicks(),1);assert.equal(permit,1);});
test('Chat does not switch model/workspace',async()=>{const f=fixture({mode:'chat'});await ensureChatMode({doc:f.doc,allowSwitch:true});assert.equal(f.clicks(),0);});
test('nonempty Work draft remains untouched',async()=>{const f=fixture({text:'private draft'});await assert.rejects(ensureChatMode({doc:f.doc,allowSwitch:true}),{code:'CHATGPT_MODE_WORK'});assert.equal(f.clicks(),0);});
test('repair in Work never sends or silently migrates conversation',async()=>{const f=fixture();await assert.rejects(ensureChatMode({doc:f.doc,allowSwitch:false}),{code:'CHATGPT_MODE_WORK'});});
test('mode changing immediately before Send is rejected',()=>{const f=fixture({mode:'chat'});assertChatMode(f.doc);f.setMode('work');assert.throws(()=>assertChatMode(f.doc),{code:'CHATGPT_MODE_WORK'});});
test('unknown mode fails closed',async()=>{const f=fixture({toggle:false,label:'Unknown composer'});await assert.rejects(ensureChatMode({doc:f.doc,allowSwitch:true}),{code:'CHATGPT_MODE_UNKNOWN'});});
test('revoked authorization prevents mode switch',async()=>{const f=fixture();await assert.rejects(ensureChatMode({doc:f.doc,allowSwitch:true,authorize:async()=>{throw Error('stopped');}}));assert.equal(f.clicks(),0);});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {start,claim,beginAttempt,retryAttempt,canStart,stop,acknowledge,studioScope} from '../protocol.mjs';
const scope='123e4567-e89b-42d3-a456-426614174000';
test('one root Start is authorized and active after navigation; stop cleans ownership',()=>{
  assert.equal(studioScope('http://localhost:8877/',scope,scope),true);
  const state=start({studioTab:7,scope});assert.equal(state.active,true);
  assert.equal(canStart(state),false);
  stop(state);assert.equal(state.active,false);assert.deepEqual(state.ownedTabs,[]);
});
test('every exchange owns fresh ChatGPT tab and exact attempt binding',()=>{
  const state=start({studioTab:7,scope});
  assert.equal(claim(state,{studioTab:7,scope,id:'one',version:1,prompt:'YÊU CẦU STUDIO one\nX'}),true);
  beginAttempt(state,9);assert.equal(state.job.attempt,1);assert.equal(state.job.chatTab,9);
  state.job.phase='reply';assert.equal(acknowledge(state,{id:'one',version:1,accepted:true}),true);
  assert.equal(claim(state,{studioTab:7,scope,id:'two',version:1,prompt:'YÊU CẦU STUDIO two\nX'}),true);
  beginAttempt(state,10);assert.equal(state.job.chatTab,10);
});
test('retry is bounded to one fresh tab after exact receipt reconciliation',()=>{
  const state=start({studioTab:7,scope});claim(state,{studioTab:7,scope,id:'one',version:1,prompt:'YÊU CẦU STUDIO one\nX'});beginAttempt(state,9);
  assert.equal(retryAttempt(state,{id:'other',version:1,accepted:false,visibleUser:null},10),false);
  assert.equal(retryAttempt(state,{id:'one',version:1,accepted:true,visibleUser:null},10),false);
  assert.equal(retryAttempt(state,{id:'one',version:1,accepted:false,visibleUser:'YÊU CẦU STUDIO one\nX',visibleReply:'done'},10),false);
  assert.equal(retryAttempt(state,{id:'one',version:1,accepted:false,visibleUser:null},10),true);
  assert.equal(state.job.attempt,2);assert.equal(state.job.chatTab,10);
  assert.equal(retryAttempt(state,{id:'one',version:1,accepted:false,visibleUser:null},11),false);
});
test('actual Studio runtime guards invalidated send and retires intervals/listener',async()=>{
  const code=await readFile(new URL('../studio.js',import.meta.url),'utf8');
  const timers=new Map();let next=0,removed=0;const listeners=[];
  const domListeners=new Set();
  const button=()=>({style:{},dataset:{},textContent:'',setAttribute(){},addEventListener(type,fn){domListeners.add(fn)},removeEventListener(type,fn){domListeners.delete(fn)}});
  const nodes=new Map(['status','start','smoke','stop','manager','manager-content','collapse','badge','count','error-badge','empty','sessions','dismiss-dialog','dismiss-video','dismiss-files','dismiss-warning','dismiss-error','dismiss-confirm','dismiss-cancel'].map(key=>['#'+key,button()]));
  const shadow={innerHTML:'',querySelector:key=>nodes.get(key)};
  const root={style:{},dataset:{},attachShadow:()=>shadow,remove(){removed++}};
  const document={...button(),createElement:()=>root,documentElement:{append(){}}};
  const context={location:{origin:'http://localhost:8877',pathname:`/story-video/projects/${scope}/production`},document,chrome:{runtime:{sendMessage:async()=>{throw Error('Extension context invalidated')},onMessage:{addListener:fn=>listeners.push(fn),removeListener:fn=>{listeners.splice(listeners.indexOf(fn),1)}}}},setInterval:fn=>{timers.set(++next,fn);return next},clearInterval:id=>timers.delete(id),fetch:async()=>({ok:true,json:async()=>({})}),localStorage:{getItem:()=>null},console};
  vm.runInNewContext(code,context);
  await new Promise(resolve=>setImmediate(resolve));
  for(const timer of [...timers.values()])await timer();
  assert.equal(timers.size,0);assert.equal(listeners.length,0);assert.equal(domListeners.size,0);
  assert.equal(nodes.get('#start').disabled,true);assert.match(nodes.get('#status').textContent,/Tải lại trang Studio/);
});

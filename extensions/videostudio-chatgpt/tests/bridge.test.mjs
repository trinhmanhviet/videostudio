import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {start,claim,beginAttempt,result,canStart,canDiscard,acknowledge,receiptPath,studioScope,archivePrevious} from '../protocol.mjs';
const scope='123e4567-e89b-42d3-a456-426614174000',prompt='YÊU CẦU STUDIO req\nhello';
test('Studio scope accepts exact localhost root/production only',()=>{
  assert.equal(studioScope('http://localhost:8877/',scope,scope),true);
  assert.equal(studioScope(`http://localhost:8877/story-video/projects/${scope}/production`,scope,scope),true);
  for(const url of [`http://127.0.0.1:8877/story-video/projects/${scope}/production`,`http://localhost:8878/story-video/projects/${scope}/production`,`http://localhost:8877/story-video/projects/${scope}/production/extra`])assert.equal(studioScope(url,scope,scope),false);
  assert.equal(studioScope('http://localhost:8877/',scope,'other'),false);
});
test('ownership and immutable request correlation reject unrelated tabs and mismatched responses',()=>{
  const state=start({studioTab:7,scope});
  assert.equal(claim(state,{studioTab:8,scope,id:'req',version:1,prompt}),false);
  assert.equal(claim(state,{studioTab:7,scope,id:'req',version:1,prompt}),true);
  assert.equal(claim(state,{studioTab:7,scope,id:'req',version:1,prompt:'changed'}),false);
  beginAttempt(state,9);state.job.phase='sent';
  assert.equal(result(state,{chatTab:10,id:'req',text:'{}'}),false);
  assert.equal(result(state,{chatTab:9,id:'other',text:'{}'}),false);
  assert.equal(result(state,{chatTab:9,id:'req',text:'{}'}),true);
  assert.equal(result(state,{chatTab:9,id:'req',text:'{}'}),false);
});
test('unresolved dispatch cannot be silently replaced',()=>{
  const state=start({studioTab:7,scope});claim(state,{studioTab:7,scope,id:'req',version:1,prompt});beginAttempt(state,9);
  assert.equal(canStart({...state,active:false}),false);
  assert.equal(canStart({...state,active:false,job:{...state.job,phase:'reply'}}),false);
  assert.equal(canStart({...state,active:false,job:null}),true);
});
test('only exact accepted receipt clears job',()=>{
  const state=start({studioTab:7,scope});claim(state,{studioTab:7,scope,id:'req',version:1,prompt});beginAttempt(state,9);state.job.phase='sent';result(state,{chatTab:9,id:'req',text:'{}'});
  assert.equal(acknowledge(state,{id:'other',version:1,accepted:true}),false);
  assert.equal(acknowledge(state,{id:'req',version:2,accepted:true}),false);
  assert.equal(acknowledge(state,{id:'req',version:1,accepted:true}),true);
  assert.equal(state.job,null);
});
test('manual discard guard remains restricted, not exposed in UI',()=>{
  const state={...start({studioTab:7,scope}),active:false,job:{id:'req',version:1,phase:'uncertain'}};
  assert.equal(canDiscard(state,{studioTab:7,scope}),true);
  assert.equal(canDiscard({...state,active:true},{studioTab:7,scope}),false);
  assert.equal(canDiscard(state,{studioTab:8,scope}),false);
});
test('one-click new session archives old pending request without resubmitting it',()=>{
  const old=start({studioTab:7,scope});claim(old,{studioTab:7,scope,id:'req',version:1,prompt});beginAttempt(old,9);
  const archived=archivePrevious(old);
  assert.deepEqual(archived,{scope,id:'req',version:1,attempt:1,phase:'dispatching'});
  assert.equal(old.active,false);
  assert.equal(old.job.attempt,1);
});
test('receipt URL encodes exact request and scope',()=>assert.equal(receiptPath(scope,'req'),`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges/req`));
test('manifest has narrow hosts and no automation or cookie permissions',async()=>{
  const manifest=JSON.parse(await readFile(new URL('../manifest.json',import.meta.url)));
  assert.deepEqual(manifest.host_permissions,['http://localhost:8877/*','https://chatgpt.com/*']);
  assert.deepEqual(manifest.permissions,['storage']);
  assert.deepEqual(manifest.content_scripts[1].js,['send-button.js','logical-text.js','chatgpt.js']);
});

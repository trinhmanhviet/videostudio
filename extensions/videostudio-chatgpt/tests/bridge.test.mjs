import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {start, claim, result, canStart, acknowledge, receiptPath, studioScope} from '../protocol.mjs';

const scope='123e4567-e89b-42d3-a456-426614174000';
test('Studio scope accepts only exact localhost production route and matching IDs',()=>{
  assert.equal(studioScope(`http://localhost:8877/story-video/projects/${scope}/production`,scope,scope),true);
  for(const url of [`http://127.0.0.1:8877/story-video/projects/${scope}/production`,`http://localhost:8878/story-video/projects/${scope}/production`,`http://localhost:8877/story-video/projects/${scope}/production/extra`])assert.equal(studioScope(url,scope,scope),false);
  assert.equal(studioScope(`http://localhost:8877/story-video/projects/${scope}/production`,scope,'other'),false);
});
test('ownership and immutable request correlation reject unrelated tabs and mismatched responses',()=>{
  const state=start({studioTab:7,chatTab:9,scope});
  assert.equal(claim(state,{studioTab:8,chatTab:9,scope,id:'req',version:1,prompt:'hello'}),false);
  assert.equal(claim(state,{studioTab:7,chatTab:9,scope,id:'req',version:1,prompt:'hello'}),true);
  assert.equal(claim(state,{studioTab:7,chatTab:9,scope,id:'req',version:1,prompt:'changed'}),false);
  state.job.phase='sent'; // Only a verified exact visible user turn permits a reply.
  assert.equal(result(state,{chatTab:10,id:'req',text:'{}'}),false);
  assert.equal(result(state,{chatTab:9,id:'other',text:'{}'}),false);
  assert.equal(result(state,{chatTab:9,id:'req',text:'{}'}),true);
  assert.equal(result(state,{chatTab:9,id:'req',text:'{}'}),false);
});
test('restarting after an unresolved dispatch must not erase the durable request',()=>{
  const state=start({studioTab:7,chatTab:9,scope});
  assert.equal(claim(state,{studioTab:7,chatTab:9,scope,id:'req',version:1,prompt:'YÊU CẦU STUDIO req\nhello'}),true);
  state.job.phase='dispatching';
  // A Stop/Start may not reset this durable state: it would resend the same pending exchange.
  assert.equal(canStart({...state,active:false}),false);
  assert.equal(canStart({...state,active:false,job:{...state.job,phase:'reply'}}),false);
  assert.equal(canStart({...state,active:false,job:null}),true);
});
test('only an exact accepted receipt clears the job for the next text exchange',()=>{
  const state=start({studioTab:7,chatTab:9,scope});
  claim(state,{studioTab:7,chatTab:9,scope,id:'req',version:1,prompt:'hello'});
  state.job.phase='sent';result(state,{chatTab:9,id:'req',text:'{}'});
  assert.equal(acknowledge(state,{id:'other',version:1,accepted:true}),false);
  assert.equal(acknowledge(state,{id:'req',version:2,accepted:true}),false);
  assert.equal(state.job.phase,'reply');
  assert.equal(acknowledge(state,{id:'req',version:1,accepted:true}),true);
  assert.equal(state.job,null);
});
test('receipt URL encodes exact request and scope',()=>{
  assert.equal(receiptPath(scope,'req'),`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges/req`);
});
test('manifest has narrow hosts and no automation or cookie permissions',async()=>{
  const manifest=JSON.parse(await readFile(new URL('../manifest.json',import.meta.url)));
  assert.deepEqual(manifest.host_permissions,['http://localhost:8877/*','https://chatgpt.com/*']);
  assert.deepEqual(manifest.permissions,['storage']);
  assert.equal(manifest.content_scripts.length,2);
  assert.deepEqual(manifest.content_scripts[0].matches,['http://localhost:8877/*']);
});

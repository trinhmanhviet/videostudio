import test from 'node:test';
import assert from 'node:assert/strict';
import { start, claim, beginAttempt } from '../protocol.mjs';

const oldScope='123e4567-e89b-42d3-a456-426614174000';
const newScope='123e4567-e89b-42d3-a456-426614174001';
const old=start({studioTab:7,scope:oldScope});
claim(old,{studioTab:7,scope:oldScope,id:'request-old',version:1,prompt:'YÊU CẦU STUDIO request-old\nhello'});
beginAttempt(old,9);
const values=new Map([['videostudio_bridge_v2',old]]), removed=[];
let listener;
globalThis.chrome={
  storage:{local:{get:async key=>({[key]:values.get(key)}),set:async data=>{for(const [k,v] of Object.entries(data))values.set(k,v);}}},
  tabs:{remove:async id=>{removed.push(id);},create:async()=>{throw Error('unexpected ChatGPT send')},get:async()=>{throw Error('unexpected inspect')}},
  runtime:{onMessage:{addListener:fn=>{listener=fn;}}},
};
globalThis.fetch=async()=>{throw Error('unexpected server call/retry of old exchange')};
await import('../background.js?lifecycle-test');
const sender={frameId:0,tab:{id:7},url:'http://localhost:8877/'};
const send=message=>new Promise(resolve=>listener(message,sender,resolve));

test('one Start from root archives an old unresolved attempt without retrying it',async()=>{
  const response=await send({kind:'start',scope:newScope});
  assert.equal(response.ok,true);
  assert.equal(values.get('videostudio_bridge_v2').scope,newScope);
  assert.deepEqual(removed,[9]);
  assert.equal(values.get('videostudio_bridge_last_abandoned').id,'request-old');
});

test('one Stop fully disables the owner bridge without affecting other tabs',async()=>{
  const response=await send({kind:'stop'});
  assert.equal(response.ok,true);
  const state=values.get('videostudio_bridge_v2');
  assert.equal(state.active,false);
  assert.deepEqual(state.ownedTabs,[]);
  assert.deepEqual(removed,[9]);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const context={};
runInNewContext(await readFile(new URL('../send-button.js',import.meta.url),'utf8'),context);
const {confirmSend}=context.VideoStudioSendButton;

async function scenario(change=()=>{},acceptAt=Infinity){
  let ticks=0,clicks=1,owned=true,received=false;
  const result=await confirmSend({
    received:()=>received,
    canRetry:()=>owned,
    click:()=>{clicks++;if(clicks===acceptAt)received=true;},
    wait:async()=>{ticks++;change({ticks,loseOwnership:()=>{owned=false;},restoreOwnership:()=>{owned=true;},receipt:()=>{received=true;}});},
  });
  return {result,clicks,ticks};
}

test('a no-op first Send is automatically clicked again in the same composer',async()=>{
  const result=await scenario(()=>{},2);
  assert.equal(result.result,true);assert.equal(result.clicks,2);
});
test('a delayed receipt never causes a second Send',async()=>{
  const result=await scenario(s=>{if(s.ticks===8)s.receipt();});
  assert.equal(result.result,true);assert.equal(result.clicks,1);
});
for(const evidence of ['composer cleared','generation started','foreign user turn','draft replaced']){
  test(`${evidence} permanently suppresses retries even if the composer later returns`,async()=>{
    const result=await scenario(s=>{if(s.ticks===3)s.loseOwnership();if(s.ticks===5)s.restoreOwnership();});
    assert.equal(result.result,false);assert.equal(result.clicks,1);
  });
}
test('an unresponsive Send has a bounded budget of three clicks',async()=>{
  const result=await scenario();
  assert.equal(result.result,false);assert.equal(result.clicks,3);assert.equal(result.ticks,80);
});

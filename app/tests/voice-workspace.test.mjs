import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/voice-workspace.js',import.meta.url),'utf8');
const ctx=vm.createContext({crypto:{randomUUID:()=> 'one-id'}});vm.runInContext(source,ctx);
const ui=ctx.VoiceWorkspace;
const plain=x=>JSON.parse(JSON.stringify(x));
test('library filters real catalog, accents, favorites and private without changing protected voices',()=>{
 const rows=[{id:'a',name:'Vương Bờm',kind:'clone'},{id:'b',name:'manhviet',kind:'clone'},{id:'c',name:'Thiện Minh',kind:'preset'}];
 assert.deepEqual(plain(ui.filterVoices(rows,'vuong bom','all',[])).map(x=>x.id),['a']);
 assert.equal(ui.filterVoices(rows,'','private',[]).length,2);
 assert.deepEqual(plain(ui.filterVoices(rows,'','favorites',['c'])).map(x=>x.id),['c']);
 assert.equal(rows.length,3);
});
test('audio requests include only effective controls and preserve full TXT',()=>{
 const a=plain(ui.buildRequest({text:'  Một\n\nHai ',voice_id:'v',speech_engine:'vieneu',khanh_steps:16,speech_speed:1.2,speech_rhythm:'story',speech_reference_id:'ref'}));
 assert.equal(a.text,'Một\n\nHai');assert.equal(a.speech_rhythm,'story');assert.equal(a.speech_speed,1.2);assert.equal(a.khanh_steps,undefined);
 assert.equal(ui.buildRequest({...a,speech_engine:'khanhtts',khanh_steps:16}).khanh_steps,16);
 assert.throws(()=>ui.buildRequest({...a,speech_speed:3}));
 assert.throws(()=>ui.buildRequest({...a,text:''}));
});
test('network ambiguity retains same durable submission key, edited payload gets a new key',()=>{
 const body={text:'a',voice_id:'v'};const first=ui.pendingRequest(body,null,()=> 'first');
 assert.equal(ui.pendingRequest(body,first,()=> 'wrong').key,'first');
 assert.equal(ui.pendingRequest({...body,text:'b'},first,()=> 'second').key,'second');
});
test('reuse copies effective audio settings and restores text without history metadata',()=>{
 const a=ui.reuseSettings({id:'x',title:'name',request:{text:'full',voice_id:'clone',speech_engine:'khanhtts',khanh_steps:16,speech_rhythm:'story',speech_speed:.8,speech_reference_id:'r'}});
 assert.equal(a.text,'full');assert.equal(a.speech_reference_id,'r');assert.equal(a.id,undefined);
});
test('page slices clamp on empty and after a filter changes',()=>{
 assert.deepEqual(plain(ui.pageItems([],9,8)),{items:[],page:1,pages:1,total:0});
 assert.equal(ui.pageItems(Array.from({length:9},(_,i)=>i),9,8).page,2);
});

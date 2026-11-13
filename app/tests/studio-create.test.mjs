import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({console, crypto: {randomUUID: (() => {let n=0;return () => `key-${++n}`;})()}});
const path = new URL('../static/studio-create.js', import.meta.url);
if (fs.existsSync(path)) vm.runInContext(fs.readFileSync(path, 'utf8'), context);
const api = context.StudioCreate || {};
const estimate = text => text.trim() ? text.trim().split(/\s+/).length * 12 : 0;
const plain = value => JSON.parse(JSON.stringify(value));

test('automatic minutes are visible and follow text and voice until explicitly edited', () => {
  assert.equal(typeof api.createRow, 'function');
  const row = api.createRow({voice:'voice-a'}, {text:'one two'}, estimate);
  assert.equal(row.duration_mode, 'auto');
  assert.equal(row.unit, '60');
  assert.equal(Number(row.seconds), .4);
  row.text = 'one two three';
  api.syncDuration(row, estimate);
  assert.equal(Number(row.seconds), .6);
  api.setMinutes(row, '.6');
  row.text = 'one';
  api.syncDuration(row, estimate);
  assert.equal(row.duration_mode, 'manual');
  assert.equal(Number(row.seconds), .6);
  api.resetDuration(row, estimate);
  assert.equal(row.duration_mode, 'auto');
  assert.equal(Number(row.seconds), .2);
});

test('a direct empty or nonpositive duration stays manual and is rejected', () => {
  assert.equal(typeof api.validateRow, 'function');
  const row = api.createRow({voice:'v'}, {text:'hello'}, estimate);
  for (const value of ['', '0', '-1', 'NaN']) {
    api.setMinutes(row, value);
    api.syncDuration(row, estimate);
    assert.equal(row.duration_mode, 'manual');
    assert.match(api.validateRow(row), /phút/);
  }
});

test('new rows inherit every chosen setting without copying source text or submission state', () => {
  assert.equal(typeof api.settingsOf, 'function');
  const previous = {key:'old',text:'old text',title:'old title',style:'meme',input:'script',voice:'v',image_provider:'meta',speech_engine:'khanhtts',speech_batch_size:321,khanh_steps:32,speech_speed:1.2,speech_rhythm:'story',duration_mode:'manual',seconds:3,unit:'60',flow_batch_size:4,meta_batch_size:7,quality_mode:'quality',uncertain:true,error:'unknown',submitted_duration_seconds:180};
  const row = api.createRow(api.settingsOf(previous), {}, estimate);
  for (const key of ['style','input','voice','image_provider','speech_engine','speech_batch_size','khanh_steps','speech_speed','speech_rhythm','seconds','unit','flow_batch_size','meta_batch_size','quality_mode']) assert.equal(row[key],previous[key],key);
  assert.equal(row.text,'');assert.equal(row.title,'');assert.equal(row.uncertain,false);
  assert.equal(row.submitted_duration_seconds,undefined);assert.notEqual(row.key,'old');
});

test('draft round trip restores text, order, selection, overrides and uncertain retry identity', () => {
  assert.equal(typeof api.serializeDraft, 'function');
  const rows = [api.createRow({voice:'a'}, {text:'first'}, estimate), api.createRow({voice:'b'}, {text:'second'}, estimate)];
  rows[1].uncertain=true;rows[1].submitted_duration_seconds=24;rows[1].error='Connection lost';
  api.setMinutes(rows[0],2.5);
  const snapshot = {rows:rows.reverse(),common:api.settingsOf(rows[1]),selectedKeys:[rows[0].key],activeKey:rows[1].key};
  const restored=api.restoreDraft(api.serializeDraft(snapshot));
  assert.deepEqual(plain(restored.rows),plain(snapshot.rows));
  assert.deepEqual(plain(restored.selectedKeys),snapshot.selectedKeys);
  assert.equal(restored.activeKey,snapshot.activeKey);
  assert.equal(api.restoreDraft('{broken'),null);
});

test('editing a row renews its request identity, while uncertain submissions remain frozen', () => {
  assert.equal(typeof api.editRow, 'function');
  const row=api.createRow({voice:'a'}, {text:'hello'}, estimate);
  const key=row.key;
  assert.equal(api.editRow(row,{text:'changed'},estimate),true);
  assert.notEqual(row.key,key);
  row.uncertain=true;row.submitted_duration_seconds=99;
  const uncertainKey=row.key;
  assert.equal(api.editRow(row,{text:'different',seconds:5},estimate),false);
  assert.equal(row.key,uncertainKey);assert.equal(row.text,'changed');assert.equal(row.submitted_duration_seconds,99);
});

test('apply to selected and reorder retain unselected overrides and uncertain payloads', () => {
  assert.equal(typeof api.applySettings, 'function');
  const rows=[api.createRow({voice:'a'}, {text:'first'},estimate),api.createRow({voice:'b'}, {text:'second'},estimate),api.createRow({voice:'c'}, {text:'third',uncertain:true},estimate)];
  const result=api.applySettings(rows,new Set([rows[0].key,rows[2].key]),{voice:'new',speech_engine:'khanhtts',duration_mode:'manual',seconds:2,unit:'60'},estimate);
  assert.equal(rows[0].voice,'new');assert.equal(rows[0].seconds,2);
  assert.equal(rows[1].voice,'b');assert.equal(rows[2].voice,'c');
  assert.equal(result.changed,1);assert.equal(result.skipped,1);
  const key=rows[0].key;
  api.moveRow(rows,0,2);
  assert.equal(rows[2].key,key);
});

// Small DOM boundary: tests exercise mounted controls without starting a browser or AI.
class Element {
  constructor(tag, document) {this.tagName=tag.toUpperCase();this.ownerDocument=document;this.children=[];this.attributes={};this.dataset={};this.value='';this.textContent='';this.className='';this.classList={add:()=>{},remove:()=>{},toggle:()=>{}};}
  append(...nodes) {for(const node of nodes){if(node.parentNode)node.parentNode.children=node.parentNode.children.filter(child=>child!==node);node.parentNode=this;this.children.push(node);}}
  replaceChildren(...nodes) {this.children=[];this.append(...nodes);}
  setAttribute(name,value) {this.attributes[name]=String(value);}
  getAttribute(name) {return this.attributes[name];}
  get lastChild() {return this.children.at(-1);}
  focus() {this.ownerDocument.activeElement=this;}
  contains(target) {return this===target || this.children.some(child=>child.contains(target));}
}
function fixture(options={}) {
  const document={activeElement:null,createElement(tag){return new Element(tag,this);}};
  const root=document.createElement('main');const data=new Map();
  const storage={getItem:key=>data.get(key)||null,setItem:(key,value)=>data.set(key,value)};
  const state=options.state || {batchRows:[]};
  const controller=api.mount(root,{state,storage,estimateNarrationSeconds:estimate,...options});
  const descendants=node=>[node,...node.children.flatMap(descendants)];
  const find=predicate=>descendants(root).find(predicate);
  return {controller,state,storage,root,find,document};
}

test('loading voices fills empty selections and refresh preserves the focused editor', () => {
  let voices=[];
  const {state,controller,find,document}=fixture({voiceOptions:()=>voices});
  const textarea=find(node=>node.tagName==='TEXTAREA');
  textarea.focus();textarea.value='one two';textarea.oninput();
  voices=[['voice-a','Voice A']];controller.refresh();
  assert.equal(state.batchRows[0].voice,'voice-a');
  assert.equal(controller.common.voice,'voice-a');
  assert.equal(document.activeElement,textarea);
  assert.equal(textarea.value,'one two');
  const minute=find(node=>node.attributes['aria-label']==='Độ dài (phút) — mục đang sửa');
  minute.value=String(state.batchRows[0].seconds);minute.oninput();
  textarea.value='one two three';textarea.oninput();
  assert.equal(state.batchRows[0].duration_mode,'manual');
  assert.equal(Number(state.batchRows[0].seconds),.4);
});

test('mounted editor autosaves the entire draft and keeps the previous settings for a new row', () => {
  const {state,controller,find,storage}=fixture({voiceOptions:()=>[['a','Voice A']]});
  const textarea=find(node=>node.tagName==='TEXTAREA');textarea.value='kept after reload';textarea.oninput();
  const engine=find(node=>node.attributes['aria-label']==='Bộ đọc — mục đang sửa');engine.value='khanhtts';engine.onchange();
  const snapshot=api.restoreDraft(storage.getItem(api.DRAFT_KEY));
  assert.equal(snapshot.rows[0].text,'kept after reload');assert.equal(snapshot.rows[0].speech_engine,'khanhtts');
  const newRow=controller.addRow();assert.equal(newRow.speech_engine,'khanhtts');assert.equal(newRow.text,'');
  assert.equal(state.batchRows.length,2);
});

test('common controls immediately configure a single video and its minute override survives typing',()=>{
  const {state,find}=fixture({voiceOptions:()=>[['a','Voice A']]});
  const engine=find(node=>node.attributes['aria-label']==='Bộ đọc — thiết lập chung');
  engine.value='khanhtts';engine.onchange();
  assert.equal(state.batchRows[0].speech_engine,'khanhtts');
  const minutes=find(node=>node.attributes['aria-label']==='Độ dài (phút) — thiết lập chung');
  minutes.value='3.5';minutes.oninput();
  const textarea=find(node=>node.tagName==='TEXTAREA');textarea.value='A longer script';textarea.oninput();
  assert.equal(state.batchRows[0].duration_mode,'manual');
  assert.equal(Number(state.batchRows[0].seconds),3.5);
  assert.equal(state.batchRows[0].speech_engine,'khanhtts');
});

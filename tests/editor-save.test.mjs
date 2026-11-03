import test from 'node:test';
import assert from 'node:assert/strict';
import {EditingWorkspace} from '../static/editor.js';
import {PlanHistory} from '../static/editor-model.mjs';

test('editing while save is in flight keeps newer draft and advances the server revision',async()=>{
  const buttons=new Map();globalThis.document={querySelector:selector=>{if(!buttons.has(selector))buttons.set(selector,{});return buttons.get(selector);}};
  const editor=Object.create(EditingWorkspace.prototype),plan={revision:0,clips:[{id:'title',text:'First title'}]};
  Object.assign(editor,{history:new PlanHistory(plan),view:{editable:true},revision:0,dirty:true,jobId:'fixture',toast(){},updateSaveState(){}});
  editor.applyView=function(view){this.view=view;this.revision=view.revision;};
  let finish;editor.api=()=>new Promise(resolve=>finish=resolve);
  const saving=editor.save();editor.history.push({...plan,clips:[{id:'title',text:'New typing while saving'}]});
  finish({revision:1,editable:true,plan:{...plan,revision:1}});await saving;
  assert.equal(editor.history.current.clips[0].text,'New typing while saving');
  assert.equal(editor.revision,1);assert.equal(editor.dirty,true);
  delete globalThis.document;
});

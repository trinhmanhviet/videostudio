import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../videostudio/gemini_new_chat.js', import.meta.url), 'utf8');
function element({tag='A', label='', text='', testid=null, covered=false}) {
  return {
    tagName:tag, innerText:text, clicks:0,
    getAttribute(name){return name==='aria-label'?label:name==='data-test-id'?testid:null;},
    getBoundingClientRect(){return {x:10,y:20,width:120,height:32};},
    contains(node){return node===this;},
    click(){this.clicks++;}, covered,
  };
}
function execute(candidates, pointTarget=null) {
  const doc={
    querySelectorAll(){return candidates;},
    elementFromPoint(){return pointTarget??candidates.find(x=>x.text.startsWith('Cuộc'))??null;},
  };
  return runInNewContext(source,{document:doc});
}

test('chooses the sidebar New Chat, not the Gemini logo sharing its aria-label',()=>{
  const logo=element({label:'Cuộc trò chuyện mới',text:'Gemini',testid:'side-nav-sparkle-button'});
  const sidebar=element({label:'Cuộc trò chuyện mới',text:'Cuộc trò chuyện mới\nCtrl+Shift+O'});
  const result=execute([logo,sidebar],sidebar);
  assert.equal(result,true);
  assert.equal(sidebar.clicks,1);
  assert.equal(logo.clicks,0);
});

test('fails closed when the sidebar control is missing or covered',()=>{
  const logo=element({label:'Cuộc trò chuyện mới',text:'Gemini'});
  assert.equal(execute([logo],logo),false);
  const sidebar=element({label:'Cuộc trò chuyện mới',text:'Cuộc trò chuyện mới\nCtrl+Shift+O'});
  const overlay=element({tag:'DIV',text:'overlay'});
  assert.equal(execute([sidebar],overlay),false);
  assert.equal(sidebar.clicks,0);
});

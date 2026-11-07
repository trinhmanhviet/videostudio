import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read = path => fs.existsSync(new URL(path, import.meta.url)) ? fs.readFileSync(new URL(path, import.meta.url), 'utf8') : '';
const editor = read('../static/meme-editor.html');
const resources = read('../static/resources.js');
function library() {
  const context = vm.createContext({window: {}, URLSearchParams, console});
  vm.runInContext(resources, context);
  return context.window.ResourceLibrary;
}

test('library search matches bilingual and accent-free catalog terms', () => {
  const api = library();
  assert.ok(api, 'resource library helpers are available');
  const prop = {id:'fishing_rod', label:'Cần câu', search_terms:['fishing rod', 'đạo cụ cầm tay']};
  assert.equal(api.matches(prop, 'can cau'), true);
  assert.equal(api.matches(prop, 'fishing rod'), true);
  assert.equal(api.matches(prop, 'dien thoai'), false);
});

test('asset previews use the actual catalog source and encoded asset IDs', () => {
  const api = library();
  assert.ok(api, 'resource library helpers are available');
  assert.equal(api.imageURL({id:'a b',source:'memestudio'}, 'props'), '/meme-assets/props/a%20b.png');
  assert.equal(api.imageURL({id:'a b',uploaded:true}, 'props'), '/prop-assets/a%20b.png');
  assert.equal(api.imageURL({id:'garden'}, 'backgrounds'), '/meme-assets/backgrounds/garden.png');
});

test('editor seeks using actual staging timing and preserves unknown timing', () => {
  const script = editor.match(/<script>([\s\S]*?)<\/script>/)?.[1] || '';
  const start = script.indexOf('function beatTiming(');
  assert.ok(start >= 0, 'editor exposes staging timing lookup');
  const end = script.indexOf('function ', start + 10);
  const context = vm.createContext({editorData:{timeline:{beats:[{index:1,start:2.4,end:5.1}]}}, Number});
  vm.runInContext(script.slice(start, end), context);
  assert.equal(context.beatTiming(1).start, 2.4);
  assert.equal(context.beatTiming(0), null);
});

test('editor has one preview, scene filmstrip, and a tabbed inspector with retained real actions', () => {
  assert.match(editor, /id="sceneFilmstrip"/);
  assert.match(editor, /role="tablist"[^>]*aria-label="Chỉnh sửa/);
  assert.equal((editor.match(/id="videoPlayer"/g) || []).length, 1);
  for (const id of ['propsList','beatsList','scenesContainer','btnSaveScript','btnRerender','btnDownloadVideo','propFileInput']) assert.match(editor, new RegExp('id="'+id+'"'));
  assert.match(editor, /if \(renderBusy\) return/);
});

test('resource shell exposes working categories and escapes data through DOM text', () => {
  const html = read('../static/resources.html');
  for (const id of ['characters','props','backgrounds','voices','sfx']) assert.match(html, new RegExp('data-resource="'+id+'"'));
  assert.match(resources, /textContent\s*=/);
  assert.doesNotMatch(resources, /\.innerHTML\s*=/);
  assert.match(resources, /\/api\/voices\/clone/);
  assert.match(resources, /\/api\/resources\/props\/upload/);
});

test('character and resource scripts parse and share the navy workspace styles', () => {
  const characters = read('../static/characters.html');
  new vm.Script(characters.match(/<script>([\s\S]*?)<\/script>/)[1]);
  new vm.Script(resources);
  assert.match(characters, /href="\/editor-workspace.css"/);
  assert.match(characters, /href="\/resources.html\?tab=characters"/);
});

const flush = () => new Promise(resolve => setImmediate(resolve));
async function editorUI() {
  const nodes = new Map();
  const make = tag => ({tag, children:[], style:{}, dataset:{}, value:'', hidden:false, disabled:false, textContent:'', attributes:{},
    classList:{add(){},remove(){}},
    setAttribute(name,value){this.attributes[name]=value;}, hasAttribute(name){return name in this.attributes;},
    append(...children){this.children.push(...children);}, appendChild(child){this.children.push(child);return child;},
    replaceChildren(...children){this.children=[...children];}, cloneNode(){return {...make(this.tag),src:this.src};},
    play(){return Promise.resolve();}, click(){return this.onclick?.call(this);}
  });
  for (const [,id] of editor.matchAll(/id="([^"]+)"/g)) nodes.set('#'+id, make('div'));
  const data = {script:{title:['Tập phim','Mới'], scenes:{a:{bg:'room'},b:{bg:'garden'}}, props:{rod:{label:'Cần câu'},phone:{label:'Điện thoại'}}, beats:[{scene:'a',who:'bo',text:'A',props:{rod:{placement:'held'}}},{scene:'b',who:'con',text:'B',props:{phone:{placement:'held'}}}]}, props_status:{all:[{id:'rod',label:'Cần câu',has_asset:false},{id:'phone',label:'Điện thoại',has_asset:false}],missing:['rod','phone']}, timeline:{beats:[{index:0,start:0,end:3},{index:1,start:3,end:6}]},video_url:'/video.mp4'};
  const calls = [];
  let finishRender;
  const context = vm.createContext({console,URLSearchParams,Number,Date,Set,window:{location:{search:'?job=abc'}},
    document:{querySelector:selector=>nodes.get(selector),querySelectorAll:()=>[],createElement:make},
    setTimeout:()=>0, navigator:{clipboard:{writeText:async()=>{}}},
    fetch:async(path,options)=>{
      calls.push({path,options});
      if(path.endsWith('/re-render'))await new Promise(resolve=>{finishRender=resolve;});
      return {ok:true,json:async()=>path==='/api/meme/catalog'?{backgrounds:['room','garden'],face_names:['noi','cuoi']}:path.endsWith('/update-script')?{script:JSON.parse(options.body)}:data};
    }
  });
  vm.runInContext(editor.match(/<script>([\s\S]*?)<\/script>/)[1],context);
  await flush(); await flush();
  return {context,nodes,calls,finish:()=>finishRender()};
}

test('selecting a scene changes inspector scope and seeks its real MP4 timestamp', async()=>{
  const ui = await editorUI();
  assert.equal(ui.nodes.get('#sceneFilmstrip').children.length,2);
  vm.runInContext("selectScene('b')",ui.context);
  assert.equal(ui.nodes.get('#selectedSceneLabel').textContent,'Cảnh b');
  assert.equal(ui.nodes.get('#videoPlayer').currentTime,3);
  assert.equal(ui.nodes.get('#propCount').textContent,1);
  assert.equal(ui.nodes.get('#beatCount').textContent,1);
  ui.nodes.get('#propScopeSelect').value='episode';
  ui.nodes.get('#propScopeSelect').onchange();
  assert.equal(ui.nodes.get('#propCount').textContent,2);
});

test('rerender saves edits first, prevents duplicate requests, and releases controls', async()=>{
  const ui = await editorUI();
  const first=ui.nodes.get('#btnRerender').onclick();
  await flush();
  await ui.nodes.get('#btnRerender').onclick();
  assert.equal(ui.calls.filter(call=>call.path.endsWith('/re-render')).length,1);
  assert.equal(ui.calls.filter(call=>call.path.endsWith('/update-script')).length,1);
  assert.equal(ui.nodes.get('#btnRerender').disabled,true);
  ui.finish(); await first;
  assert.equal(ui.nodes.get('#btnRerender').disabled,false);
  assert.equal(ui.nodes.get('#renderModal').hidden,true);
  assert.equal(ui.nodes.get('#saveStatus').textContent,'✓ Đã xuất video mới');
});

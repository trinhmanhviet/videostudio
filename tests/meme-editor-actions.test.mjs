import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../static/index.html',import.meta.url),'utf8');
function setup(){
  const nodes=new Map();
  const node=()=>({hidden:false,children:[],src:'',after(child){if(child.id)nodes.set('#'+child.id,child);},append(child){this.children.push(child);},querySelector(){return null;}});
  for(const key of ['completedHeroSection','heroQuickDownloadBtn','heroDownloadBtn','heroVideoPlayer','heroChangeVoiceBtn'])nodes.set('#'+key,node());
  const context=vm.createContext({console,$:s=>nodes.get(s)??null,safeURL:s=>s,text:(tag,label,className)=>({...node(),tag,label,className}),window:{openSceneEditor(){}},openOptionalWorkspace(){},openResetImagesModal(){}});
  const helper=source.match(/function supportsImageEditing\(j\)\{[^\n]*\}/)?.[0]??'';
  const append=source.slice(source.indexOf('function appendJobActionButtons('),source.indexOf('function jobCardRenderState('));
  const hero=source.slice(source.indexOf('function updateHeroCompletedVideo('),source.indexOf('function renderProjectJobs('));
  vm.runInContext(helper+'\n'+append+'\n'+hero,context);
  return {nodes,node,append:context.appendJobActionButtons,hero:context.updateHeroCompletedVideo};
}
const job=mode=>({id:'j',status:'completed',request:{workflow_mode:mode},output_url:'/video.mp4',checkpoints:{speech:{},images:{scenes:[],image_provider:mode==='meme'?'meme_assets':'flow'}}});
test('meme cards hide unsupported image editors and image-reset actions',()=>{
  const ui=setup(),card=ui.node();ui.append(card,job('meme'));assert.equal(card.children.length,0);
  const ordinary=ui.node();ui.append(ordinary,job('research'));assert.equal(ordinary.children.length,3);
});
test('hero removes editor actions for meme then restores them for ordinary video',()=>{
  const ui=setup();ui.hero([job('research')]);
  for(const id of ['heroSceneEditBtn','heroOptionalEditBtn','heroResetImagesBtn'])assert.notEqual(ui.nodes.get('#'+id).hidden,true);
  ui.hero([job('meme')]);
  for(const id of ['heroSceneEditBtn','heroOptionalEditBtn','heroResetImagesBtn'])assert.equal(ui.nodes.get('#'+id).hidden,true);
  ui.hero([job('research')]);
  for(const id of ['heroSceneEditBtn','heroOptionalEditBtn','heroResetImagesBtn'])assert.equal(ui.nodes.get('#'+id).hidden,false);
});

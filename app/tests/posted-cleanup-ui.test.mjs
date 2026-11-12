import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../static/content-studio.js',import.meta.url),'utf8');
const context=vm.createContext({URL,URLSearchParams,crypto:{randomUUID:()=> 'receipt-1'}});
vm.runInContext(source,context);
const ui=context.ContentStudio;
const plain=value=>JSON.parse(JSON.stringify(value));

test('posted cleanup requires only explicit confirmation and ignores old manual fields',()=>{
  assert.deepEqual(plain(ui.postedCleanupPayload({title:'Tên video'})),{confirm:true});
  assert.deepEqual(plain(ui.postedCleanupPayload({}, {platform:'',published_at:'invalid'})),{confirm:true});
});

test('publication URLs accept absolute HTTPS only and history uses the same validation',()=>{
  for(const value of ['javascript:alert(1)','http://example.com','//example.com/post','/post','https://user:pass@example.com','https:example.com','not a url']){
    assert.equal(ui.httpsPostURL(value),null);
  }
  assert.equal(ui.httpsPostURL('https://example.com/post?q=1'),'https://example.com/post?q=1');
});

test('publication retry freezes both request body and idempotency key per job, including reopening',()=>{
  const saved=new Map(),storage={getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value)};
  let sequence=0;const uuid=()=> 'key-'+(++sequence);
  const first=ui.postedCleanupRequest(storage,'job-1',{confirm:true,title:'First'},uuid);
  const retry=ui.postedCleanupRequest(storage,'job-1',{confirm:true,title:'Changed'},uuid);
  assert.equal(first.key,retry.key);assert.equal(first.identity,retry.identity);
  assert.equal(ui.postedCleanupRequest(storage,'job-2',{confirm:true,title:'Other'},uuid).key,'key-2');
  assert.equal(JSON.parse(retry.identity).title,'First');
});

test('history rows retain publication metadata without a live job and validate link before rendering',()=>{
  assert.deepEqual(plain(ui.publicationSummary({id:'entry',job_id:'deleted-job',title:'Video đã đăng',platform:'tiktok',channel_name:'Kênh cũ',post_url:'javascript:alert(1)',cleanup_state:'pending'})),
    {title:'Video đã đăng',platform:'TikTok',channel:'Kênh cũ',url:null,cleanup:'Chờ dọn tệp',pending:true});
  assert.equal(ui.publicationSummary({cleanup_state:'completed'}).cleanup,'Đã xóa job/tệp');
});

// A small DOM fixture runs the real event handlers without launching a browser or a server.
function fixture(reply, {saved=new Map(), now}={}) {
  const nodes=[];let doc;
  class Node {
    constructor(tag,cls='',text=''){this.tagName=tag.toUpperCase();this.className=cls;this.textContent=text;this.children=[];this.dataset={};this.value='';this.disabled=false;this.classList={add:()=>{}};nodes.push(this);}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=[...children];}
    setAttribute(name,value){this[name]=value;}
    removeAttribute(name){delete this[name];}
    remove(){this.removed=true;}
    focus(){doc.activeElement=this;}
    pause(){this.pauses=(this.pauses||0)+1;}
    contains(node){return this===node||this.children.some(child=>child.contains?.(node));}
    querySelectorAll(selector){const descendants=this.children.flatMap(child=>[child,...child.querySelectorAll('*')]);return selector==='*'?descendants:descendants.filter(node=>node.tagName.toLowerCase()===selector||selector===`[name="${node.name}"]`);}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  }
  const root=new Node('section');doc={body:new Node('body'),activeElement:null,createElement:tag=>new Node(tag),addEventListener:()=>{},removeEventListener:()=>{},querySelector:selector=>selector==='#studio-library'?root:null,querySelectorAll:()=>[]};
  const calls=[];
  const localStorage={getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)};
  const sandbox=vm.createContext({URL,URLSearchParams,document:doc,crypto:{randomUUID:()=> 'click-key'},localStorage,AbortSignal:{timeout:ms=>({timeout:ms})},setTimeout:(callback,ms)=>{if(ms===1000)queueMicrotask(callback);return 0;},clearTimeout:()=>{},...(now?{Date:class extends Date{static now(){return now();}}}:{}),location:{href:'http://localhost/',origin:'http://localhost'},fetch:async(path,options)=>{calls.push({path,options});const data=await reply(path,options);return {ok:data.status?data.status<400:true,status:data.status||200,json:async()=>data.body??data};}});
  vm.runInContext(source.replace('  installShell();','  global.__test={videoCard,openVideo,loadLibrary,state,batchRowNode};'),sandbox);
  return {nodes,root,saved,calls,sandbox,api:sandbox.__test,all:parent=>[parent,...parent.querySelectorAll('*')],find:(parent,label)=>[parent,...parent.querySelectorAll('*')].find(node=>node.textContent===label)};
}

test('first timeout reconciles its receipt without a second click and suppresses duplicate confirmation',async()=>{
  let release;let posts=0;
  const app=fixture(async(path,options)=>{
    if(path.endsWith('/posted-cleanup')){
      if(options.method==='POST'){posts++;await new Promise(resolve=>release=resolve);throw Object.assign(new Error('signal timed out'),{name:'TimeoutError'});}
      return {ok:true,entry:{id:'history-entry'},cleanup_pending:true};
    }
    return {items:[],total:0,total_pages:1};
  });
  const refreshed=[];app.sandbox.loadProjects=()=>{refreshed.push('projects');throw Error('Refresh unavailable');};app.sandbox.loadJobs=async()=>refreshed.push('jobs');
  const card=app.api.videoCard({job_id:'job 1',title:'Video test',versions:[]});
  app.find(card,'Đã đăng & dọn').onclick();
  const form=app.nodes.find(node=>node.tagName==='FORM'),submit=app.all(form).find(node=>node.type==='submit');
  assert.equal(app.all(form).filter(node=>['INPUT','SELECT','TEXTAREA'].includes(node.tagName)).length,0);
  assert.equal(app.calls.length,0);
  const event={preventDefault(){}};const first=form.onsubmit(event);await form.onsubmit(event);
  assert.equal(posts,1);assert.equal(submit.disabled,true);assert.equal(submit.textContent,'Đang dọn…');
  release();await first;
  const requests=app.calls.filter(call=>call.path.endsWith('/posted-cleanup'));
  assert.equal(requests.length,2);assert.equal(requests[0].path,'/api/jobs/job%201/posted-cleanup');
  assert.equal(requests[1].options.method,'GET');assert.equal(requests[1].options.body,undefined);
  assert.equal(requests[0].options.headers['Idempotency-Key'],requests[1].options.headers['Idempotency-Key']);
  assert.deepEqual(JSON.parse(requests[0].options.body),{confirm:true});assert.equal(app.saved.size,0);
  assert.ok(app.nodes.find(node=>node.className==='studio-dialog').removed);
  assert.deepEqual(refreshed,['projects','jobs']);assert.ok(app.calls.some(call=>call.path==='/api/factory/queue'));
});

test('dropped first request checks status then retries the exact frozen body automatically',async()=>{
  let posts=0;
  const app=fixture(async(path,options)=>{
    if(path.endsWith('/posted-cleanup')){
      if(options.method==='GET')return {ok:false,pending:true};
      if(++posts===1)throw new TypeError('Network lost');
      return {ok:true,entry:{id:'recovered'},cleanup_pending:false};
    }
    return {items:[],total:0,total_pages:1};
  });
  const card=app.api.videoCard({job_id:'job',title:'Video',versions:[]});app.find(card,'Đã đăng & dọn').onclick();
  await app.nodes.find(node=>node.tagName==='FORM').onsubmit({preventDefault(){}});
  const requests=app.calls.filter(call=>call.path.endsWith('/posted-cleanup'));
  assert.deepEqual(requests.map(call=>call.options.method),['POST','GET','POST']);
  assert.equal(requests[0].options.body,requests[2].options.body);
  assert.equal(requests[0].options.headers['Idempotency-Key'],requests[2].options.headers['Idempotency-Key']);
  assert.ok(app.nodes.find(node=>node.className==='studio-dialog').removed);assert.equal(app.saved.size,0);
});

test('exhausted network recovery retains the frozen receipt across reload and waits for confirmation',async()=>{
  const app=fixture(async(path,options)=>{
    if(options.method==='GET')return {ok:false,pending:true};
    throw Object.assign(new Error('aborted'),{name:'AbortError'});
  });
  const card=app.api.videoCard({job_id:'job',title:'Video',versions:[]});app.find(card,'Đã đăng & dọn').onclick();
  const form=app.nodes.find(node=>node.tagName==='FORM');await form.onsubmit({preventDefault(){}});
  const posts=app.calls.filter(call=>call.options.method==='POST');assert.equal(posts.length,3);
  assert.equal(app.calls.filter(call=>call.options.method==='GET').length,3);
  assert.equal(app.find(form,'Đã đăng & dọn').disabled,false);assert.equal(app.saved.size,1);
  const saved=JSON.parse([...app.saved.values()][0]);
  const reopened=fixture(async(path)=>path.endsWith('/posted-cleanup')?{ok:true,entry:{id:'after-reload'}}:{items:[]},{saved:app.saved});
  const freshCard=reopened.api.videoCard({job_id:'job',title:'Changed title',versions:[]});reopened.find(freshCard,'Đã đăng & dọn').onclick();
  assert.equal(reopened.calls.length,0,'reopening never sends an unconfirmed cleanup');
  await reopened.nodes.find(node=>node.tagName==='FORM').onsubmit({preventDefault(){}});
  const retry=reopened.calls.find(call=>call.options.method==='POST');assert.equal(retry.options.body,saved.identity);assert.equal(retry.options.headers['Idempotency-Key'],saved.key);
  assert.equal(reopened.saved.size,0);
});

test('recovery shares a three-minute deadline across posts and receipt checks',async()=>{
  let elapsed=0;
  const app=fixture(async(path,options)=>{
    elapsed+=options.signal.timeout;
    throw Object.assign(new Error('signal timed out'),{name:'TimeoutError'});
  },{now:()=>elapsed});
  const card=app.api.videoCard({job_id:'job',title:'Video',versions:[]});app.find(card,'Đã đăng & dọn').onclick();
  await app.nodes.find(node=>node.tagName==='FORM').onsubmit({preventDefault(){}});
  assert.equal(app.calls.filter(call=>call.options.method==='POST').length,3);
  assert.ok(elapsed<=180000,'all request timeouts fit within one recovery deadline');
  assert.ok(app.calls.filter(call=>call.options.method==='GET').every(call=>call.options.signal.timeout<=5000));
  assert.equal(app.saved.size,1);
});

test('server failures reconcile but semantic conflicts never retry or replace the saved body',async()=>{
  for(const status of [500,503,409,422]){
    const app=fixture(async(path,options)=>options.method==='GET'?{ok:true,entry:{id:'committed'}}:{status,body:{detail:'Rejected '+status}});
    const card=app.api.videoCard({job_id:'job',title:'Video',versions:[]});app.find(card,'Đã đăng & dọn').onclick();
    const form=app.nodes.find(node=>node.tagName==='FORM');await form.onsubmit({preventDefault(){}});
    assert.equal(app.calls.filter(call=>call.options.method==='POST').length,1);
    assert.equal(app.calls.filter(call=>call.options.method==='GET').length,status>=500?1:0);
    if(status<500)assert.ok(app.find(form,'Rejected '+status));
    if(status===409)assert.equal(JSON.parse([...app.saved.values()][0]).identity,'{"confirm":true}');
  }
});

test('validation rejection allows confirmation again, while video modal also exposes the action',async()=>{
  const app=fixture(async()=>({status:422,body:{detail:'Sửa giờ đăng'}}));
  app.api.openVideo({job_id:'job',title:'Video',output_url:'/output.mp4'});
  const modal=app.nodes.find(node=>node.className==='studio-dialog-box');app.find(modal,'Đã đăng & dọn').onclick();
  const form=app.nodes.find(node=>node.tagName==='FORM');
  await form.onsubmit({preventDefault:()=>{}});
  assert.equal(app.find(form,'Đã đăng & dọn').disabled,false);assert.equal(app.saved.size,0);assert.ok(app.find(form,'Sửa giờ đăng'));
});

test('history uses its own filters and renders deleted-job entries with a manual cleanup retry',async()=>{
  const app=fixture(async path=>path.endsWith('/cleanup')?{ok:true,cleanup_pending:false}:{items:[{id:'entry/1',job_id:'gone',title:'Saved title',platform:'tiktok',channel_name:'Old channel',post_url:'https://example.com/post',published_at:'2026-11-12T10:00:00+07:00',cleanup_state:'pending'}],page:2,total_pages:3,total:21});
  Object.assign(app.api.state,{libraryView:'history',publication:{q:'story & title',platform:'tiktok',page:2,page_size:20}});
  await app.api.loadLibrary();
  const query=new URL('http://local'+app.calls[0].path).searchParams;
  assert.equal(query.get('q'),'story & title');assert.equal(query.get('platform'),'tiktok');assert.equal(query.get('page_size'),'20');
  assert.ok(app.find(app.root,'Saved title'));
  assert.ok(app.all(app.root).some(node=>node.textContent.includes('2026')),'ledger date includes the year');
  const link=app.find(app.root,'Mở bài đã đăng');assert.equal(link.href,'https://example.com/post');assert.equal(link.rel,'noopener noreferrer');
  assert.equal(app.calls.some(call=>call.options.method==='POST'),false);
  await app.find(app.root,'Thử dọn job/tệp').onclick();
  const post=app.calls.find(call=>call.options.method==='POST');assert.equal(post.path,'/api/publication-history/entry%2F1/cleanup');assert.deepEqual(JSON.parse(post.options.body),{confirm:true});
});

test('publication ledger stays reachable when the video list cannot load',async()=>{
  const app=fixture(async path=>path.startsWith('/api/factory/videos')?{status:500,body:{detail:'Unavailable'}}:{items:[],page:1,total_pages:1,total:0});
  await app.api.loadLibrary();
  const tab=app.find(app.root,'Sổ đăng');assert.ok(tab);await tab.onclick();
  assert.ok(app.calls.some(call=>call.path.startsWith('/api/publication-history?')));
});

test('ledger lists every recorded destination once, with validated links and individual posting times',async()=>{
  const entry={id:'multi',title:'Multiple posts',platform:'youtube',channel_name:'Primary',post_url:'https://youtube.com/watch?v=1',published_at:'2026-11-12T03:00:00Z',cleanup_state:'completed',posts:[
    {platform:'youtube',channel_name:'Primary',post_url:'https://youtube.com/watch?v=1',published_at:'2026-11-12T10:00:00+07:00'},
    {platform:'facebook',channel_name:'Second Page',post_url:'https://facebook.com/post/2',published_at:'2026-11-13T04:00:00Z'},
    {platform:'facebook',channel_name:'Second Page',post_url:'https://facebook.com/post/2',published_at:'2026-11-13T04:00:00Z'},
    {platform:'tiktok',channel_name:'Unsafe link channel',post_url:'javascript:alert(1)',published_at:'2026-11-14T05:00:00Z'},
  ]};
  const app=fixture(async()=>({items:[entry],page:1,total_pages:1,total:1}));app.api.state.libraryView='history';await app.api.loadLibrary();
  const all=app.all(app.root),links=all.filter(node=>node.tagName==='A');assert.equal(links.length,2);
  assert.equal(links[1].href,'https://facebook.com/post/2');assert.equal(links[1].rel,'noopener noreferrer');
  assert.equal(all.filter(node=>node.textContent.includes('Second Page')).length,1);
  assert.ok(all.some(node=>node.textContent.includes('TikTok')&&node.textContent.includes('Unsafe link channel')));
  assert.ok(all.some(node=>node.textContent.includes('13/11/2026')));assert.ok(all.some(node=>node.textContent.includes('14/11/2026')));
});


test('video preview focuses one player and updates the active download when switching formats',()=>{
  const app=fixture(async()=>({}));
  const portrait='http://localhost/api/jobs/job/files/final.mp4',wide='http://localhost/api/jobs/job/files/wide.mp4';
  app.api.openVideo({job_id:'job',title:'Video',output_url:portrait,wide_url:wide});
  const player=app.nodes.find(node=>node.tagName==='VIDEO');
  assert.equal(app.nodes.filter(node=>node.tagName==='VIDEO').length,1);
  assert.equal(player.src,portrait);
  const download=app.nodes.find(node=>node.tagName==='A'&&node.download==='');
  assert.equal(download.href,portrait);
  app.nodes.find(node=>node.textContent==='Ngang 16:9'&&node.tagName==='BUTTON').onclick();
  assert.equal(player.src,wide);assert.equal(download.href,wide);assert.ok(player.pauses>=1);
  const close=app.nodes.find(node=>node['aria-label']==='Đóng');close.onclick();assert.ok(player.pauses>=2);
});

test('an old lost-reply receipt remains replayable through the new confirmation',async()=>{
  const app=fixture(async()=>({ok:true,entry:{id:'entry'}}));
  const identity=JSON.stringify({confirm:true,title:'Old receipt',platform:'other',published_at:'2026-11-12T10:00:00+07:00'});
  app.saved.set('videostudio.posted-cleanup.v1.job',JSON.stringify({key:'old-key',identity}));
  const card=app.api.videoCard({job_id:'job',title:'Video',versions:[]});app.find(card,'Đã đăng & dọn').onclick();
  await app.nodes.find(node=>node.tagName==='FORM').onsubmit({preventDefault(){}});
  const call=app.calls.find(call=>call.path.endsWith('/posted-cleanup'));
  assert.equal(call.options.headers['Idempotency-Key'],'old-key');assert.equal(call.options.body,identity);
});


test('invalid saved cleanup bodies cannot block a fresh confirmation',()=>{
  for(const identity of ['null','{}','[]','"invalid"']){
    const saved=new Map([['videostudio.posted-cleanup.v1.job',JSON.stringify({key:'bad',identity})]]);
    const storage={getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v)};
    const receipt=ui.postedCleanupRequest(storage,'job',{confirm:true},()=> 'new-key');
    assert.equal(receipt.key,'new-key');assert.deepEqual(JSON.parse(receipt.identity),{confirm:true});
  }
});


test('batch row offers six aligned settings and leaves speech batch enabled for meme narration',()=>{
  const app=fixture(async()=>({}));
  const row=app.api.batchRowNode({title:'Meme',text:'Story',style:'meme',input:'script',voice:'v',seconds:60,unit:'1',image_provider:'comfy',speech_batch_size:33},0);
  const settings=app.all(row).find(node=>node.className==='studio-batch-settings');assert.equal(settings.children.length,6);
  const speech=app.all(settings).find(node=>node['aria-label']==='Batch giọng đọc video 1');
  assert.equal(speech.type,'number');assert.equal(speech.min,'1');assert.equal(speech.max,'512');assert.equal(speech.step,'1');assert.equal(speech.value,'33');assert.equal(speech.disabled,false);
  const image=app.all(settings).find(node=>node['aria-label']==='Dịch vụ tạo ảnh video 1');assert.equal(image.disabled,true);
});

test('video format switches retain the social caption panel and posted-cleanup action',()=>{
  const app=fixture(async()=>({})),social=app.sandbox.document.createElement('section');social.textContent='Social captions';
  app.sandbox.socialPanel=()=>social;
  app.api.openVideo({job_id:'job',title:'Video',output_url:'/portrait.mp4',wide_url:'/wide.mp4'});
  app.nodes.find(node=>node.textContent==='Ngang 16:9'&&node.tagName==='BUTTON').onclick();
  const modal=app.nodes.find(node=>node.className==='studio-dialog-box');assert.ok(app.all(modal).includes(social));assert.ok(app.find(modal,'Đã đăng & dọn'));
});

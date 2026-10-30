// Real offline renderer + shipped worker: recover a closed tab's completed reply.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const {chromium}=require('C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
(async()=>{
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'extensions/videostudio-chatgpt');
 const protocol=await import(pathToFileURL(path.join(dir,'protocol.mjs')).href);
 const scope='123e4567-e89b-42d3-a456-426614174000',id='offline-tab-recovery',prompt=`YÊU CẦU STUDIO ${id}\nWrite a script`;
 const url='https://chatgpt.com/c/123e4567-e89b-42d3-a456-426614174111';
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 try{
  const page=await browser.newPage();await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'}));await page.goto(url);
  await page.setContent('<div data-message-author-role="user" style="white-space:pre-wrap"></div><section data-talvt-turn-state="complete"><div data-message-author-role="assistant"><pre><code>{"recovered":true}</code></pre></div></section><form><textarea id="prompt-textarea" aria-label="Message ChatGPT"></textarea><button aria-label="Send">Send</button></form>');
  await page.evaluate(prompt=>{
   document.querySelector('[data-message-author-role="user"]').textContent=prompt;
   window.chrome={runtime:{onMessage:{addListener:fn=>window.contentListener=fn},sendMessage:async()=>{throw Error('Read-only recovery must not send content callbacks');}}};
  },prompt);
  for(const name of ['send-button.js','logical-text.js','chatgpt.js'])await page.addScriptTag({path:path.join(dir,name)});
  let state=protocol.start({studioTab:7,scope}),listener;const actions=[];
  state.job={id,prompt,version:1,attempt:1,phase:'sent',send_attempted:true,chatTab:20,conversation_url:url,startedAt:Date.now()-60000};state.chatTab=20;state.ownedTabs=[20];
  const chrome={storage:{local:{get:async()=>({videostudio_bridge_v2:structuredClone(state)}),set:async value=>{state=value.videostudio_bridge_v2;}}},runtime:{onMessage:{addListener:fn=>listener=fn}},tabs:{
   query:async()=>[{id:30,url}],create:async()=>{throw Error('Must not create another tab');},remove:async()=>{throw Error('Must not close tabs during inspection');},
   sendMessage:async(tab,message)=>{actions.push(message.kind);if(tab===20)throw Error('Old tab was closed');return page.evaluate(message=>new Promise(resolve=>contentListener(message,null,resolve)),message);},onUpdated:{addListener(){},removeListener(){}}
  }};
  vm.runInNewContext(fs.readFileSync(path.join(dir,'background.js'),'utf8').replace(/^import .*?;\r?\n/,''),{chrome,...protocol,URL,fetch:async()=>({ok:true,json:async()=>({id,version:1,accepted:false})}),AbortSignal,setTimeout,clearTimeout,Date,Error,Promise,Number,String});
  const result=await new Promise(resolve=>listener({kind:'reconcile',scope,inspect_only:true},{url:`http://localhost:8877/story-video/projects/${scope}/production`,frameId:0,tab:{id:7}},resolve));
  assert.equal(result.status,'reply');const job=protocol.sessionSlot(state,scope).job;
  assert.equal(job.chatTab,30);assert.deepEqual(JSON.parse(job.text),{recovered:true});assert.ok(actions.every(action=>action==='inspect'));
  console.log('PASS closed tab -> new same-URL renderer -> exact completed JSON reply, zero sends');
  const foreign=await page.evaluate(()=>new Promise(resolve=>contentListener({kind:'inspect',id:'foreign',prompt:'YÊU CẦU STUDIO foreign\nX',match_only:true},null,resolve)));
  assert.equal(foreign.visibleUser,null);assert.equal(foreign.visibleReply,null);console.log('PASS unrelated request text remains private');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

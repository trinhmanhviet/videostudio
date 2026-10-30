/* Real content script + shipped service worker + real isolated FastAPI/SQLite.
   All ChatGPT content/model infrastructure is fixture data, never an account. */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');const {randomUUID}=require('node:crypto');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'data','connection-e2e',randomUUID());
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  fs.mkdirSync(folder,{recursive:true});
  const proc=spawn('C:/Python312/python.exe',[path.join(__dirname,'serve_extension_fixture.py'),folder],{cwd:root,env:{...process.env,VS_DATABASE:path.join(folder,'import.sqlite3'),VS_STORYFORGE_ROOT:folder,VS_VOICES_EXPORT:path.join(folder,'empty-voices.json'),VS_LLM_TRANSPORT:'extension',VS_WORKER_ENABLED:'0'},stdio:['ignore','pipe','pipe']});
  let logs='';proc.stderr.on('data',chunk=>logs+=chunk);
  let browser;
  try{
    const port=await new Promise((resolve,reject)=>{
      let text='';const timer=setTimeout(()=>reject(Error('Fixture startup timeout '+logs)),10000);
      proc.stdout.on('data',chunk=>{text+=chunk;const line=text.split('\n')[0];try{const value=JSON.parse(line);if(value.port){clearTimeout(timer);resolve(value.port);}}catch{}});
      proc.once('exit',()=>{clearTimeout(timer);reject(Error('Fixture exited '+logs));});
    });
    const base='http://127.0.0.1:'+port;
    async function api(url,options={}){const result=await fetch(base+url,options);if(!result.ok)throw Error(await result.text());return result.json();}
    for(let i=0;i<50;i++){try{await api('/api/health');break;}catch{await delay(100);}}
    const connection=await api('/api/connector/sessions',{method:'POST'}),scope=connection.project_id;
    browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
    const context=await browser.newContext();
    await context.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
    const protocol=await import('../extensions/videostudio-chatgpt/protocol.mjs');
    let listener,alarmListener,tabCounter=20,owner=true,legacyNext=false;const storage={},tabs=new Map(),created=[],closed=[];
    const sender={frameId:0,tab:{id:7},url:`http://localhost:8877/story-video/projects/${scope}/production`};
    const send=(message,from=sender)=>new Promise(resolve=>listener(message,from,resolve));
    const chrome={storage:{local:{get:async key=>({[key]:structuredClone(storage[key])}),set:async value=>Object.assign(storage,structuredClone(value))}},
      alarms:{get:async()=>null,create:async()=>{},onAlarm:{addListener:fn=>alarmListener=fn}},runtime:{getManifest:()=>JSON.parse(fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/manifest.json'))),onMessage:{addListener:fn=>listener=fn}},
      tabs:{get:async id=>{if(id===7){if(!owner)throw Error('Owner closed');return {id,url:sender.url,status:'complete'};}if(!tabs.has(id))throw Error('Unknown tab');return {id,status:'complete',url:'https://chatgpt.com/'};},
        create:async options=>{
          const id=++tabCounter,page=await context.newPage();tabs.set(id,page);created.push(options);
          await page.goto('https://chatgpt.com/');
          await page.setContent('<div role="group" aria-label="Composer mode"><button id="chat" aria-selected="false">Chat</button><button id="work" aria-selected="true">Work</button></div><form><div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send">Send</button></form>');
          await page.exposeFunction('toWorker',message=>send(message,{frameId:0,tab:{id},url:'https://chatgpt.com/'}));
          await page.evaluate(()=>{
            window.clicks=0;window.switches=0;window.chrome={runtime:{sendMessage:window.toWorker,onMessage:{addListener:fn=>window.contentListener=fn}}};
            document.querySelector('#chat').onclick=()=>{switches++;document.querySelector('#chat').setAttribute('aria-selected','true');document.querySelector('#work').setAttribute('aria-selected','false');};
            document.querySelector('button[aria-label="Send"]').onclick=()=>{
              clicks++;const input=document.querySelector('#prompt-textarea'),user=document.createElement('div');user.style.whiteSpace='pre-wrap';user.setAttribute('data-message-author-role','user');user.innerText=input.innerText;input.innerHTML='';document.body.append(user);
              const answer=document.createElement('section');answer.setAttribute('data-talvt-turn-state','complete');answer.innerHTML='<div data-message-author-role="assistant"><pre><code>{"connection_test":"videostudio","ok":true}</code></pre></div>';document.body.append(answer);
            };
          });
          const manifest=JSON.parse(fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/manifest.json')));
          for(const file of manifest.content_scripts[1].js)await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt',file)});
          if(legacyNext){
            legacyNext=false;
            // Reproduce the prior shipped content script's pre-Send mode error.
            // The retry tab loads only the actual current content script above.
            await page.evaluate(()=>{const current=contentListener;window.contentListener=(message,sender,reply)=>{
              if(message.kind!=='deliver')return current(message,sender,reply);
              reply({ok:true});void toWorker({kind:'uncertain',id:message.id,attempt:message.attempt,reason:'Chat mode not confirmed'});
            };});
          }
          return {id,status:'complete'};
        },
        sendMessage:async(id,message)=>{if(id===7)return {ok:true};return tabs.get(id).evaluate(message=>new Promise(resolve=>contentListener(message,null,resolve)),message);},
        remove:async id=>{closed.push(id);await tabs.get(id)?.close();tabs.delete(id);}}};
    const workerFetch=(url,options={})=>fetch(base+new URL(url).pathname,{...options,headers:{...options.headers,Origin:'chrome-extension://'+'a'.repeat(32)}});
    const source=fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/background.js'),'utf8').replace(/^import .*?;\r?\n/,'');
    vm.runInNewContext(source,{...protocol,chrome,URL,fetch:workerFetch,AbortSignal,Date,Error,Number,String,Promise,setTimeout,clearTimeout});
    assert.equal((await send({kind:'start',scope})).ok,true);
    const pulse=async()=>{alarmListener({name:'videostudio-bridge-heartbeat'});await send({kind:'snapshot'});};
    await pulse();
    let state=await api('/api/connector/bridges/'+scope+'/status');
    assert.equal(state.heartbeat.ready,true);assert.equal(state.heartbeat.runtime_version,JSON.parse(fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/manifest.json'))).version);assert.equal(state.ready,false);
    const smoke=await api('/api/connector/smoke/'+scope,{method:'POST'});
    const pending=(await api('/api/connector/bridges/'+scope+'/pending')).items[0];assert.equal(pending.id,smoke.exchange_id);
    assert.equal((await send({kind:'claim',...pending})).ok,true);
    let snapshot;const deadline=Date.now()+12000;
    do{snapshot=await send({kind:'snapshot'});if(snapshot.job?.phase==='reply')break;await delay(100);}while(Date.now()<deadline);
    assert.equal(snapshot.job?.phase,'reply',JSON.stringify(snapshot));
    const page=tabs.get(snapshot.job.chatTab),counts=await page.evaluate(()=>({clicks,switches}));assert.deepEqual(counts,{clicks:1,switches:1});
    const receipt=await api(`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges/${pending.id}/response`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:pending.version,response_text:snapshot.job.text})});
    assert.equal(receipt.accepted,true);assert.equal((await send({kind:'imported',scope,id:pending.id,version:pending.version,accepted:true})).ok,true);
    await pulse();state=await api('/api/connector/bridges/'+scope+'/status');assert.equal(state.ready,true);
    const preflight=await api('/api/preflight?scope='+scope);assert.equal(preflight.ready,true,JSON.stringify(preflight));
    assert.ok(preflight.checks.every(check=>check.ok));assert.ok(created.every(options=>options.active===false));
    legacyNext=true;
    const legacySmoke=await api('/api/connector/smoke/'+scope,{method:'POST'}),legacyPending=(await api('/api/connector/bridges/'+scope+'/pending')).items[0];
    assert.equal(legacySmoke.exchange_id,legacyPending.id);assert.equal((await send({kind:'claim',...legacyPending})).ok,true);
    const legacyDeadline=Date.now()+3000;
    do{snapshot=await send({kind:'snapshot'});if(snapshot.job?.phase==='uncertain')break;await delay(50);}while(Date.now()<legacyDeadline);
    assert.equal(snapshot.job?.reason,'Chat mode not confirmed');
    assert.equal(await tabs.get(snapshot.job.chatTab).evaluate(()=>clicks),0);
    await pulse();const blocked=await api('/api/connector/bridges/'+scope+'/status');
    assert.equal(blocked.heartbeat.ready,true);assert.equal(blocked.ready,false);assert.equal(blocked.smoke.status,'pending');assert.match(blocked.smoke.reason,/Chat mode not confirmed/);
    assert.equal((await send({kind:'reconcile',scope})).status,'retried');
    const recoveryDeadline=Date.now()+12000;
    do{snapshot=await send({kind:'snapshot'});if(snapshot.job?.phase==='reply')break;await delay(100);}while(Date.now()<recoveryDeadline);
    assert.equal(snapshot.job?.phase,'reply',JSON.stringify(snapshot));assert.equal(snapshot.job.id,legacyPending.id);assert.equal(snapshot.job.attempt,2);
    assert.deepEqual(await tabs.get(snapshot.job.chatTab).evaluate(()=>({clicks,switches})),{clicks:1,switches:1});
    await api(`/api/v1/projects/${scope}/runs/${scope}/chatgpt-exchanges/${legacyPending.id}/response`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:legacyPending.version,response_text:snapshot.job.text})});
    await send({kind:'imported',scope,id:legacyPending.id,version:legacyPending.version,accepted:true});await pulse();
    assert.equal((await api('/api/preflight?scope='+scope)).ready,true);
    owner=false;await pulse(); // closed owner must not produce another active heartbeat
    fs.writeFileSync(path.join(folder,'verification.json'),JSON.stringify({fixture_only:true,counts,created,closed,gate:state,preflight,recovered_legacy_pre_send_mode_failure:true,ok:true},null,2));
    console.log('PASS Work→Chat → worker reply → API receipt → heartbeat → gates ready; legacy unsent mode failure recovers once without duplicate Send');
  }finally{await browser?.close();proc.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});

/* Real Chrome renderer test, with no Playwright focus emulation. CDP is used
   only in this test. Fresh profile; intercepted pages; simulated extension API. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),{randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'..'),out=path.join(root,'data','extension-background');
const profile=path.join(out,'profiles',randomUUID()),delay=ms=>new Promise(r=>setTimeout(r,ms));
const report={scope:'intercepted_fixture_only',signed_in_account:false,focus_emulation:false};
(async()=>{
  fs.mkdirSync(profile,{recursive:true});
  const proc=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',[
    '--user-data-dir='+profile,'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
    '--no-first-run','--no-default-browser-check','--disable-background-networking','about:blank',
  ],{stdio:'ignore'});
  let ws,next=0;const pending=new Map();
  const command=(method,params={},sessionId)=>new Promise((resolve,reject)=>{
    const id=++next,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},10000);
    pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
  });
  const evaluate=async(session,expression)=>{
    const r=await command('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);
    if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;
  };
  try{
    const file=path.join(profile,'DevToolsActivePort');for(let i=0;i<100&&!fs.existsSync(file);i++)await delay(100);
    const [port,endpoint]=fs.readFileSync(file,'utf8').trim().split(/\r?\n/);
    ws=new WebSocket('ws://127.0.0.1:'+port+endpoint);
    await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
    ws.addEventListener('message',event=>{
      const m=JSON.parse(event.data),p=pending.get(m.id);
      if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result||{});}
      if(m.method==='Fetch.requestPaused')void command('Fetch.fulfillRequest',{requestId:m.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/html'}],body:Buffer.from('<!doctype html><html><body></body></html>').toString('base64')},m.sessionId).catch(()=>{});
    });
    async function page(url,background){
      const target=await command('Target.createTarget',{url:'about:blank',background});
      const {sessionId}=await command('Target.attachToTarget',{targetId:target.targetId,flatten:true});
      await command('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]},sessionId);
      await command('Page.enable',{},sessionId);await command('Runtime.enable',{},sessionId);await command('Page.navigate',{url},sessionId);
      for(let i=0;i<50;i++){if(await evaluate(sessionId,'location.href==='+JSON.stringify(url)+'&&document.readyState==="complete"'))return sessionId;await delay(100);}
      throw Error('Fixture not loaded');
    }
    const foreground=await page('https://foreground.invalid/',false);
    await evaluate(foreground,`document.body.innerHTML='<input id="typing" value="keep typing here">';document.querySelector('input').focus();`);
    const chat=await page('https://chatgpt.com/',true);
    await evaluate(chat,`(()=>{
      document.body.innerHTML='<div role="group" aria-label="Composer mode"><button id="chat" aria-selected="false">Chat</button><button id="work" aria-selected="true">Work</button></div><form><div id="prompt-textarea" role="textbox" contenteditable="true" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send" disabled>Send</button></form>';
      window.messages=[];window.visibilityLog=[];window.clicks=0;window.switches=0;
      document.addEventListener('visibilitychange',()=>visibilityLog.push(document.visibilityState));
      window.chrome={runtime:{sendMessage:async m=>{messages.push(m);return {ok:true};},onMessage:{addListener:fn=>{window.extensionListener=fn;}}}};
      document.querySelector('#chat').onclick=()=>{switches++;document.querySelector('#chat').setAttribute('aria-selected','true');document.querySelector('#work').setAttribute('aria-selected','false');};
      const composer=document.querySelector('#prompt-textarea'),button=document.querySelector('button[aria-label="Send"]');
      composer.addEventListener('input',()=>{button.disabled=false;});
      button.onclick=()=>{
        clicks++;const prompt=composer.innerText;composer.innerHTML='';
        const user=document.createElement('div');user.setAttribute('data-message-author-role','user');user.style.whiteSpace='pre-wrap';user.textContent=prompt;document.body.append(user);
        const answer=document.createElement('section');answer.setAttribute('data-talvt-turn-state','complete');answer.innerHTML='<div data-message-author-role="assistant"><pre><code>{"background":true,"ok":true}</code></pre></div>';document.body.append(answer);
      };
    })()`);
    const files=JSON.parse(fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/manifest.json'))).content_scripts[1].js;
    for(const file of files)await evaluate(chat,fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt',file),'utf8'));
    report.before=await evaluate(chat,'({visibility:document.visibilityState,focused:document.hasFocus()})');
    assert.equal(report.before.visibility,'hidden');assert.equal(report.before.focused,false);
    const prompt='YÊU CẦU STUDIO bg-test\nReturn a synthetic background result.';
    await evaluate(chat,'new Promise(resolve=>extensionListener('+JSON.stringify({kind:'deliver',id:'bg-test',attempt:1,prompt})+',null,resolve))');
    const deadline=Date.now()+15000;let result;
    do{result=await evaluate(chat,'({messages,clicks,switches,visibility:document.visibilityState,focused:document.hasFocus(),visibilityLog})');if(result.messages.some(m=>['reply','uncertain'].includes(m.kind)))break;await delay(200);}while(Date.now()<deadline);
    report.result=result;assert.equal(result.messages.at(-1)?.kind,'reply',JSON.stringify(result));
    assert.equal(result.clicks,1);assert.equal(result.switches,1);assert.equal(result.visibility,'hidden');assert.equal(result.focused,false);assert.ok(!result.visibilityLog.includes('visible'));
    report.foreground=await evaluate(foreground,'({visibility:document.visibilityState,focused:document.hasFocus(),inputFocused:document.activeElement?.id==="typing",value:document.querySelector("input").value})');
    assert.equal(report.foreground.visibility,'visible');assert.equal(report.foreground.focused,true);assert.equal(report.foreground.inputFocused,true);assert.equal(report.foreground.value,'keep typing here');
    const recovered=await evaluate(chat,'new Promise(resolve=>extensionListener('+JSON.stringify({kind:'inspect',id:'bg-test',prompt})+',null,resolve))');
    assert.equal(recovered.visibleReply,'{"background":true,"ok":true}');report.hidden_delivery=true;report.hidden_recovery=true;report.ok=true;
    console.log('PASS hidden ChatGPT tab sends once, receives and recovers while foreground input keeps focus');
  }finally{
    fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2));
    if(ws?.readyState===WebSocket.OPEN){await command('Browser.close').catch(()=>{});ws.close();}else proc.kill();
    for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Test browser closed'));}
  }
})().catch(error=>{console.error(error);process.exitCode=1;});

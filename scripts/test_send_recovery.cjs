// Offline Chromium fixture: runs the shipped scripts, never contacts ChatGPT.
const path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try{
    for(const scenario of ['noop','cleared','replaced','disabled','delayed']){
      const page=await browser.newPage();
      await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><body></body>'}));
      await page.goto('https://chatgpt.com/');
      await page.setContent('<form><textarea id="prompt-textarea" aria-label="Message ChatGPT"></textarea><button type="button" aria-label="Send">Send</button></form>');
      await page.evaluate(scenario=>{
        window.calls=[];window.clicks=0;
        const nativeTimeout=window.setTimeout.bind(window);
        window.setTimeout=(fn,ms)=>nativeTimeout(fn,Math.min(ms,2));
        window.chrome={runtime:{sendMessage:async message=>{calls.push(message);return {ok:true};},onMessage:{addListener:fn=>window.listener=fn}}};
        const input=document.querySelector('textarea'),button=document.querySelector('button');
        const accept=()=>{
          const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent=input.value;document.body.append(user);input.value='';
          const turn=document.createElement('section');turn.dataset.talvtTurnState='complete';turn.innerHTML='<div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div>';document.body.append(turn);
        };
        button.onclick=()=>{
          clicks++;
          if(scenario==='noop'&&clicks===1)return;
          if(scenario==='cleared'){input.value='';return;}
          if(scenario==='replaced'){input.value='My unrelated draft';return;}
          if(scenario==='disabled'){button.setAttribute('aria-disabled','true');return;}
          if(scenario==='delayed'){nativeTimeout(accept,10);return;}
          accept();
        };
      },scenario);
      for(const name of ['send-button.js','logical-text.js','chatgpt.js'])await page.addScriptTag({path:path.join(__dirname,'../extensions/videostudio-chatgpt',name)});
      await page.evaluate(()=>listener({kind:'deliver',id:'req',attempt:1,prompt:'YÊU CẦU STUDIO req\nLong script content'},null,()=>{}));
      await page.waitForFunction(()=>calls.some(c=>['reply','uncertain'].includes(c.kind)),null,{timeout:10000});
      const result=await page.evaluate(()=>({clicks,last:calls.at(-1)}));
      assert.equal(result.clicks,scenario==='noop'?2:1,scenario);
      assert.equal(result.last.kind,['noop','delayed'].includes(scenario)?'reply':'uncertain',scenario);
      console.log('PASS',scenario);await page.close();
    }
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

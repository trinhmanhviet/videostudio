/* Offline real-Chromium checks of the shipped content scripts. All sites mocked. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.VS_PLAYWRIGHT_PATH||'C:/Users/leath/AppData/Local/Programs/aicoworker/resources/openclaw/node_modules/playwright-core');
const root=path.resolve(__dirname,'..');
const scope='123e4567-e89b-42d3-a456-426614174000';
const prompt='YÊU CẦU STUDIO req\nhello';
const failures=[];
async function check(name,fn){try{await fn();console.log('PASS',name);}catch(e){failures.push(name);console.error('FAIL',name,e.message);}}
(async()=>{
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  const context=await browser.newContext();
  await context.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><body></body></html>'}));
  async function chat(html){
    const page=await context.newPage();await page.goto('https://chatgpt.com/');await page.setContent('<style>.whitespace-pre-wrap,[data-message-author-role="user"]{white-space:pre-wrap}</style>'+html);
    await page.evaluate(()=>{window.messages=[];window.extensionListener=null;window.chrome={runtime:{sendMessage:async m=>{messages.push(m);return {ok:true};},onMessage:{addListener:fn=>{window.extensionListener=fn;}}}};});
    const files=JSON.parse(fs.readFileSync(path.join(root,'extensions/videostudio-chatgpt/manifest.json'))).content_scripts[1].js;
    for(const file of files)await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt',file)});
    return page;
  }
  const inspect=page=>page.evaluate(({prompt})=>new Promise(resolve=>extensionListener({kind:'inspect',id:'req',prompt},null,resolve)),{prompt});
  try{
    await check('owned empty Work composer switches to Chat before sending',async()=>{
      for(const attribute of ['aria-pressed','aria-selected']){
        const page=await chat(`<div role="group" aria-label="Composer mode"><button id="chat" ${attribute}="false">Chat</button><button id="work" ${attribute}="true">Work</button></div><form><div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send">Send</button></form>`);
        await page.evaluate(({attribute})=>{
          window.switches=0;window.clicks=0;
          document.querySelector('#chat').onclick=()=>{switches++;document.querySelector('#chat').setAttribute(attribute,'true');document.querySelector('#work').setAttribute(attribute,'false');};
          document.querySelector('button[aria-label="Send"]').onclick=()=>{
            clicks++;const input=document.querySelector('#prompt-textarea'),user=document.createElement('div');user.setAttribute('data-message-author-role','user');user.style.whiteSpace='pre-wrap';user.innerText=input.innerText;input.innerHTML='';document.body.append(user);
            const reply=document.createElement('section');reply.setAttribute('data-talvt-turn-state','complete');reply.innerHTML='<div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div>';document.body.append(reply);
          };
        },{attribute});
        await page.evaluate(prompt=>extensionListener({kind:'deliver',id:'req',attempt:1,prompt},null,()=>{}),prompt);
        await page.waitForFunction(()=>messages.some(m=>['reply','uncertain'].includes(m.kind)),undefined,{polling:100,timeout:12000});
        const result=await page.evaluate(()=>({switches,clicks,messages}));
        assert.equal(result.messages.at(-1).kind,'reply',JSON.stringify(result));assert.equal(result.switches,1);assert.equal(result.clicks,1);await page.close();
      }
    });
    await check('selected Chat using aria-selected is accepted without a mode click',async()=>{
      const page=await chat('<div role="group" aria-label="Composer mode"><button id="chat" aria-selected="true">Chat</button><button aria-selected="false">Work</button></div><form><div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"></div><button aria-label="Send" type="button">Send</button></form>');
      await page.evaluate(()=>{window.clicked=0;document.querySelector('button[aria-label="Send"]').onclick=()=>window.clicked++;});
      await page.evaluate(prompt=>extensionListener({kind:'deliver',id:'req',attempt:1,prompt},null,()=>{}),prompt);
      await page.waitForFunction(()=>clicked||messages.some(m=>m.kind==='uncertain'),undefined,{timeout:2000});
      assert.equal(await page.evaluate(()=>clicked),1);await page.close();
    });
    await check('reload recovery reads modern completed ChatGPT turn',async()=>{
      const page=await chat(`<section data-talvt-turn-state="complete"><div data-chatgpt-search-unit-key="a:user"><div class="whitespace-pre-wrap">${prompt}</div></div><div data-chatgpt-search-unit-key="b:assistant"><pre><code>{"ok":true}</code></pre></div></section>`);
      assert.equal((await inspect(page)).visibleReply,'{"ok":true}');await page.close();
    });
    await check('recovery refuses a still-streaming reply even when feedback is visible',async()=>{
      const page=await chat(`<div data-message-author-role="user">${prompt}</div><section data-testid="conversation-turn-2"><div data-message-author-role="assistant"><pre><code>{"partial":true}</code></pre></div><button data-testid="good-response-turn-action-button">Good</button></section><button data-testid="stop-button">Stop generating</button>`);
      assert.equal((await inspect(page)).visibleReply,null);await page.close();
    });
    await check('recovery rejects duplicate exact user-turn markers',async()=>{
      const page=await chat(`<div data-message-author-role="user">${prompt}</div><div data-message-author-role="user">${prompt}</div><section data-testid="conversation-turn-2"><div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div><button data-testid="good-response-turn-action-button">Good</button></section>`);
      assert.equal((await inspect(page)).visibleReply,null);await page.close();
    });
    await check('content recovery rejects a different request sharing the marker prefix',async()=>{
      const page=await chat('<div data-message-author-role="user">YÊU CẦU STUDIO req-other\nUnrelated</div><section data-talvt-turn-state="complete"><div data-message-author-role="assistant"><pre><code>{"wrong":true}</code></pre></div></section>');
      assert.equal((await inspect(page)).visibleReply,null);await page.close();
    });
    await check('content recovery accepts a completed reply after the user bubble is collapsed',async()=>{
      const page=await chat('<div data-message-author-role="user">YÊU CẦU STUDIO req\n[collapsed bubble]</div><section data-talvt-turn-state="complete"><div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div></section>');
      assert.equal((await inspect(page)).visibleReply,'{"ok":true}');await page.close();
    });
    await check('repaired long prompt reacquires the current Send control and sends once',async()=>{
      const page=await chat('<form><div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send">Send</button></form>');
      const longPrompt='YÊU CẦU STUDIO req\n'+('Long narration sentence. '.repeat(150));
      await page.evaluate(()=>{
        window.clicks=0;window.insertions=0;
        const original=document.execCommand.bind(document);
        document.execCommand=(command,show,value)=>{
          if(command==='insertText'){window.insertions++;if(value.length>1500)value=value.slice(0,80);}
          return original(command,show,value);
        };
        document.querySelector('#prompt-textarea').addEventListener('input',()=>{
          const old=document.querySelector('button'),button=old.cloneNode(true);old.replaceWith(button);
          button.onclick=()=>{
            window.clicks++;const input=document.querySelector('#prompt-textarea');
            const user=document.createElement('div');user.setAttribute('data-message-author-role','user');user.style.whiteSpace='pre-wrap';user.innerText=input.innerText;input.innerHTML='';document.body.append(user);
            const reply=document.createElement('section');reply.setAttribute('data-talvt-turn-state','complete');reply.innerHTML='<div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div>';document.body.append(reply);
          };
        });
      });
      await page.evaluate(prompt=>extensionListener({kind:'deliver',id:'req',attempt:1,prompt},null,()=>{}),longPrompt);
      await page.waitForFunction(()=>messages.some(message=>['reply','uncertain'].includes(message.kind)),undefined,{polling:100,timeout:14000});
      const result=await page.evaluate(()=>({clicks,insertions,messages}));
      assert.equal(result.messages.at(-1).kind,'reply',JSON.stringify(result));
      assert.equal(result.clicks,1);assert.ok(result.insertions>2);await page.close();
    });
    await check('a composer replaced while waiting for Send is never submitted',async()=>{
      const page=await chat('<form><div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send" disabled>Send</button></form>');
      await page.evaluate(()=>{
        window.clicks=0;document.querySelector('button').onclick=()=>window.clicks++;
        const input=document.querySelector('#prompt-textarea');
        input.addEventListener('input',()=>setTimeout(()=>{
          const replacement=input.cloneNode(false);replacement.textContent='Different draft';input.replaceWith(replacement);document.querySelector('button').disabled=false;
        },350),{once:true});
      });
      await page.evaluate(prompt=>extensionListener({kind:'deliver',id:'req',attempt:1,prompt},null,()=>{}),prompt);
      await page.waitForFunction(()=>messages.some(message=>message.kind==='uncertain'),undefined,{polling:100,timeout:4000});
      const result=await page.evaluate(()=>({clicks,messages}));
      assert.equal(result.clicks,0);assert.match(result.messages.at(-1).reason,/Composer changed/);await page.close();
    });
    await check('delivery waits for a delayed composer and enabled Send, then sends exactly once',async()=>{
      const page=await chat('');
      await page.evaluate(({prompt})=>{
        setTimeout(()=>{
          document.body.innerHTML='<form><div id="prompt-textarea" role="textbox" contenteditable="true" aria-label="Message ChatGPT"></div><button type="button" aria-label="Send" disabled>Send</button></form>';
          const button=document.querySelector('button');
          document.querySelector('#prompt-textarea').addEventListener('input',()=>setTimeout(()=>{button.disabled=false;},500));
          button.onclick=()=>{window.clicks=(window.clicks||0)+1;document.querySelector('#prompt-textarea').innerHTML='';const user=document.createElement('div');user.style.whiteSpace='pre-wrap';user.setAttribute('data-message-author-role','user');user.textContent=prompt;document.body.append(user);const reply=document.createElement('section');reply.setAttribute('data-talvt-turn-state','complete');reply.innerHTML='<div data-message-author-role="assistant"><pre><code>{"ok":true}</code></pre></div>';document.body.append(reply);};
        },400);
        extensionListener({kind:'deliver',id:'req',attempt:1,prompt},null,()=>{});
      },{prompt});
      await page.waitForFunction(()=>messages.some(m=>m.kind==='reply'||m.kind==='uncertain'),{},{timeout:8000});
      const result=await page.evaluate(()=>({clicks:window.clicks,messages}));
      assert.equal(result.clicks,1);assert.equal(result.messages.at(-1).kind,'reply');await page.close();
    });
    await check('a temporary Studio HTTP error recovers without another Start',async()=>{
      const page=await context.newPage();await page.goto(`http://localhost:8877/story-video/projects/${scope}/production`);
      await page.evaluate(()=>{
        document.body.innerHTML='';window.polls=0;
        window.chrome={runtime:{sendMessage:async()=>({ok:true,active:true,job:null}),onMessage:{addListener(){},removeListener(){}}}};
        window.fetch=async path=>{if(path.endsWith('/pending')){window.polls++;if(window.polls===1)throw Error('temporary disconnect');}return {ok:true,json:async()=>({items:[]})};};
      });
      await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt/studio.js')});
      await page.waitForTimeout(1600);
      assert.ok(await page.evaluate(()=>polls>=2),'bridge stopped polling permanently');await page.close();
    });
    await check('in-flight worker receipt errors reconnect without resetting the pending request',async()=>{
      const page=await context.newPage();await page.goto(`http://localhost:8877/story-video/projects/${scope}/production`);
      await page.evaluate(()=>{
        document.body.innerHTML='';window.polls=0;
        window.chrome={runtime:{sendMessage:async message=>{
          if(message.kind==='reconcile'){window.polls++;return {ok:false,error:'server offline',transient:true};}
          return {ok:true,active:true,job:{id:'req',phase:'sent'}};
        },onMessage:{addListener(){},removeListener(){}}}};
        window.fetch=async()=>({ok:true,json:async()=>({})});
      });
      await page.addScriptTag({path:path.join(root,'extensions/videostudio-chatgpt/studio.js')});
      await page.waitForTimeout(1600);
      assert.ok(await page.evaluate(()=>polls>=2),'in-flight bridge stopped polling permanently');await page.close();
    });
    await check('scoped Studio locks text provider to normal-Chrome ChatGPT bridge',async()=>{
      const page=await context.newPage();await page.goto(`http://localhost:8877/story-video/projects/${scope}/production`);
      await page.route('**/api/**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({ready:false,items:[],voices:[],projects:[],checks:[],flow_batch_sizes:[1]})}));
      await page.setContent(fs.readFileSync(path.join(root,'static/index.html'),'utf8'));
      assert.equal(await page.locator('#textProvider').inputValue(),'chatgpt');assert.equal(await page.locator('#textProvider').isDisabled(),true);
      assert.equal(await page.locator('#browserStart').isVisible(),false);await page.close();
    });
    await check('main video tool follows extension mode instead of offering dedicated Gemini',async()=>{
      const page=await context.newPage();await page.goto('http://localhost:8877/');
      await page.route('**/api/**',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({ready:false,text_transport:'extension',items:[],voices:[],projects:[],checks:[],flow_batch_sizes:[1]})}));
      await page.setContent(fs.readFileSync(path.join(root,'static/index.html'),'utf8'));
      await page.waitForTimeout(150);
      assert.equal(await page.locator('#textProvider').inputValue(),'chatgpt');
      assert.equal(await page.locator('#textProvider').isDisabled(),true);
      assert.equal(await page.locator('#browserStart').isVisible(),false);await page.close();
    });
  }finally{await browser.close();}
  if(failures.length)throw Error(`${failures.length} bridge UI checks failed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
